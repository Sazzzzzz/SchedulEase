"""
View object responsible for creating and editing configurations.
"""

from enum import Enum, auto
from typing import Optional

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    BufferControl,
    ConditionalContainer,
    FormattedTextControl,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.containers import HSplit
from prompt_toolkit.layout.processors import PasswordProcessor
from prompt_toolkit.validation import ValidationError, Validator
from prompt_toolkit.widgets.toolbars import ValidationToolbar
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ..config import CONFIG_PATH, create_config, load_config
from ..shared import AppEvent, EventBus
from .base_view import View


class State(Enum):
    """State management for the configuration steps."""

    ACCOUNT = auto()
    PASSWORD = auto()
    CONFIRM = auto()
    COMPLETE = auto()


class PasswordValidator(Validator):
    """Validator that checks if password matches the first password."""

    def __init__(self, password: Optional[str] = None):
        self.password = password

    def validate(self, document):
        if self.password is None:
            return
        if len(document.text) < len(self.password):
            raise ValidationError(message="⚠ 密码太短")
        elif document.text != self.password:
            raise ValidationError(message="✗ 密码不匹配")


class ConfigView(View):
    """Configuration Interface for account setup"""

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        self.bus = bus

        # State management
        self.state: State = State.ACCOUNT
        self.account: str = ""
        self.password: str = ""

        self._create_layout()

    def _create_layout(self):
        # Input buffers
        self.account_buffer = Buffer(
            accept_handler=self._handle_account_input,
            multiline=False,
        )

        self.password_buffer = Buffer(
            accept_handler=self._handle_password_input,
            multiline=False,
        )
        # Validator will be set after password input
        self.confirm_buffer = Buffer(
            accept_handler=self._handle_confirm_input,
            multiline=False,
            validate_while_typing=True,
            validator=PasswordValidator(),
        )

        # UI Components
        self.header = Window(
            content=FormattedTextControl(self._get_header),
            height=7,
            wrap_lines=True,
        )

        self.instructions = Window(
            content=FormattedTextControl(self._get_instructions),
            wrap_lines=True,
        )

        self.input_label = Window(
            content=FormattedTextControl(self._get_input_label),
            height=1,
            style="class:label",
        )

        # Create separate input fields for each step
        self.account_input = VSplit(
            [
                Window(
                    content=FormattedTextControl("> ", style="cyan bold"),
                    width=2,
                    dont_extend_width=True,
                ),
                Window(
                    content=BufferControl(buffer=self.account_buffer),
                ),
            ]
        )
        self._prefill_account()

        self.password_input = VSplit(
            [
                Window(
                    content=FormattedTextControl("> ", style="cyan bold"),
                    width=2,
                    dont_extend_width=True,
                ),
                Window(
                    content=BufferControl(
                        buffer=self.password_buffer,
                        input_processors=[PasswordProcessor()],
                    ),
                ),
            ]
        )

        self.confirm_input = VSplit(
            [
                Window(
                    content=FormattedTextControl("> ", style="cyan bold"),
                    width=2,
                    dont_extend_width=True,
                ),
                Window(
                    content=BufferControl(
                        buffer=self.confirm_buffer,
                        input_processors=[PasswordProcessor()],
                    ),
                ),
            ]
        )
        self.shortcuts = Window(
            content=FormattedTextControl(self._get_shortcuts),
            height=2,
            wrap_lines=True,
        )
        # Conditional containers for each input
        self.account_field = ConditionalContainer(
            content=self.account_input,
            filter=Condition(lambda: self.state is State.ACCOUNT),
        )

        self.password_field = ConditionalContainer(
            content=self.password_input,
            filter=Condition(lambda: self.state is State.PASSWORD),
        )

        self.confirm_field = ConditionalContainer(
            content=self.confirm_input,
            filter=Condition(lambda: self.state is State.CONFIRM),
        )

        self.error_toolbar = ValidationToolbar()

        self.success_panel = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(self._get_success_panel),
                wrap_lines=True,
            ),
            filter=Condition(lambda: self.state is State.COMPLETE),
        )

        # Main layout
        self.main = HSplit(
            [
                self.header,
                self.separator,
                self.instructions,
                self.separator,
                self.input_label,
                self.account_field,
                self.password_field,
                self.confirm_field,
                self.success_panel,
                self.shortcuts,
                self.error_toolbar,
            ],
            key_bindings=self._get_local_kb(),
        )

        self.layout = Layout(self.main, focused_element=self.account_input)

    def _get_local_kb(self) -> KeyBindings:
        """Define local key bindings for the view."""
        kb = KeyBindings()

        @kb.add(
            "enter", eager=True, filter=Condition(lambda: self.state is State.COMPLETE)
        )
        def _enter(event: KeyPressEvent):
            if self.state is State.COMPLETE:
                self.bus.publish(AppEvent.CONFIG_CONFIRMED)

        return kb

    def _prefill_account(self):
        """Prefill the account input with existing account if available."""
        try:
            config = load_config()
            existing_account = config.get("user", {}).get("account", "")
            self.account_buffer.text = existing_account
        except Exception:
            return None

    def _get_header(self) -> ANSI:
        """Generate the header panel."""
        title = Text(
            "Course Election Configuration", style="bold cyan", justify="center"
        )
        subtitle = Text("编辑账号与密码", style="dim", justify="center")

        panel = Panel(
            Group(title, subtitle),
            border_style="cyan",
            padding=(1, 2),
        )
        return self._get_rich_content(panel)

    def _get_instructions(self) -> ANSI:
        """Generate context-sensitive instructions."""
        # TODO: Rewrite this in `Group` for better formatting
        instructions = {
            State.ACCOUNT: [
                "• [bold yellow]请输入学号[/bold yellow]",
            ],
            State.PASSWORD: [
                "• [bold yellow]请输入密码：[/bold yellow]",
                "• 该密码将仅用于教务网站登录",
                "• 为保护您的隐私，请勿泄露配置文件",
            ],
            State.CONFIRM: [
                "• [bold yellow]请再次输入密码以确认[/bold yellow]",
                "• 密码必须完全匹配",
            ],
            State.COMPLETE: [
                "[bold green]✓ 配置已成功保存！[/bold green]",
                f"• 其余设置可在配置文件[italic cyan]{CONFIG_PATH}[/italic cyan]中手动编辑",
                "• 请重新进入程序以加载配置",
            ],
        }

        current_instructions = instructions.get(self.state, [])
        text = Text()
        for instruction in current_instructions:
            text.append_text(Text.from_markup(instruction + "\n"))

        return self._get_rich_content(text)

    def _get_input_label(self) -> ANSI:
        """Generate the input field label."""
        labels = {
            State.ACCOUNT: "[bold cyan]Student ID:[/bold cyan]",
            State.PASSWORD: "[bold cyan]Password:[/bold cyan]",
            State.CONFIRM: "[bold cyan]Confirm Password:[/bold cyan]",
            State.COMPLETE: "[bold green]Configuration Complete![/bold green]",
        }

        label = labels.get(self.state, "")
        return self._get_rich_content(Text.from_markup(label))

    def _get_success_panel(self) -> ANSI:
        """Generate the success panel after configuration is complete.

        This looks really good : )"""
        content = Group(
            Text("Configuration Complete!", style="bold green", justify="center"),
            Text(""),
            Text(f"Account: {self.account}", style="cyan"),
            Text("Password: " + "•" * len(self.password), style="cyan"),
            Text(""),
            Text("已成功保存您的账号与密码！", justify="center"),
        )

        panel = Panel(
            content,
            title="[bold green]Success[/bold green]",
            border_style="green",
            padding=(1, 2),
        )

        return self._get_rich_content(panel)

    def _get_shortcuts(self) -> ANSI:
        return self._get_rich_content(
            Text.from_markup(
                "• [bold red]Ctrl+C[/bold red]: [bold]退出程序[/bold] • [bold cyan]Enter[/bold cyan]: [bold]下一步[/bold]"
            )
        )

    def _handle_account_input(self, buffer: Buffer) -> bool:
        """Handle account name input."""
        account = buffer.text.strip()
        self.account = account
        self.state = State.PASSWORD
        self.layout.focus(self.password_input)
        return False  # Don't close the buffer

    def _handle_password_input(self, buffer: Buffer) -> bool:
        """Handle password input."""
        password = buffer.text
        if not password:
            return False

        self.password = password
        self.confirm_buffer.validator = PasswordValidator(password)
        self.state = State.CONFIRM
        self.layout.focus(self.confirm_input)
        return False

    def _handle_confirm_input(self, buffer: Buffer) -> bool:
        """Handle (already validated) password confirmation."""
        try:
            create_config(self.account, self.password)
            self.state = State.COMPLETE
        except Exception:
            return False

        return True


if __name__ == "__main__":
    # This module is only responsible for certain views, not for running the application.
    # Following lines are for testing purposes only.
    from prompt_toolkit import Application

    kb = KeyBindings()
    bus = EventBus()

    @kb.add("c-c")
    def _(event: KeyPressEvent):
        """Pressing Ctrl-C will exit the application."""
        event.app.exit()

    view = ConfigView(bus)
    app = Application(
        layout=view.layout,
        full_screen=True,
        key_bindings=kb,
        mouse_support=True,
    )
    app.run()
