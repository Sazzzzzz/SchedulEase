# Bisection method to find the expiration time of the login session
# Result: 30min +- 2sec, confirmed by secondary testing
# This is really poor python code with `.env` file needed, only for testing purposes

import json
import os
import time

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()


class Test:
    def __init__(self) -> None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
        }
        self.session = requests.Session()
        self.session.headers.update(headers)

    def login(self) -> bool:
        response = self.session.get(
            "https://eamis.nankai.edu.cn/eams/homeExt.action",
            allow_redirects=True,
        )
        login_response = self.session.post(
            "https://iam.nankai.edu.cn/api/v1/login?os=web",
            headers={
                # Actually with experiment, only `content-type`, `csrf-token` and `referrer` are needed
                "accept": "*/*",
                "accept-language": "zh-CN",
                "cache-control": "no-cache",
                "content-type": "application/json",
                "csrf-token": self.session.cookies.get("csrf-token"),
                "pragma": "no-cache",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "x-fe-version": "3.0.9.8465",
                "x-version-check": "0",
                "referer": response.url,
            },
            data=json.dumps(
                {
                    "login_scene": "feilian",
                    "account_type": "userid",
                    "account": os.getenv("ACCOUNT"),
                    "password": os.getenv("PASSWORD"),
                }
            ),
            allow_redirects=True,
        )

        self.login_status = json.loads(login_response.content)
        if self.login_status.get("code") == 0:
            return True
        else:
            return False

    def execute(self) -> bool:
        after_login = self.session.get(
            "https://iam.nankai.edu.cn" + self.login_status["data"]["next"]["link"]
        )
        course_select = self.session.get(
            "https://eamis.nankai.edu.cn/eams/stdElectCourse.action",
            headers={"Referer": after_login.url, "X-Requested-With": "XMLHttpRequest"},
            params={"_": "1749625169272"},
            allow_redirects=True,
        )
        soup = BeautifulSoup(course_select.content, "html.parser")
        # print(soup)
        if "进入选课" in soup.text:
            return True
        else:
            return False


def bisect(min: int, max: int, precision: int = 1):
    """A function to find max time of between login and valid execution time with bisect method.
    Args:
        min (int): The minimum value of the range.
        max (int): The maximum value of the range.
        precision (int, optional): The precision of the result. Defaults to 1.
    """
    if min > max:
        raise ValueError("min should be less than or equal to max")
    if precision <= 0:
        raise ValueError("precision should be a positive integer")

    while max - min > precision:
        test = Test()
        mid = (min + max) // 2
        is_login = test.login()
        if not is_login:
            print("Login Unsuccessful! Retrying...")
            continue
        print(f"Login Successful! Trying with {mid} seconds...")
        time.sleep(mid)
        result = test.execute()
        if result:
            print(f"Execution successful with {mid} seconds.")
            min = mid
        else:
            print(f"Execution failed with {mid} seconds.")
            max = mid

    # validate the final result
    test = Test()
    is_login = test.login()
    if not is_login:
        raise ValueError("Login failed after final attempt")
    time.sleep(min)
    result = test.execute()
    if not result:
        print(f"Execution failed with {min} seconds!")
    else:
        print(f"Validation on min {min} seconds successful!")

    test = Test()
    is_login = test.login()
    if not is_login:
        raise ValueError("Login failed after final validation")
    time.sleep(max)
    result = test.execute()
    if result:
        print(f"Execution failed with {max} seconds!")
    else:
        print(f"Validation on max {max} seconds successful!")

    print(f"Max time found: {max} seconds")
    print(f"Min time found: {min} seconds")
    print(f"Precision: {precision} seconds")


if __name__ == "__main__":
    print("Starting the bisect process...")
    try:
        bisect(1, 2 * 60 * 60, 120)
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
