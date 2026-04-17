from datetime import datetime, timedelta

import questionary
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from typer import Argument, Exit, Option, confirm

from ..service import LibicService, Reservation

console = Console()


def _show_reservations_table(
    service: LibicService,
    reservations: list[Reservation],
    title: str,
) -> None:
    table = Table(title=title, header_style="bold blue")
    table.add_column("序号", justify="center")
    table.add_column("座位信息", justify="center")
    table.add_column("预约时间", style="green", justify="center")
    table.add_column("预约状态", style="magenta", justify="center")
    table.add_column("UUID", style="cyan", justify="center")

    for idx, r in enumerate(reservations, start=1):
        table.add_row(
            str(idx),
            f"{r.section} {r.seat}",
            f"{r.start.strftime('%Y-%m-%d %H:%M')} - {r.end.strftime('%H:%M')}",
            service.STATUS_MAP.get(r.status, str(r.status)),
            r.uuid,
        )

    console.print(table)


async def list_reservations(
    service: LibicService,
    date: datetime | None = Option(
        None,
        "--date",
        "-d",
        formats=["%m-%d"],
        help="Inspection date in MM-DD format (defaults to today)",
    ),
    start: datetime | None = Option(
        None,
        "--from",
        "-f",
        formats=["%m-%d"],
        help="Start date in MM-DD",
    ),
    end: datetime | None = Option(
        None,
        "--to",
        "-t",
        formats=["%m-%d"],
        help="End date in MM-DD",
    ),
    filter_status: int | None = Option(
        None,
        "--status",
        help="Filter reservations by status code (e.g. 1093 for active, 1094 for pending)",
    ),
) -> None:
    """列出我的预约记录"""
    # Param validation
    if date and (start or end):
        console.print("[red]Error: Use either --date or --from/--to, not both.[/red]")
        raise Exit(1)

    if end and not start:
        console.print("[red]Error: --to and --from must be provided together.[/red]")
        raise Exit(1)

    if start:
        if not end:
            end = datetime.today()
        if start > end:
            console.print("[red]Error: Start date cannot be after end date![/red]")
            raise Exit(1)
    elif date:
        start = end = datetime.today()
    else:
        # Default to today if nothing is provided
        start = end = datetime.today()

    current_year = datetime.now().year
    start = start.replace(year=current_year)
    end = end.replace(year=current_year)

    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    duration = f"{start_str} to {end_str}" if start_str != end_str else start_str

    reservations = await service.list_reservations(
        start,
        end,
        filter=service.Status(filter_status) if filter_status is not None else None,
    )

    _show_reservations_table(
        service,
        reservations,
        title=f"My Reservations ({duration})",
    )


async def reserve_seat(
    service: LibicService,
    section_name: str | None = Argument(
        None, help="The Section name to reserve (use 'sections' command to find)"
    ),
    seat_name: str | None = Argument(
        None, help="The Seat Device ID to reserve (use 'seats' command to find)"
    ),
    date: datetime | None = Option(
        None,
        formats=["%m-%d"],
        help="Reservation date in MM-DD format (defaults to today)",
    ),
    start: datetime | None = Option(
        None, "--from", "-f", formats=["%H:%M"], help="Start time in HH:MM format"
    ),
    end: datetime = Option(
        ..., "--to", "-t", formats=["%H:%M"], help="End time in HH:MM format"
    ),
    seat_id: str | None = Option(
        None,
        "--seat-id",
        help="Directly specify the Seat Device ID to reserve (bypasses section/seat name lookup)",
    ),
) -> None:
    """预约座位"""
    if seat_id:
        dev_id = seat_id
    elif section_name is not None and seat_name is not None:
        try:
            section = (await service.get_sections())[section_name]
        except KeyError as e:
            console.print(
                f"[bold red]未找到预约区域'{section_name}'。请检查输入是否正确，或使用 'libic sections' 命令查看所有可用区域。[/bold red]"
            )
            raise Exit(1) from e
        try:
            seat = await service.get_section_seats(section.id)
            dev_id: str = seat[seat_name]["devId"]

        except KeyError as e:
            console.print(
                f"[bold red]未找到座位'{seat_name}'。请检查输入是否正确，或使用 'libic seats' 命令查看该区域的所有可用座位。[/bold red]"
            )
            raise Exit(1) from e
    else:
        console.print(
            "[bold red]Error: You must provide either --seat-id or both section_name and seat_name![/bold red]"
        )
        raise Exit(1)

    if start is None:
        console.print(
            "[yellow] 未指定开始时间，默认使用当前时间作为预约开始时间。[/yellow]"
        )
        start = datetime.now() + timedelta(
            minutes=2
        )  # Libic system clock is often ahead

    start_t = start.time().replace(microsecond=0)
    end_t = end.time()
    if end_t <= start_t:
        console.print("[bold red]错误：结束时间必须在开始时间之后！[/bold red]")
        raise Exit(1)

    if date is None:
        date_t = datetime.today().date()
        if start_t < datetime.now().time():
            confirm(
                "预约的开始时间已过，是否预约明天的座位？", abort=True, default=True
            )
            date_t += timedelta(days=1)
    else:
        # Extract the date part from the parsed datetime object
        date_t = date.date()

    console.print(
        f"[bold yellow]正在预约时段 {start_t} 到 {end_t} 的座位 {dev_id} ...[/bold yellow]"
    )

    try:
        await service.reserve_seat(dev_id, start_t, end_t, date_t)
        console.print("[bold green]预约成功！[/bold green]")
    except Exception as e:
        console.print(f"[bold red]{e}[/bold red]")


async def cancel_reservation(
    service: LibicService,
    uuid: str | None = Argument(None, help="UUID of the pending reservation"),
) -> None:
    """取消预约"""
    if uuid is None:
        reservations = await service.list_reservations(
            datetime.today(),
            datetime.today() + timedelta(days=1),
            filter=LibicService.Status.NOT_STARTED,
        )
        if not reservations:
            console.print("[bold yellow]目前没有待开始的预约。[/bold yellow]")
            raise Exit(0)
        elif len(reservations) == 1:
            r = reservations[0]
            Prompt.ask(
                f"[dim yellow]是否取消在 [/dim yellow][yellow]{r.section} {r.seat} {r.start.strftime('%H:%M')} - {r.end.strftime('%H:%M')}[yellow][dim yellow] 的预约?[/dim yellow]",
                choices=["y", "n"],
                default="y",
            )
            uuid = r.uuid
        else:
            choices = [
                questionary.Choice(
                    title=f"{r.start.strftime('%H:%M')} - {r.end.strftime('%H:%M')} {r.section} {r.seat}",
                    value=r.uuid,
                )
                for r in reservations
            ]
            choices.append(questionary.Choice(title="退出", value="q"))

            result: str = await questionary.select(
                "发现多个待开始的预约。请选择一个要取消的预约：",
                choices=choices,
            ).ask_async()

            if result == "q" or result is None:
                console.print("[bold yellow]已停止取消预约[/bold yellow]")
                raise Exit(0)

            uuid = result
    try:
        await service.cancel_reservation(uuid)
        console.print("[bold green]预约已取消[/bold green]")
    except Exception as e:
        console.print(f"[bold red]取消预约失败: {e}[/bold red]")


async def end_reservation(
    service: LibicService,
    uuid: str | None = Argument(None, help="UUID of the active reservation"),
):
    """结束预约"""
    if uuid is None:
        reservations = await service.list_reservations(
            datetime.today(),
            datetime.today() + timedelta(days=1),
            filter=LibicService.Status.IN_USE,
        )
        if not reservations:
            console.print("[bold yellow]目前没有正在进行的预约。[/bold yellow]")
            raise Exit(0)
        elif len(reservations) == 1:
            r = reservations[0]
            ans = Prompt.ask(
                f"[dim yellow]是否结束在 [/dim yellow][yellow]{r.section} {r.seat} {r.start.strftime('%H:%M')} - {r.end.strftime('%H:%M')}[yellow][dim yellow] 的预约?[/dim yellow]",
                choices=["y", "n"],
                default="y",
            )
            if ans.lower() != "y":
                console.print("[bold red]已停止结束预约[/bold red]")
                raise Exit(0)
            uuid = r.uuid
        else:
            choices = [
                questionary.Choice(
                    title=f"{r.start.strftime('%H:%M')} - {r.end.strftime('%H:%M')} {r.section} {r.seat}",
                    value=r.uuid,
                )
                for r in reservations
            ]
            choices.append(questionary.Choice(title="退出", value="q"))

            result: str = await questionary.select(
                "发现多个正在进行的预约。请选择一个要结束的预约：",
                choices=choices,
            ).ask_async()

            if result == "q" or result is None:
                console.print("[bold yellow]已停止结束预约[/bold yellow]")
                raise Exit(0)

            uuid = result
    try:
        await service.end_reservation(uuid)
        console.print("[bold green]成功结束预约[/bold green]")
    except Exception as e:
        console.print(f"[bold red]结束预约失败: {e}[/bold red]")
