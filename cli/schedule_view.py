"""
View object responsible for schedule election time
"""

# TODO: log too long
import asyncio
import logging
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Optional

from prompt_toolkit.application import get_app
import schedule
from prompt_toolkit import ANSI
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
from prompt_toolkit.widgets.toolbars import ValidationToolbar
from rich.console import Group
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .base_view import View
from ..service import EamisService
from ..shared import AppEvent, Course, EventBus

logger = logging.getLogger(__name__)


class LoggerMixin(View):
    # TODO: Add doc
    def __init__(self, level: str):
        super().__init__()
        self.logger = logger
        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[
                RichHandler(console=self.console, markup=False, enable_link_path=False)
            ],
        )

    def get_log(self, lines: int) -> ANSI:
        """
        Returns the last lines of captured logs as ANSI formatted text.
        """
        log_lines = self.io.getvalue().splitlines()[-lines:]
        return ANSI("\n".join(log_lines))


class State(Enum):
    PREINPUT = auto()
    POSTINPUT = auto()
    RUNNING = auto()


class TimeValidator(Validator):
    """Enhanced validator for time input in HH:MM format with detailed validation."""

    def validate(self, document):
        text = document.text.strip()
        if not text:
            raise ValidationError(message="输入不可为空")
        try:
            datetime.strptime(text, "%H:%M")
        except ValueError:
            raise ValidationError(
                message="时间格式有误。请使用24 小时制时间格式 HH:MM（如 14:30，08:00）"
            )


class ScheduleView(View):
    """TUI interface for scheduling course elections at specific times."""

    def __init__(self, service: EamisService, bus: EventBus):
        super().__init__()
        self.service = service
        self.bus = bus
        self.logger = LoggerMixin(
            self.service.config.get("settings", {}).get("log_level", "NOTSET")
        )

        # State management
        self._state = State.PREINPUT
        self.courses: list[Course] = []
        self.target_datetime: Optional[datetime] = None
        self._refresh_task: Optional[asyncio.Task] = None

        self._create_layout()

    def _create_layout(self):
        # Input buffer for time entry
        self.time_buffer = Buffer(
            accept_handler=self._handle_time_input,
            multiline=False,
            validator=TimeValidator(),
            validate_while_typing=True,
        )

        # UI Components - Header (always visible)
        self.header = Window(
            content=FormattedTextControl(self._get_header),
            height=6,
            wrap_lines=True,
        )

        # Course list (always visible)
        self.course_list = Window(
            content=FormattedTextControl(self._get_course_list),
            wrap_lines=True,
        )

        # Time input section (only visible when not scheduled)
        self.time_input = ConditionalContainer(
            content=HSplit(
                [
                    Window(
                        content=FormattedTextControl(self._get_time_instructions),
                        wrap_lines=True,
                        height=4,
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
                content=FormattedTextControl(self._get_status_panel),
                wrap_lines=True,
                height=8,
            ),
            filter=Condition(lambda: self.state is not State.PREINPUT),
        )

        self.log_panel = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(self._get_log_panel),
                wrap_lines=True,
            ),
            filter=Condition(lambda: self.state is not State.PREINPUT),
        )

        # Shortcut panel (always visible, content changes based on state)
        self.shortcuts = Window(
            content=FormattedTextControl(self._get_shortcuts),
            height=2,
            wrap_lines=True,
        )
        self.error_toolbar = ConditionalContainer(
            content=ValidationToolbar(),
            filter=Condition(lambda: self.state is State.PREINPUT),
        )
        # Main layout - cleaner conditional structure
        self.main = HSplit(
            [
                self.header,
                self.course_list,
                self.separator,
                # Time input OR status/log sections (mutually exclusive)
                self.time_input,  # Only shown when not scheduled
                self.status_panel,  # Only shown when scheduled
                # self.separator,
                self.log_panel,  # Only shown when scheduled and has logs
                self.shortcuts,
                self.error_toolbar,
            ],
            key_bindings=self._get_local_kb(),
        )

        self.layout = Layout(self.main, focused_element=self.time_input)

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, value: State):
        """
        Descriptor to set states. Used to manage refresh task automatically.
        """
        # from PREINPUT to POSTINPUT, common scenerio
        # from POSTINPUT to RUNNING, common scenerio
        # from POSTINPUT to PREINPUT, happens when user cancels the election
        # from PREINPUT to RUNNING, happens when manual election is triggered
        # other cases, raise an error
        match (self._state, value):
            case (State.PREINPUT, State.POSTINPUT):
                self._start_refresh()
            case (State.POSTINPUT, State.RUNNING):
                pass
            case (State.POSTINPUT, State.PREINPUT):
                self._stop_refresh()
            case (State.PREINPUT, State.RUNNING):
                self._start_refresh()
            case _:
                raise ValueError(f"Invalid state transition: {self._state} -> {value}")
        self._state = value

    def _get_local_kb(self) -> KeyBindings:
        """Define local key bindings for the view."""
        kb = KeyBindings()

        @kb.add("c-s")
        def _c_s(event: KeyPressEvent):
            """Simulate scheduled execution for testing."""
            if self.state is not State.RUNNING:
                logger.info("🧪 [TEST] Simulating scheduled execution...")
                self._execute_election_background()

        @kb.add("c-x")
        def _c_x(event: KeyPressEvent):
            """Cancel current scheduling."""
            if self.state is State.POSTINPUT:
                self.cancel()

        @kb.add("home")
        def _home(event: KeyPressEvent, eager=True):
            """Return to the main menu."""
            if self.state is State.RUNNING:
                self.bus.publish(AppEvent.RETURN_TO_MAIN)

        return kb

    def _get_header(self):
        """Generate the header panel."""
        title = Text("Course Election Scheduler", style="bold cyan", justify="center")
        subtitle = Text("定时选课界面", style="dim", justify="center")
        panel = Panel(
            Group(title, subtitle),
            border_style="cyan",
            padding=(1, 2),
        )
        return self._get_rich_content(panel)

    def _get_course_list(self):
        """Display the list of courses to be scheduled."""
        table = Table(
            title=f"Courses to Schedule ({len(self.courses)})", show_header=True
        )
        table.add_column("No.", style="dim", width=4)
        table.add_column("Code", style="yellow", width=20)
        table.add_column("Course Name", style="cyan")
        table.add_column("Teachers", style="green")

        for i, course in enumerate(self.courses, 1):
            # Create a simple course overview
            table.add_row(
                str(i),
                course.code,
                course.name,
                ", ".join(course.teachers),
            )

        return self._get_rich_content(table)

    def _get_time_instructions(self):
        """Generate time input instructions."""
        instructions = [
            "[bold cyan] 请输入计划选课的时间 [/bold cyan]",
            "• 使用24小时制 (HH:MM)，例如：14:30，08:00",
            "• 如果该时间点已经过去，将安排于明天",
            "• Ctrl+S 将立刻向服务器发送选课请求",
            "• 请务必使用英文冒号分割小时与分钟",
        ]

        text = Text()
        for instruction in instructions:
            text.append_text(Text.from_markup(instruction + "\n"))
        return self._get_rich_content(text)

    def _get_status_panel(self):
        """Display current scheduling status."""
        now = datetime.now()
        if self.target_datetime is None:
            status = "✅ 选课请求已发送！"
            remaining = "🎯 请求由手动触发"
            status_color = "yellow"
        elif (sec := (self.target_datetime - now).total_seconds()) > 0:
            if self.state is State.POSTINPUT:
                hours, remainder = divmod(int(sec), 3600)
                minutes, seconds = divmod(remainder, 60)
                countdown = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                status = f"⏰ 选课请求计划于: {self.target_datetime.strftime('%Y-%m-%d %H:%M')}"
                remaining = f"⏳ 剩余时间: {countdown}"
                status_color = "green"
            elif self.state is State.RUNNING:
                status = "✅ 选课请求已发送！"
                remaining = "🎯 请求由手动触发"
                status_color = "yellow"
            else:
                raise RuntimeError("Unknown state")
        elif sec <= 0:
            status = "✅ 选课请求已发送！"
            remaining = "🎯 计划的选课时间已过去"
            status_color = "yellow"
        else:
            raise RuntimeError("Unknown state")

        content = Group(
            Text(status, style=f"bold {status_color}"),
            Text(remaining, style="cyan"),
        )

        panel = Panel(
            content,
            title="[bold green]Scheduling Status[/bold green]",
            border_style="green",
            padding=(1, 2),
        )

        return self._get_rich_content(panel)

    def _get_log_panel(self) -> ANSI:
        """Display scheduling and execution logs using rich logging."""

        return self.logger.get_log(self.service.config["settings"].get("log_lines", 0))

    def _get_shortcuts(self) -> ANSI:
        """Display control instructions."""
        match self.state:
            case State.PREINPUT:
                controls = "• [bold red]Ctrl+C[/bold red]: [bold]退出程序[/bold]  • [bold green]Ctrl+S[/bold green]: [bold]立即选课[/bold]"
            case State.POSTINPUT:
                controls = "• [bold red]Ctrl+C[/bold red]: [bold]退出程序[/bold]  • [bold green]Ctrl+S[/bold green]: [bold]立即选课[/bold]  • [bold yellow]Ctrl+X[/bold yellow]: [bold]编辑时间[/bold]"
            case State.RUNNING:
                controls = "• [bold red]Ctrl+C[/bold red]: [bold]退出程序[/bold]  • [bold green]Home[/bold green]: [bold]返回主页[/bold]"

        return self._get_rich_content(Text.from_markup(controls))

    def _start_refresh(self):
        """Start the auto-refresh page when scheduling begins."""
        if self._refresh_task is None:
            self._refresh_task = asyncio.create_task(self._refresh_loop())

    def _stop_refresh(self):
        """Stop auto-refreshing."""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            self._refresh_task = None

    async def _refresh_loop(self):
        """Refresh the UI and check schedule."""
        try:
            while True:
                # Check for scheduled jobs and update UI
                schedule.run_pending()
                get_app().invalidate()
                # app.invalidate()

                await asyncio.sleep(0.5)  # refresh every 0.5 sec
        except asyncio.CancelledError:
            pass

    def _handle_time_input(self, buffer: Buffer) -> bool:
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
            self.target_datetime = target_datetime
            self.state = State.POSTINPUT

            # Schedule the job
            schedule.every().day.at(time_str).do(self._execute_election_background).tag(
                "election"
            )
            logger.info(
                f"✅ Election scheduled for {target_datetime.strftime('%Y-%m-%d %H:%M')}"
            )
            logger.info(f"📋 {len(self.courses)} courses will be processed")
            return True
        except Exception:
            return False

    def set_courses(self, courses: list[Course]):
        """Set the courses to be scheduled for election."""
        self.courses = courses
        logger.info(f"📚 Loaded {len(courses)} courses for scheduling")

    def cancel(self):
        """Cancel the current scheduling and return to input mode."""
        schedule.clear()
        self.target_datetime = None
        self.state = State.PREINPUT
        logger.info("❌ Scheduling cancelled - returning to input mode")
        self.layout.focus(self.time_input)

    def _execute_election_background(self):
        """
        Non-blocking wrapper scheduled by `schedule`.
        """
        if self.state is State.RUNNING:
            logger.warning("Election already in progress.")
            return None
        logger.debug("🚀 Starting course election process...")
        self.state = State.RUNNING
        self._election_spawned = True
        asyncio.create_task(self._execute_election_async())

    async def _execute_election_async(self):
        """turn the election job into async function

        implementing the "fire and forget" mechanism"""
        logger.debug("🚀 Starting course election process (async)...")

        for i, course in enumerate(self.courses):
            if i > 0:
                await asyncio.sleep(
                    self.service.config["settings"].get("course_delay", 0)
                )
            try:
                logger.info(
                    f"🎯 Attempting to elect course {i + 1}/{len(self.courses)}: {course.name}"
                )
                await asyncio.to_thread(
                    self.service.elect_course, course, self.service.Operation.ELECT
                )
                logger.info(f"✅ Successfully elected course: {course.name}")
            except Exception as e:
                logger.error(f"❌ 选课 {course.name} 失败: {e}")

        logger.debug("🎉 Course election completed!")
        schedule.clear("election")

    def _execute_election(self):
        """Execute the course election process."""
        logger.info("🚀 Starting course election process...")
        self.service.elect_courses(self.courses)
        schedule.clear("election")
        logger.info("🎉 Course election completed!")


# --- Main Application Logic ---
if __name__ == "__main__":
    from prompt_toolkit import Application

    from ..tests.dummy_service import dummy_service

    test_courses = [
        Course.from_row(row, dummy_service)
        for row in dummy_service.course_info.head(5).to_dicts()
    ]  # Take some rows
    view = ScheduleView(dummy_service, EventBus())
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
