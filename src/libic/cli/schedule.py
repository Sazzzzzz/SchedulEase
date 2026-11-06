"""LIBIC 的定时预约和预约保护。

后台有三类一次性任务：daily、monitor 和 reschedule。每个任务执行一轮并自行
注册后继任务；auto/watch 入口只负责启动和统一清理。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from click import confirm
from rich.console import Console
from typer import Argument, Exit, Option

from ...common.config import Config
from ...common.exceptions import ServiceError
from ..service import LibicService, Reservation
from .reserve import _validate
from .utils import get_libic_service

logger = logging.getLogger(__name__)
console = Console()

type TaskKind = Literal["daily", "monitor", "reschedule"]
type AsyncAction = Callable[[LibicService], Awaitable[Any]]

ACTIVE = {
    LibicService.Status.NOT_STARTED,
    LibicService.Status.STARTED_NOT_SIGNED,
    LibicService.Status.IN_USE,
    LibicService.Status.TEMP_LEAVE,
}


@dataclass(frozen=True)
class ReschedulePlan:
    reservation: Reservation
    deadline: datetime
    execute_at: datetime


@dataclass
class ScheduledJob:
    kind: TaskKind
    when: datetime | None
    task: asyncio.Task[Any]


@dataclass
class Coordinator:
    config: Config
    protect_leave: bool = True
    protect_start: bool = True
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    jobs: dict[str, ScheduledJob] = field(default_factory=dict)
    stopping: bool = False

    def spawn(
        self,
        loop: asyncio.AbstractEventLoop,
        kind: TaskKind,
        key: str,
        coroutine: Coroutine[Any, Any, Any],
        *,
        when: datetime | None = None,
    ) -> asyncio.Task[Any] | None:
        """注册一次性任务；相同 key 的旧任务会被替换。"""
        if self.stopping:
            coroutine.close()
            return None
        old = self.jobs.get(key)
        if old and old.task is not asyncio.current_task():
            old.task.cancel()
        task = loop.create_task(coroutine, name=f"libic:{kind}:{key}")
        self.jobs[key] = ScheduledJob(kind, when, task)
        return task

    def cancel(self, key: str) -> None:
        job = self.jobs.pop(key, None)
        if job and job.task is not asyncio.current_task():
            job.task.cancel()

    async def stop(self) -> None:
        self.stopping = True
        pending = [job.task for job in self.jobs.values() if not job.task.done()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        self.jobs.clear()
        logger.info("调度已停止，待执行任务已清理")


@asynccontextmanager
async def session(coordinator: Coordinator):
    """使用短生命周期会话，并串行登录和写操作。"""
    async with coordinator.lock:
        fresh = await get_libic_service(coordinator.config, interactive=False)
        try:
            yield fresh
        finally:
            await fresh.aclose()


async def run_at(
    coordinator: Coordinator,
    when: datetime,
    action: AsyncAction,
    task_name: str = "定时任务",
) -> Any:
    """按服务端时间等待，临近执行时刷新会话并重新校时。"""
    async with session(coordinator) as libic:
        now = await libic.get_server_time()
    prepare = when - timedelta(minutes=coordinator.config.libic.prepare_minutes)
    await asyncio.sleep(max(0, (prepare - now).total_seconds()))

    logger.info("%s：开始准备会话，执行时间 %s", task_name, when)
    async with session(coordinator) as libic:
        now = await libic.get_server_time()

    delay = timedelta(seconds=coordinator.config.libic.overshoot_seconds)
    await asyncio.sleep(max(0, (when - now + delay).total_seconds()))
    async with session(coordinator) as libic:
        logger.info("%s：开始执行", task_name)
        return await action(libic)


def _reschedule_plan(
    coordinator: Coordinator, reservation: Reservation
) -> ReschedulePlan | None:
    """把预约快照转换成唯一的重约计划。"""
    deadline: datetime | None = None
    if (
        coordinator.protect_start
        and reservation.status == LibicService.Status.NOT_STARTED
        and reservation.sign_time is None
    ):
        deadline = reservation.start
    elif (
        coordinator.protect_leave
        and reservation.status == LibicService.Status.TEMP_LEAVE
    ):
        deadline = reservation.leave_deadline

    if deadline is None:
        return None
    return ReschedulePlan(
        reservation=reservation,
        deadline=deadline,
        execute_at=deadline
        - timedelta(minutes=coordinator.config.libic.protect_minutes),
    )


def _schedule_reschedule(
    loop: asyncio.AbstractEventLoop,
    coordinator: Coordinator,
    reservation: Reservation,
    now: datetime,
) -> str | None:
    """创建、保留或取消一条预约对应的 reschedule 任务。"""
    key = f"reschedule:{reservation.uuid}"
    plan = _reschedule_plan(coordinator, reservation)
    if plan is None:
        coordinator.cancel(key)
        return None
    if plan.deadline <= now:
        coordinator.cancel(key)
        logger.error("%s 已错过保护截止时间，不修改预约", reservation.seat)
        return None

    existing = coordinator.jobs.get(key)
    if existing and existing.when == plan.deadline:
        return key

    coordinator.spawn(
        loop,
        "reschedule",
        key,
        reschedule_task(loop, coordinator, plan),
        when=plan.deadline,
    )
    logger.info(
        "保护任务已创建：%s %s (%s)，将在 %s 复查",
        reservation.section,
        reservation.seat,
        reservation.uuid,
        max(now, plan.execute_at),
    )
    return key


def _sync_reschedules(
    loop: asyncio.AbstractEventLoop,
    coordinator: Coordinator,
    reservations: list[Reservation],
    now: datetime,
) -> None:
    """让 reschedule 任务与一次完整巡检快照保持一致。"""
    expected = {
        key
        for reservation in reservations
        if (key := _schedule_reschedule(loop, coordinator, reservation, now))
    }
    for key in list(coordinator.jobs):
        if key.startswith("reschedule:") and key not in expected:
            coordinator.cancel(key)


async def reschedule_task(
    loop: asyncio.AbstractEventLoop,
    coordinator: Coordinator,
    plan: ReschedulePlan,
) -> None:
    """第三类任务：到保护时间复查并替换一条预约。"""
    original = plan.reservation

    async def execute(service: LibicService) -> None:
        records = await service.list_reservations(
            original.start.date(), original.end.date()
        )
        current = next((item for item in records if item.uuid == original.uuid), None)
        if current is None:
            logger.info("保护任务跳过：%s (%s) 已不存在", original.seat, original.uuid)
            return

        refreshed = _reschedule_plan(coordinator, current)
        if refreshed is None or refreshed.deadline != plan.deadline:
            logger.info(
                "保护任务跳过：%s (%s) 状态或截止时间已变化",
                current.seat,
                current.uuid,
            )
            _schedule_reschedule(
                loop, coordinator, current, await service.get_server_time()
            )
            return
        await _replace_reservation(loop, coordinator, service, current, plan.deadline)

    try:
        await run_at(
            coordinator,
            plan.execute_at,
            execute,
            task_name=f"保护 {original.section} {original.seat} ({original.uuid})",
        )
    except asyncio.CancelledError:
        logger.info("保护任务已取消：%s (%s)", original.seat, original.uuid)
        raise
    except Exception as error:
        logger.error("%s 保护失败：%s", original.seat, error)


async def _replace_reservation(
    loop: asyncio.AbstractEventLoop,
    coordinator: Coordinator,
    service: LibicService,
    reservation: Reservation,
    deadline: datetime,
) -> None:
    now = await service.get_server_time()
    if now >= deadline:
        logger.error("%s 已错过保护截止时间，不修改预约", reservation.seat)
        return

    minimum = await service.get_min_reservation_minutes(reservation)
    now = await service.get_server_time()
    if now >= deadline:
        raise ServiceError("读取座位规则后已过截止时间，不修改预约")

    leaving = reservation.status == LibicService.Status.TEMP_LEAVE
    new_start = (now if leaving else reservation.start) + timedelta(
        minutes=coordinator.config.libic.rebook_minutes
    )
    new_start = new_start.replace(microsecond=0)
    old_result = "旧预约处理结果未确认"
    try:
        if leaving:
            await service.end_reservation(reservation.uuid)
            old_result = "旧预约已结束"
        else:
            await service.cancel_reservation(reservation.uuid)
            old_result = "旧预约已取消"

        remaining = (reservation.end - new_start).total_seconds()
        if new_start >= reservation.end or remaining < minimum * 60:
            logger.warning(
                "%s：%s，剩余时段不足，停止续约", reservation.seat, old_result
            )
            return

        replacement = await service.reserve_seat(
            reservation.dev_id,
            new_start.time(),
            reservation.end.time(),
            new_start.date(),
        )
        logger.info(
            "%s：%s，已重预约 %s–%s",
            reservation.seat,
            old_result,
            new_start.strftime("%H:%M:%S"),
            reservation.end.strftime("%H:%M:%S"),
        )
        _schedule_reschedule(
            loop, coordinator, replacement, await service.get_server_time()
        )
    except Exception as error:
        logger.error(
            "%s：%s；目标 %s–%s；%s。停止该预约链，不重试。",
            reservation.seat,
            old_result,
            new_start,
            reservation.end,
            error,
        )


def _next_check(config: Config, now: datetime) -> datetime:
    opening = datetime.combine(now.date(), config.libic.check_start)
    closing = datetime.combine(now.date(), config.libic.check_end)
    if now < opening:
        return opening
    return opening + timedelta(days=1) if now >= closing else now


async def monitor_task(
    loop: asyncio.AbstractEventLoop,
    coordinator: Coordinator,
    scheduled_at: datetime | None = None,
) -> None:
    """第二类任务：执行一次巡检，并注册下一次 monitor。"""
    if scheduled_at is not None:
        await asyncio.sleep(max(0, (scheduled_at - datetime.now()).total_seconds()))

    now = datetime.now()
    active_at = _next_check(coordinator.config, now)
    if active_at > now:
        logger.info("巡检暂停，%s 恢复", active_at)
        coordinator.spawn(
            loop,
            "monitor",
            "monitor",
            monitor_task(loop, coordinator, active_at),
            when=active_at,
        )
        return

    try:
        logger.info("巡检开始")
        async with session(coordinator) as service:
            now = await service.get_server_time()
            end = now.date() + timedelta(
                days=max(1, coordinator.config.libic.advance_days)
            )
            records = [
                item
                for item in await service.list_reservations(now.date(), end)
                if item.status in ACTIVE
            ]
            _sync_reschedules(loop, coordinator, records, now)
            pending = sum(
                item.status == LibicService.Status.NOT_STARTED for item in records
            )
            logger.info(
                "巡检完成：%d 条有效预约（未开始 %d、进行中 %d），%d 个保护任务",
                len(records),
                pending,
                len(records) - pending,
                sum(
                    job.kind == "reschedule" and not job.task.done()
                    for job in coordinator.jobs.values()
                ),
            )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.error("巡检失败：%s；下一轮继续", error)

    next_run = _next_check(
        coordinator.config,
        now + timedelta(minutes=coordinator.config.libic.check_minutes),
    )
    logger.info("将在 %s 执行下次巡检", next_run.strftime("%m-%d %H:%M"))
    coordinator.spawn(
        loop,
        "monitor",
        "monitor",
        monitor_task(loop, coordinator, next_run),
        when=next_run,
    )


async def watch(
    service: LibicService,
    no_leave: bool = Option(False, "--no-leave", help="关闭暂离保护"),
    no_start: bool = Option(False, "--no-start", help="关闭签到保护"),
):
    """开启预约保护：自动推迟暂离和未签到预约。"""
    if no_leave and no_start:
        logger.error("至少启用一种保护")
        raise Exit(2)
    loop = asyncio.get_running_loop()
    coordinator = Coordinator(
        service.config,
        protect_leave=not no_leave,
        protect_start=not no_start,
    )
    logger.info(
        "预约保护已启动：暂离保护=%s，签到保护=%s，巡检间隔=%s 分钟",
        coordinator.protect_leave,
        coordinator.protect_start,
        coordinator.config.libic.check_minutes,
    )
    await service.aclose()
    coordinator.spawn(loop, "monitor", "monitor", monitor_task(loop, coordinator))
    try:
        await asyncio.Event().wait()
    finally:
        await coordinator.stop()


async def daily_task(
    loop: asyncio.AbstractEventLoop,
    coordinator: Coordinator,
    day: date,
) -> None:
    """第一类任务：处理一天的周计划，并注册下一天的 daily。"""
    send_at = datetime.combine(day, coordinator.config.libic.send_time)

    async def reserve(service: LibicService) -> None:
        now = await service.get_server_time()
        if now.date() != day:
            logger.warning("每日任务已跨日，跳过 %s", day)
            return

        target = day + timedelta(days=coordinator.config.libic.advance_days)
        plans = [
            plan
            for plan in coordinator.config.libic.weekly
            if plan.weekday == target.isoweekday()
        ]
        logger.info("每日任务：预约日期 %s，匹配 %d 条周计划", target, len(plans))
        sections = await service.get_sections() if plans else {}
        for plan in plans:
            start = datetime.combine(target, plan.start)
            end = datetime.combine(target, plan.end)

            # clamp reservation time to library open scope
            (open_t, close_t) = await service.get_open_scope(
                sections[plan.section].id, target
            )
            clamped_start, clamped_end = (
                max(plan.start, open_t),
                min(plan.end, close_t),
            )
            if clamped_start >= clamped_end:
                logger.warning(
                    "%s %s 预约失败：请求的预约时间不在图书馆开放时间 %s - %s 内",
                    plan.section,
                    plan.seat,
                    open_t,
                    close_t,
                )
                continue
            if (clamped_start, clamped_end) != (plan.start, plan.end):
                logger.warning(
                    "原预约时间超过图书馆开放时间，已调整为 %s–%s",
                    clamped_start.strftime("%H:%M"),
                    clamped_end.strftime("%H:%M"),
                )
                start = datetime.combine(target, clamped_start)
                end = datetime.combine(target, clamped_end)

            try:
                if await service.get_server_time() >= start:
                    raise ServiceError("已错过使用开始时间，跳过本次预约")
                seats = await service.get_section_seats(sections[plan.section].id)
                dev_id = str(seats[plan.seat]["devId"])
                reservation = await service.reserve_seat(
                    dev_id, plan.start, plan.end, target
                )
                logger.info("%s %s 已预约 %s–%s", plan.section, plan.seat, start, end)
                if coordinator.protect_leave or coordinator.protect_start:
                    _schedule_reschedule(
                        loop,
                        coordinator,
                        reservation,
                        await service.get_server_time(),
                    )
            except Exception as error:
                logger.error(
                    "%s %s %s 预约失败：%s；不重试",
                    plan.section,
                    plan.seat,
                    start,
                    error,
                )
        logger.info("每日任务处理完成：%s", target)

    logger.info(
        "每日任务已创建：%s 发送，预约 %s",
        max(send_at, datetime.now()),
        day + timedelta(days=coordinator.config.libic.advance_days),
    )
    try:
        await run_at(coordinator, send_at, reserve, task_name=f"每日预约 {day}")
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.error("每日任务 %s 失败：%s；不重试，继续安排下一天", day, error)
    finally:
        next_day = day + timedelta(days=1)
        coordinator.spawn(
            loop,
            "daily",
            "daily",
            daily_task(loop, coordinator, next_day),
            when=datetime.combine(next_day, coordinator.config.libic.send_time),
        )


async def auto(
    service: LibicService,
    no_watch: bool = Option(False, "--no-watch", help="关闭预约保护"),
    no_leave: bool = Option(False, "--no-leave", help="关闭暂离保护"),
    no_start: bool = Option(False, "--no-start", help="关闭签到保护"),
    no_clamp: bool = Option(False, "--no-clamp", help="关闭预约时间限制"),
):
    """协调 daily、monitor 和 reschedule 三类任务。"""
    if not service.config.libic.weekly:
        logger.error("请先在 libic.weekly 中配置周计划")
        raise Exit(2)

    loop = asyncio.get_running_loop()
    coordinator = Coordinator(
        service.config,
        protect_leave=not (no_watch or no_leave),
        protect_start=not (no_watch or no_start),
    )
    now = await service.get_server_time()
    await service.aclose()
    logger.info(
        "自动预约已启动：发现 %d 条预约计划，暂离保护=%s，签到保护=%s",
        len(coordinator.config.libic.weekly),
        coordinator.protect_leave,
        coordinator.protect_start,
    )
    coordinator.spawn(loop, "daily", "daily", daily_task(loop, coordinator, now.date()))
    if coordinator.protect_leave or coordinator.protect_start:
        coordinator.spawn(loop, "monitor", "monitor", monitor_task(loop, coordinator))
    try:
        await asyncio.Event().wait()
    finally:
        await coordinator.stop()


async def schedule_reservation(
    service: LibicService,
    section_name: str | None = Argument(None, help="区域名称"),
    seat_name: str | None = Argument(None, help="座位名称"),
    date: datetime = Option(..., formats=["%m-%d"], help="预约日期 MM-DD"),
    start: datetime = Option(
        ..., "--from", "-f", formats=["%H:%M"], help="开始时间 HH:MM"
    ),
    end: datetime = Option(..., "--to", "-t", formats=["%H:%M"], help="结束时间 HH:MM"),
    send_time: datetime = Option(
        ...,
        "--at",
        formats=["%m/%d/%H:%M:%S", "%m/%d/%H:%M", "%m-%d/%H:%M"],
        help="发送时间 MM/DD/HH:MM[:SS]",
    ),
    seat_id: str | None = Option(None, "--seat-id", help="直接指定座位设备 ID"),
):
    """定时发送座位预约请求。"""
    now = await service.get_server_time()
    send = send_time.replace(year=now.year)
    reserve_date = date.replace(year=now.year).date()
    if send <= now or reserve_date < now.date() or end.time() <= start.time():
        logger.error("日期或时段无效：发送时间已过，或结束时间早于开始时间")
        raise Exit(2)
    if not seat_id and (section_name is None or seat_name is None):
        logger.error("请提供区域及座位名称，或 --seat-id")
        raise Exit(2)

    dev_id, section_id, start_t, end_t, _ = await _validate(
        service, section_name, seat_name, date, start, end, seat_id
    )
    if await service.get_server_time() >= datetime.combine(reserve_date, start_t):
        raise ServiceError("已错过预约开始时间")
    if section_id:
        (open_t, close_t) = await service.get_open_scope(section_id, reserve_date)
        if not (open_t <= start_t < end_t <= close_t):
            clamped_start, clamped_end = max(start_t, open_t), min(end_t, close_t)

            if clamped_start >= clamped_end:
                console.print(
                    f"[bold red]预约失败：请求的预约时间不在图书馆开放时间 {open_t} - {close_t} 内[/bold red]"
                )
                raise Exit(1)
            # todo: change all `confirm` to click components
            confirm(
                f"提示：请求的预约时间 {start_t.strftime('%H:%M')} - {end_t.strftime('%H:%M')} 不在图书馆开放时间 {open_t.strftime('%H:%M')} - {close_t.strftime('%H:%M')} 内。您是否要预约 {clamped_start.strftime('%H:%M')} - {clamped_end.strftime('%H:%M')}？",
                abort=True,
                default=True,
            )

            start_t = clamped_start
            end_t = clamped_end

    async def reserve(service: LibicService):
        await service.reserve_seat(dev_id, start_t, end_t, reserve_date)
        logger.info(
            "定时预约成功：座位 %s，%s %s–%s", dev_id, reserve_date, start_t, end_t
        )

    coordinator = Coordinator(service.config, protect_leave=False, protect_start=False)
    logger.info(
        "定时预约任务已创建：%s %s，将在 %s 发送，预约 %s %s–%s",
        section_name or "",
        seat_name or seat_id,
        send + timedelta(seconds=service.config.libic.overshoot_seconds),
        reserve_date,
        start_t,
        end_t,
    )
    await service.aclose()
    try:
        await run_at(
            coordinator,
            send,
            reserve,
            task_name=f"定时预约 {section_name or ''} {seat_name or seat_id} {reserve_date}",
        )
    except Exception as error:
        logger.error(f"预约失败：{error}")
        raise Exit(1) from error
