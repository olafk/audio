"""Persistent settings in ~/.config/channel-picker/settings.json."""

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
SETTINGS_FILE = CONFIG_DIR / "channel-picker" / "settings.json"
AUTOSTART_FILE = CONFIG_DIR / "autostart" / "channel-picker.desktop"

DEFAULTS = {
    "last_device": None,
    "selection": {},        # node_name -> [0-based channel indices]
    "channel_names": {},    # node_name -> {"3": "Kick", ...}
    "custom_name": None,    # virtual input name, None = automatic
    "active": False,        # was the virtual input running when the app closed?
    "presets": {},          # name -> {"device", "channels", "custom_name"}
}


class Settings:
    def __init__(self, path: Path = SETTINGS_FILE):
        self.path = path
        self.data = json.loads(json.dumps(DEFAULTS))
        try:
            self.data.update(json.loads(path.read_text()))
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.data[key]

    def __setitem__(self, key, value):
        self.data[key] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.replace(self.path)


def autostart_enabled() -> bool:
    return AUTOSTART_FILE.exists()


def set_autostart(enabled: bool, exec_line: str) -> None:
    if not enabled:
        AUTOSTART_FILE.unlink(missing_ok=True)
        return
    AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART_FILE.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Channel Picker\n"
        "Comment=Expose selected channels of a multichannel audio interface\n"
        f"Exec={exec_line} --minimized\n"
        "Icon=audio-input-microphone\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
