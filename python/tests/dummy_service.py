from functools import cached_property
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, Future
import httpx
import polars as pl
import random
from python.service import EamisService, Profile
import logging
from time import sleep

from python.shared import Course

logger = logging.getLogger(__name__)


class DummyEamisService(EamisService):
    """
    A dummy EamisService for testing purposes.
    It inherits from EamisService, loads course data from a local file,
    and mimics network methods to return empty/mock responses.
    """

    def __init__(self):
        """
        Initializes the dummy service. Bypasses the parent EamisService constructor
        to avoid needing a real config or httpx.Client.
        """
        self.data_path = Path(__file__).parent.parent / "data" / "output.json"
        logger.info(f"Dummy service initialized, Using test data from {self.data_path}")

    @cached_property
    def course_info(self) -> pl.DataFrame:
        """
        Overrides the parent property to load course information from a local JSON file.
        """
        if not self.data_path.exists():
            raise FileNotFoundError(
                f"Could not find test data at '{self.data_path}'. "
                "Please ensure the file exists."
            )
        logger.info(f"Loading test data from {self.data_path}")
        return pl.read_json(self.data_path)

    # --- Override network-bound methods ---

    def initial_connection(self) -> None:
        """Mimics a successful connection."""
        logger.info("Mimicking successful initial connection.")
        pass

    def login(self) -> httpx.Response:
        """Returns a mock successful login response."""
        logger.info("Mimicking successful login.")
        return httpx.Response(200, text="Mock login successful")

    @cached_property
    def postlogin_response(self) -> httpx.Response:
        """Returns a mock response."""
        logger.info("Mimicking post-login response.")
        return self.login()

    def get_profiles(self) -> list[Profile]:
        """Returns an empty list of profiles."""
        logger.info("Mimicking retrieval of profiles.")
        sleep(random.random())
        logger.info("Get profiles successfully!")
        return []

    def get_course_data(self, profile: Profile) -> list[dict[str, Any]]:
        """Returns an empty list of course data."""
        logger.info(f"Mimicking retrieval of course data for profile: {profile}")
        sleep(random.random())
        logger.info("Get course data successfully!")
        return []

    def get_all_course_info(self) -> pl.DataFrame:
        """Returns the DataFrame from the local file."""
        logger.info("Mimicking retrieval of all course information.")
        return self.course_info

    def elect_course(
        self,
        course: Course,
        operation: EamisService.Operation = EamisService.Operation.ELECT,
    ) -> None:
        """Mimics a successful course election."""
        logger.info(
            f"Mimicking successful election for course: {course}, operation: {operation}"
        )
        sleep(random.random())
        logger.info("Elect course successfully!")
        pass

    def elect_courses(self, courses: list[Course], max_delay: float = 0) -> None:
        """
        Elect multiple courses with optional delay.
        """
        # the usage of submit+future instead of map is to handle exceptions
        # that may occur during the election process
        logger.info(
            f"Electing {len(courses)} courses with max delay {max_delay} seconds."
        )
        with ThreadPoolExecutor(max_workers=len(courses)) as executor:
            # max_workers setting here is pretty safe
            # because I don't really expect any one to elect more than 10 courses at once...
            results: tuple[Future, ...] = tuple(
                executor.submit(
                    self.delay_task,
                    random.uniform(0, max_delay),
                    self.elect_course,
                    course,
                    EamisService.Operation.ELECT,
                )
                for course in courses
            )
            for future in results:
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Unexpected error: {e}")
        logger.info("Elect courses successfully!")
