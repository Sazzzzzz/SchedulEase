from pathlib import Path
import tomllib
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


DEFAULT_CONFIG_TEMPLATE = """# SchedulEase Configuration File

# --- Service Configuration ---
# Base URL for the university's EAMIS portal.
[service]
eamis_url = "https://eamis.nankai.edu.cn"

# --- Request Headers ---
# These headers mimic a real browser.
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
# !!! IMPORTANT !!!
# Please fill in your university portal username and password below.
[user]
account = "{account}"
password = "{password}"
encrypted_password = "{encrypted_password}"
"""

SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "data" / "config.toml"


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
                password=password,
                encrypted_password=encrypt(password),
            )
        )

    print("Default configuration file created.")


def load_config() -> dict[str, str]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration file not found at {CONFIG_PATH}. Please create it first."
        )
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)
