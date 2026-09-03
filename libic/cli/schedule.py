import asyncio
from datetime import datetime, timedelta

from rich.console import Console
from typer import Argument, Context, Exit, Option

from ..service import LibicService
from .reserve import _validate
from .utils import get_libic_service

console = Console()


async def schedule_reservation(
    ctx: Context,
    section_name: str | None = Argument(
        None, help="The Section name to reserve (use 'sections' command to find)"
    ),
    seat_name: str | None = Argument(
        None, help="The Seat Device ID to reserve (use 'seats' command to find)"
    ),
    date: datetime = Option(
        ...,
        formats=["%m-%d"],
        help="Reservation date in MM-DD format",
    ),
    start: datetime = Option(
        ..., "--from", "-f", formats=["%H:%M"], help="Start time in HH:MM format"
    ),
    end: datetime = Option(
        ..., "--to", "-t", formats=["%H:%M"], help="End time in HH:MM format"
    ),
    send_time: datetime = Option(
        ...,
        "--at",
        formats=["%m/%d/%H:%M:%S", "%m-%d/%H:%M"],
        help="Time to send the reservation in MM/DD/HH:MM format",
    ),
    seat_id: str | None = Option(
        None,
        "--seat-id",
        help="Directly specify the Seat Device ID to reserve (bypasses section/seat name lookup)",
    ),
) -> None:
    """在指定时间发送座位预约请求。"""
    service: LibicService = ctx.obj["service"]
    dev_id, start_t, end_t, reserve_date = await _validate(
        service, section_name, seat_name, date, start, end, seat_id
    )
    server_now = await service.get_server_time()
    send_at = send_time.replace(year=server_now.year)
    if send_at <= server_now:
        console.print("[bold red]错误：发送时间必须晚于当前服务器时间！[/bold red]")
        raise Exit(1)

    prepare_at = send_at - timedelta(minutes=service.config.libic.prepare_minutes)
    console.print(
        f"预约任务已创建：将在 [cyan]{send_at:%Y-%m-%d %H:%M:%S}[/cyan] 发送，"
        f"预约 [cyan]{reserve_date:%Y-%m-%d} {start_t} - {end_t}[/cyan]。"
    )
    delay = (prepare_at - server_now).total_seconds()
    if delay > 0:
        console.print(f"将在 [cyan]{prepare_at:%H:%M:%S}[/cyan] 开始准备。")
        await asyncio.sleep(delay)

    console.print("[green]正在刷新登录状态…[/green]")
    try:
        await service.client.aclose()
        service = await get_libic_service(service.config, force_login=True)
    except Exception as e:
        console.print(f"[bold red]准备失败：{e}[/bold red]")
        raise Exit(1) from e

    server_now = await service.get_server_time()
    delay = (
        send_at - server_now
    ).total_seconds() + service.config.libic.overshoot_seconds
    if delay > 0:
        console.print(f"准备完成，将在 [cyan]{send_at:%H:%M:%S}[/cyan] 发送预约。")
        await asyncio.sleep(delay)

    console.print(
        f"[bold yellow]正在预约时段 {start_t} 到 {end_t} 的座位 {dev_id} ...[/bold yellow]"
    )
    try:
        await service.reserve_seat(dev_id, start_t, end_t, reserve_date)
    except Exception as e:
        console.print(f"[bold red]预约失败：{e}[/bold red]")
        raise Exit(1) from e
    console.print("[bold green]预约成功！[/bold green]")
