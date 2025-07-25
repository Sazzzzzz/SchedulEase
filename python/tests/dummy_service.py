from functools import cached_property
from pathlib import Path

import polars as pl

from python.service import EamisService


class DummyEamisService(EamisService):
    """
    A dummy EamisService for testing purposes.
    It inherits from EamisService, loads course data from a local file,
    and raises errors for network-related methods using __getattribute__.
    """

    # Methods that should not be called in the dummy service
    _mocked_methods = {
        "initial_connection",
        "login",
        "postlogin_response",
        "profiles",
        "get_profiles",
        "get_course_data",
        "get_all_course_info",
        "elect_course",
        "elect_courses",
    }

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

    def __getattribute__(self, name: str):
        """
        Intercepts attribute access. If the attribute is a mocked network method,
        it raises a NotImplementedError. Otherwise, it proceeds as normal.
        """
        if name in object.__getattribute__(self, "_mocked_methods"):
            raise NotImplementedError(
                f"'{name}' is a network-bound method and is not implemented in DummyEamisService."
            )
        return object.__getattribute__(self, name)
