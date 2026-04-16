from datetime import datetime

from rich.console import Console
from rich.table import Table
from typer import Argument, Exit

from ..cli.utils import SESSION_FILE
from ..core.libic_service import LibicService

console = Console()


async def clear_cache(service: LibicService):
    """清除登录缓存，强制重新登录"""
    # Current implementation has bugs: `clear_cache` will trigger a login. Thus `SESSION_FILE` must be present.
    SESSION_FILE.unlink()
    console.print("[green]成功清除缓存。[/green]")


async def confirm_status(service: LibicService) -> None:
    """查看当前登录状态"""
    info = await service.get_user_info()
    console.print(
        f"成功登陆：[bold green]{info.get('trueName')} ({info.get('pid')})[/bold green]"
    )


async def print_sections(service: LibicService) -> None:
    """列出所有可预约的区域信息"""
    tree = await service.get_seat_menu_tree()

    for building in tree.buildings:
        console.print(f"[bold green]🏛 {building.name}[/bold green] (ID: {building.id})")
        for floor in building.floors:
            for section in floor.sections:
                console.print(
                    f"  ├─ [{section.id}] {section.name} "
                    f"(空闲座位: {section.remain_count}/{section.room_count})"
                )
        console.print()


async def list_seats(
    service: LibicService,
    section_name: str = Argument(
        ..., help="The Section name to query (use 'sections' command to find)"
    ),
    date: datetime | None = Argument(
        None,
        formats=["%m-%d"],
        help="Reservation date in MM-DD format (defaults to today)",
    ),
) -> None:
    """列出指定区域的座位预约情况"""
    if date is None:
        seat_date = datetime.today().date()
    else:
        seat_date = date.replace(year=datetime.now().year).date()
    try:
        section = (await service.get_sections())[section_name]
    except KeyError as e:
        console.print(
            f"[bold red]未找到预约区域'{section_name}'。请检查输入是否正确，或使用 'libic sections' 命令查看所有可用区域。[/bold red]"
        )
        raise Exit(1) from e
    seats_data = await service.get_room_seats(str(section.id), seat_date)

    table = Table(
        title=f"{seat_date} {section.name} 座位列表",
        header_style="bold blue",
    )
    table.add_column("座位ID", style="cyan")
    table.add_column("座位名称", style="magenta")
    table.add_column("预约状态")

    table_right = Table(
        title=f"{seat_date} {section.name} 座位列表 (续表)", show_header=False
    )
    table_right.add_column("座位ID", style="cyan")
    table_right.add_column("座位名称", style="magenta")
    table_right.add_column("预约状态")

    active_seats = [s for s in seats_data if s["devStatus"] == 0]
    mid = (len(active_seats) + 1) // 2

    for index, s in enumerate(active_seats):
        reservations = s.get("resvInfo", [])
        res_str = (
            "[yellow]"
            + "\n".join(
                [
                    f"{r['startTime'].split(' ')[1]} - {r['endTime'].split(' ')[1]}"
                    for r in reservations
                ]
            )
            + "[/yellow]"
            if reservations
            else "[green]Available[/green]"
        )

        row_data = (str(s["devId"]), s["devName"], res_str)
        if index < mid:
            table.add_row(*row_data)
        else:
            table_right.add_row(*row_data)

    from rich.columns import Columns

    # If the right table has no rows, only show the left one
    if mid >= len(active_seats):
        console.print(table)
    else:
        console.print(Columns([table, table_right], expand=True))
