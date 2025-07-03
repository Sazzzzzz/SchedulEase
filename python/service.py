from collections import OrderedDict
import re
from typing import NamedTuple

from bs4 import BeautifulSoup, Tag
import httpx

from config import load_config

config = load_config()

LOGIN_API = httpx.URL("https://iam.nankai.edu.cn/api/v1/login?os=web")
EAMIS_URL = httpx.URL(config["service"]["eamis_url"])
INITIAL_URL = EAMIS_URL.join("/eams/homeExt.action")


class ServiceError(Exception):
    """Base exception for service."""


class ConnectionError(ServiceError):
    """Raised for network or connection-related errors."""


class LoginError(ServiceError):
    """Raised for login-related errors."""

class ProfileError(ServiceError):
    """Raised for profile-related errors"""


class Profile(NamedTuple):
    title: str
    url: httpx.URL
    id: str

class EamisService:
    # Known Errors:
    # CODE_MAPPING = {
    #     0: "Success",
    #     40000: "Parameter error",
    #     10110001: "Account or password incorrect",
    # }

    def __init__(self) -> None:
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

    def login(self) -> httpx.Response:
        # Redirect to site
        try:
            prelogin_response = self.client.get(INITIAL_URL, follow_redirects=True)
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
            link = EAMIS_URL.join(content["data"]["next"]["link"])
        except KeyError as e:
            raise ServiceError(
                f"Missing 'next' link in response: {content}, likely due to a change in the API format."
            ) from e
        return self.client.get(link, follow_redirects=True)

    def get_profiles(self) -> tuple[httpx.Response, list[Profile]]:
        """Fetch election categories available for the user."""
        try:
            course_elect_menu_response = self.client.get(
                EAMIS_URL.join("/eams/stdElectCourse.action"),
                headers={
                    "Referer": str(self.login().url),
                    "X-Requested-With": "XMLHttpRequest",
                },
                params={"_": "1749625169272"},
                follow_redirects=True,
            )
        except httpx.HTTPError as e:
            raise ConnectionError(f"Failed to fetch course election menu: {e}") from e
        except Exception as e:
            raise ConnectionError(
                f"An unknown error occurred while fetching course election menu: {e}"
            ) from e
        soup = BeautifulSoup(course_elect_menu_response.content, "lxml")
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
            except (AttributeError, IndexError) as e:
                raise ProfileError(f"Failed to parse course category: {e}") from e
            course_categories.append(
                Profile(
                    title=title,
                    url=EAMIS_URL.join(href),
                    id=profile_id,
                )
            )

        return course_elect_menu_response, course_categories

if __name__ == "__main__":
    service = EamisService()
    response = service.login()