"""
View object responsible for displaying and managing the course election process.
"""

from enum import Enum, auto
import re
from itertools import combinations
from typing import Any, Generator, Optional

from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.validation import ValidationError, Validator
from prompt_toolkit.widgets import ValidationToolbar
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..service import Service
from ..shared import AppEvent, Course, EventBus, Weekdays
from .base_view import View


class State(Enum):
    NORMAL = auto()
    CONFLICT = auto()


class CourseCompleter(Completer):
    """
    A custom completer for courses that fuzzy searches course names and teacher names.
    """

    def __init__(self, service: Service):
        self.service = service
        self.candidates = [
            Course.from_row(row, service) for row in service.course_info.to_dicts()
        ]

    def get_completions(
        self, document, complete_event
    ) -> Generator[Completion, Any, None]:
        """
        Yields completions based on the user's input.
        """
        text_to_match = document.text_before_cursor
        text_to_match = re.sub(r"\[\d+(?::\d+)?\]", " ", text_to_match).strip()
        if not text_to_match:
            return

        for course in self.candidates:
            if text_to_match in course.search_string:
                yield Completion(
                    text=course.query_string,
                    start_position=-len(document.text_before_cursor),
                    display=course.search_string,
                    display_meta=course.meta_string,
                )


class CourseValidator(Validator):
    def __init__(self, service: Service):
        self.service = service

    def validate(self, document) -> None:
        """
        Validates the course input against the service.
        Raises ValidationError if the course is not found.
        """
        query = document.text.strip()
        if not query:
            raise ValidationError(message="课程名称不能为空！")

        try:
            Course.from_input(query, self.service)
        except ValueError:
            raise ValidationError(
                message="输入格式有误！请从课程列表中选择正确的课程名称。"
            )


# TODO: fix the bug related to string Course id
class Curriculum:
    """
    A container class responsible for storing elected course and conflict analysis.
    """

    # TODO: support deleting course
    def __init__(self, initial_courses: Optional[list[Course]] = None):
        self.courses: list[Course] = initial_courses or []
        self.conflicts: dict[
            int, set[int]
        ] = {}  # Use course IDs instead of Course objects
        self._rebuild_conflicts()

    def add_course(self, course: Course):
        # Confliction Test
        for existing_course in self.courses:
            if (
                existing_course.id == course.id
                and existing_course.expLessonGroupNo == course.expLessonGroupNo
            ):
                return False  # Course already exists
            if Course.overlaps(existing_course, course):
                self.conflicts.setdefault(existing_course.id, set()).add(course.id)
                self.conflicts.setdefault(course.id, set()).add(existing_course.id)
        self.courses.append(course)
        return True

    def remove_course(self, course_to_remove: Course):
        """Removes a course and recalculates all conflicts."""
        self.courses.remove(course_to_remove)
        self._rebuild_conflicts()

    def _rebuild_conflicts(self):
        """Recalculates all conflicts from scratch."""
        self.conflicts.clear()
        for c1, c2 in combinations(self.courses, 2):
            if Course.overlaps(c1, c2):
                self.conflicts.setdefault(c1.id, set()).add(c2.id)
                self.conflicts.setdefault(c2.id, set()).add(c1.id)

    def clear_all(self):
        """Clears all courses and conflicts."""
        self.courses.clear()
        self.conflicts.clear()


# TUI implementation
class ElectionView(View):
    # TODO: add feature to save current course list
    """Election Interface"""

    def __init__(self, service: Service, bus: EventBus) -> None:
        super().__init__()
        # Backend service
        self.service = service
        self.bus = bus
        self.curriculum = Curriculum()
        self.state = State.NORMAL
        self.error_message = ""
        self.register()
        self.create_layout()

    def register(self):
        self.bus.subscribe(AppEvent.APP_NO_SCHEDULE_VIEW, self.on_no_schedule_view)

    def on_no_schedule_view(self):
        self.error_message = "预览模式下无法进入选课界面"

    def create_layout(self):
        self.completer = CourseCompleter(self.service)
        self.input = Buffer(
            completer=self.completer,
            complete_while_typing=True,
            accept_handler=self.add_course,
            multiline=False,
            validator=CourseValidator(self.service),
            validate_while_typing=True,
            enable_history_search=False,
        )

        # Widgets
        self.table = Window(
            content=FormattedTextControl(self._get_curriculum_table, focusable=False),
            wrap_lines=True,
        )
        self.election_list = ConditionalContainer(
            Window(
                content=FormattedTextControl(self._get_election_list, focusable=True),
                wrap_lines=True,
            ),
            filter=Condition(lambda: len(self.curriculum.courses) > 0),
        )
        self.input_panel = VSplit(
            [
                # A non-focusable window for the "> " prompt.
                Window(
                    content=FormattedTextControl("> ", style="orange"),
                    width=2,
                    dont_extend_width=True,
                ),
                # The actual input buffer window.
                Window(content=BufferControl(buffer=self.input)),
            ]
        )
        self.error_toolbar = ValidationToolbar()
        self.error_message_box = ConditionalContainer(
            Window(
                content=FormattedTextControl(
                    lambda: self.error_message,
                    style="bold red",
                ),
                height=1,
                wrap_lines=True,
            ),
            filter=Condition(lambda: self.error_message != ""),
        )
        self.conditional_separator = ConditionalContainer(
            self.separator,
            filter=Condition(lambda: len(self.curriculum.courses) > 0),
        )
        self.prompt = Window(
            height=6,
            content=FormattedTextControl(self._get_prompt),
        )
        self.shortcuts = Window(
            height=2,
            content=FormattedTextControl(self._get_shortcuts),
        )
        self.completions_menu = CompletionsMenu(max_height=12, scroll_offset=1)
        self.main = HSplit(
            [
                self.table,
                self.separator,
                self.election_list,
                self.conditional_separator,
                self.prompt,
                self.input_panel,
                self.error_message_box,
                self.shortcuts,
                self.error_toolbar,
            ]
        )

        self.layout = Layout(
            FloatContainer(
                content=self.main,
                floats=[
                    Float(
                        # TODO: Adjust position and size
                        content=self.completions_menu,
                        xcursor=True,
                        ycursor=True,
                    ),
                ],
                key_bindings=self._get_local_kb(),
            )
        )
        self.focus_index = 0

    def _get_local_kb(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("left", filter=Condition(lambda: self.state is State.NORMAL))
        def _left(event):
            self.focus_index -= 1

        @kb.add("right", filter=Condition(lambda: self.state is State.NORMAL))
        def _right(event):
            self.focus_index += 1

        @kb.add(
            "backspace",
            eager=True,
            filter=Condition(
                lambda: self.layout.has_focus(self.election_list)
                and self.state is State.NORMAL
            ),
        )
        def _backspace(event):
            if self.focus_index == 0:
                return None
            self.curriculum.remove_course(self.curriculum.courses[self.focus_index - 1])
            self.focus_index -= 1

        @kb.add("c-s", filter=Condition(lambda: self.state is State.NORMAL))
        def _c_s(event):
            if not self.curriculum.courses:
                self.error_message = "请至少选择一门课程！"
                return None
            if self.curriculum.conflicts:
                self.error_message = "课程存在冲突！若要坚持选课，可能会造成选课失败。"
                self.state = State.CONFLICT
                return None
            self.bus.publish(AppEvent.ELECTION_CONFIRMED, self.curriculum.courses)

        @kb.add("y", filter=Condition(lambda: self.state is State.CONFLICT))
        def _y(event):
            self.state = State.NORMAL
            self.error_message = ""
            self.bus.publish(AppEvent.ELECTION_CONFIRMED, self.curriculum.courses)

        @kb.add("n", filter=Condition(lambda: self.state is State.CONFLICT))
        def _n(event):
            self.state = State.NORMAL
            self.error_message = ""

        return kb

    def _get_shortcuts(self) -> ANSI:
        if self.state is State.NORMAL:
            return self._get_rich_content(
                Text.from_markup(
                    "• [bold red]Ctrl+C[/bold red]: [bold]退出程序[/bold]  • [bold cyan]Left/Right[/bold cyan]: [bold]切换选中课程[/bold]  • [bold green]Backspace[/bold green]: [bold]删除课程[/bold]  • [bold yellow]Ctrl+S[/bold yellow]: [bold]下一步[/bold]",
                )
            )
        else:
            return self._get_rich_content(
                Text.from_markup(
                    "• [bold red]N[/bold red]: [bold]返回修改[/bold]  • [bold green]Y[/bold green]: [bold]确定选课[/bold]",
                )
            )

    def _get_curriculum_table(self, classes: int = 14) -> ANSI:
        """
        Displays a curriculum table with 2-line rows showing course names and locations/conflicts.
        """
        table = Table(
            title="[bold cyan]Weekly Curriculum[/bold cyan]",
            show_header=True,
            header_style="bold magenta",
        )

        # Define columns
        table.add_column("Classes", style="italic", justify="center")
        weekdays_list = list(Weekdays)
        for day in weekdays_list:
            table.add_column(day.value, justify="center")

        # Create schedule grid to hold course lists for each time slot
        schedule_grid = {
            period: {day: [] for day in weekdays_list}
            for period in range(1, classes + 1)
        }

        # Populate schedule grid with courses
        for course in self.curriculum.courses:
            for weekday, duration in course.duration.items():
                for period in range(duration.start, duration.end + 1):
                    if period in schedule_grid:
                        schedule_grid[period][weekday].append(course)

        # Build table rows with 2-line format
        for period in range(1, classes + 1):
            row_data = [f"Class {period}"]

            for weekday in weekdays_list:
                courses_in_slot: list[Course] = schedule_grid[period][weekday]

                if not courses_in_slot:
                    # Empty slot - add empty 2-line cell
                    cell_content = "\n"
                elif len(courses_in_slot) == 1:
                    # Single course - show name on first line, location on second line
                    course = courses_in_slot[0]
                    cell_content = f"{course.name}\n"
                else:
                    # Multiple courses (conflict) - show first course name on first line,
                    # second course name in red on second line
                    main_course = courses_in_slot[0]
                    conflict_course = courses_in_slot[1]
                    cell_content = (
                        f"{main_course.name}\n[red]{conflict_course.name}[/red]"
                    )

                row_data.append(cell_content)

            table.add_row(*row_data)

        return self._get_rich_content(table)

    def _get_prompt(self) -> ANSI:
        message = """\
• 输入课程/老师名称添加课程
• 程序将自动进行冲突检测，无需提前排除冲突课程"""
        return self._get_rich_content(
            Panel(
                Text.from_markup(message),
                title="[bold cyan]Commands[/bold cyan]",
                border_style="cyan",
                padding=(1, 2),
                expand=False,
            )
        )

    def _get_election_list(self) -> ANSI:
        """Display selected courses summary, conflicts, and commands."""
        renderables = []

        renderables.append(Text("Selected Courses:", style="bold green"))
        for i, course in enumerate(self.curriculum.courses, 1):
            if i == self.focus_index:
                line = Text(
                    f" › {i}. {course.name} - {'; '.join(course.teachers)}",
                    style="cyan bold",
                )
            else:
                line = Text(f"  {i}. {course.name} - {'; '.join(course.teachers)}")
            if course.id in self.curriculum.conflicts:
                line.append(" ⚠ CONFLICT", style="bold red")
            renderables.append(line)

        # Display conflicts if any

        # This was first implemented to avoid duplicate pairs
        # but later simplified to just list all conflicts
        # The confliction between classes is essentially a graph
        # By displaying all conflicts, one could make sense of the full picture
        # of conflicts and resolve them accordingly
        if not self.curriculum.conflicts:
            return self._get_rich_content(Group(*renderables))
        renderables.append(Text("\nConflicts Detected:", style="bold red"))
        # TODO: Nasty logic, fix later
        for course_id, conflicting_ids in self.curriculum.conflicts.items():
            course = next(
                (c for c in self.curriculum.courses if c.id == course_id), None
            )
            if not course:
                continue
            # for conf_id in conflicting_ids:
            #     conf_course = next(
            #         (c for c in self.curriculum.courses if c.id == conf_id),
            #         None,
            #     )
            #     if conf_course:
            #         renderables.append(
            #             Text(f"  • {course.name} 与 {conf_course.name} 冲突！")
            #         )
            if (num_conflicts := len(conflicting_ids)) == 1:
                conf_id = next(iter(conflicting_ids))
                conf_course = next(
                    (c for c in self.curriculum.courses if c.id == conf_id),
                )
                renderables.append(
                    Text(f"  • {course.name} 与 {conf_course.name} 冲突！")
                )
            elif num_conflicts > 1:
                renderables.append(
                    Text(
                        f"  • {course.name} 与 {', '.join(c.name for c in self.curriculum.courses if c.id in conflicting_ids)} 冲突！"
                    )
                )

        return self._get_rich_content(Group(*renderables))

    def _update_focus(self, index: int):
        if index == 0:
            self.layout.focus(self.input)
        else:
            self.layout.focus(self.election_list)

    @property
    def focus_index(self) -> int:
        """Get the current focus index.

        focus_index = 0: input field
        focus_index > 0: election list, index corresponds to the course in the list"""
        return self._focus_index

    @focus_index.setter
    def focus_index(self, value: int) -> None:
        self._focus_index = value % (len(self.curriculum.courses) + 1)
        self._update_focus(self._focus_index)

    def add_course(self, buffer: Buffer) -> bool:
        """Adds a course to the curriculum based on user input."""
        course = Course.from_input(buffer.text, self.service)
        self.error_message = ""
        return not self.curriculum.add_course(course)


if __name__ == "__main__":
    # This module is only responsible for certain views, not for running the application.
    # Following lines are for testing purposes only.
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyPressEvent

    from ..tests.dummy_service import dummy_service

    kb = KeyBindings()

    @kb.add("c-c")
    def _(event: KeyPressEvent):
        """Pressing Ctrl-C will exit the application."""
        event.app.exit()

    view = ElectionView(dummy_service, EventBus())
    app = Application(
        layout=view.layout,
        full_screen=True,
        key_bindings=kb,
    )
    app.run()
