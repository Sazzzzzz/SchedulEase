from datetime import datetime, timedelta

from rich.console import Console
from rich.table import Table
from typer import Argument, Exit, Option

from .utils import async2sync, service

console = Console()


@async2sync
async def list(
    date: datetime | None = Option(
        None,
        "--date",
        "-d",
        formats=["%m-%d"],
        help="Inspection date in MM-DD format (defaults to today)",
    ),
    start: datetime | None = Option(
        None,
        "--start",
        "-s",
        formats=["%m-%d"],
        help="Start date in MM-DD",
    ),
    end: datetime | None = Option(
        None,
        "--end",
        "-e",
        formats=["%m-%d"],
        help="End date in MM-DD",
    ),
) -> None:
    """List active and pending reservations."""
    if date and (start or end):
        console.print("[red]Error: Use either --date or --start/--end, not both.[/red]")
        raise Exit(1)

    if (start and not end) or (end and not start):
        console.print("[red]Error: --start and --end must be provided together.[/red]")
        raise Exit(1)

    current_year = datetime.now().year

    def fix_year(dt: datetime | None) -> datetime | None:
        return dt.replace(year=current_year) if dt else None

    date = fix_year(date)
    start = fix_year(start)
    end = fix_year(end)

    if start and end:
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")
        title_date = f"{start_str} to {end_str}"
    elif date:
        start_str = end_str = date.strftime("%Y-%m-%d")
        title_date = start_str
    else:
        # Default to today if nothing is provided
        start_str = end_str = datetime.today().strftime("%Y-%m-%d")
        title_date = start_str

    if start and end and start > end:
        console.print("[red]Error: Start date cannot be after end date![/red]")
        raise Exit(1)

    reservations = await service.list_reservations(start_str, end_str)

    if not reservations:
        console.print(f"[dim]No reservations found for {title_date}.[/dim]")
        return

    table = Table(title=f"My Reservations ({title_date})")
    table.add_column("Seats")
    table.add_column("Time", style="green")
    table.add_column("Status", style="magenta")
    table.add_column("UUID", style="cyan")

    for r in reservations:
        reserve_date = datetime.fromtimestamp(r["resvBeginTime"] / 1000).date()
        start_time = datetime.fromtimestamp(r["resvBeginTime"] / 1000).strftime("%H:%M")
        end_time = datetime.fromtimestamp(r["resvEndTime"] / 1000).strftime("%H:%M")
        devs = ", ".join([d["devName"] for d in r.get("resvDevInfoList", [])])

        status_map = {1093: "Active/Pending", 1217: "Terminated"}
        status = status_map.get(r["resvStatus"], str(r["resvStatus"]))
        table.add_row(
            devs,
            f"{reserve_date}: {start_time} - {end_time}",
            status,
            r["uuid"],
        )

    console.print(table)


@async2sync
async def reserve(
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
    start_time: str = Option(..., "--start", "-s", help="Start time in HH:MM format"),
    end_time: str = Option(..., "--end", "-e", help="End time in HH:MM format"),
    seat_id: str | None = Option(
        None,
        "--seat-id",
        help="Directly specify the Seat Device ID to reserve (bypasses section/seat name lookup)",
    ),
):
    """Reserve a specific seat device."""
    if seat_id:
        dev_id = seat_id
    elif section_name is not None and seat_name is not None:
        section = (await service.get_sections())[section_name]
        seat = await service.get_section_seats(section.id)
        dev_id = seat[seat_name]["devId"]
    else:
        console.print(
            "[red]Error: You must provide either --seat-id or both section_name and seat_name![/red]"
        )
        raise Exit(1)

    start_t = datetime.strptime(start_time, "%H:%M").time()
    end_t = datetime.strptime(end_time, "%H:%M").time()

    if date is None:
        date_t = datetime.today().date()
        if start_t < datetime.now().time():
            console.print(
                "[yellow]Warning: Start time is in the past. Defaulting reservation date to tomorrow.[/yellow]"
            )
            date_t += timedelta(days=1)
    else:
        # Extract the date part from the parsed datetime object
        date_t = date.date()

    console.print(f"Booking Dev {dev_id} from {start_t} to {end_t}...")

    try:
        await service.reserve_seat(str(dev_id), start_t, end_t, date_t)
        console.print("[bold green]Reservation successful![/bold green]")
    except Exception as e:
        console.print(f"[bold red]Failed: {e}[/bold red]")


@async2sync
async def cancel(
    uuid: str = Argument(..., help="UUID of the pending reservation"),
):
    """Cancel a pending (future) reservation."""
    try:
        await service.cancel_reservation(uuid)
        console.print("[bold green]Reservation canceled successfully.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Failed to cancel: {e}[/bold red]")


@async2sync
async def end(
    uuid: str = Argument(..., help="UUID of the active reservation"),
):
    """End an active/current reservation early."""
    try:
        await service.end_reservation(uuid)
        console.print("[bold green]Reservation ended successfully.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Failed to end: {e}[/bold red]")
