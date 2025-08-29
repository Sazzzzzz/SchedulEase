import hashlib
import tomllib
import logging
from pathlib import Path
from typing import Any

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

DEFAULT_CONFIG_TEMPLATE = """# SchedulEase Configuration File

# --- Request Headers ---
# General headers to mimic a real browser.
# You may modify them to your own browser's headers if needed.
[headers]
User-Agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
Accept = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
Accept-Language = "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
Accept-Encoding = "gzip, deflate, br"
DNT = "1"
Connection = "keep-alive"
Upgrade-Insecure-Requests = "1"
Sec-Fetch-Dest = "document"
Sec-Fetch-Mode = "navigate"
Sec-Fetch-Site = "none"
Sec-Fetch-User = "?1"
Cache-Control = "max-age=0"
Sec-Ch-Ua = '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
Sec-Ch-Ua-Mobile = "?0"
Sec-Ch-Ua-Platform = '"macOS"'

# --- User Credentials ---
# University portal username and password below.
# Actual password will not be recorded for safety. 
# DO NOT share this file with others.
[user]
account = "{account}"
encrypted_password = "{encrypted_password}"

# --- Application Settings ---
# General application settings go here.
[settings]
# delay time between requests of different course profiles
profile_delay = 0.5
# maximum number allowed to finish all course election requests
course_delay = 0.5
# logging level users see at schedule page
log_level = "INFO"
# number of log lines to display in the UI
log_lines = 16
"""
logger = logging.getLogger(__name__)
SCRIPT_DIR = Path(__file__).parent.resolve()
DATA_PATH = SCRIPT_DIR / "data"
CONFIG_PATH = DATA_PATH / "config.toml"


# Adapted from the original code
def encrypt(password: str) -> str:
    MAX_SAFE_INT = "9007199254740991"
    t = hashlib.md5(MAX_SAFE_INT.encode()).hexdigest()
    n_hex = hashlib.sha1(t.encode()).hexdigest()
    iv_bytes = n_hex.encode("utf-8")
    key_bytes = t.encode("utf-8")
    iv_for_aes = iv_bytes[:16]
    cipher = AES.new(key_bytes[:32], AES.MODE_CBC, iv_for_aes)
    encrypted = cipher.encrypt(pad(password.encode("utf-8"), 16))

    return encrypted.hex()


def create_config(account: str, password: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(
            DEFAULT_CONFIG_TEMPLATE.format(
                account=account,
                encrypted_password=encrypt(password),
            )
        )

    logger.info("Default configuration file created.")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration file not found at {CONFIG_PATH}. Please create it first."
        )
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


# TODO: Consider add test login function to verify credentials
