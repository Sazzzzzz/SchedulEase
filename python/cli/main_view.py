"""
Main (landing) view for the TUI application.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable

from prompt_toolkit import ANSI
from prompt_toolkit.application import get_app
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ..shared import AppEvent, EventBus
from .base_view import View


class LogLevel(Enum):
    ERROR = auto()
    INFO = auto()
    SUCCESS = auto()


@dataclass
class Option:
    name: str
    action: Callable[[], None]


class State(Enum):
    # These record the index of active options
    ON_HALT = tuple()
    FORCE_SCHEDULE = (1, 2)
    NORMAL = (0, 1, 2)


class MainView(View):
    """Default landing page view."""

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        self.bus = bus

        # Options and selection state
        self.total_options = [
            Option("进入选课", lambda: self.bus.publish(AppEvent.MAIN_ENTER_ELECTION)),
            Option("账户设置", lambda: self.bus.publish(AppEvent.MAIN_ENTER_CONFIG)),
            Option("退出程序", lambda: self.bus.publish(AppEvent.MAIN_EXIT)),
        ]
        self.state = State.ON_HALT
        self.index: int = 0  # currently highlighted option
        self.register()

        # In-memory log entries (message, level)
        self.logs: list[tuple[str, LogLevel]] = []

        self._create_layout()

    @property
    def state(self) -> State:
        return self._state

    @state.setter
    def state(self, state: State):
        self._state = state
        self.options = [self.total_options[i] for i in state.value]
        get_app().invalidate()

    def register(self):
        self.bus.subscribe(AppEvent.APP_NO_CONFIG, self.set_on_schedule)
        self.bus.subscribe(AppEvent.APP_OK, self.set_on_election)

    def set_on_schedule(self):
        self.state = State.FORCE_SCHEDULE

    def set_on_election(self):
        self.state = State.NORMAL

    def _create_layout(self):
        # UI components
        self.title_box = Window(
            content=FormattedTextControl(self._get_title), height=7, wrap_lines=True
        )
        self.log_box = Window(
            content=FormattedTextControl(self._get_log_panel), wrap_lines=True
        )
        self.options_bar = Window(
            content=FormattedTextControl(self._get_options_bar),
        )
        self.shortcuts = Window(
            height=2,
            content=FormattedTextControl(self._get_shortcuts),
            wrap_lines=True,
        )

        # Main layout
        self.main = HSplit(
            [
                self.title_box,
                self.log_box,
                self.separator,
                self.options_bar,
                self.shortcuts,
            ],
            key_bindings=self._get_local_kb(),
        )

        self.layout = Layout(self.main)

    # --------- Public helpers ---------
    def add_log(self, message: str, level: LogLevel = LogLevel.INFO) -> None:
        """Append a log line and keep a modest cap to avoid overflow."""
        self.logs.append((message, level))
        # Keep last 100 entries
        if len(self.logs) > 100:
            self.logs = self.logs[-100:]
        get_app().invalidate()

    # --------- Private: UI builders ---------
    def _get_title(self) -> ANSI:
        title = Text("SchedulEase", style="bold cyan", justify="center")
        subtitle = Text("NKU选课助手", justify="center")
        return self._get_rich_content(
            Panel(Group(title, subtitle), border_style="cyan", padding=(1, 2))
        )

    def _get_log_panel(self) -> ANSI:
        if not self.logs:
            empty = Text("No recent activity.", style="dim", justify="center")
            content = Group(empty)
        else:
            lines: list[Text] = []
            for msg, level in self.logs[-30:]:  # show last 30 messages
                match level:
                    case LogLevel.SUCCESS:
                        mark = "✔"
                        style = "green"
                    case LogLevel.ERROR:
                        mark = "✖"
                        style = "red"
                    case _:
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
        return self._get_rich_content(panel)

    def _get_options_bar(self) -> ANSI:
        items: list[Text] = []
        for i, opt in enumerate(self.total_options):
            if opt in self.options:
                # Find the position of this option in the filtered self.options list
                option_index = self.options.index(opt)
                if option_index == self.index:
                    items.append(
                        Text.from_markup(f"[bold cyan]› {opt.name} ‹[/bold cyan]")
                    )
                else:
                    items.append(Text.from_markup(f"{opt.name}"))
            else:
                items.append(Text.from_markup(f"[strike]{opt.name}[/strike]"))

        # Center the options inside a panel
        row = Text("\n").join(items)
        panel = Panel(
            row, border_style="cyan", title="[bold]Options[/bold]", padding=(0, 2)
        )
        return self._get_rich_content(panel)

    def _get_shortcuts(self) -> ANSI:
        return self._get_rich_content(
            Text.from_markup(
                "• [bold red]Ctrl+C[/bold red]: [bold]退出程序[/bold]  • [bold cyan]Left/Right[/bold cyan]: [bold]浏览选项[/bold]  • [bold green]Enter[/bold green]: [bold]进入界面[/bold]"
            )
        )

    def _get_local_kb(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("left")
        def _left(_):
            if len(self.options) > 0:
                self.index = (self.index - 1) % len(self.options)

        @kb.add("right")
        def _right(_):
            if len(self.options) > 0:
                self.index = (self.index + 1) % len(self.options)

        @kb.add("up")
        def _up(_):
            # mirror horizontal navigation for convenience
            if len(self.options) > 0:
                self.index = (self.index - 1) % len(self.options)

        @kb.add("down")
        def _down(_):
            if len(self.options) > 0:
                self.index = (self.index + 1) % len(self.options)

        @kb.add("enter")
        def _enter(event):
            if 0 <= self.index < len(self.options):
                opt = self.options[self.index]
                label, handler = opt.name, opt.action
                if handler is not None:
                    try:
                        handler()
                    except Exception as e:
                        self.add_log(
                            f"Failed to run '{label}': {e}", level=LogLevel.ERROR
                        )

        return kb


if __name__ == "__main__":
    # Simple harness to preview the view
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyPressEvent

    kb = KeyBindings()
    view = MainView(bus=EventBus())

    @kb.add("c-c")
    def _(event: KeyPressEvent):
        event.app.exit()

    app = Application(
        layout=view.layout, full_screen=True, key_bindings=kb, mouse_support=True
    )
    app.run()
