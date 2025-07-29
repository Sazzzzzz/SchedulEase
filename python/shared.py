from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING, Any, NamedTuple, Optional, Self

import polars as pl

if TYPE_CHECKING:
    from python.service import EamisService


class Weekdays(enum.Enum):
    MONDAY = "Monday"
    TUESDAY = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY = "Thursday"
    FRIDAY = "Friday"
    SATURDAY = "Saturday"
    SUNDAY = "Sunday"

    @staticmethod
    def from_index(index: int) -> Weekdays:
        """
        Convert an index (1-7) to a Weekdays enum.
        """
        if 1 <= index <= len(Weekdays):
            return list(Weekdays)[index - 1]
        raise ValueError(f"Index {index} is out of range for Weekdays enum.")


class Duration(NamedTuple):
    """
    NamedTuple representing a time duration with start and end units.

    Basically dedicated to `Course` class to represent its time slots.
    """

    start: int
    end: int

    @staticmethod
    def overlaps(duration1: Duration, duration2: Duration) -> bool:
        """
        Check if two durations overlap.
        """
        return duration1.start <= duration2.end and duration2.start <= duration1.end

    @staticmethod
    def default() -> "Duration":
        """
        Return a default Duration that does not overlap with any other.
        """
        return Duration(start=0, end=0)


@dataclass(frozen=True)
class Course:
    """
    Class representing a course with its details.
    """

    id: int
    name: str
    code: str
    teachers: list[str]
    profileUrl: str
    profileId: str
    expLessonGroup: Optional[int]
    expLessonGroupNo: Optional[int]

    # Every Course instance will have a reference to father service
    # This is to avoid hidden dependencies on the EamisService on class level
    # And the memory overhead is negligible
    service: EamisService = field(repr=False, hash=False, compare=False)

    # These are two factories to create a Course instance
    # Actually `@classmethod` and `@staticmethod` are interchangeable here because no inheritance is used
    @classmethod
    def from_input(cls, query: str, service: EamisService) -> Course:
        """
        Create a Course instance from a query string.
        The query string should be in the format "[id]" or "[id:groupNo]".
        Otherwise raise a ValueError.
        """
        if m := re.match(r"\[(\d+):(\d+)\]", query):
            course_id = int(m.group(1))
            group_no = int(m.group(2))
            row = service.course_info.filter(
                (pl.col("id") == course_id) & (pl.col("expLessonGroupNo") == group_no)
            ).to_dicts()
        elif m := re.match(r"\[(\d+)\]", query):
            course_id = int(m.group(1))
            group_no = None
            row = service.course_info.filter(
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
        return Course.from_row(row[0], service)

    @classmethod
    def from_row(cls, row: dict[str, Any], service: EamisService) -> Self:
        """
        Create a Course instance from a Polars DataFrame row.
        """
        return cls(
            # TODO: Use `str` for course id
            id=row["id"],
            name=row["name"],
            code=row["code"],
            teachers=list(row["teachers"]),
            profileUrl=row["profileUrl"],
            profileId=row["profileId"],
            expLessonGroup=row["expLessonGroup"],
            expLessonGroupNo=row["expLessonGroupNo"],
            service=service,
        )

    # This method can stay as it operates on two instances
    @staticmethod
    def overlaps(course1: Course, course2: Course) -> bool:
        """
        Check if two courses overlap based on their time slots.
        """
        return any(
            Duration.overlaps(
                course1.duration.get(weekday, Duration.default()),
                course2.duration.get(weekday, Duration.default()),
            )
            for weekday in Weekdays
        )

    @cached_property
    def search_string(self) -> str:
        """Return a string for displaying the course."""
        return f"{self.code} {self.name} {' '.join(self.teachers)}"

    @cached_property
    def meta_string(self) -> str:
        """Return a string for displaying additional information."""
        return f"{self.id} {f'Group: {self.expLessonGroupNo}' if self.expLessonGroupNo else ''}"

    @cached_property
    def query_string(self) -> str:
        """
        Return a string representation of the course ID and group number.
        """
        return (
            f"[{self.id}] {self.name}"
            if self.expLessonGroupNo is None
            else f"[{self.id}:{self.expLessonGroupNo}] {self.name}"
        )

    @cached_property
    def specifics(self) -> dict[str, Any]:
        """
        Get specific details about a course from the DataFrame.
        """
        # This still relies on the df, which is acceptable if you see
        # Course as a "view" into the main DataFrame.
        course_details = self.service.course_info.filter(
            (pl.col("id") == self.id)
            & (
                pl.col("expLessonGroupNo") == self.expLessonGroupNo
                if self.expLessonGroupNo is not None
                else pl.col("expLessonGroupNo").is_null()
            )
        ).to_dicts()

        if not course_details:
            raise ValueError(f"Course with id={self.id} not found")

        return course_details[0]

    @cached_property
    def duration(self) -> dict[Weekdays, Duration]:
        """
        Get the duration of a course based on its schedule.
        This method assumes that one class would not have multiple time slots on the same day.
        """
        arrange_info = self.specifics.get("arrangeInfo", [])
        if not arrange_info:
            return {}
        return {
            Weekdays.from_index(arrangement["weekDay"]): Duration(
                start=arrangement["startUnit"],
                end=arrangement["endUnit"],
            )
            for arrangement in arrange_info
        }
