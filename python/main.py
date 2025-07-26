"""
Presenter for the whole SchedulEase application.
"""
import schedule
import threading
import time
from typing import Optional

from prompt_toolkit import print_formatted_text as print
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.shortcuts import radiolist_dialog, message_dialog, button_dialog

from cli.config_view import setup_config, load_config
from cli.election_view import ElectionView
from cli.schedule_view import ScheduleView
from python.tests.dummy_service import DummyEamisService
from service import EamisService, ConnectionError, LoginError
from shared import Course


class Application:
    """Main CLI Application."""

    def __init__(self):
        self.service: Optional[EamisService] = None
        self.selected_courses: list[Course] = []
        self.scheduler_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

    def _run_scheduler(self):
        """Target for the scheduler thread."""
        while not self.stop_event.is_set():
            schedule.run_pending()
            time.sleep(1)

    def run(self):
        """Main application entry point."""
        print(HTML("<b><ansicyan>Welcome to SchedulEase! 🎉</ansicyan></b>"))

        # --- Config and Service Initialization ---
        try:
            config = load_config()
            print("Configuration loaded. Initializing service...")
            # self.service = EamisService(config)
            self.service = DummyEamisService()
            self.service.initial_connection()
            print(HTML("<ansigreen>✓ Service initialized successfully.</ansigreen>"))
        except FileNotFoundError:
            if button_dialog(
                title="Configuration Not Found",
                text="No existing configuration found. Would you like to create one now?",
                buttons=[("Yes", True), ("No", False)],
            ).run():
                setup_config()
                self.run()  # Restart
            return
        except (ConnectionError, LoginError) as e:
            message_dialog(title="Service Error", text=f"Failed to connect: {e}").run()
            return
        except Exception as e:
            message_dialog(
                title="Error", text=f"An unexpected error occurred: {e}"
            ).run()
            return

        # --- Start Scheduler Thread ---
        self.scheduler_thread = threading.Thread(
            target=self._run_scheduler, daemon=True
        )
        self.scheduler_thread.start()

        # --- Main Menu Loop ---
        while True:
            next_run = schedule.next_run() if schedule.jobs else None
            next_run_time = (
                next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else "Not scheduled"
            )
            menu_title = HTML(
                "<b><ansicyan>SchedulEase Main Menu</ansicyan></b>\n"
                f"Selected Courses: <b>{len(self.selected_courses)}</b> | "
                f"Next Election: <b>{next_run_time}</b>"
            )

            choice = radiolist_dialog(
                title=menu_title,
                values=[
                    ("elect", "Elect Courses"),
                    ("schedule", "Schedule Election"),
                    ("config", "Edit Config"),
                    ("exit", "Exit"),
                ],
            ).run()

            if choice == "elect":
                election_view = ElectionView(self.service)
                self.selected_courses = election_view.run(self.selected_courses)
            elif choice == "schedule":
                if not self.selected_courses:
                    message_dialog(
                        title="No Courses",
                        text="Please select courses to elect first.",
                    ).run()
                    continue
                schedule_view = ScheduleView(self.service)
                schedule_view.run(self.selected_courses)
            elif choice == "config":
                setup_config()
                message_dialog(
                    title="Config Updated",
                    text="Configuration updated. Please restart the application to apply changes.",
                ).run()
                break  # Force restart
            elif choice == "exit" or choice is None:
                break

        # --- Cleanup ---
        self.stop_event.set()
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=2)
        print(HTML("<b><ansiyellow>Goodbye!</ansiyellow></b>"))


if __name__ == "__main__":
    app = Application()
    app.run()