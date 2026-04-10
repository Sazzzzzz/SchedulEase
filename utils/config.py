import hashlib
import logging
import tomllib
from pathlib import Path

import tomli_w
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
SCRIPT_DIR = Path(__file__).parent.resolve()
DATA_PATH = SCRIPT_DIR.parent / "data"
CONFIG_PATH = DATA_PATH / "config.toml"


class UserConfig(BaseModel):
    account: str
    encrypted_password: str


class HeaderConfig(BaseModel):
    user_agent: str = Field(
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        alias="User-Agent",
    )
    accept: str = Field(
        default="text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        alias="Accept",
    )
    accept_language: str = Field(
        default="en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        alias="Accept-Language",
    )
    accept_encoding: str = Field(
        default="gzip, deflate, br",
        alias="Accept-Encoding",
    )
    dnt: str = Field(
        default="1",
        alias="DNT",
    )
    sec_fetch_dest: str = Field(
        default="document",
        alias="Sec-Fetch-Dest",
    )
    sec_fetch_mode: str = Field(
        default="navigate",
        alias="Sec-Fetch-Mode",
    )
    sec_fetch_site: str = Field(
        default="none",
        alias="Sec-Fetch-Site",
    )
    sec_fetch_user: str = Field(
        default="?1",
        alias="Sec-Fetch-User",
    )
    cache_control: str = Field(
        default="max-age=0",
        alias="Cache-Control",
    )
    sec_ch_ua: str = Field(
        default='"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        alias="Sec-CH-UA",
    )
    sec_ch_ua_mobile: str = Field(
        default="?0",
        alias="Sec-CH-UA-Mobile",
    )
    sec_ch_ua_platform: str = Field(
        default="",
        alias="Sec-CH-UA-Platform",
    )


class EamisConfig(BaseModel):
    profile_delay: float = 0.5
    course_delay: float = 0.5
    log_level: int = logging.INFO
    log_lines: int = 16


class LibicConfig(BaseModel):
    browser: str = "chromium"
    browser_channel: str = "msedge"
    headless: bool = False


class Config(BaseModel):
    user: UserConfig
    header: HeaderConfig
    eamis: EamisConfig
    libic: LibicConfig


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


def save_config(config: Config) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Convert the Pydantic model to a standard dictionary
    config_dict = config.model_dump()

    with CONFIG_PATH.open("wb") as f:
        tomli_w.dump(config_dict, f)

    logger.info("Configuration file saved.")


def create_config(account: str, password: str) -> None:
    # 1. Create the user sub-config (which doesn't have defaults)
    user_config = UserConfig(account=account, encrypted_password=encrypt(password))

    # 2. Assemble the main Config object (other parts will use their defaults)
    new_config = Config(
        user=user_config,
        header=HeaderConfig(),
        eamis=EamisConfig(),
        libic=LibicConfig(),
    )

    # 3. Save it
    save_config(new_config)
    logger.info("Default configuration file created.")


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Configuration file not found at {CONFIG_PATH}. Please create it first."
        )

    with CONFIG_PATH.open("rb") as f:
        raw = tomllib.load(f)
    return Config.model_validate(raw)
