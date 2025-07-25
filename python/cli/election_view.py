import io
import os
import re
from typing import Any, Generator

import polars as pl
from prompt_toolkit import PromptSession
from prompt_toolkit import print_formatted_text as print
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI, HTML
from rich.console import Console
from rich.table import Table

from python.shared import Course, Weekdays


class CourseCompleter(Completer):
    """
    A custom completer for courses that fuzzy searches course names and teacher names.
    """

    def __init__(self, df: pl.DataFrame):
        self.df = df
        self.candidates = [Course.from_row(row) for row in df.to_dicts()]

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
    A class responsible for storing elected course and conflict analysis.
    """

    def __init__(self):
        self.courses: list[Course] = []  # Changed from set to list
        self.conflicts: dict[
            str, set[str]
        ] = {}  # Use course IDs instead of Course objects

    def add_course(self, course: Course):
        # Check if course is already in curriculum
        for existing_course in self.courses:
            if existing_course.id == course.id:
                return False  # Course already exists
            if Course.overlaps(existing_course, course):
                self.conflicts.setdefault(existing_course.id, set()).add(course.id)
                self.conflicts.setdefault(course.id, set()).add(existing_course.id)
        self.courses.append(course)
        return True


class ElectionView:
    """
    A class responsible for accepting course selections and displaying the curriculum table with `rich`.
    The upper part of the screen is reserved for displaying the curriculum table,
    while the lower part is reserved for user input with prompted hints.
    """

    def __init__(self):
        self.io = io.StringIO()
        self.console = Console(file=self.io, force_terminal=True, width=100)
        self.session = PromptSession()
        self.curriculum = Curriculum()

    def clear_screen(self):
        """Clear the terminal screen."""
        os.system("cls" if os.name == "nt" else "clear")

    def display_layout(self):
        """Display the complete layout with curriculum table and instructions."""
        self.clear_screen()

        # Display curriculum table
        curriculum_output = self.get_curriculum_table()
        print(ANSI(curriculum_output))

        # Display selected courses summary
        if self.curriculum.courses:
            print(HTML("<b><ansigreen>Selected Courses:</ansigreen></b>"))
            for i, course in enumerate(self.curriculum.courses, 1):
                conflict_marker = (
                    " <ansired>⚠ CONFLICT</ansired>"
                    if course.id in self.curriculum.conflicts
                    else ""
                )
                print(
                    HTML(f"  {i}. {course.name} - {course.teachers}{conflict_marker}")
                )

        # Display conflicts if any
        if self.curriculum.conflicts:
            print(HTML("\n<b><ansired>Conflicts Detected:</ansired></b>"))
            for course_id, conflicting_course_ids in self.curriculum.conflicts.items():
                # Find course by ID
                course = next(
                    (c for c in self.curriculum.courses if c.id == course_id), None
                )
                if course:
                    conflict_names = []
                    for conf_id in conflicting_course_ids:
                        conf_course = next(
                            (c for c in self.curriculum.courses if c.id == conf_id),
                            None,
                        )
                        if conf_course:
                            conflict_names.append(conf_course.name)
                    if conflict_names:
                        conflict_list = ", ".join(conflict_names)
                        print(
                            HTML(f"  • {course.name} conflicts with: {conflict_list}")
                        )

        print("\n" + "=" * 80)
        print(HTML("<b><ansicyan>Commands:</ansicyan></b>"))
        print("  • Type course name/teacher to search and add")
        print("  • 'remove <number>' to remove a course by number")
        print("  • 'clear' to remove all courses")
        print("  • 'quit' or Ctrl+C to exit")
        print("=" * 80 + "\n")

    def add_course(self, course: Course):
        """Add a course to the curriculum."""
        return self.curriculum.add_course(course)

    def remove_course(self, index: int):
        """Remove a course by index (1-based)."""
        if 1 <= index <= len(self.curriculum.courses):
            course_to_remove = self.curriculum.courses[index - 1]
            self.curriculum.courses.remove(course_to_remove)

            # Clean up conflicts
            course_id = course_to_remove.id
            if course_id in self.curriculum.conflicts:
                # Remove this course from other courses' conflict lists
                for conflicting_course_id in self.curriculum.conflicts[course_id]:
                    if conflicting_course_id in self.curriculum.conflicts:
                        self.curriculum.conflicts[conflicting_course_id].discard(
                            course_id
                        )
                        if not self.curriculum.conflicts[conflicting_course_id]:
                            del self.curriculum.conflicts[conflicting_course_id]
                del self.curriculum.conflicts[course_id]

            return True
        return False

    def clear_all_courses(self):
        """Clear all courses from the curriculum."""
        self.curriculum.courses.clear()
        self.curriculum.conflicts.clear()

    def get_curriculum_table(self, classes: int = 14):
        """
        Displays a curriculum table based on schedule data.
        """

        table = Table(
            title="[bold cyan]Weekly Curriculum[/bold cyan]",
            show_header=True,
            header_style="bold magenta",
        )

        # Define columns
        table.add_column("Classes", style="dim", width=6)
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

        return output

    def run(self, df: pl.DataFrame):
        """Main application loop."""
        Course.df = df
        course_completer = CourseCompleter(df)

        try:
            while True:
                self.display_layout()

                user_input = self.session.prompt(
                    "Enter command or search for course: ",
                    completer=course_completer,
                    complete_while_typing=True,
                ).strip()

                if not user_input:
                    continue

                # Handle commands
                if user_input.lower() == "quit":
                    break
                elif user_input.lower() == "clear":
                    self.clear_all_courses()
                    continue
                elif user_input.lower().startswith("remove "):
                    try:
                        index = int(user_input.split(" ", 1)[1])
                        if self.remove_course(index):
                            print(
                                HTML(
                                    "<ansigreen>Course removed successfully!</ansigreen>"
                                )
                            )
                        else:
                            print(
                                HTML(
                                    f"<ansired>Invalid course number: {index}</ansired>"
                                )
                            )
                        input("Press Enter to continue...")
                    except (ValueError, IndexError):
                        print(
                            HTML(
                                "<ansired>Invalid remove command. Use: remove <number></ansired>"
                            )
                        )
                        input("Press Enter to continue...")
                    continue

                # Try to parse as course selection
                try:
                    course = Course.from_input(user_input)
                    if course:
                        if self.add_course(course):
                            print(
                                HTML(
                                    f"<ansigreen>Added: {course.name} - {course.teachers}</ansigreen>"
                                )
                            )
                        else:
                            print(
                                HTML(
                                    "<ansiyellow>Course already selected!</ansiyellow>"
                                )
                            )
                        input("Press Enter to continue...")
                    else:
                        print(
                            HTML(
                                "<ansired>Course not found. Please try again.</ansired>"
                            )
                        )
                        input("Press Enter to continue...")
                except Exception as e:
                    print(HTML(f"<ansired>Error adding course: {e}</ansired>"))
                    input("Press Enter to continue...")

        except KeyboardInterrupt:
            print(HTML("\n<ansiyellow>Exiting application...</ansiyellow>"))


# --- Main Application Logic ---
if __name__ == "__main__":
    try:
        # Load your DataFrame
        df = pl.read_json("data/output.json")

        # Create and run the election view
        election_view = ElectionView()

        print(
            HTML("<b><ansicyan>Welcome to SchedulEase Course Selection!</ansicyan></b>")
        )
        print("Loading course data...")
        input("Press Enter to start...")

        election_view.run(df)

    except FileNotFoundError:
        print(
            HTML(
                "<ansired>Error: Could not find 'data/output.json'. Please ensure the file exists.</ansired>"
            )
        )
    except Exception as e:
        print(HTML(f"<ansired>An error occurred: {e}</ansired>"))
