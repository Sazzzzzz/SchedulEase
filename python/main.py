"""
Presenter for the whole SchedulEase application.
"""

import threading
from argparse import ArgumentParser
from enum import Enum, auto

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

from .cli.base_view import View
from .cli.config_view import ConfigView
from .cli.election_view import ElectionView
from .cli.main_view import LogLevel, MainView
from .cli.schedule_view import ScheduleView
from .config import CONFIG_PATH, load_config
from .service import EamisService
from .shared import AppEvent, Course, EventBus


class Page(Enum):
    MAIN = auto()
    ELECTION = auto()
    SCHEDULE = auto()
    CONFIG = auto()


class MainApp(Application):
    def __init__(self, test: bool = False, **kwargs):
        # service should only be specified when testing
        self.bus = EventBus()
        # self.election_view = ElectionView(service, self.bus)
        # self.schedule_view = ScheduleView(service, self.bus)
        # self.config_view = ConfigView(self.bus)
        self.main_view = MainView(self.bus)
        self.lookup: dict[Page, View] = {Page.MAIN: self.main_view}
        super().__init__(
            layout=self.main_view.layout, key_bindings=self.get_keybindings(), **kwargs
        )
        self.register()
        self._state = Page.MAIN
        self.layout = self.main_view.layout
        threading.Thread(target=self.check_status, args=(test,), daemon=True).start()

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, state: Page):
        self._state = state
        self.layout = self.lookup.get(state, self.main_view).layout

    def register(self):
        self.bus.subscribe(AppEvent.MAIN_EXIT, self.exit)
        self.bus.subscribe(AppEvent.MAIN_ENTER_CONFIG, self.set_on_config)
        self.bus.subscribe(AppEvent.MAIN_ENTER_ELECTION, self.set_on_election)

        self.bus.subscribe(AppEvent.RETURN_TO_MAIN, self.set_on_main)

        self.bus.subscribe(AppEvent.CONFIG_CONFIRMED, self.on_config_confirmed)

        self.bus.subscribe(AppEvent.ELECTION_CONFIRMED, self.on_election_confirmed)

    def check_status(self, test: bool) -> None:
        # Check for config
        config = None
        try:
            config = load_config()
            self.add_log(
                f"成功加载配置 [italic cyan]{CONFIG_PATH}[/italic cyan]",
                level=LogLevel.SUCCESS,
            )
        except Exception:
            self.add_log(
                f"无法从 [italic cyan]{CONFIG_PATH}[/italic cyan] 加载配置，请先设置账户",
                LogLevel.ERROR,
            )
            return None
        finally:
            self.config_view = ConfigView(self.bus)
            # Prevent bug from empty lookup dictionary
            self.lookup[Page.CONFIG] = self.config_view

            self.bus.publish(AppEvent.APP_NO_CONFIG)

            assert config is not None
        if test:
            from .tests.dummy_service import DummyEamisService

            self.service = DummyEamisService(config)
        else:
            self.service = EamisService(config)
        # Check for connection
        try:
            self.service.initial_connection()
            self.add_log("成功与网站建立连接", LogLevel.SUCCESS)
        except Exception as e:
            self.add_log(f"连接失败: {e}", LogLevel.ERROR)
            return None

        # login
        try:
            self.service.postlogin_response
            self.add_log("成功登录", LogLevel.SUCCESS)
        except Exception as e:
            self.add_log(f"连接失败: {e}", LogLevel.ERROR)
            return None
        # Load course info
        try:
            self.service.course_info
            self.add_log("成功加载课程信息", LogLevel.SUCCESS)
        except Exception as e:
            self.add_log(f"加载课程信息失败: {e}", LogLevel.ERROR)
            return None
        self.election_view = ElectionView(self.service, self.bus)
        self.schedule_view = ScheduleView(self.service, self.bus)
        self.lookup[Page.ELECTION] = self.election_view
        self.lookup[Page.SCHEDULE] = self.schedule_view
        self.bus.publish(AppEvent.APP_OK)
        self.add_log("应用程序已准备就绪", LogLevel.INFO)

    def add_log(self, message: str, level: LogLevel = LogLevel.INFO):
        self.main_view.add_log(message, level)

    def set_on_election(self):
        self.state = Page.ELECTION

    def set_on_config(self):
        self.state = Page.CONFIG

    def set_on_main(self):
        self.state = Page.MAIN

    def on_config_confirmed(self):
        self.exit()

    def on_election_confirmed(self, courses: list[Course]):
        self.schedule_view.set_courses(courses)
        self.state = Page.SCHEDULE

    def get_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-c")
        def _(event: KeyPressEvent):
            """Press Ctrl-C to exit the application."""
            event.app.exit()

        return kb


def main():
    parser = ArgumentParser(description="SchedulEase CLI")
    parser.add_argument(
        "--test", action="store_true", help="Run SchedulEase in test mode."
    )

    args = parser.parse_args()
    test: bool = bool(args.test)
    app = MainApp(test=test, full_screen=True)
    app.run()


if __name__ == "__main__":
    main()
