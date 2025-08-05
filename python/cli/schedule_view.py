import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from prompt_toolkit.filters import Condition
from prompt_toolkit.layout import (
    BufferControl,
    ConditionalContainer,
    FormattedTextControl,
    VSplit,
    Window,
)
from prompt_toolkit.layout.containers import HSplit
import schedule
from prompt_toolkit import PromptSession
from prompt_toolkit.validation import ValidationError, Validator
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from python.cli.base_view import View
from python.service import EamisService
from python.shared import Course


class TimeValidator(Validator):
    """Validator for time input in HH:MM format."""

    def validate(self, document):
        text = document.text.strip()
        if not text:
            raise ValidationError(message="Time cannot be empty")

        try:
            datetime.strptime(text, "%H:%M")
        except ValueError:
            raise ValidationError(
                message="Please enter time in HH:MM format (e.g., 14:30, 08:00)"
            )


# Previous CLI implementation
# class ScheduleView(View):
#     """Main scheduling interface for course elections."""

#     def __init__(self, service: EamisService):
#         self.service = service
#         self.session = PromptSession()
#         self.courses: list[Course] = []
#         self.time: Optional[str] = None
#         self.is_running = False
#         self.stop_event = threading.Event()

#         # Setup logging
#         self.setup_logging()
#         self.logger = logging.getLogger(__name__)

#     def setup_logging(self):
#         """Setup rich logging handler."""
#         logging.basicConfig(
#             level=logging.INFO,
#             format="%(message)s",
#             datefmt="[%X]",
#             handlers=[RichHandler(console=self.console, rich_tracebacks=True)],
#         )

#     def get_time_input(self) -> str:
#         """Get time input from user with validation."""
#         while True:
#             self.console.print("\n[bold cyan]Schedule Course Election[/bold cyan]")
#             self.console.print("Enter the time when you want to start course election.")
#             self.console.print("Format: HH:MM (24-hour format, e.g., 14:30)")

#             try:
#                 time_str = self.session.prompt(
#                     "Enter time: ",
#                     validator=TimeValidator(),
#                 ).strip()

#                 # Validate that the time is in the future
#                 target_time = datetime.strptime(time_str, "%H:%M").time()
#                 now = datetime.now()
#                 target_datetime = datetime.combine(now.date(), target_time)

#                 # If target time is earlier than current time, assume it's for tomorrow
#                 if target_datetime <= now:
#                     target_datetime += timedelta(days=1)
#                     self.console.print(
#                         f"[yellow]Note: Time {time_str} is in the past today, scheduling for tomorrow.[/yellow]"
#                     )

#                 self.console.print(
#                     f"[green]✓ Scheduled for: {target_datetime.strftime('%Y-%m-%d %H:%M')}[/green]"
#                 )
#                 return time_str

#             except KeyboardInterrupt:
#                 self.console.print("\n[yellow]Operation cancelled.[/yellow]")
#                 return ""
#             except Exception as e:
#                 self.console.print(f"[red]Error: {e}[/red]")
#                 return ""

#     def election_job(self):
#         """Job function to be executed at scheduled time."""
#         self.logger.info("🚀 Starting course election process...")

#         try:
#             if not self.courses:
#                 self.logger.error("No courses scheduled for election!")
#                 return

#             self.logger.info(f"Attempting to elect {len(self.courses)} courses:")
#             for course in self.courses:
#                 self.logger.info(f"  • {course.name} - {course.teachers}")

#             # Use the service's elect_courses method
#             self.service.elect_courses(self.courses, max_delay=1.0)

#             self.logger.info("✅ Course election process completed!")

#         except Exception as e:
#             self.logger.error(f"❌ Error during course election: {e}")

#     def run(self, courses: list[Course]):
#         """Main application entry point with courses provided as parameters."""
#         try:
#             self.console.print(
#                 Panel.fit(
#                     "[bold cyan]SchedulEase - Course Election Scheduler[/bold cyan]\n"
#                     "Schedule automatic course elections at specific times.",
#                     border_style="cyan",
#                 )
#             )
#             # Set the courses provided as parameters
#             self.courses = courses

#             # Display courses to be scheduled
#             if courses:
#                 self.console.print(
#                     f"\n[green]📚 Courses to be scheduled ({len(courses)}):[/green]"
#                 )
#                 for i, course in enumerate(courses, 1):
#                     self.console.print(f"  {i}. {course.name} - {course.teachers}")
#             else:
#                 self.console.print(
#                     "[yellow]No courses provided for scheduling.[/yellow]"
#                 )
#                 return

#             # Get time input
#             if not (time_str := self.get_time_input()):
#                 return

#             # Schedule the job
#             schedule.clear()  # Clear any existing jobs
#             schedule.every().day.at(time_str).do(self.election_job).tag("election")

#             self.console.print(f"\n[green]✅ Election scheduled for {time_str}[/green]")
#             self.console.print(
#                 f"[green]📚 {len(self.courses)} courses will be elected[/green]"
#             )
#             self.console.print(
#                 "[bold]Returning to main menu. The job will run in the background.[/bold]"
#             )
#             input("Press Enter to continue...")

#         except Exception as e:
#             self.console.print(f"[red]❌ Unexpected error: {e}[/red]")
#             self.logger.error(f"Unexpected error: {e}")

# Current TUI implementation


# --- Main Application Logic ---
if __name__ == "__main__":
    from python.tests.dummy_service import DummyEamisService

    try:
        # Initialize dummy service for testing
        service = DummyEamisService()

        # Load course data for testing from the dummy service
        test_courses = [
            Course.from_row(row, service)
            for row in service.course_info.head(2).to_dicts()
        ]  # Take first 2 courses

        # Create and run scheduler
        scheduler = ScheduleView(service)
        scheduler.run(test_courses)

    except FileNotFoundError:
        console = Console()
        console.print(
            "[red]Error: Could not find required files. Please ensure 'python/data/output.json' exists.[/red]"
        )
    except Exception as e:
        console = Console()
        console.print(f"[red]An error occurred: {e}[/red]")
