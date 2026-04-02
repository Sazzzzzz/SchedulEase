import logging

from typer import Typer

from .query import seats, sections, status
from .reserve import cancel, end, list, reserve

logger = logging.getLogger(__name__)

app = Typer(help="NKU Library Reservation CLI")


app.command(name="status")(status)
app.command(name="list")(list)
app.command(name="sections")(sections)
app.command(name="reserve")(reserve)
app.command(name="seats")(seats)
app.command(name="cancel")(cancel)
app.command(name="end")(end)


def main():
    app()


if __name__ == "__main__":
    main()

# I didn't use callback function for @async2sync because I wasn't sure if all APIs were async
# I didn't use context for service because I thought dependency injection would be better
