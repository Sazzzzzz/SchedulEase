import enum
import re
from collections import OrderedDict
from datetime import datetime
from functools import cached_property
from itertools import chain
from typing import Any, Iterable, NamedTuple, TypeAlias, cast

import hjson
import httpx
import polars as pl
from bs4 import BeautifulSoup, Tag

from config import load_config
from shared import Course

# API URLs
LOGIN_URL = httpx.URL("https://iam.nankai.edu.cn")
EAMIS_URL = httpx.URL("https://eamis.nankai.edu.cn")
LOGIN_API = LOGIN_URL.join("/api/v1/login?os=web")
SITE_URL = EAMIS_URL.join("/eams/homeExt.action")
PROFILE_URL = EAMIS_URL.join("/eams/stdElectCourse.action")
COURSE_INFO_URL = EAMIS_URL.join("/eams/stdElectCourse!data.action")
ELECT_URL = EAMIS_URL.join("/eams/stdElectCourse!batchOperator.action")


class ServiceError(Exception):
    """Base exception for service."""


class ConnectionError(ServiceError):
    """Raised for network or connection-related errors."""


class LoginError(ServiceError):
    """Raised for login-related errors."""


class ParseError(ServiceError):
    """Raised for errors in parsing data from the service, likely due to changes in the API or HTML structure."""

class ElectError(ServiceError):
    """Raised for errors during course election, such as failure to elect or cancel a course."""

class Profile(NamedTuple):
    title: str
    url: httpx.URL
    id: str


CourseInfo: TypeAlias = dict[str, Any]


class EamisService:
    # "startWeek", "endWeek", "credits" can be added later if needed
    COURSE_FIELDS = [
        "id",
        "name",
        "code",
        "profileId",
        "profileUrl",
        "teachers",
        "campusName",
        "arrangeInfo",
        "expLessonGroups",
    ]
    SCHEDULE_FIELDS = [
        "weekDay",
        "startUnit",
        "endUnit",
        "rooms",
        "expLessonGroupNo",
    ]

    class Operation(enum.Enum):
        """Enum for course operations."""

        ELECT = True
        CANCEL = False

    @staticmethod
    def create_timestamp():
        now = datetime.now()
        timestamp = int(now.timestamp() * 1000)
        return timestamp

    def __init__(self, config: dict[str, Any]) -> None:
        self.client = httpx.Client()
        self.account: str = config["user"]["account"]
        self.password: str = config["user"]["password"]
        self.encrypted_password: str = config["user"]["encrypted_password"]

        self.client.headers.update(OrderedDict(config["headers"]))

    def initial_connection(self) -> None:
        try:
            response = self.client.get(EAMIS_URL, follow_redirects=False)
            response.raise_for_status()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to EAMIS service: {e}") from e
        self.client.headers["Sec-Fetch-Site"] = "same-origin"

    # These cached properties exist to ensure:
    # 1. The login process is only executed once per instance.
    # 2. The values will be available when accessed instead of manual invocation.
    @cached_property
    def postlogin_response(self) -> httpx.Response:
        """Cached property to store the response after login."""
        return self.login()

    def login(self):
        """Login to EAMIS service.
        Known response codes:
        CODE_MAPPING = {
            0: "Success",
            40000: "Parameter error",
            10110001: "Account or password incorrect",
        }
        """
        # Redirect to site
        try:
            prelogin_response = self.client.get(SITE_URL, follow_redirects=True)
            prelogin_response.raise_for_status()
        except Exception as e:
            raise ConnectionError(f"Failed to access EAMIS initial URL: {e}") from e

        # API call to login
        login_headers: OrderedDict[str, str] = OrderedDict(
            {
                "Cache-Control": "no-cache",
                "Content-Type": "application/json",
                "Csrf-Token": self.client.cookies.get("csrf-token", ""),  # type: ignore
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
                "Referer": str(prelogin_response.url),
            }
        )
        try:
            login_response = self.client.post(
                LOGIN_API,
                json={
                    "login_scene": "feilian",
                    "account_type": "userid",
                    "account": self.account,
                    "password": self.encrypted_password,
                },
                headers=login_headers,
            )
            login_response.raise_for_status()
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to log in to EAMIS service: {e}") from e
        content = login_response.json()
        try:
            code, message = content["code"], content["message"]
        except KeyError as e:
            raise ServiceError(f"Unexpected response format: {content}") from e
        match code:
            case 0:
                pass
            case 10110001:
                raise LoginError(
                    f"Login failed: {message}. Please check your account and password."
                )
            case 40000:
                raise LoginError(
                    f"Login failed: {message}. Parameter error, likely due to a change in the API format."
                )
            case _:
                raise LoginError(f"Login failed with code {code}: {message}")
        try:
            link = LOGIN_URL.join(content["data"]["next"]["link"])
        except KeyError as e:
            raise ServiceError(
                f"Missing 'next' link in response: {content}, likely due to a change in the API format, or login for multiple times."
            ) from e
        return self.client.get(link, follow_redirects=True)

    @cached_property
    def profiles(self) -> list[Profile]:
        """Cached property to store course profiles after fetching them."""
        return self.get_profiles()

    def get_profiles(self) -> list[Profile]:
        """Fetch election categories available for the user."""
        try:
            course_elect_menu_response = self.client.get(
                PROFILE_URL,
                headers={
                    "Referer": str(self.postlogin_response.url),
                    "X-Requested-With": "XMLHttpRequest",
                },
                params={"_": EamisService.create_timestamp()},
                follow_redirects=True,
            )
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to fetch course election menu: {e}") from e
        except Exception as e:
            raise ConnectionError(
                f"An unknown error occurred while fetching course election menu: {e}"
            ) from e
        soup = BeautifulSoup(course_elect_menu_response.content, "lxml")

        # Check if the course election menu is available
        if soup.find(string=re.compile(r"无法选课")):
            raise ServiceError("Course election menu is currently not available.")
        # TODO: Add logic when course election menu is not available
        selection_divs = soup.find_all("div", id=re.compile(r"^electIndexNotice\d+$"))

        course_categories: list[Profile] = []
        for div in selection_divs:
            assert isinstance(div, Tag), "Expected a Tag object"
            try:
                title_element = div.find("h3")
                assert title_element is not None, "Title element not found"
                title = title_element.get_text(strip=True)

                link_element = div.find("a", href=True)
                assert isinstance(link_element, Tag), "Link element not found"
                href = link_element.get("href")
                assert isinstance(href, str), "href attribute not found in link element"
                profile_id = href.split("=")[-1] if "=" in href else None
                assert profile_id is not None, "Profile ID not found in href"

            except Exception as e:
                raise ParseError(
                    f"Failed to parse course category: {e}. Likely due to changes in the HTML structure."
                ) from e
            course_categories.append(
                Profile(
                    title=title,
                    url=EAMIS_URL.join(href),
                    id=profile_id,
                )
            )

        return course_categories

    def get_course_data(self, profile: Profile) -> list[CourseInfo]:
        try:
            course_info = self.client.get(
                COURSE_INFO_URL,
                params={"profileId": profile.id},
                headers={
                    "Referer": str(profile.url),
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
        except Exception as e:
            raise ConnectionError(f"Failed to fetch course info: {e}") from e
        course_info_parsed = BeautifulSoup(course_info.content, "lxml")
        try:
            # Previous logic used to parse the course info for future reference:
            # info = (
            #     course_info_parsed.find("body")
            #     .find("p")  # type: ignore
            #     .get_text(strip=True)  # type: ignore
            #     .split("=", 1)[-1]
            #     .strip()
            # )[:-1]
            paragraph = course_info_parsed.select_one("body > p")
            assert paragraph is not None, "Paragraph element not found"
            info = paragraph.get_text(strip=True).split("=", 1)[-1].strip()[:-1]
        except Exception as e:
            raise ParseError(
                f"Failed to parse course info: {e}. Likely due to changes in the API return structure."
            ) from e
        raw_data = cast(list[CourseInfo], hjson.loads(info))
        return EamisService.process_raw_data(raw_data, profile)

    @cached_property
    def course_info(self) -> pl.DataFrame:
        """Cached property to store course information as a Polars DataFrame."""
        return self.get_all_course_info()

    def get_all_course_info(self) -> pl.DataFrame:
        """Fetch all course information for the user."""

        all_course_info = chain.from_iterable(
            self.get_course_data(profile) for profile in self.profiles
        )

        df = EamisService.create_dataframe(all_course_info)
        return df

    # The function is currently implemented with native Python
    # TODO: Optimize this function using Polars for better performance

    @staticmethod
    def process_raw_data(data: list[CourseInfo], profile: Profile) -> list[CourseInfo]:
        """Process raw course data from EAMIS service. Appends profile information to the data."""

        for course in data:
            course["profileId"] = profile.id
            course["profileUrl"] = str(profile.url)

        return data

    @staticmethod
    def expand_lesson_groups(df: pl.DataFrame) -> pl.DataFrame:
        """
        Expand courses with multiple lesson groups into separate rows.
        Each row will represent one lesson group with its filtered arrangements.
        """

        # First, let's create a helper function to process each row
        def process_row(row_data):
            """Process a single row and return list of expanded rows"""
            exp_lesson_groups = row_data["expLessonGroups"]
            arrange_info = cast(list[dict], row_data["arrangeInfo"])

            # If no lesson groups, create one row with None values
            if not exp_lesson_groups:
                return [
                    {
                        **{
                            col: row_data[col]
                            for col in row_data.keys()
                            if col not in ["expLessonGroups", "arrangeInfo"]
                        },
                        "expLessonGroupNo": None,
                        "expLessonGroup": None,
                        "arrangeInfo": [
                            {k: v for k, v in arr.items() if k != "expLessonGroupNo"}
                            for arr in arrange_info
                        ],
                    }
                ]

            # Create one row for each lesson group
            expanded_rows = []
            for local_group_no, server_group_id in exp_lesson_groups.items():
                # Filter arrangements for this specific lesson group
                filtered_arrangements = [
                    {k: v for k, v in arr.items() if k != "expLessonGroupNo"}
                    for arr in arrange_info
                    if arr.get("expLessonGroupNo") == local_group_no
                ]

                # Create new row
                new_row = {
                    **{
                        col: row_data[col]
                        for col in row_data.keys()
                        if col not in ["expLessonGroups", "arrangeInfo"]
                    },
                    "expLessonGroupNo": local_group_no,
                    "expLessonGroup": server_group_id,
                    "arrangeInfo": filtered_arrangements,
                }
                expanded_rows.append(new_row)

            return expanded_rows

        # Convert DataFrame to list of dicts for processing
        rows_data = df.to_dicts()

        # Process each row and flatten the results
        all_expanded_rows = []
        for row in rows_data:
            expanded = process_row(row)
            all_expanded_rows.extend(expanded)

        # Convert back to DataFrame
        return pl.DataFrame(all_expanded_rows)

    @staticmethod
    def create_dataframe(data: Iterable[CourseInfo]) -> pl.DataFrame:
        """Create a Polars DataFrame from the processed course data. Processes the data to keep only the fields of interest."""

        df = pl.DataFrame(data)
        # Preserve only the fields of interest and split teachers into list
        df = df.select(EamisService.COURSE_FIELDS).with_columns(
            pl.col("teachers").str.split(",").alias("teachers")
        )

        df = df.with_columns(
            # process expLessonGroups into dict
            pl.col("expLessonGroups").map_elements(
                lambda exp_list: {
                    item.get("indexNo"): item.get("id") for item in exp_list
                },
                return_dtype=pl.Object,
            ),
            # process arrangeInfo to keep only the fields of interest
            pl.col("arrangeInfo").map_elements(
                lambda arrange_list: [
                    {
                        field: item.get(field)
                        for field in EamisService.SCHEDULE_FIELDS
                        if field in item
                    }
                    for item in arrange_list
                ],
                return_dtype=pl.Object,
            ),
        )
        # Expand lesson groups into separate rows
        df = EamisService.expand_lesson_groups(df)
        return df

    def elect_course(self, course: Course, operation: Operation) -> None:
        """Elect or cancel a course."""
        opt = str(operation.value).lower()
        expGroup = course.expLessonGroup if course.expLessonGroup else "_"
        try:
            elect_response = self.client.post(
                ELECT_URL,
                headers={
                    "Referer": course.profileUrl,
                    "X-Requested-With": "XMLHttpRequest",
                },
                data={
                    "optype": opt,
                    "operator0": f"{course.id}:{opt}:0",
                    "lesson0": str(course.id),
                    f"expLessonGroup_{course.id}": expGroup,
                },
                params={"profileId": course.profileId},
            )
        except Exception as e:
            raise ConnectionError(f"Failed to elect course: {e}") from e

        soup = BeautifulSoup(elect_response.content, "lxml")
        if operation == EamisService.Operation.ELECT:
            match text := soup.get_text():
                case text if "选课成功" in text:
                    return None
                case text if "当前选课不开放" in text:
                    raise ElectError("Course election is currently not open.")
                case text if "已经选过" in text:
                    raise ElectError(f"Course {course.name} is already elected.")
                case text if "计划外名额已满" in text:
                    raise ElectError(
                        f"Course {course.name} is considered as extra and has no available spots."
                    )
                case _:
                    raise ElectError(
                        f"Failed to elect course {course.name}. Response: {text}"
                    )
        else:  # Cancel operation
            match text := soup.get_text():
                case text if "退课成功" in text:
                    return None
                case _:
                    raise ElectError(
                        f"Failed to cancel course {course.name}. Response: {text}"
                    )

    # TODO: Implement method for multiple course election
    # This requires error supressing; retry logic and concurrency control


if __name__ == "__main__":
    config = load_config()
    service = EamisService(config)
    service.get_profiles()
    # service.course_info
    # import json

    # test_profile = Profile(
    #     title="TestProfile",
    #     url=httpx.URL("https://eamis.nankai.edu.cn/fake_profile"),
    #     id="1234",
    # )
    # with open("test.json", "r", encoding="utf-8") as f:
    #     data = json.load(f)
    # df = EamisService.create_dataframe(
    #     EamisService.process_raw_data(data, test_profile)
    # )
    # df.write_json("data/output.json")