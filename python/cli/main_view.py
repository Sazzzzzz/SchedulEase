"""
Main (landing) view for the TUI application.
"""

from enum import Enum, auto
from typing import Callable, Optional

from prompt_toolkit import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ..service import EamisService
from .base_view import View


class LogLevel(Enum):
    ERROR = auto()
    INFO = auto()
    SUCCESS = auto()


class MainView(View):
    """Default landing page view."""

    def __init__(
        self,
        service: EamisService,
        on_start_election: Callable[[], None],
        on_settings: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        super().__init__()
        self.service = service

        # Options and selection state
        self.options: list[tuple[str, Callable[[], None]]] = [
            ("Start Election", on_start_election),
            ("Settings", on_settings),
            ("Exit", on_exit),
        ]
        self.index: int = 0  # currently highlighted option

        # In-memory log entries (message, level)
        self.logs: list[tuple[str, LogLevel]] = []

        # Key bindings for navigation and selection
        self.kb = self.get_local_kb()

        # UI components
        self.title_box = Window(
            content=FormattedTextControl(self.get_title), height=5, wrap_lines=True
        )
        self.log_box = Window(
            content=FormattedTextControl(self.get_log_panel), wrap_lines=True
        )
        self.options_bar = Window(
            content=FormattedTextControl(self.get_options_bar),
        )
        self.shortcuts = Window(
            height=2,
            content=FormattedTextControl(self.get_shortcuts),
            wrap_lines=True,
        )

        # Main layout
        self.main = HSplit(
            [
                self.title_box,
                self.separator,
                self.log_box,
                self.separator,
                self.options_bar,
                self.shortcuts,
            ],
            key_bindings=self.kb,
        )

        self.layout = Layout(self.main)

    # --------- Public helpers ---------
    def add_log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        """Append a log line and keep a modest cap to avoid overflow."""
        self.logs.append((message, level))
        # Keep last 100 entries
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]

    # --------- Private: UI builders ---------
    def get_title(self) -> ANSI:
        title = Text("SchedulEase", style="bold cyan", justify="center")
        subtitle = Text("NKU选课助手", justify="center")
        return self.get_rich_content(
            Panel(Group(title, subtitle), border_style="cyan", padding=(1, 2))
        )

    def get_log_panel(self) -> ANSI:
        if not self.logs:
            empty = Text("No recent activity.", style="dim", justify="center")
            content = Group(empty)
        else:
            lines: list[Text] = []
            for msg, level in self.logs[-30:]:  # show last 30 messages
                if level == "success":
                    mark = "✔"
                    style = "green"
                elif level == "error":
                    mark = "✖"
                    style = "red"
                else:
                    mark = "•"
                    style = "cyan"
                lines.append(
                    Text.from_markup(f"[bold {style}]{mark}[/bold {style}] {msg}")
                )
            content = Group(*lines)

        panel = Panel(
            content,
            title="[bold cyan]Activity[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
        return self.get_rich_content(panel)

    def get_options_bar(self) -> ANSI:
        items: list[Text] = []
        for i, (label, _) in enumerate(self.options):
            if i == self.index:
                items.append(Text.from_markup(f"[bold cyan]› {label} ‹[/bold cyan]"))
            else:
                items.append(Text.from_markup(f"[dim]{label}[/dim]"))

        # Center the options inside a panel
        row = Text("\n").join(items)
        panel = Panel(
            row, border_style="cyan", title="[bold]Options[/bold]", padding=(0, 2)
        )
        return self.get_rich_content(panel)

    def get_shortcuts(self) -> ANSI:
        return self.get_rich_content(
            Text.from_markup(
                "• [bold red]Ctrl+C[/bold red]: [bold]退出程序[/bold]  • [bold cyan]Left/Right[/bold cyan]: [bold]浏览选项[/bold]  • [bold green]Enter[/bold green]: [bold]进入界面[/bold]"
            )
        )

    def get_local_kb(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("left")
        def _left(_):
            self.index = (self.index - 1) % len(self.options)

        @kb.add("right")
        def _right(_):
            self.index = (self.index + 1) % len(self.options)

        @kb.add("up")
        def _up(_):
            # mirror horizontal navigation for convenience
            self.index = (self.index - 1) % len(self.options)

        @kb.add("down")
        def _down(_):
            self.index = (self.index + 1) % len(self.options)

        @kb.add("enter")
        def _enter(event):
            label, handler = self.options[self.index]
            if handler is not None:
                try:
                    handler()
                except Exception as e:
                    self.add_log(f"Failed to run '{label}': {e}", level=LogLevel.ERROR)
                else:
                    self.add_log(f"Executed '{label}'", level=LogLevel.SUCCESS)
            else:
                # Fallback: just log the selection
                self.add_log(f"Selected '{label}'")

        return kb


if __name__ == "__main__":
    # Simple harness to preview the view
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyPressEvent

    from ..tests.dummy_service import DummyEamisService

    def on_start():
        view.add_log("Navigating to Election view…")

    def on_settings():
        view.add_log("Opening Settings…")

    def on_exit():
        view.add_log("Exit requested. Press Ctrl+C to quit.")

    service = DummyEamisService()
    view = MainView(
        service, on_start_election=on_start, on_settings=on_settings, on_exit=on_exit
    )

    kb = KeyBindings()

    @kb.add("c-c")
    def _(event: KeyPressEvent):
        event.app.exit()

    app = Application(
        layout=view.layout, full_screen=True, key_bindings=kb, mouse_support=True
    )
    app.run()
