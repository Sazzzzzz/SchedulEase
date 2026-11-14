"""`libic config` 交互式配置向导。"""

import platform
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any

import questionary
from playwright.sync_api import sync_playwright
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from common.config import (
    CONFIG_PATH,
    Config,
    EamisConfig,
    HeaderConfig,
    LibicConfig,
    UserConfig,
    encrypt,
    load_config,
    save_config,
)

console = Console()

STYLE = questionary.Style(
    [
        ("qmark", "fg:#00afff bold"),
        ("question", "bold"),
        ("answer", "fg:#00d7ff bold"),
        ("pointer", "fg:#00afff bold"),
        ("highlighted", "fg:#00afff bold"),
        ("selected", "fg:#00d7ff"),
        ("instruction", "fg:#666666"),
    ]
)

# 配置值 -> 显示名
BROWSERS = {
    "edge": "Edge",
    "chrome": "Chrome",
    "safari": "Safari",
    "firefox": "Firefox",
}
# 配置值 -> `playwright install` 使用的浏览器名
PLAYWRIGHT_BROWSERS = {
    "edge": "msedge",
    "chrome": "chrome",
    "safari": "webkit",
    "firefox": "firefox",
}
SAVE = "__save__"


def ask(fn, *args, **kwargs):
    """调用 questionary；用户取消时抛 KeyboardInterrupt。"""
    result = fn(*args, **kwargs).ask()
    if result is None:
        raise KeyboardInterrupt
    return result


def _browser_choices():
    return [
        questionary.Choice(title=title, value=value)
        for value, title in BROWSERS.items()
    ]


def _channel_installed(name: str) -> bool:
    """检测 Chrome/Edge 这类系统浏览器是否已安装。"""
    system = platform.system()
    if name == "chrome":
        if system == "Darwin":
            candidates = [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            ]
        elif system == "Windows":
            candidates = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                str(Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe"),
            ]
        else:
            candidates = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/opt/google/chrome/chrome",
            ]
    elif name == "msedge":
        if system == "Darwin":
            candidates = [
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
            ]
        elif system == "Windows":
            candidates = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]
        else:
            candidates = ["/usr/bin/microsoft-edge", "/opt/microsoft/msedge/msedge"]
    else:
        return False
    return any(Path(path).exists() for path in candidates)


def _browser_installed(browser: str) -> bool:
    name = PLAYWRIGHT_BROWSERS[browser]
    try:
        if name in {"webkit", "firefox"}:
            with sync_playwright() as playwright:
                path = getattr(playwright, name).executable_path
            return bool(path) and Path(path).exists()
        return _channel_installed(name)
    except Exception:
        # 检测失败时按未安装处理，让用户自行决定是否安装
        return False


def _install_browser(browser: str) -> bool:
    name = PLAYWRIGHT_BROWSERS[browser]
    console.print(f"[cyan]正在安装 {BROWSERS[browser]}…[/cyan]")
    result = subprocess.run([sys.executable, "-m", "playwright", "install", name])
    return result.returncode == 0


def _ensure_browser_installed(browser: str) -> None:
    if _browser_installed(browser):
        console.print(f"[green]✓ 已检测到 {BROWSERS[browser]}[/green]")
        return
    if not ask(
        questionary.confirm,
        f"未检测到 {BROWSERS[browser]}，是否现在安装？",
        default=True,
        style=STYLE,
    ):
        console.print(
            f"[yellow]已跳过，可稍后手动运行 `playwright install {PLAYWRIGHT_BROWSERS[browser]}`[/yellow]"
        )
        return
    if _install_browser(browser):
        console.print("[green]✓ 浏览器安装完成[/green]")
    else:
        console.print(
            f"[red]安装失败，请稍后手动执行 `playwright install {PLAYWRIGHT_BROWSERS[browser]}`[/red]"
        )


def _select_browser(current: str) -> str:
    default = current if current in BROWSERS else "edge"
    browser = ask(
        questionary.select,
        "选择浏览器",
        choices=_browser_choices(),
        default=default,
        style=STYLE,
    )
    _ensure_browser_installed(browser)
    return browser


def _is_float(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def _validate_time(text):
    try:
        hour, minute = (int(x) for x in text.split(":"))
        time(hour, minute)
        return True
    except Exception:
        return "格式应为 HH:MM（例如 07:30）"


VALIDATORS = {
    "blank": lambda t: True if t.strip() else "不能为空",
    "float": lambda t: True if _is_float(t) else "请输入数字",
    "int": lambda t: True if t.strip().lstrip("-").isdigit() else "请输入整数",
}


@dataclass(frozen=True)
class Field:
    """一个可编辑配置项：如何读取当前值、如何提问并得到新值。"""

    label: str
    desc: str
    get: Callable[[LibicConfig], Any]
    editor: Callable[[LibicConfig], Any]


def _number_field(label, desc, get, cast, validate):
    """数字型字段：提问、校验后转成 float/int。"""

    def editor(libic):
        return cast(
            ask(
                questionary.text,
                f"{label}（{desc}）",
                default=str(get(libic)),
                validate=validate,
                style=STYLE,
            )
        )

    return Field(label, desc, get, editor)


def _time_field(label, desc, get):
    """时间型字段：按 HH:MM 提问并解析成 time。"""

    def editor(libic):
        raw = ask(
            questionary.text,
            f"{label}（{desc}，HH:MM）",
            default=get(libic).strftime("%H:%M"),
            validate=_validate_time,
            style=STYLE,
        )
        hour, minute = (int(x) for x in raw.split(":"))
        return time(hour, minute)

    return Field(label, desc, get, editor)


FIELDS = {
    "browser": Field(
        "浏览器",
        "Playwright 使用的浏览器",
        lambda libic: libic.browser,
        lambda libic: _select_browser(libic.browser),
    ),
    "headless": Field(
        "无头模式",
        "是否隐藏浏览器窗口",
        lambda libic: libic.headless,
        lambda libic: ask(
            questionary.confirm, "无头模式", default=libic.headless, style=STYLE
        ),
    ),
    "prepare_minutes": _number_field(
        "提前准备",
        "开抢前提前打开页面（分钟）",
        lambda libic: libic.prepare_minutes,
        float,
        VALIDATORS["float"],
    ),
    "overshoot_seconds": _number_field(
        "超时冗余",
        "抢座请求的超时余量（秒）",
        lambda libic: libic.overshoot_seconds,
        float,
        VALIDATORS["float"],
    ),
    "check_minutes": _number_field(
        "巡检间隔",
        "巡检任务的轮询间隔（分钟）",
        lambda libic: libic.check_minutes,
        float,
        VALIDATORS["float"],
    ),
    "check_start": _time_field(
        "巡检开始", "每天开始巡检的时间", lambda libic: libic.check_start
    ),
    "check_end": _time_field(
        "巡检结束", "每天停止巡检的时间", lambda libic: libic.check_end
    ),
    "protect_minutes": _number_field(
        "保护提前量",
        "预约保护窗口（分钟）",
        lambda libic: libic.protect_minutes,
        float,
        VALIDATORS["float"],
    ),
    "rebook_minutes": _number_field(
        "重预约延迟",
        "重预约的等待时间（分钟）",
        lambda libic: libic.rebook_minutes,
        float,
        VALIDATORS["float"],
    ),
    "advance_days": _number_field(
        "提前天数",
        "可提前预约的天数",
        lambda libic: libic.advance_days,
        int,
        VALIDATORS["int"],
    ),
    "send_time": _time_field(
        "发送时间", "每日定时预约的触发时间", lambda libic: libic.send_time
    ),
}


def _show(config, key):
    value = FIELDS[key].get(config.libic)
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, time):
        return value.strftime("%H:%M")
    return str(value)


class Wizard:
    def __init__(self):
        self.config: Config | None = None

    def run(self):
        console.print(
            Panel.fit(
                "[bold cyan]libic config[/bold cyan]\n[dim]图书馆预约助手配置向导[/dim]",
                box=box.ROUNDED,
                border_style="cyan",
            )
        )
        self.config = self._load()
        account, pwd = self._account()
        browser = self._browser()
        headless = self._headless()
        self.config = self._assemble(account, pwd, browser, headless)
        self._review()
        save_config(self.config)
        console.print(
            Panel.fit(
                f"[green bold]✓ 配置已保存至[/green bold] [cyan]{CONFIG_PATH}[/cyan]",
                border_style="green",
            )
        )

    def _load(self):
        try:
            # console.print(f"[dim]已读取: {CONFIG_PATH}[/dim]")
            return load_config()
        except FileNotFoundError:
            console.print("[yellow]未找到配置，将创建新配置[/yellow]")
            return None
        except Exception as exc:
            console.print(f"[red]读取失败: {exc}[/red]")
            raise SystemExit(1) from exc

    def _account(self):
        console.print("\n[bold blue]▍账户信息[/bold blue]")
        current = self.config.user.account if self.config else ""
        if current:
            if not ask(
                questionary.confirm,
                f"当前账户为 {current}，是否修改？",
                default=False,
                style=STYLE,
            ):
                return current, None
            account = ask(
                questionary.text,
                "账户",
                default=current,
                validate=VALIDATORS["blank"],
                style=STYLE,
            )
        else:
            console.print("[yellow]未检测到账户信息，请先设置[/yellow]")
            account = ask(
                questionary.text, "账户", validate=VALIDATORS["blank"], style=STYLE
            )
        return account, self._password()

    def _password(self):
        while True:
            pwd = ask(
                questionary.password, "密码", validate=VALIDATORS["blank"], style=STYLE
            )
            if pwd == ask(questionary.password, "确认密码", style=STYLE):
                return pwd
            console.print("[red]两次输入不一致，请重试[/red]")

    def _browser(self):
        console.print("\n[bold blue]▍浏览器设置[/bold blue]")
        current = self.config.libic.browser if self.config else "edge"
        return _select_browser(current)

    def _headless(self):
        default = self.config.libic.headless if self.config else False
        return ask(
            questionary.confirm,
            "是否启用无头模式（headless）？",
            default=default,
            style=STYLE,
        )

    def _assemble(self, account, pwd, browser, headless):
        if self.config:
            return self.config.model_copy(
                update={
                    "user": UserConfig(
                        account=account,
                        encrypted_password=self.config.user.encrypted_password
                        if pwd is None
                        else encrypt(pwd),
                    ),
                    "libic": self.config.libic.model_copy(
                        update={"browser": browser, "headless": headless}
                    ),
                }
            )
        return Config(
            user=UserConfig(account=account, encrypted_password=encrypt(pwd)),
            header=HeaderConfig(),
            eamis=EamisConfig(),
            libic=LibicConfig(browser=browser, headless=headless),
        )

    def _review(self):
        console.print("\n[bold blue]▍其他配置[/bold blue]")
        while True:
            self._table()
            choice = ask(
                questionary.select,
                "选择要修改的项，或保存并退出",
                choices=[questionary.Choice(title="✓ 保存并退出", value=SAVE)]
                + [
                    questionary.Choice(
                        title=f"{field.label}（当前：{_show(self.config, key)}）",
                        value=key,
                    )
                    for key, field in FIELDS.items()
                ],
                default=SAVE,
                style=STYLE,
            )
            if choice == SAVE:
                return
            self._edit(choice)
            console.print("[green]已更新[/green]")

    def _table(self):
        table = Table(
            title="当前配置", box=box.ROUNDED, border_style="cyan", title_justify="left"
        )
        table.add_column("#", style="dim", justify="right")
        table.add_column("选项", style="bold")
        table.add_column("当前值", style="cyan")
        table.add_column("说明", style="dim")
        for index, (key, field) in enumerate(FIELDS.items(), 1):
            table.add_row(str(index), field.label, _show(self.config, key), field.desc)
        console.print(table)

    def _edit(self, key):
        config = self.config
        assert config is not None  # run() 中已赋值
        field = FIELDS[key]
        value = field.editor(config.libic)
        self.config = config.model_copy(
            update={"libic": config.libic.model_copy(update={key: value})}
        )


def config():
    """交互式配置 libic 的账户、浏览器及预约参数。"""
    try:
        Wizard().run()
    except KeyboardInterrupt:
        console.print("\n[yellow]配置已取消，更改未保存[/yellow]")
