import re
from typing import Any, Generator, NamedTuple, Optional

import polars as pl
from prompt_toolkit import PromptSession
from prompt_toolkit import print_formatted_text as print
from prompt_toolkit.completion import Completer, Completion


class Course(NamedTuple):
    id: str
    name: str
    code: str
    teachers: list[str]
    profileUrl: str
    profileId: str
    expLessonGroup: Optional[int]
    expLessonGroupNo: Optional[int]

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

    @property
    def query_string(self) -> str:
        """
        Return a string representation of the course ID and group number.
        """
        return (
            f"[{self.id}] {self.name}"
            if self.expLessonGroupNo is None
            else f"[{self.id}:{self.expLessonGroupNo}] {self.name}"
        )

    @staticmethod
    def from_query_string(query: str, df: pl.DataFrame) -> "Course":
        """
        Create a Course instance from a query string.
        The query string should be in the format "[id]" or "[id:groupNo]".
        """
        if m := re.match(r"\[(\d+):(\d+)\]", query):
            course_id = int(m.group(1))
            group_no = int(m.group(2))
            row = df.filter(
                (pl.col("id") == course_id) & (pl.col("expLessonGroupNo") == group_no)
            ).to_dicts()
        elif m := re.match(r"\[(\d+)\]", query):
            course_id = int(m.group(1))
            group_no = None
            row = df.filter(
                (pl.col("id") == course_id) & (pl.col("expLessonGroupNo").is_null())
            ).to_dicts()
        else:
            raise ValueError(f"Invalid query string format: {query}")

        if not row:
            raise ValueError(
                f"Course with id={course_id} and group_no={group_no} not found"
            )
        elif len(row) > 1:
            raise ValueError(
                f"Multiple courses found with id={course_id} and group_no={group_no}"
            )
        return Course.from_row(row[0])


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
            course = Course.from_query_string(selected_course, df)
            print(f"\nYou selected: {course.search_string}")

    except KeyboardInterrupt:
        print("\nExiting.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
