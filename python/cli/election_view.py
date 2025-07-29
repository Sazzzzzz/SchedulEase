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
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from python.cli.base_view import View
from python.service import EamisService
from python.shared import Course, Weekdays


class CourseCompleter(Completer):
    """
    A custom completer for courses that fuzzy searches course names and teacher names.
    """

    def __init__(self, service: EamisService):
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
    def __init__(self, service: EamisService) -> None:
        super().__init__()
        # Backend service
        self.service = service
        self.curriculum = Curriculum()
        self.completer = CourseCompleter(service)
        self.input = Buffer(
            completer=self.completer,
            complete_while_typing=True,
            accept_handler=self.add_course,
            multiline=False,
        )

        # Widgets
        self.focus_index = 0
        self.kb = self.get_local_kb()
        self.error_message = ""
        self.table = Window(
            content=FormattedTextControl(self.get_curriculum_table, focusable=False),
            wrap_lines=True,
        )
        self.election_list = Window(
            content=FormattedTextControl(self.get_election_list),
            wrap_lines=True,
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
        self.error_toolbar = ConditionalContainer(
            content=Window(
                content=FormattedTextControl(lambda: self.error_message),
                height=1,
                style="class:validation-error,bg:#ff0000, bg:#ffffff",
            ),
            filter=Condition(lambda: self.error_message != ""),
        )
        self.main = HSplit(
            [
                self.table,
                self.separator,
                self.election_list,
                self.separator,
                Window(
                    height=1,
                    content=FormattedTextControl(
                        text="Please enter a course name or teacher: ",
                        style="orange",
                    ),
                ),
                self.input_panel,
                self.error_toolbar,
            ]
        )

        self.layout = Layout(
            FloatContainer(
                content=self.main,
                floats=[
                    Float(
                        # TODO: Adjust position and size
                        content=CompletionsMenu(
                            # max_height=5, scroll_offset=1
                        ),
                        xcursor=True,
                        ycursor=True,
                    ),
                ],
                key_bindings=self.kb,
            )
        )

    def get_local_kb(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("left")
        def _(event):
            self.focus_index -= 1
            self.focus_index %= len(self.curriculum.courses) + 1

        @kb.add("right")
        def _(event):
            self.focus_index += 1
            self.focus_index %= len(self.curriculum.courses) + 1

        @kb.add("c-o")
        def _(event):
            if self.focus_index == 0:
                return None
            self.curriculum.remove_course(self.curriculum.courses[self.focus_index - 1])
            self.focus_index -= 1

        return kb

    def update_focus(self, index: int):
        if index == 0:
            self.layout.focus(self.input)
        else:
            self.layout.focus(self.election_list)

    def add_course(self, buffer: Buffer) -> bool:
        """Adds a course to the curriculum based on user input."""
        try:
            course = Course.from_input(buffer.text, self.service)
        except ValueError:
            self.error_message = "输入格式有误！请确保从课程列表中选择正确的课程名称。"
            return False
        self.error_message = ""
        return not self.curriculum.add_course(course)

    def get_curriculum_table(self, classes: int = 14) -> ANSI:
        # TODO: cleaner logic
        # Current logic is generated by AI
        """
        Displays a curriculum table based on schedule data.
        """

        table = Table(
            title="[bold cyan]Weekly Curriculum[/bold cyan]",
            show_header=True,
            header_style="bold magenta",
        )

        # Define columns
        table.add_column("Classes", style="dim")
        weekdays_list = list(Weekdays)
        for day in weekdays_list:
            table.add_column(day.value, justify="center")

        # Populate rows
        # 1. Create a grid to hold schedule data
        schedule_grid = {
            period: {day: "" for day in weekdays_list}
            for period in range(1, classes + 1)
        }

        # 2. Fill the grid with course information
        for course in self.curriculum.courses:
            for weekday, duration in course.duration.items():
                for period in range(duration.start, duration.end + 1):
                    if period in schedule_grid:
                        # Handle potential conflicts by appending names
                        if schedule_grid[period][weekday]:
                            schedule_grid[period][weekday] += (
                                f"\n[red]{course.name}[/red]"
                            )
                        else:
                            schedule_grid[period][weekday] = course.name

        # 3. Add rows to the rich table from the grid
        for period in range(1, classes + 1):
            row_data = [f"Class {period}"]
            for day in weekdays_list:
                row_data.append(schedule_grid[period][day])
            table.add_row(*row_data)

        return self.get_rich_content(table)

    def get_election_list(self) -> ANSI:
        """Display selected courses summary, conflicts, and commands."""
        renderables = []
        # Display commands
        command_text = Text.from_markup(
            """\
• 输入课程/老师名称添加课程
• 使用左右方向键选中已选课程
• 使用 Ctrl+O 删除选中课程"""
        )
        renderables.append(
            Panel(
                command_text,
                title="[bold cyan]Commands[/bold cyan]",
                border_style="cyan",
                padding=(1, 2),
                expand=False,
            )
        )

        # Display selected courses if any
        if not self.curriculum.courses:
            return self.get_rich_content(Group(*renderables))
        renderables.append(Text("Selected Courses:", style="bold green"))
        for i, course in enumerate(self.curriculum.courses, 1):
            if i == self.focus_index:
                line = Text(
                    f"  {i}. {course.name} - {'; '.join(course.teachers)}",
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
            return self.get_rich_content(Group(*renderables))
        renderables.append(Text("\nConflicts Detected:", style="bold red"))
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
            if len(conflicting_ids) == 1:
                conf_id = conflicting_ids.pop()
                conf_course = next(
                    (c for c in self.curriculum.courses if c.id == conf_id),
                )
                renderables.append(
                    Text(f"  • {course.name} 与 {conf_course.name} 冲突！")
                )
            else:
                renderables.append(
                    Text(
                        f"  • {course.name} 与 {', '.join(c.name for c in self.curriculum.courses if c.id in conflicting_ids)} 冲突！"
                    )
                )

        return self.get_rich_content(Group(*renderables))


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

    view = ElectionView(DummyEamisService())
    app = Application(layout=view.layout, full_screen=True, key_bindings=kb)
    app.run()
