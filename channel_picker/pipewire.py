"""PipeWire access via its CLI tools (pw-dump, pw-loopback, pactl). No Qt in here."""

import json
import re
import shlex
import subprocess
from dataclasses import dataclass, field

VIRTUAL_NODE_NAME = "channel_picker"
PRO_AUDIO_PROFILE = "pro-audio"


@dataclass
class Device:
    node_name: str
    description: str
    channels: int
    positions: list[str]
    card_name: str | None = None
    profile: str | None = None
    profiles: list[str] = field(default_factory=list)

    @property
    def needs_pro_audio(self) -> bool:
        return (self.card_name is not None
                and self.profile != PRO_AUDIO_PROFILE
                and PRO_AUDIO_PROFILE in self.profiles)

    @property
    def label(self) -> str:
        return f"{self.description} ({self.channels} ch)"


def parse_positions(value) -> list[str]:
    """audio.position comes as a list, "AUX0,AUX1" or "[ AUX0 AUX1 ]"."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [p for p in re.split(r"[\s,\[\]]+", str(value)) if p]


def _format_info(params: dict) -> tuple[int, list[str]]:
    for key in ("Format", "EnumFormat"):
        for fmt in params.get(key) or []:
            if not isinstance(fmt, dict):
                continue
            channels = fmt.get("channels")
            positions = parse_positions(fmt.get("position"))
            if isinstance(channels, int) and channels > 0:
                return channels, positions
    return 0, []


def parse_devices(dump: list[dict], include_virtual: bool = False) -> list[Device]:
    """Extract capture devices from pw-dump output."""
    cards = {}
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Device":
            continue
        info = obj.get("info") or {}
        props = info.get("props") or {}
        params = info.get("params") or {}
        active = [p.get("name") for p in params.get("Profile") or [] if isinstance(p, dict)]
        cards[obj["id"]] = {
            "name": props.get("device.name"),
            "profile": active[0] if active else None,
            "profiles": [p.get("name") for p in params.get("EnumProfile") or []
                         if isinstance(p, dict) and p.get("name")],
        }

    devices = []
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        info = obj.get("info") or {}
        props = info.get("props") or {}
        if props.get("media.class") != "Audio/Source":
            continue
        name = props.get("node.name")
        if not name or name == VIRTUAL_NODE_NAME:
            continue
        if not include_virtual and props.get("device.api") != "alsa":
            continue

        channels, positions = _format_info(info.get("params") or {})
        if props.get("audio.channels"):
            channels = int(props["audio.channels"])
        positions = parse_positions(props.get("audio.position")) or positions
        if not channels:
            channels = len(positions)
        if not channels:
            continue
        if len(positions) != channels:
            positions = [f"AUX{i}" for i in range(channels)]

        card = cards.get(props.get("device.id"), {})
        devices.append(Device(
            node_name=name,
            description=props.get("node.description") or props.get("node.nick") or name,
            channels=channels,
            positions=positions,
            card_name=card.get("name"),
            profile=card.get("profile"),
            profiles=card.get("profiles", []),
        ))
    return devices


def list_capture_devices(include_virtual: bool = False) -> list[Device]:
    out = subprocess.run(["pw-dump"], capture_output=True, text=True, check=True).stdout
    return parse_devices(json.loads(out), include_virtual)


def pick_default(devices: list[Device], preferred_name: str | None = None) -> Device | None:
    """Last used device, else the 16-channel one, else the one with the most channels."""
    if not devices:
        return None
    for d in devices:
        if d.node_name == preferred_name:
            return d
    for d in devices:
        if d.channels == 16:
            return d
    return max(devices, key=lambda d: d.channels)


def switch_to_pro_audio(card_name: str) -> None:
    subprocess.run(["pactl", "set-card-profile", card_name, PRO_AUDIO_PROFILE],
                   capture_output=True, text=True, check=True)


def default_virtual_name(channels: list[int]) -> str:
    """channels are 0-based indices; the name uses 1-based numbers."""
    return "Interface Ch " + "/".join(str(c + 1) for c in channels)


def _props(d: dict) -> str:
    """Serialize to PipeWire's SPA-JSON-ish property syntax."""
    parts = []
    for k, v in d.items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, list):
            v = "[ " + " ".join(v) + " ]"
        else:
            v = json.dumps(str(v))
        parts.append(f"{k}={v}")
    return "{ " + " ".join(parts) + " }"


def loopback_command(device: Device, channels: list[int], description: str) -> list[str]:
    """Build the pw-loopback command exposing `channels` (0-based) of `device` as a new source."""
    if not channels:
        raise ValueError("no channels selected")
    out_positions = [f"AUX{i}" for i in range(len(channels))]
    capture = {
        "target.object": device.node_name,
        "audio.position": [device.positions[c] for c in channels],
        "stream.dont-remix": True,
        "node.passive": True,
        # never fall back to another source (e.g. the laptop mic) if the interface is missing
        "node.dont-reconnect": True,
        "node.dont-fallback": True,
    }
    playback = {
        "media.class": "Audio/Source",
        "node.name": VIRTUAL_NODE_NAME,
        "node.description": description,
        "audio.position": out_positions,
    }
    return [
        "pw-loopback",
        "-n", "channel-picker",
        "-c", str(len(channels)),
        "-m", "[ " + " ".join(out_positions) + " ]",
        "--capture-props", _props(capture),
        "--playback-props", _props(playback),
    ]


class Loopback:
    """Owns the pw-loopback child process that provides the virtual source."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self.command: list[str] | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, command: list[str]) -> None:
        self.stop()
        self.command = command
        self._proc = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, text=True)

    def exit_error(self) -> str | None:
        """If the process died, return its stderr (or exit code)."""
        if self._proc is None or self._proc.poll() is None:
            return None
        err = (self._proc.stderr.read() if self._proc.stderr else "").strip()
        code = self._proc.returncode
        self._proc = None
        return err or f"pw-loopback exited with code {code}"

    def stop(self) -> None:
        if self._proc is not None:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None

    def command_line(self) -> str:
        return shlex.join(self.command) if self.command else ""
