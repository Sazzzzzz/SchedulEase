import logging
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Optional

import schedule
from prompt_toolkit import ANSI, HTML
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
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
from prompt_toolkit.validation import ValidationError, Validator
from rich.console import Group
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from python.cli.base_view import View
from python.service import EamisService
from python.shared import Course

logger = logging.getLogger(__name__)


class LoggerMixin(View):
    def __init__(self):
        super().__init__()
        self.logger = logger
        logging.basicConfig(
            level="NOTSET",
            format="%(message)s",
            datefmt="[%X]",
            handlers=[
                RichHandler(console=self.console, markup=False, enable_link_path=False)
            ],
        )

    def get_log(self) -> ANSI:
        """
        Returns the captured logs as ANSI formatted text.
        """
        return ANSI(self.io.getvalue())


class State(Enum):
    PREINPUT = auto()
    POSTINPUT = auto()


class TimeValidator(Validator):
    """Enhanced validator for time input in HH:MM format with detailed validation."""

    def validate(self, document):
        text = document.text.strip()
        if not text:
            raise ValidationError(message="Time cannot be empty")
        try:
            datetime.strptime(text, "%H:%M")
        except ValueError:
            raise ValidationError(
                message="Invalid time format. Please use HH:MM (24-hour format, e.g., 14:30, 08:00)"
            )


class ScheduleView(View):
    """TUI interface for scheduling course elections at specific times."""

    def __init__(self, service: EamisService):
        super().__init__()
        self.service = service
        self.logger = LoggerMixin()

        # State management
        self.state = State.PREINPUT
        self.courses: list[Course] = []
        self.target_time: Optional[datetime] = None
        self.error_message: str = ""

        # Input buffer for time entry
        self.time_buffer = Buffer(
            accept_handler=self.handle_time_input,
            multiline=False,
            validator=TimeValidator(),
            validate_while_typing=True,
        )

        # Key bindings
        self.kb = self.get_local_kb()

        # UI Components - Header (always visible)
        self.header = Window(
            content=FormattedTextControl(self.get_header),
            height=5,
            wrap_lines=True,
        )

        # Course list (always visible)
        self.course_list = Window(
            content=FormattedTextControl(self.get_course_list),
            wrap_lines=True,
        )

        # Time input section (only visible when not scheduled)
        self.time_input_section = ConditionalContainer(
            content=HSplit(
                [
                    Window(
                        content=FormattedTextControl(self.get_time_instructions),
                        wrap_lines=True,
                        height=4,
                    ),
                    Window(
                        content=FormattedTextControl(
                            HTML("<bold><cyan>Enter Time (HH:MM):</cyan></bold>")
                        ),
                        height=1,
                    ),
                    VSplit(
                        [
                            Window(
                                content=FormattedTextControl("> ", style="cyan bold"),
                                width=2,
                                dont_extend_width=True,
                            ),
                            Window(content=BufferControl(buffer=self.time_buffer)),
                        ]
                    ),
                ]
            ),
            filter=Condition(lambda: self.state is State.PREINPUT),
        )

        # Status and log panels (only visible when scheduled)
        self.status_panel = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(self.get_status_panel),
                wrap_lines=True,
            ),
            filter=Condition(lambda: self.state is State.POSTINPUT),
        )

        self.log_panel = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(self.get_log_panel),
                wrap_lines=True,
            ),
            filter=Condition(lambda: self.state is State.POSTINPUT),
        )

        # Error toolbar (visible when there are errors)
        self.error_toolbar = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(lambda: self.error_message),
                height=1,
                style="class:error,fg:#ff0000",
            ),
            filter=Condition(lambda: self.error_message != ""),
        )

        # Shortcut panel (always visible, content changes based on state)
        self.shortcut_panel = Window(
            content=FormattedTextControl(self.get_shortcuts),
            height=3,
            wrap_lines=True,
        )

        # Main layout - cleaner conditional structure
        self.main = HSplit(
            [
                self.header,
                self.separator,
                self.course_list,
                self.separator,
                # Time input OR status/log sections (mutually exclusive)
                self.time_input_section,  # Only shown when not scheduled
                self.status_panel,  # Only shown when scheduled
                self.separator,
                self.log_panel,  # Only shown when scheduled and has logs
                self.error_toolbar,
                self.shortcut_panel,
            ]
        )

        self.layout = Layout(self.main, focused_element=self.time_input_section)

    def get_local_kb(self) -> KeyBindings:
        """Define local key bindings for the view."""
        kb = KeyBindings()

        @kb.add("c-s")
        def _(event: KeyPressEvent):
            """Simulate scheduled execution for testing."""
            if self.state is State.POSTINPUT:
                logger.info("🧪 [TEST] Simulating scheduled execution...")
                self.execute_election()

        @kb.add("c-x")
        def _(event: KeyPressEvent):
            """Cancel current scheduling."""
            if self.state is State.POSTINPUT:
                self.cancel()

        return kb

    def set_courses(self, courses: list[Course]):
        """Set the courses to be scheduled for election."""
        self.courses = courses
        logger.info(f"📚 Loaded {len(courses)} courses for scheduling")

    def get_header(self):
        """Generate the header panel."""
        title = Text("Course Election Scheduler", style="bold cyan", justify="center")
        subtitle = Text(
            "Schedule automatic course elections", style="dim", justify="center"
        )
        panel = Panel(
            Group(title, subtitle),
            border_style="cyan",
            padding=(1, 2),
        )
        return self.get_rich_content(panel)

    def get_course_list(self):
        """Display the list of courses to be scheduled."""
        table = Table(
            title=f"Courses to Schedule ({len(self.courses)})", show_header=True
        )
        table.add_column("No.", style="dim", width=4)
        table.add_column("Course Name", style="cyan")
        table.add_column("Teachers", style="green")
        table.add_column("Schedule", style="yellow", width=20)

        for i, course in enumerate(self.courses, 1):
            # Create a simple course overview
            # TODO: Add stripping for long names/schedule
            schedule_str = ", ".join(
                [
                    f"{day.name}: {duration.start}-{duration.end}"
                    for day, duration in course.duration.items()
                ]
            )
            table.add_row(
                str(i),
                course.name,
                ", ".join(course.teachers),
                schedule_str,
            )

        return self.get_rich_content(table)

    def get_time_instructions(self):
        """Generate time input instructions."""
        instructions = [
            "• Enter the time when course election should start",
            "• Use 24-hour format (HH:MM), e.g., 14:30, 08:00",
            "• If the time is in the past today, it will be scheduled for tomorrow",
        ]

        text = Text()
        for instruction in instructions:
            text.append_text(Text.from_markup(instruction + "\n"))
        return self.get_rich_content(text)

    def get_status_panel(self):
        """Display current scheduling status."""
        if self.state is State.PREINPUT:
            return self.get_rich_content(Text(""))

        now = datetime.now()
        assert self.target_datetime is not None, "Target datetime should be set"
        time_remaining = self.target_datetime - now
        if time_remaining.total_seconds() > 0:
            hours, remainder = divmod(int(time_remaining.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            countdown = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            status = f"⏰ Election scheduled for: {self.target_datetime.strftime('%Y-%m-%d %H:%M')}"
            remaining = f"⏳ Time remaining: {countdown}"
            status_color = "green"
        else:
            status = "✅ Scheduled time has passed"
            remaining = "🎯 Election should have been triggered"
            status_color = "yellow"

        content = Group(
            Text(status, style=f"bold {status_color}"),
            Text(remaining, style="cyan"),
            Text(""),
            Text("Controls:", style="bold"),
            Text.from_markup(
                "• Press [bold]Ctrl+S[/bold] to simulate execution (testing)",
                style="dim",
            ),
            Text.from_markup(
                "• Press [bold]Ctrl+X[/bold] to cancel scheduling", style="dim"
            ),
        )

        panel = Panel(
            content,
            title="[bold green]Scheduling Status[/bold green]",
            border_style="green",
            padding=(1, 2),
        )

        return self.get_rich_content(panel)

    def get_log_panel(self) -> ANSI:
        """Display scheduling and execution logs using rich logging."""

        return self.logger.get_log()

    def get_shortcuts(self) -> ANSI:
        """Display control instructions."""
        if self.state is State.PREINPUT:
            # Add "enter"
            controls = "• [bold red]Ctrl+C[/bold red]: Exit  • [bold yellow]Ctrl+X[/bold yellow]: Cancel  • [bold green]Ctrl+S[/bold green]: Test"
        else:
            controls = "• [bold red]Ctrl+C[/bold red]: Exit  • [bold cyan]Enter[/bold cyan]: Schedule"

        return self.get_rich_content(Text.from_markup(controls, justify="center"))

    def handle_time_input(self, buffer: Buffer) -> bool:
        """Handle time input and schedule the election with enhanced validation."""
        time_str = buffer.text.strip()

        try:
            target_time = datetime.strptime(time_str, "%H:%M").time()
            now = datetime.now()
            target_datetime = datetime.combine(now.date(), target_time)

            # If target time is earlier than current time, schedule for tomorrow
            if target_datetime <= now:
                target_datetime += timedelta(days=1)
                logger.info(f"⚠️ Time {time_str} is past today, scheduling for tomorrow")

            # Manage state
            self.error_message = ""
            self.target_datetime = target_datetime
            self.state = State.POSTINPUT

            # Schedule the job
            schedule.every().day.at(time_str).do(self.execute_election).tag("election")

            # Add confirmation messages
            logger.info(
                f"✅ Election scheduled for {target_datetime.strftime('%Y-%m-%d %H:%M')}"
            )
            logger.info(f"📋 {len(self.courses)} courses will be processed")

            # Clear the input buffer to prevent it from staying visible
            buffer.text = ""
            return True
        except Exception as e:
            self.error_message = f"Error scheduling election: {str(e)}"
            return False

    def execute_election(self):
        """Execute the course election process."""
        logger.info("🚀 Starting course election process...")
        self.service.elect_courses(self.courses)
        logger.info("🎉 Course election completed!")

    def cancel(self):
        """Cancel the current scheduling and return to input mode."""
        schedule.clear()
        self.target_datetime = None
        self.error_message = ""
        logger.info("❌ Scheduling cancelled - returning to input mode")

        self.layout.focus(self.time_input_section)


# --- Main Application Logic ---
if __name__ == "__main__":
    from prompt_toolkit import Application

    from python.tests.dummy_service import DummyEamisService

    service = DummyEamisService()
    test_courses = [
        Course.from_row(row, service) for row in service.course_info.head(2).to_dicts()
    ]  # Take first 2 courses
    view = ScheduleView(service)
    view.set_courses(test_courses)  # Set courses for scheduling

    kb = KeyBindings()

    @kb.add("c-c")
    def _(event: KeyPressEvent):
        """Pressing Ctrl-C will exit the application."""
        event.app.exit()

    app = Application(
        layout=view.layout,
        full_screen=True,
        key_bindings=kb,
        mouse_support=True,
    )
    app.run()
