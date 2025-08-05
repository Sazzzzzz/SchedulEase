"""
CLI for creating and editing configurations.
"""

import enum
from enum import auto
from typing import Optional
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
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
from prompt_toolkit.validation import Validator, ValidationError
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from python.cli.base_view import View
from python.service import EamisService
from python.config import load_config, create_config


class State(enum.Enum):
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
        if document.text != self.password:
            raise ValidationError(message="Passwords do not match!")


class ConfigView(View):
    """Configuration Interface for account setup"""

    def __init__(self, service: EamisService):
        super().__init__()
        self.service = service

        # State management
        self.state: State = State.ACCOUNT
        self.account: str = ""
        self.password: str = ""
        self.error_message: str = ""
        self.success_message: str = ""

        # Input buffers
        self.account_buffer = Buffer(
            accept_handler=self.handle_account_input,
            multiline=False,
        )

        self.password_buffer = Buffer(
            accept_handler=self.handle_password_input,
            multiline=False,
        )
        # Validator will be set after password input
        self.confirm_buffer = Buffer(
            accept_handler=self.handle_confirm_input,
            multiline=False,
            validate_while_typing=True,
        )

        # Key bindings
        self.kb = self.get_local_kb()

        # UI Components
        self.header = Window(
            content=FormattedTextControl(self.get_header),
            height=5,
            wrap_lines=True,
        )

        self.instructions = Window(
            content=FormattedTextControl(self.get_instructions),
            wrap_lines=True,
        )

        self.input_label = Window(
            content=FormattedTextControl(self.get_input_label),
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
        self.prefill_account()

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

        self.error_toolbar = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(lambda: self.error_message),
                height=1,
                style="class:error,fg:#ff0000",
            ),
            filter=Condition(lambda: self.error_message != ""),
        )

        self.success_panel = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(self.get_success_panel),
                wrap_lines=True,
            ),
            filter=Condition(lambda: self.state is State.COMPLETE),
        )

        self.password_match_indicator = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(self.get_password_match_status),
                height=1,
            ),
            filter=Condition(
                lambda: self.state is State.CONFIRM and bool(self.confirm_buffer.text)
            ),
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
                self.password_match_indicator,
                self.error_toolbar,
                self.success_panel,
            ]
        )

        self.layout = Layout(self.main, focused_element=self.account_input)

    def get_local_kb(self) -> KeyBindings:
        """Define local key bindings for the view."""
        kb = KeyBindings()

        @kb.add("c-c")
        def _(event):
            """Cancel and return to previous view."""
            # In a real app, this would navigate back
            event.app.exit()

        @kb.add("escape")
        def _(event):
            """Go back to previous step."""
            if self.state is State.PASSWORD:
                self.state = State.ACCOUNT
                self.password_buffer.reset()
                self.error_message = ""
                self.layout.focus(self.account_input)
            elif self.state is State.CONFIRM:
                self.state = State.PASSWORD
                self.confirm_buffer.reset()
                self.error_message = ""
                self.layout.focus(self.password_input)

        return kb

    def prefill_account(self):
        """Prefill the account input with existing account if available."""
        try:
            config = load_config()
            existing_account = config.get("user", {}).get("account", "")
            self.account_buffer.text = existing_account
        except Exception:
            return None

    def get_header(self) -> ANSI:
        """Generate the header panel."""
        title = Text(
            "Course Election Configuration", style="bold cyan", justify="center"
        )
        subtitle = Text(
            "Set up your account credentials", style="dim", justify="center"
        )

        panel = Panel(
            Group(title, subtitle),
            border_style="cyan",
            padding=(1, 2),
        )
        return self.get_rich_content(panel)

    def get_instructions(self) -> ANSI:
        """Generate context-sensitive instructions."""
        # TODO: Rewrite this in `Group` for better formatting
        instructions = {
            State.ACCOUNT: [
                "• Enter your student ID or account name",
                "• Press [bold cyan]Enter[/bold cyan] to continue",
                "• Press [bold red]Ctrl+C[/bold red] to cancel",
            ],
            State.PASSWORD: [
                "• Enter your password (hidden for security)",
                "• Press [bold cyan]Enter[/bold cyan] to continue",
                "• Press [bold yellow]Escape[/bold yellow] to go back",
            ],
            State.CONFIRM: [
                "• Re-enter your password to confirm",
                "• Passwords must match exactly",
                "• Press [bold cyan]Enter[/bold cyan] to save configuration",
                "• Press [bold yellow]Escape[/bold yellow] to go back",
            ],
            State.COMPLETE: [
                "✓ Configuration saved successfully!",
                "• Your credentials have been securely stored",
                "• You can now proceed to course election",
            ],
        }

        current_instructions = instructions.get(self.state, [])
        text = Text()
        for instruction in current_instructions:
            text.append_text(Text.from_markup(instruction + "\n"))

        return self.get_rich_content(text)

    def get_input_label(self) -> ANSI:
        """Generate the input field label."""
        labels = {
            State.ACCOUNT: "[bold cyan]Student ID:[/bold cyan]",
            State.PASSWORD: "[bold cyan]Password:[/bold cyan]",
            State.CONFIRM: "[bold cyan]Confirm Password:[/bold cyan]",
            State.COMPLETE: "[bold green]Configuration Complete![/bold green]",
        }

        label = labels.get(self.state, "")
        return self.get_rich_content(Text.from_markup(label))

    def get_password_match_status(self) -> ANSI:
        """Show real-time password matching status."""
        if not self.confirm_buffer.text:
            return ANSI("")

        if self.confirm_buffer.text == self.password:
            status = Text("✓ Passwords match", style="green bold")
        else:
            if len(self.confirm_buffer.text) < len(self.password):
                status = Text("⚠ Password is too short", style="yellow")
            else:
                status = Text("✗ Passwords do not match", style="red bold")

        return self.get_rich_content(status)

    def get_success_panel(self) -> ANSI:
        """Generate the success panel after configuration is complete."""
        content = Group(
            Text("Configuration Complete!", style="bold green", justify="center"),
            Text(""),
            Text(f"Account: {self.account}", style="cyan"),
            Text("Password: " + "•" * len(self.password), style="cyan"),
            Text(""),
            Text("Your configuration has been saved.", style="dim", justify="center"),
        )

        panel = Panel(
            content,
            title="[bold green]Success[/bold green]",
            border_style="green",
            padding=(1, 2),
        )

        return self.get_rich_content(panel)

    def handle_account_input(self, buffer: Buffer) -> bool:
        """Handle account name input."""
        account = buffer.text.strip()
        if not account:
            self.error_message = "Account name cannot be empty!"
            return False

        self.account = account
        self.state = State.PASSWORD
        self.error_message = ""
        self.layout.focus(self.password_input)
        return False  # Don't close the buffer

    def handle_password_input(self, buffer: Buffer) -> bool:
        """Handle password input."""
        password = buffer.text
        if not password:
            self.error_message = "Password cannot be empty!"
            return False

        self.password = password
        self.confirm_buffer.validator = PasswordValidator(password)
        self.state = State.CONFIRM
        self.error_message = ""
        self.layout.focus(self.confirm_input)
        return False

    def handle_confirm_input(self, buffer: Buffer) -> bool:
        """Handle password confirmation."""
        if buffer.text != self.password:
            self.error_message = "Passwords do not match! Please try again."
            return False

        try:
            create_config(self.account, self.password)
            self.state = State.COMPLETE
            self.error_message = ""
            self.success_message = "Configuration saved successfully!"
        except Exception as e:
            self.error_message = f"Failed to save configuration: {str(e)}"
            return False

        return False


if __name__ == "__main__":
    # This module is only responsible for certain views, not for running the application.
    # Following lines are for testing purposes only.
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyPressEvent

    from python.tests.dummy_service import DummyEamisService

    kb = KeyBindings()

    @kb.add("c-c")
    def _(event: KeyPressEvent):
        """Pressing Ctrl-C will exit the application."""
        event.app.exit()

    view = ConfigView(DummyEamisService())
    app = Application(
        layout=view.layout,
        full_screen=True,
        key_bindings=kb,
        mouse_support=True,
    )
    app.run()
