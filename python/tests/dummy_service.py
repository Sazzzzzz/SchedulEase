from functools import cached_property
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from python.service import EamisService, Profile


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
        return pl.read_json(self.data_path)

    # --- Override network-bound methods ---

    def initial_connection(self) -> None:
        """Mimics a successful connection."""
        pass

    def login(self) -> httpx.Response:
        """Returns a mock successful login response."""
        return httpx.Response(200, text="Mock login successful")

    @cached_property
    def postlogin_response(self) -> httpx.Response:
        """Returns a mock response."""
        return self.login()

    def get_profiles(self) -> list[Profile]:
        """Returns an empty list of profiles."""
        return []

    def get_course_data(self, profile: Profile) -> list[dict[str, Any]]:
        """Returns an empty list of course data."""
        return []

    def get_all_course_info(self) -> pl.DataFrame:
        """Returns the DataFrame from the local file."""
        return self.course_info

    def elect_course(self, *args, **kwargs) -> None:
        """Mimics a successful course election."""
        pass

    def elect_courses(self, *args, **kwargs) -> None:
        """Mimics a successful batch course election."""
        pass
