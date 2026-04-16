import asyncio
import inspect
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
from typing import Any, Concatenate

from click import get_current_context
from rich.console import Console
from rich.panel import Panel

from ..core.exceptions import LoginError
from ..core.libic_service import LibicService
from ..utils.config import DATA_PATH, Config

SESSION_FILE = DATA_PATH / "session.json"
logger = logging.getLogger(__name__)
console = Console()


def adapter[**P, R](
    func: Callable[Concatenate[LibicService, P], Coroutine[Any, Any, R]],
) -> Callable[P, R]:
    """
    This function is for converting core logic async functions into `Typer` commands. It automatically injects the `LibicService` instance from the Typer context.
    """
    # Using `functools.partial` would lose the original function's signature
    # so here we use `Concatenate` with `inspect` to remove the first parameter for the exposed command.
    original = inspect.signature(func)
    # remove first parameter
    exposed_params = list(original.parameters.values())[1:]
    exposed_sig = original.replace(parameters=exposed_params)

    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        ctx = get_current_context()
        bound = exposed_sig.bind(*args, **kwargs)
        bound.apply_defaults()
        service: LibicService = ctx.obj["service"]
        loop: asyncio.AbstractEventLoop = ctx.obj["loop"]

        return loop.run_until_complete(func(service, *bound.args, **bound.kwargs))

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    wrapper.__signature__ = exposed_sig  # type: ignore
    return wrapper


async def get_libic_service(config: Config, force_login: bool = False) -> LibicService:

    needs_login = True
    session_data: dict[str, Any] = {}

    if not force_login and SESSION_FILE.exists():
        with SESSION_FILE.open() as f:
            session_data = json.load(f)
        if (
            t := session_data.get("timestamp")
        ) and datetime.now() - datetime.fromtimestamp(t) < timedelta(minutes=30):
            needs_login = False
            logger.info("Valid session found. Hydrating service from cache...")
        else:
            logger.info("Cached session is missing or stale. Logging in again...")

    if needs_login:
        logger.info("No valid session found. Logging in...")
        try:
            with console.status("[green]正在登录图书馆系统…", spinner="dots"):
                service = await LibicService.from_login(config)
        except LoginError as e:
            console.print(
                Panel.fit(
                    "[bold red]登录失败[/bold red]\n"
                    "[dim]请检查您的账号密码并重试。或检查您是否安装浏览器驱动。[/dim]",
                    title="Authentication",
                    border_style="red",
                )
            )
            logger.error("Failed to log in.")
            raise e
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with SESSION_FILE.open("w") as f:
            json.dump(service.export_session(), f, indent=4)
        console.print(
            "[bold green]成功登陆！[/bold green][dim]本次登录已保存。后续命令将无需重新登录。[/dim]",
        )
    else:
        service = LibicService.from_session(config, session_data)

    return service
