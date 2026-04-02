import asyncio
import json
import logging
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Callable, Coroutine, ParamSpec, TypeVar

from ..core.libic_service import LibicService
from ..utils.config import DATA_PATH, load_config

SESSION_FILE = DATA_PATH / "session.json"
logger = logging.getLogger(__name__)
P = ParamSpec("P")
T = TypeVar("T")


def async2sync(func: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, T]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return asyncio.run(func(*args, **kwargs))

    return wrapper


@async2sync
async def get_libic_service(
    config: dict[str, Any], force_login: bool = False
) -> LibicService:

    needs_login = True
    session_data: dict[str, Any] = {}

    if not force_login and SESSION_FILE.exists():
        with open(SESSION_FILE, "r") as f:
            session_data = json.load(f)
        if (
            t := session_data.get("timestamp")
        ) and datetime.now() - datetime.fromtimestamp(t) < timedelta(minutes=30):
            needs_login = False
            logger.info("Valid session found. Hydrating service from cache...")
        else:
            logger.info("Cached session is missing or stale. Logging in again...")

    if needs_login:
        service = await LibicService.from_login(config)
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SESSION_FILE, "w") as f:
            json.dump(service.export_session(), f)
    else:
        service = LibicService.from_session(config, session_data)

    return service


service = get_libic_service(load_config())
