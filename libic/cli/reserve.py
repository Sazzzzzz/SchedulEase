from datetime import datetime, timedelta
from typing import cast

from rich.console import Console
from rich.table import Table
from typer import Argument, Exit, Option, confirm

from ..service import LibicService

console = Console()


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

    reservations = await service.list_reservations(start, end)

    if not reservations:
        console.print(f"[dim]未发现在 {duration} 的预约。[/dim]")
        return

    table = Table(title=f"我的预约 ({duration})", header_style="bold blue")

    table.add_column("座位信息", justify="center")
    table.add_column("预约时间", style="green", justify="center")
    table.add_column("预约状态", style="magenta", justify="center")
    table.add_column("UUID", style="cyan", justify="center")

    for r in reservations:
        if filter_status and r["resvStatus"] != filter_status:
            continue
        reserve_date = service.from_timestamp(r["resvBeginTime"]).date()
        start_time = service.from_timestamp(r["resvBeginTime"]).strftime("%H:%M")
        end_time = service.from_timestamp(r["resvEndTime"]).strftime("%H:%M")
        devs = ", ".join([d["devName"] for d in r.get("resvDevInfoList", [])])
        status = service.STATUS_MAP.get(r["resvStatus"], str(r["resvStatus"]))
        table.add_row(
            devs,
            f"{reserve_date}: {start_time}-{end_time}",
            status,
            r["uuid"],
        )

    console.print(table)


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
        console.print("[bold red]Error: End time must be after start time![/bold red]")
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

    console.print(f"Booking Dev {dev_id} from {start_t} to {end_t}...")

    try:
        await service.reserve_seat(dev_id, start_t, end_t, date_t)
        console.print("[bold green]Reservation successful![/bold green]")
    except Exception as e:
        console.print(f"[bold red]Failed: {e}[/bold red]")


async def cancel_reservation(
    service: LibicService,
    uuid: str | None = Argument(None, help="UUID of the pending reservation"),
) -> None:
    """取消预约"""
    if uuid is None:
        console.print("[red]Error: UUID is required to cancel a reservation![/red]")
        raise Exit(1)
    try:
        await service.cancel_reservation(uuid)
        console.print("[bold green]Reservation canceled successfully.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Failed to cancel: {e}[/bold red]")


async def end_reservation(
    service: LibicService,
    uuid: str | None = Argument(None, help="UUID of the active reservation"),
):
    """结束预约"""
    if uuid is None:
        reservations = await service.list_reservations(
            datetime.today(), datetime.today()
        )
        if not reservations:
            console.print("[dim]No active reservations found for today.[/dim]")
            return
        if len([r for r in reservations if r["resvStatus"] == 1093]) == 1:
            await list_reservations(
                service, date=datetime.today(), start=None, end=None
            )
            if not confirm("End this reservation early?", default=True, abort=True):
                return None
            uuid = cast(str, reservations[0]["uuid"])
        else:
            console.print(
                "[red]Error: Multiple reservations found. Please specify the UUID to end.[/red]"
            )
            await list_reservations(
                service, date=datetime.today(), start=None, end=None
            )
            raise Exit(1)
    try:
        await service.end_reservation(uuid)
        console.print("[bold green]Reservation ended successfully.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Failed to end: {e}[/bold red]")
