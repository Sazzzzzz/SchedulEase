from typing import NamedTuple, Optional

import polars as pl
from prompt_toolkit import PromptSession, prompt
from prompt_toolkit import print_formatted_text as print
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style

style = Style.from_dict(
    {
        "course": "#ff0066",
        "code": "#00ff44",
        "teacher": "#44ff00 italic",
    }
)


class Course(NamedTuple):
    id: str
    name: str
    code: str
    teachers: list[str]
    profileUrl: str
    profileId: str
    expLessonGroup: Optional[str]
    expLessonGroupNo: Optional[str]

    @property
    def display_string(self) -> FormattedText:
        return FormattedText(
            [
                ("class:code", f" {self.code} "),
                ("class:course", self.name),
                ("class:teacher", " ".join(self.teachers)),
            ]
        )

    @property
    def search_string(self) -> str:
        """Return a string for displaying the course."""
        return f"{self.code} {self.name} {' '.join(self.teachers)}"

    @property
    def meta_string(self) -> str:
        """Return a string for displaying additional information."""
        return f"{self.id} {f'Group: {self.expLessonGroupNo}' if self.expLessonGroupNo else ''}"

    @staticmethod
    def from_row(row: dict) -> "Course":
        """
        Create a Course instance from a Polars DataFrame row.
        """
        return Course(
            id=row["id"],
            name=row["name"],
            code=row["code"],
            teachers=list(row["teachers"]),
            profileUrl=row["profileUrl"],
            profileId=row["profileId"],
            expLessonGroup=row["expLessonGroup"],
            expLessonGroupNo=row["expLessonGroupNo"],
        )


class CourseCompleter(Completer):
    """
    A custom completer for courses that fuzzy searches course names and teacher names.
    """

    def __init__(self, df: pl.DataFrame):
        self.df = df
        self.candidates = [Course.from_row(row) for row in df.to_dicts()]

    def get_completions(self, document, complete_event):
        """
        Yields completions based on the user's input.
        """
        text_to_match = document.text_before_cursor

        if not text_to_match:
            return

        for course in self.candidates:
            if text_to_match in course.search_string:
                yield Completion(
                    text=course.name,
                    start_position=-len(document.text_before_cursor),
                    display=course.display_string,  # How the suggestion is shown in the dropdown
                    display_meta=course.meta_string,
                )


# --- Main Application Logic ---
if __name__ == "__main__":
    session = PromptSession()
    try:
        # Load your DataFrame
        df = pl.read_json("data/output.json")
        course_completer = CourseCompleter(df)

        print("Search for a course by name or teacher. Press Tab for suggestions.")
        print("Select a course to see its ID. Press Ctrl+C to exit.")

        while True:
            selected_course = session.prompt(
                "Course Search: ",
                completer=course_completer,
                complete_while_typing=True,
            )
            print(f"\nYou selected: {selected_course}")

    except KeyboardInterrupt:
        print("\nExiting.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
