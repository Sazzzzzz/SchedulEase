import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

import schedule
from prompt_toolkit import PromptSession
from prompt_toolkit.validation import ValidationError, Validator
from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

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


class ScheduleView:
    """Main scheduling interface for course elections."""

    def __init__(self, service: EamisService):
        self.service = service
        self.console = Console()
        self.session = PromptSession()
        self.courses: list[Course] = []
        self.time: Optional[str] = None
        self.is_running = False
        self.stop_event = threading.Event()

        # Setup logging
        self.setup_logging()
        self.logger = logging.getLogger(__name__)

    def setup_logging(self):
        """Setup rich logging handler."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(console=self.console, rich_tracebacks=True)],
        )

    def get_time_input(self) -> str:
        """Get time input from user with validation."""
        while True:
            self.console.print("\n[bold cyan]Schedule Course Election[/bold cyan]")
            self.console.print("Enter the time when you want to start course election.")
            self.console.print("Format: HH:MM (24-hour format, e.g., 14:30)")

            try:
                time_str = self.session.prompt(
                    "Enter time: ",
                    validator=TimeValidator(),
                ).strip()

                # Validate that the time is in the future
                target_time = datetime.strptime(time_str, "%H:%M").time()
                now = datetime.now()
                target_datetime = datetime.combine(now.date(), target_time)

                # If target time is earlier than current time, assume it's for tomorrow
                if target_datetime <= now:
                    target_datetime += timedelta(days=1)
                    self.console.print(
                        f"[yellow]Note: Time {time_str} is in the past today, scheduling for tomorrow.[/yellow]"
                    )

                self.console.print(
                    f"[green]✓ Scheduled for: {target_datetime.strftime('%Y-%m-%d %H:%M')}[/green]"
                )
                return time_str

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Operation cancelled.[/yellow]")
                return ""
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")

    def election_job(self):
        """Job function to be executed at scheduled time."""
        self.logger.info("🚀 Starting course election process...")

        try:
            if not self.courses:
                self.logger.error("No courses scheduled for election!")
                return

            self.logger.info(f"Attempting to elect {len(self.courses)} courses:")
            for course in self.courses:
                self.logger.info(f"  • {course.name} - {course.teachers}")

            # Use the service's elect_courses method
            self.service.elect_courses(self.courses, max_delay=1.0)

            self.logger.info("✅ Course election process completed!")

        except Exception as e:
            self.logger.error(f"❌ Error during course election: {e}")

    def create_status_table(self) -> Table:
        """Create status table for live display."""
        table = Table(title="[bold cyan]Election Scheduler Status[/bold cyan]")
        table.add_column("Property", style="bold")
        table.add_column("Value", style="green")

        table.add_row("Scheduled Time", self.time or "Not set")
        table.add_row("Courses Count", str(len(self.courses)))
        table.add_row("Status", "Running" if self.is_running else "Waiting")
        table.add_row("Current Time", datetime.now().strftime("%H:%M:%S"))

        if self.courses:
            table.add_row("", "")  # Separator
            table.add_row("Scheduled Courses", "")
            for i, course in enumerate(self.courses, 1):
                table.add_row(f"  Course {i}", f"{course.name} - {course.teachers}")

        return table

    def monitoring_loop(self):
        """Main monitoring loop with live display."""
        with Live(
            self.create_status_table(), refresh_per_second=1, console=self.console
        ) as live:
            self.logger.info("📊 Monitoring started. Press Ctrl+C to stop.")

            while not self.stop_event.is_set():
                try:
                    schedule.run_pending()
                    live.update(self.create_status_table())
                    time.sleep(1)
                except Exception as e:
                    self.logger.error(f"Error in monitoring loop: {e}")

    def run(self, courses: list[Course]):
        """Main application entry point with courses provided as parameters."""
        try:
            self.console.print(
                Panel.fit(
                    "[bold cyan]SchedulEase - Course Election Scheduler[/bold cyan]\n"
                    "Schedule automatic course elections at specific times.",
                    border_style="cyan",
                )
            )
            # Set the courses provided as parameters
            self.courses = courses

            # Display courses to be scheduled
            if courses:
                self.console.print(
                    f"\n[green]📚 Courses to be scheduled ({len(courses)}):[/green]"
                )
                for i, course in enumerate(courses, 1):
                    self.console.print(f"  {i}. {course.name} - {course.teachers}")
            else:
                self.console.print(
                    "[yellow]No courses provided for scheduling.[/yellow]"
                )
                return

            # Get time input

            if not (time := self.get_time_input()):
                return

            self.time = time

            # Schedule the job
            schedule.every().day.at(time).do(self.election_job)

            self.console.print(f"\n[green]✅ Election scheduled for {time}[/green]")
            self.console.print(
                f"[green]📚 {len(self.courses)} courses will be elected[/green]"
            )

            self.is_running = True

            # Start monitoring in a separate thread
            monitor_thread = threading.Thread(target=self.monitoring_loop, daemon=True)
            monitor_thread.start()

            # Keep main thread alive and handle keyboard interrupt
            try:
                monitor_thread.join()
            except KeyboardInterrupt:
                self.console.print("\n[yellow]🛑 Stopping scheduler...[/yellow]")
                self.stop_event.set()
                schedule.clear()
                self.logger.info("Scheduler stopped by user.")

        except Exception as e:
            self.console.print(f"[red]❌ Unexpected error: {e}[/red]")
            self.logger.error(f"Unexpected error: {e}")


# --- Main Application Logic ---
if __name__ == "__main__":
    import polars as pl
    from config import load_config

    try:
        # Load configuration and initialize service
        config = load_config()
        service = EamisService(config)

        # Load course data for testing
        df = pl.read_json("data/output.json")

        # Create some test courses (in real usage, these would come from previous page)
        Course.df = df
        test_courses = [
            Course.from_row(row) for row in df.to_dicts()[:2]
        ]  # Take first 2 courses

        # Create and run scheduler
        scheduler = ScheduleView(service)
        scheduler.run(test_courses)

    except FileNotFoundError:
        console = Console()
        console.print(
            "[red]Error: Could not find required files. Please ensure 'data/output.json' exists.[/red]"
        )
    except Exception as e:
        console = Console()
        console.print(f"[red]An error occurred: {e}[/red]")
