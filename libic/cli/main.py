import asyncio
import logging

from typer import Context, Typer

from ...common.config import load_config
from .query import clear_cache, confirm_status, list_seats, print_sections
from .reserve import (
    cancel_reservation,
    end_reservation,
    list_reservations,
    reserve_seat,
)
from .utils import adapter, get_libic_service

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


@app.callback()
def inject_context(ctx: Context) -> None:
    """Inject LibicService instance and event loop into the Typer context for use in commands.
    This function works well with `--help` command and won't trigger a login with simple `--help` usage."""
    ctx.ensure_object(dict)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    ctx.call_on_close(loop.close)
    ctx.obj["loop"] = loop
    ctx.obj["service"] = loop.run_until_complete(get_libic_service(load_config()))


def main():
    app()


if __name__ == "__main__":
    main()
