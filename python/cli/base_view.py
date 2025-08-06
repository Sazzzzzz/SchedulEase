import io
from abc import ABC

from prompt_toolkit import ANSI
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from rich.console import Console
from rich.rule import Rule


class View(ABC):
    """
    Base class for TUI views. Provides boilerplate for view objects.
    """

    def __init__(self):
        self.io = io.StringIO()
        self.console = Console(
            file=self.io,
            force_terminal=True,
            # TODO: May be adjusted later
            width=110,
        )

        # Prebuilt widget
        self.separator = Window(
            height=1,
            content=FormattedTextControl(text=self.get_line_separator),
        )

    def get_rich_content(self, *args, **kwargs) -> ANSI:
        """
        A utility function to render rich content to a string buffer.
        """
        # TODO: Add function signature from `rich.print` using ParamSpec and TypeVar
        # TODO: Generalize this function to accept custom console and stream
        self.console.print(*args, **kwargs)
        output = self.io.getvalue()
        self.io.seek(0)
        self.io.truncate(0)
        return ANSI(output)

    def get_line_separator(self) -> ANSI:
        """
        Returns a horizontal line separator for the layout.
        """
        return self.get_rich_content(Rule(style="cyan"))
