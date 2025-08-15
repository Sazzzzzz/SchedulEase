"""
Presenter for the whole SchedulEase application.
"""

import threading
from argparse import ArgumentParser
from enum import Enum, auto
from typing import Optional

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
    def __init__(self, service: Optional[EamisService] = None, **kwargs):
        # service should only be specified when testing
        self.service = service
        self.bus = EventBus()
        # self.election_view = ElectionView(service, self.bus)
        # self.schedule_view = ScheduleView(service, self.bus)
        # self.config_view = ConfigView(self.bus)
        self.main_view = MainView(self.bus)
        super().__init__(
            layout=self.main_view.layout, key_bindings=self.get_keybindings(), **kwargs
        )
        self.register()
        self._state = Page.MAIN
        self.layout = self.main_view.layout
        threading.Thread(target=self.check_status, daemon=True).start()

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

        self.bus.subscribe(AppEvent.ELECTION_CONFIRMED, self.on_election_confirmed)

    def check_status(self) -> None:
        # Check for config
        config = None
        try:
            config = load_config()
            self.main_view.add_log(
                f"成功加载配置 [italic cyan]{CONFIG_PATH}[/italic cyan]",
                level=LogLevel.SUCCESS,
            )
        except Exception:
            self.main_view.add_log(
                f"无法从 [italic cyan]{CONFIG_PATH}[/italic cyan] 加载配置，请先设置账户",
                LogLevel.ERROR,
            )
            return None
        finally:
            self.config_view = ConfigView(self.bus)
            # Prevent bug from empty lookup dictionary
            self.lookup: dict[Page, View] = {
                Page.CONFIG: self.config_view,
            }
            self.bus.publish(AppEvent.APP_NO_CONFIG)

        # TODO: Handle missing config case
        if not self.service:
            assert config is not None
            self.service = EamisService(config)
        # Check for connection
        try:
            self.service.initial_connection()
            self.main_view.add_log("成功与网站建立连接", LogLevel.SUCCESS)
        except Exception as e:
            self.main_view.add_log(f"连接失败: {e}", LogLevel.ERROR)
            return None

        # login
        try:
            self.service.postlogin_response
            self.main_view.add_log("成功登录", LogLevel.SUCCESS)
        except Exception as e:
            self.main_view.add_log(f"连接失败: {e}", LogLevel.ERROR)
            return None
        # Load course info
        try:
            self.service.course_info
            self.main_view.add_log("成功加载课程信息", LogLevel.SUCCESS)
        except Exception as e:
            self.main_view.add_log(f"加载课程信息失败: {e}", LogLevel.ERROR)
            return None
        self.election_view = ElectionView(self.service, self.bus)
        self.schedule_view = ScheduleView(self.service, self.bus)
        self.lookup: dict[Page, View] = {
            Page.ELECTION: self.election_view,
            Page.SCHEDULE: self.schedule_view,
            Page.CONFIG: self.config_view,
        }
        self.bus.publish(AppEvent.APP_OK)
        self.main_view.add_log("应用程序已准备就绪", LogLevel.INFO)

    def set_on_election(self):
        self.state = Page.ELECTION

    def set_on_config(self):
        self.state = Page.CONFIG

    def set_on_main(self):
        self.state = Page.MAIN

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


def work():
    """Main entry point using real EamisService."""
    app = MainApp(full_screen=True)
    app.run()


def test():
    """Test entry point using DummyEamisService."""
    from .tests.dummy_service import dummy_service

    app = MainApp(service=dummy_service, full_screen=True)
    app.run()


def main():
    parser = ArgumentParser(description="SchedulEase CLI")
    parser.add_argument(
        "--test", action="store_true", help="Run SchedulEase in test mode."
    )

    args = parser.parse_args()
    if args.test:
        test()
    else:
        work()


if __name__ == "__main__":
    test()
