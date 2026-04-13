import asyncio
import logging

from typer import Context, Typer

from ..utils.config import load_config
from .query import seats, sections, status
from .reserve import cancel, end, list, reserve
from .utils import adapter, get_libic_service

logger = logging.getLogger(__name__)

app = Typer(help="NKU Library Reservation CLI")

app.command(name="status")(adapter(status))
app.command(name="list")(adapter(list))
app.command(name="sections")(adapter(sections))
app.command(name="reserve")(adapter(reserve))
app.command(name="seats")(adapter(seats))
app.command(name="cancel")(adapter(cancel))
app.command(name="end")(adapter(end))


@app.callback()
def inject_context(ctx: Context):
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
