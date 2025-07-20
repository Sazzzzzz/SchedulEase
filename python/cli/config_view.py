"""
CLI for creating and editing configurations.
"""

from prompt_toolkit import PromptSession
from prompt_toolkit import print_formatted_text as print
from prompt_toolkit.formatted_text import HTML

from config import create_config, load_config


def setup_config() -> None:
    """
    Interactively prompts the user for account and password to create/update the config file.
    """
    session = PromptSession()
    existing_account = ""

    try:
        config = load_config()
        existing_account = config.get("user", {}).get("account", "")
        print(HTML("<ansigreen>Existing configuration found.</ansigreen>"))
    except FileNotFoundError:
        print(
            HTML(
                "<ansiyellow>No existing configuration found. Let's create one.</ansiyellow>"
            )
        )

    print("\nPlease enter your university portal credentials.")
    account = session.prompt("Student ID: ", default=existing_account).strip()
    password = session.prompt("Password: ", is_password=True).strip()
    password_confirm = session.prompt("Confirm Password: ", is_password=True).strip()
    if password != password_confirm:
        print(HTML("<ansired>Passwords do not match. Please try again.</ansired>"))
        return None

    try:
        create_config(account, password)
        print(HTML("\n<ansigreen>Configuration saved successfully!</ansigreen>"))
    except Exception as e:
        print(HTML(f"<ansired>Failed to save configuration: {e}</ansired>"))


if __name__ == "__main__":
    setup_config()
