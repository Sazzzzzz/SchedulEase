"""
Presenter for the whole SchedulEase application.
"""

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
        super().__init__(layout=self.main_view.layout, **kwargs)
        self.lookup: dict[State, View] = {
            State.ELECTION: self.election_view,
            State.SCHEDULE: self.schedule_view,
            State.CONFIG: self.config_view,
        }
        self.key_bindings = self.get_keybindings()
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


if __name__ == "__main__":
    from .tests.dummy_service import DummyEamisService

    app = MainApp(service=DummyEamisService(), full_screen=True)
    app.run()
