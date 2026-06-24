import argparse

from core.runtime_env import load_runtime_env


def main() -> None:
    load_runtime_env()

    parser = argparse.ArgumentParser(description="Run Ra3Copilot.")
    parser.add_argument("--tui", action="store_true", help="Run the legacy Textual TUI.")
    parser.add_argument("--debug", action="store_true", help="Enable desktop webview debug mode.")
    args = parser.parse_args()

    if args.tui:
        from tui.app import run as run_tui

        run_tui()
        return

    from desktop.app import run as run_desktop

    run_desktop(debug=args.debug)


if __name__ == "__main__":
    main()