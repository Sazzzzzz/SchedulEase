from datetime import datetime

from rich.console import Console
from rich.table import Table
from typer import Argument

from .utils import async2sync, service

console = Console()


@async2sync
async def status():
    """Check current session status."""
    info = await service.get_user_info()
    console.print(
        f"Successfully logged in as: [bold green]{info.get('trueName')} ({info.get('pid')})[/bold green]"
    )


@async2sync
async def sections():
    """List all buildings, floors, and rooms."""
    tree = await service.get_seat_menu_tree()

    for building in tree.buildings:
        console.print(f"[bold green]🏛 {building.name}[/bold green] (ID: {building.id})")
        for floor in building.floors:
            for section in floor.sections:
                console.print(
                    f"  [cyan]├─ [{section.id}][/cyan] {section.name} "
                    f"(Available: {section.remain_count}/{section.room_count})"
                )
        print()


@async2sync
async def seats(
    section_name: str = Argument(
        ..., help="The Section name to query (use 'sections' command to find)"
    ),
    date: datetime | None = Argument(
        None,
        formats=["%m-%d"],
        help="Reservation date in MM-DD format (defaults to today)",
    ),
):
    """List seat availability for a specific room and date."""
    if date is None:
        seat_date = datetime.today().date()
    else:
        seat_date = date.replace(year=datetime.now().year).date()

    section = (await service.get_sections())[section_name]
    seats_data = await service.get_room_seats(str(section.id), seat_date)

    table = Table(title=f"Seats for Room {section.name} on {seat_date}")
    table.add_column("Dev ID", style="cyan")
    table.add_column("Seat Name", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Reservations")

    for s in seats_data:
        reservations = s.get("resvInfo", [])
        res_str = (
            ", ".join(
                [
                    f"{r['startTime'].split(' ')[1]} - {r['endTime'].split(' ')[1]}"
                    for r in reservations
                ]
            )
            if reservations
            else "Available"
        )
        status = "Active" if s["devStatus"] == 0 else "Offline"
        table.add_row(str(s["devId"]), s["devName"], status, res_str)

    console.print(table)
