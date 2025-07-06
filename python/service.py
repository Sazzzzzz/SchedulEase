import re
from collections import OrderedDict
from datetime import datetime
from typing import Any, NamedTuple
from functools import cached_property
import hjson
import httpx
from bs4 import BeautifulSoup, Tag

from config import load_config

# API URLs
LOGIN_URL = httpx.URL("https://iam.nankai.edu.cn")
EAMIS_URL = httpx.URL("https://eamis.nankai.edu.cn")
LOGIN_API = LOGIN_URL.join("/api/v1/login?os=web")
SITE_URL = EAMIS_URL.join("/eams/homeExt.action")
PROFILE_URL = EAMIS_URL.join("/eams/stdElectCourse.action")
COURSE_INFO_URL = EAMIS_URL.join("/eams/stdElectCourse!data.action")


class ServiceError(Exception):
    """Base exception for service."""


class ConnectionError(ServiceError):
    """Raised for network or connection-related errors."""


class LoginError(ServiceError):
    """Raised for login-related errors."""


class ParseError(ServiceError):
    """Raised for errors in parsing data from the service, likely due to changes in the API or HTML structure."""


class Profile(NamedTuple):
    title: str
    url: httpx.URL
    id: str

class EamisService:
    @staticmethod
    def create_timestamp():
        now = datetime.now()
        timestamp = int(now.timestamp() * 1000)
        return timestamp

    def __init__(self, config) -> None:
        self.client = httpx.Client()
        self.base_url: str = config["service"]["eamis_url"]
        self.account: str = config["user"]["account"]
        self.password: str = config["user"]["password"]
        self.encrypted_password: str = config["user"]["encrypted_password"]

        self.client.headers.update(OrderedDict(config["headers"]))

    def initial_connection(self) -> None:
        try:
            response = self.client.get(self.base_url)
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
        if code != 0:
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
                params={"_": self.create_timestamp()},
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

    def get_course_info(self, profile: Profile) -> Any | dict[Any, Any]:
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
        return hjson.loads(info)

    def get_all_course_info(self) -> dict[str, Any]:
        """Fetch all course information for the user."""

        all_course_info = {}
        for profile in self.profiles:
            course_info = self.get_course_info(profile)
            all_course_info[profile.id] = course_info

        return all_course_info

    # TODO: Should I store values in self as the program progresses? for example dataframe?


if __name__ == "__main__":
    config = load_config()
    service = EamisService(config)
    print(service.get_all_course_info())
