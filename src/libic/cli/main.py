"""
Main entry point for LIBIC CLI commands.

The system mainly works on the `Typer` framework. To make async commands work, it:
1. Stores the event loop in the Typer context
2. Provides `adapter` to lazily inject a service when an async command executes.
"""

import asyncio
import logging

from rich.logging import RichHandler
from typer import Context, Typer

from libic.cli.query import clear_cache, confirm_status, list_seats, print_sections
from libic.cli.reserve import (
    cancel_reservation,
    end_reservation,
    list_reservations,
    reserve_seat,
)
from libic.cli.schedule import auto, schedule_reservation, watch
from libic.cli.utils import adapter

logger = logging.getLogger(__name__)

app = Typer(help="NKU 图书馆预约助手", add_completion=False)

# --- utils ---
app.command(name="status")(adapter(confirm_status))
app.command(name="clean")(adapter(clear_cache))
# --- query ---
app.command(name="list")(adapter(list_reservations))
app.command(name="sections")(adapter(print_sections))
app.command(name="seats")(adapter(list_seats))
# --- reserve ---
app.command(name="reserve")(adapter(reserve_seat))
app.command(name="cancel")(adapter(cancel_reservation))
app.command(name="end")(adapter(end_reservation))
# --- schedule ---
app.command(name="schedule")(adapter(schedule_reservation, interactive=False))
app.command(name="watch")(adapter(watch, interactive=False))
app.command(name="auto")(adapter(auto, interactive=False))


@app.callback()
def inject_context(ctx: Context) -> None:
    """Prepare the command event loop without triggering login for help commands."""
    ctx.ensure_object(dict)
    if ctx.invoked_subcommand in {"schedule", "watch", "auto"}:
        logging.basicConfig(
            level=logging.INFO,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True)],
        )
        logging.getLogger("httpx").setLevel(logging.WARNING)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ctx.obj["loop"] = loop

    async def shutdown():
        tasks = [
            task for task in asyncio.all_tasks() if task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await loop.shutdown_asyncgens()

    def close():
        try:
            loop.run_until_complete(shutdown())
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    ctx.call_on_close(close)


def main():
    app()


if __name__ == "__main__":
    main()
