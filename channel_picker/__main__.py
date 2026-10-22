import argparse
import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from .ui import MainWindow, default_exec_line


def main() -> int:
    parser = argparse.ArgumentParser(prog="channel-picker")
    parser.add_argument("--minimized", action="store_true", help="start hidden in the system tray")
    parser.add_argument("--include-virtual", action="store_true",
                        help="also list non-ALSA sources (for testing with a fake device)")
    args, qt_args = parser.parse_known_args()

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("channel-picker")
    app.setApplicationDisplayName("Channel Picker")
    app.setDesktopFileName("channel-picker")
    app.setQuitOnLastWindowClosed(False)

    win = MainWindow(include_virtual=args.include_virtual, exec_line=default_exec_line())
    app.aboutToQuit.connect(win._shutdown)
    # Ctrl+C in the terminal should still clean up the virtual input
    signal.signal(signal.SIGINT, lambda *_: win.quit())
    signal.signal(signal.SIGTERM, lambda *_: win.quit())
    # let the Python interpreter run periodically so those handlers fire
    tick = QTimer(interval=300, timeout=lambda: None)
    tick.start()
    if not args.minimized or not win.tray.isVisible():
        win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
