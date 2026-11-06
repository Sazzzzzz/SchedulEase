import asyncio
import inspect
import json
import logging
from collections.abc import Callable, Coroutine
from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import Any, Concatenate

from rich.console import Console
from rich.panel import Panel
from typer._click.globals import get_current_context

from common.config import DATA_PATH, Config, load_config
from common.exceptions import LoginError
from libic.service import LibicService

SESSION_FILE = DATA_PATH / "session.json"
logger = logging.getLogger(__name__)
console = Console()


def adapter[**P, R](
    func: Callable[Concatenate[LibicService, P], Coroutine[Any, Any, R]],
    *,
    interactive: bool = True,
) -> Callable[P, R]:
    """
    This function is for converting core logic async functions into `Typer` commands. It injects the `LibicService` instance from the Typer context. It also runs async functions in the event loop from the Typer context.
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
        loop: asyncio.AbstractEventLoop = ctx.obj["loop"]

        async def run():
            service = await get_libic_service(load_config(), interactive=interactive)
            ctx.obj["service"] = service
            try:
                return await func(service, *bound.args, **bound.kwargs)
            finally:
                await service.aclose()

        return loop.run_until_complete(run())

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    wrapper.__signature__ = exposed_sig  # type: ignore
    return wrapper


async def get_libic_service(
    config: Config, force_login: bool = False, interactive: bool = True
) -> LibicService:

    needs_login = True
    session_data: dict[str, Any] = {}

    if not force_login and SESSION_FILE.exists():
        try:
            with SESSION_FILE.open() as f:
                session_data = json.load(f)
        except (ValueError, OSError):
            session_data = {}
        if not isinstance(session_data, dict):
            session_data = {}
        timestamp = session_data.get("timestamp")
        age = (
            datetime.now().timestamp() - timestamp
            if isinstance(timestamp, (int, float))
            else -1
        )
        if (
            0 <= age < timedelta(minutes=30).total_seconds()
            and session_data.get("token")
            and session_data.get("user_info")
        ):
            needs_login = False
            logger.debug("Valid session found. Hydrating service from cache...")
        else:
            logger.debug("Cached session is missing or stale. Logging in again...")

    if needs_login:
        logger.debug("No valid session found. Logging in...")
        if not interactive:
            logger.debug("正在登录图书馆系统")
        try:
            with (
                console.status("[green]正在登录图书馆系统…", spinner="dots")
                if interactive
                else nullcontext()
            ):
                service = await LibicService.from_login(config)
        except LoginError:
            if interactive:
                console.print(
                    Panel.fit(
                        "[bold red]登录失败[/bold red]\n"
                        "[dim]请检查您的账号密码并重试。或检查您是否安装浏览器驱动。[/dim]",
                        title="Authentication",
                        border_style="red",
                    )
                )
            logger.error("Failed to log in.")
            raise
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with SESSION_FILE.open("w") as f:
            json.dump(service.export_session(), f, indent=4)
        if interactive:
            console.print(
                "[bold green]成功登陆！[/bold green][dim]本次登录已保存。后续命令将无需重新登录。[/dim]",
            )
        else:
            logger.debug("登录成功，会话已保存")
    else:
        service = LibicService.from_session(config, session_data)

    return service
