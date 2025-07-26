import io
import re
from itertools import combinations
from typing import Any, Generator, Optional

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.layout.containers import Float, FloatContainer, HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.menus import CompletionsMenu
from rich.console import Console
from rich.table import Table

from python.service import EamisService
from python.shared import Course, Weekdays

# TODO: fix the bug related to string Course id


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
class ElectionView:
    def __init__(self, service: EamisService) -> None:
        self.service = service
        self.curriculum = Curriculum()
        self.completer = CourseCompleter(service)
        self.input = Buffer(
            completer=self.completer,
            complete_while_typing=True,
            accept_handler=self.add_course,
            multiline=False,
        )
        self.main = HSplit(
            [
                # temporarily disabled curriculum table
                Window(
                    content=FormattedTextControl(
                        self.get_curriculum_table, focusable=False
                    ),
                    wrap_lines=True,
                ),
                Window(height=1, char="-"),
                Window(content=BufferControl(buffer=self.input)),
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
            )
        )

        self.io = io.StringIO()
        self.console = Console(
            file=self.io,
            force_terminal=True,
            # TODO: May be adjusted later
            width=150,
        )

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

        self.console.print(table)
        output = self.io.getvalue()
        self.io.seek(0)
        self.io.truncate(0)

        return ANSI(output)

    def add_course(self, buffer: Buffer) -> bool:
        """Adds a course to the curriculum based on user input."""
        course = Course.from_input(buffer.text, self.service)
        return not self.curriculum.add_course(course)


if __name__ == "__main__":
    # This module is only responsible for certain views, not for running the application.
    # Following lines are for testing purposes only.
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

    from python.tests.dummy_service import DummyEamisService

    kb = KeyBindings()

    @kb.add("c-c")
    def _(event: KeyPressEvent):
        """Pressing Ctrl-C will exit the application."""
        event.app.exit()

    view = ElectionView(DummyEamisService())
    app = Application(layout=view.layout, full_screen=True, key_bindings=kb)
    app.run()
