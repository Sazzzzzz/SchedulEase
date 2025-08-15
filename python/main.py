"""
Presenter for the whole SchedulEase application.
"""

from argparse import ArgumentParser
from enum import Enum, auto

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

from .cli.base_view import View
from .cli.config_view import ConfigView
from .cli.election_view import ElectionView
from .cli.main_view import MainView
from .cli.schedule_view import ScheduleView
from .service import EamisService
from .shared import AppEvent, Course, EventBus


class State(Enum):
    MAIN = auto()
    ELECTION = auto()
    SCHEDULE = auto()
    CONFIG = auto()


class MainApp(Application):
    def __init__(self, service: EamisService, **kwargs):
        self.service = service
        self.bus = EventBus()
        self.election_view = ElectionView(service, self.bus)
        self.schedule_view = ScheduleView(service, self.bus)
        self.config_view = ConfigView(service, self.bus)
        self.main_view = MainView(service, self.bus)
        self.lookup: dict[State, View] = {
            State.ELECTION: self.election_view,
            State.SCHEDULE: self.schedule_view,
            State.CONFIG: self.config_view,
        }
        super().__init__(
            layout=self.main_view.layout, key_bindings=self.get_keybindings(), **kwargs
        )
        self.register()
        self.state = State.MAIN

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, state: State):
        self._state = state
        self.layout = self.lookup.get(state, self.main_view).layout

    def register(self):
        self.bus.subscribe(AppEvent.MAIN_EXIT, self.exit)
        self.bus.subscribe(AppEvent.MAIN_ENTER_CONFIG, self.on_config)
        self.bus.subscribe(AppEvent.MAIN_ENTER_ELECTION, self.on_election)

        self.bus.subscribe(AppEvent.RETURN_TO_MAIN, self.on_main)

        self.bus.subscribe(AppEvent.ELECTION_CONFIRMED, self.on_election_confirmed)

    def on_election(self):
        self.state = State.ELECTION

    def on_config(self):
        self.state = State.CONFIG

    def on_main(self):
        self.state = State.MAIN

    def on_election_confirmed(self, courses: list[Course]):
        self.schedule_view.set_courses(courses)
        self.state = State.SCHEDULE

    def get_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-c")
        def _(event: KeyPressEvent):
            """Press Ctrl-C to exit the application."""
            event.app.exit()

        return kb


def work():
    """Main entry point using real EamisService."""
    from .config import load_config

    config = load_config()
    service = EamisService(config)

    app = MainApp(service=service, full_screen=True)
    app.run()


def test():
    """Test entry point using DummyEamisService."""
    from .tests.dummy_service import DummyEamisService

    service = DummyEamisService()

    app = MainApp(service=service, full_screen=True)
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
    main()
