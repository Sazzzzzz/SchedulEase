"""
Presenter for the whole SchedulEase application.
"""

from cli.config_view import setup_config, load_config
from service import EamisService


def main():
    # ---- Welcome Message ----
    # TODO: Implement a more fancier version with rich or prompt_toolkit
    print("Welcome to SchedulEase! 🎉")
    # ---- Config Loading ----
    try:
        config = load_config()
    except FileNotFoundError:
        print("No existing configuration found. Let's create one.")
        setup_config()
        config = load_config()
    service = EamisService(config)


if __name__ == "__main__":
    main()