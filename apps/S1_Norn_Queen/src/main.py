"""Norn Queen: domyślnie GUI (PySide6); z --cmd / --cli wersja konsolowa (np. przez SSH)."""

import argparse
import sys


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    from cli import add_cli_arguments

    parser = argparse.ArgumentParser(
        description="Norn Queen – sterowanie urządzeniami BLE gestami z kamery.",
        epilog="Bez --cmd / --cli uruchamia się okno GUI (ręczne łączenie i start kamery).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cmd", "--cli", dest="cli", action="store_true",
                      help="wersja konsolowa: od razu łączy z urządzeniami BLE i kamerą, bez GUI")
    add_cli_arguments(parser)
    return parser.parse_known_args(argv)


def main() -> int:
    # konsola z ograniczonym kodowaniem (np. cp1250) nie może wywracać programu na polskich znakach
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    args, rest = parse_args(sys.argv[1:])

    if args.cli:
        from cli import run

        return run(args)

    from PySide6.QtWidgets import QApplication

    from main_window import MainWindow

    app = QApplication([sys.argv[0], *rest])
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
