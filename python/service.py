from collections import OrderedDict

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
        self.headers: OrderedDict[str, str] = OrderedDict(config["headers"])
        self.account: str = config["user"]["account"]
        self.password: str = config["user"]["password"]
        self.encrypted_password: str = config["user"]["encrypted_password"]

        self.client.headers.update(self.headers)

    def initial_connection(self) -> None:
        try:
            response = self.client.get(self.base_url)
            response.raise_for_status()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to EAMIS service: {e}") from e
        self.client.headers["Sec-Fetch-Site"] = "same-origin"

    def login(self) -> httpx.URL:
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
            return EAMIS_URL.join(content["data"]["next"]["link"])
        except KeyError as e:
            raise ServiceError(
                f"Missing 'next' link in response: {content}, likely due to a change in the API format."
            ) from e


if __name__ == "__main__":
    service = EamisService()
    service.login()
