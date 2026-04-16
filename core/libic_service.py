"""
Core service for interacting with the LIBIC backend.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import date, datetime, time
from typing import Any, ClassVar

import httpx
from playwright.async_api import Browser, Playwright, async_playwright
from pydantic import BaseModel, ConfigDict, Field

from ..utils.config import Config
from .exceptions import LoginError, ServiceError

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


# API URLs
LIBIC_URL = httpx.URL("https://libic.nankai.edu.cn")
LOGIN_URL = httpx.URL("https://iam.nankai.edu.cn")
LIBIC_API = LIBIC_URL.join("ic-web/")


class Building(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    id: str
    name: str
    floors: list[Floor] = Field(default_factory=list, alias="children")


class Floor(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    id: str
    name: str
    sections: list[Section] = Field(default_factory=list, alias="children")


class Section(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    id: str
    name: str
    room_count: int = Field(default=0, alias="totalCount")
    remain_count: int = Field(default=0, alias="remainCount")


class SectionTree(BaseModel):
    buildings: list[Building]


class LibicService:
    STATUS_MAP: ClassVar[dict[int, str]] = {
        3265: "已结束",  # 预约时间已到自然结束
        1217: "已结束",  # 提前结束
        1169: "已违约",
        1027: "未开始",
        1093: "使用中",
    }

    def __init__(self, config: Config) -> None:
        self.config = config
        self.account = config.user.account
        self.encrypted_password = config.user.encrypted_password

        # We will use an async client since playwright flow is async
        self.client = httpx.AsyncClient(
            headers=OrderedDict(config.header.model_dump(by_alias=True)),
            follow_redirects=False,
        )
        self.client.headers["Referer"] = str(LIBIC_URL)

    async def initial_connection(self) -> None:
        """
        Test the initial connection to the LIBIC service. Raises `ConnectionError` if the connection fails.

        This is a single method that must be invoked manually to ensure the service is reachable.
        """
        try:
            response = await self.client.get(LIBIC_URL, follow_redirects=False)
            response.raise_for_status()
            logger.info("Successfully connected to LIBIC service.")
        except Exception as e:
            logger.error(f"Failed to connect to LIBIC service: {e}")
            raise ConnectionError(f"Failed to connect to LIBIC service: {e}") from e
        self.client.headers["Sec-Fetch-Site"] = "same-origin"

    async def _send_login_request(self, iam_cookie_jar: dict) -> httpx.URL:
        """
        Send the login request to IAM with the extracted csrf-token and cookies. Mimics EAMIS login flow.
        """
        csrf_token = iam_cookie_jar.get("csrf-token", "")
        async with httpx.AsyncClient() as client:
            try:
                login_result = await client.post(
                    f"{LOGIN_URL!s}/api/v1/login?os=web",
                    headers={
                        "content-type": "application/json",
                        "csrf-token": csrf_token,
                        "referer": str(LIBIC_API),
                    },
                    cookies=iam_cookie_jar,
                    json={
                        "login_scene": "feilian",
                        "account_type": "userid",
                        "account": self.account,
                        "password": self.encrypted_password,
                    },
                )
            except httpx.HTTPError as e:
                raise LoginError(f"Failed to log in to IAM: {e}") from e
        content = login_result.json()
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
        return link

    async def _get_browser(self, p: Playwright) -> Browser:
        headless = self.config.libic.headless
        try:
            match self.config.libic.browser:
                case "chrome":
                    return await p.chromium.launch(channel="chrome", headless=headless)
                case "edge":
                    return await p.chromium.launch(channel="msedge", headless=headless)
                case "safari":
                    return await p.webkit.launch(headless=headless)
                case "firefox":
                    return await p.firefox.launch(headless=headless)
                case _:
                    raise ValueError(
                        f"Unsupported browser: {self.config.libic.browser}"
                    )
        except Exception as e:
            raise ServiceError(
                f"Failed to launch browser: {e}. You may need to install the required browser driver."
            ) from e

    async def _playwright_login(self) -> dict[str, str]:
        """
        Executes the playwright login flow to retrieve libic cookies.
        """
        logger.info("Starting Libic Playwright login flow...")
        async with (
            async_playwright() as p,
            await self._get_browser(p) as browser,
        ):
            ctx = await browser.new_context()
            page = await ctx.new_page()

            # Navigate to trigger CAS redirect
            try:
                await page.goto(
                    str(LIBIC_URL), wait_until="domcontentloaded", timeout=15000
                )
                await page.wait_for_selector("#password_account_input", timeout=15000)
            except Exception as e:
                raise LoginError(f"Failed to navigate to login page: {e}") from e

            # Extract IAM cookies (specifically csrf-token)
            iam_cookies = await ctx.cookies(urls=[str(LOGIN_URL)])
            iam_cookie_jar = {
                c.get("name", ""): c.get("value", "") for c in iam_cookies
            }

            # Send Login Request
            try:
                next_link = await self._send_login_request(iam_cookie_jar)
            except Exception as e:
                raise LoginError(f"Failed to send login request: {e}") from e

            # Proceed with CAS redirect flow
            try:
                await page.goto(
                    str(next_link),
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                await page.wait_for_selector("#app", timeout=15000)
            except Exception as e:
                raise LoginError(f"CAS redirect failed: {e}") from e

            # Post Login: Extract all Libic Cookies
            all_cookies = await ctx.cookies()
            libic_cookies = {
                c.get("name", ""): c.get("value", "")
                for c in all_cookies
                if c.get("domain", "").endswith("libic.nankai.edu.cn")
            }

            if "UNI_AUTH_JSESSIONID" not in libic_cookies:
                raise LoginError("Login failed: missing UNI_AUTH_JSESSIONID")

            return libic_cookies

    async def login(self) -> None:
        """
        Public coordinate for login configuration.
        """
        try:
            await self.initial_connection()
        except Exception as e:
            raise LoginError(f"Cannot reach LIBIC service for login: {e}") from e
        cookies = await self._playwright_login()
        self.client.cookies.update(cookies)
        self._user_info = await self.get_user_info()

        # configure client headers for modifying endpoints
        self.client.headers.update({"token": self._user_info["token"], "lan": "1"})
        logger.info("Successfully logged into Libic.")

    @classmethod
    async def from_login(cls, config: Config) -> LibicService:
        """
        LibicService constructor that performs the login flow.
        """
        service = cls(config)
        await service.login()
        return service

    def export_session(self) -> dict[str, Any]:
        """Export the active session data for caching."""
        return {
            "timestamp": datetime.timestamp(datetime.now()),
            "cookies": dict(self.client.cookies),
            "token": self.client.headers.get("token", ""),
            "user_info": self._user_info,
        }

    def restore_session(self, session_data: dict[str, Any]) -> None:
        """Restore the session state from cached data."""
        self.client.cookies.update(session_data.get("cookies", {}))
        self.client.headers.update({"token": session_data["token"], "lan": "1"})
        self._user_info = session_data.get("user_info")

    @classmethod
    def from_session(cls, config: Config, session_data: dict[str, Any]) -> LibicService:
        """Synchronous constructor that restores session from cached data."""
        service = cls(config)
        service.restore_session(session_data)
        return service

    async def get_user_info(self) -> dict:
        try:
            response = await self.client.get(LIBIC_API.join("auth/userInfo"))
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise ServiceError(f"Failed to fetch user info: {e}") from e
        except Exception as e:
            raise ServiceError("Unexpected error fetching user info") from e
        return response.json().get("data", {})

    async def get_server_time(self) -> int:
        """Returns server time in milliseconds"""
        resp = await self.client.get(LIBIC_API.join("pad/updateTime"))
        resp.raise_for_status()
        return resp.json()

    async def get_room_seats(self, room_id: str, date: date) -> list[dict]:
        """
        Retrieve all seats and reservations for a room.
        date_str format: YYYYMMDD
        """
        date_str = date.strftime("%Y%m%d")
        try:
            response = await self.client.get(
                LIBIC_API.join("reserve"),
                params={"roomIds": room_id, "resvDates": date_str, "sysKind": 8},
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise ServiceError(f"Failed to fetch room seats: {e}") from e
        except Exception as e:
            raise ServiceError("Unexpected error fetching room seats") from e
        resp = response.json()
        return resp.get("data", [])

    async def list_reservations(self, start: date, end: date) -> list[dict[str, Any]]:
        """
        start_date/end_date format: YYYY-MM-DD
        """
        start_date = start.strftime("%Y-%m-%d")
        end_date = end.strftime("%Y-%m-%d")
        try:
            response = await self.client.get(
                LIBIC_API.join("reserve/resvInfo"),
                params={
                    "beginDate": start_date,
                    "endDate": end_date,
                    "needStatus": 8582,
                    "page": 1,
                    "pageNum": 50,
                    "orderKey": "gmt_create",
                    "orderModel": "desc",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise ServiceError(f"Failed to fetch reservations: {e}") from e
        except Exception as e:
            raise ServiceError("Unexpected error fetching reservations") from e
        return response.json().get("data", [])

    async def reserve_seat(
        self, dev_id: str, start: time, end: time, date: date = date.today()
    ) -> dict:

        start_dt = datetime.combine(date, start)
        end_dt = datetime.combine(date, end)

        def fmt(dt: datetime) -> str:
            return dt.strftime("%Y-%m-%d %H:%M:%S")

        if not self._user_info:
            raise ServiceError("Must login before reserving.")

        acc_no = self._user_info["accNo"]

        payload = {
            "sysKind": 8,
            "appAccNo": acc_no,
            "memberKind": 1,
            "resvMember": [acc_no],
            "resvBeginTime": fmt(start_dt),
            "resvEndTime": fmt(end_dt),
            "testName": "",
            "captcha": "",
            "resvProperty": 0,
            "resvDev": [dev_id],
            "memo": "",
        }

        try:
            resp = await self.client.post(
                LIBIC_API.join("reserve"),
                json=payload,
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ServiceError(f"Failed to reserve seat: {e}") from e
        data = resp.json()
        if data.get("code") != 0:
            raise ServiceError(f"Reservation failed: {data.get('message')}")
        return data

    async def get_seat_menu_tree(self) -> SectionTree:
        """Fetch the nested building -> floor -> section."""
        try:
            resp = await self.client.get(LIBIC_API.join("seatMenu"))
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ServiceError(f"Failed to fetch seat menu: {e}") from e

        data = resp.json().get("data", [])
        return SectionTree(buildings=data)

    async def get_sections(self) -> dict[str, Section]:
        """Flattened mapping of section ID to Section object for quick lookup."""
        sections: dict[str, Section] = {}
        for building in (await self.get_seat_menu_tree()).buildings:
            for floor in building.floors:
                for section in floor.sections:
                    sections[section.name] = section
        return sections

    async def get_section_info(self, section_id: str) -> list[dict]:
        """Fetch opening hours for a specific section."""
        try:
            resp = await self.client.get(
                LIBIC_API.join("seatRoom/openScope"),
                params={"roomId": int(section_id)},
            )
            resp.raise_for_status()
        except Exception as e:
            raise ServiceError(f"Failed to fetch section open scope: {e}") from e
        return resp.json().get("data", [])

    async def get_section_seats(self, section_id: str) -> dict[str, Any]:
        """Fetch seat info for a specific section for today."""
        info = await self.get_room_seats(str(section_id), date.today())
        seats: dict[str, Any] = {}
        for seat in info:
            dev_name = seat.get("devName")
            if dev_name:
                seats[dev_name] = seat

        return seats

    async def cancel_reservation(self, uuid: str) -> dict:
        """Cancel a pending (future) reservation."""
        try:
            resp = await self.client.post(
                LIBIC_API.join("reserve/delete"),
                json={"uuid": uuid},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ServiceError(f"Failed to cancel reservation: {e}") from e
        data = resp.json()
        if data.get("code") != 0:
            raise ServiceError(f"Cancel failed: {data.get('message')}")
        return data

    async def end_reservation(self, uuid: str) -> dict:
        """End an active/current reservation early."""
        try:
            resp = await self.client.post(
                LIBIC_API.join("reserve/endAhaed"),
                json={"uuid": uuid},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ServiceError(f"Failed to end reservation: {e}") from e
        data = resp.json()
        if data.get("code") != 0:
            raise ServiceError(f"End reservation failed: {data.get('message')}")
        return data

    @staticmethod
    def from_timestamp(ts: int) -> datetime:
        """Convert server timestamp (in milliseconds) to datetime."""
        return datetime.fromtimestamp(ts / 1000)
