import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from channel_picker import pipewire  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


class ParseDevices(unittest.TestCase):
    def test_lists_alsa_capture_nodes_only(self):
        devices = pipewire.parse_devices(load("pro-audio.json"))
        self.assertEqual([d.channels for d in devices], [4, 16, 2])
        self.assertNotIn("channel_picker", [d.node_name for d in devices])

    def test_include_virtual_lists_fake_but_never_itself(self):
        names = [d.node_name for d in pipewire.parse_devices(load("pro-audio.json"), include_virtual=True)]
        self.assertIn("fake16", names)
        self.assertNotIn("channel_picker", names)

    def test_channels_fall_back_to_format_params(self):
        d = pipewire.parse_devices(load("pro-audio.json"))[1]
        self.assertEqual(d.channels, 16)
        self.assertEqual(d.positions[3], "AUX3")

    def test_profile(self):
        pro = pipewire.parse_devices(load("pro-audio.json"))[1]
        self.assertFalse(pro.needs_pro_audio)
        std = pipewire.parse_devices(load("standard-profile.json"))[0]
        self.assertTrue(std.needs_pro_audio)
        self.assertEqual(std.card_name, "alsa_card.usb-Vendor_Interface-00")
        self.assertEqual(std.positions, ["FL", "FR", "RL", "RR"])

    def test_parse_positions(self):
        for value in ("AUX0,AUX1", "[ AUX0 AUX1 ]", ["AUX0", "AUX1"]):
            self.assertEqual(pipewire.parse_positions(value), ["AUX0", "AUX1"])


class PickDefault(unittest.TestCase):
    def setUp(self):
        self.devices = pipewire.parse_devices(load("pro-audio.json"))

    def test_prefers_16_channels(self):
        self.assertEqual(pipewire.pick_default(self.devices).channels, 16)

    def test_last_used_wins(self):
        last = "alsa_input.usb-Vendor_Interface-00.pro-input-0"
        self.assertEqual(pipewire.pick_default(self.devices, last).node_name, last)

    def test_unknown_last_used_falls_back(self):
        self.assertEqual(pipewire.pick_default(self.devices, "gone").channels, 16)

    def test_most_channels_without_16(self):
        devices = [d for d in self.devices if d.channels != 16]
        self.assertEqual(pipewire.pick_default(devices).channels, 4)

    def test_empty(self):
        self.assertIsNone(pipewire.pick_default([]))


class LoopbackCommand(unittest.TestCase):
    def test_maps_selected_channels(self):
        dev = pipewire.parse_devices(load("pro-audio.json"))[1]
        cmd = pipewire.loopback_command(dev, [3, 5, 6], "Interface Ch 4/6/7")
        self.assertEqual(cmd[cmd.index("-c") + 1], "3")
        capture = cmd[cmd.index("--capture-props") + 1]
        playback = cmd[cmd.index("--playback-props") + 1]
        self.assertIn(f'target.object="{dev.node_name}"', capture)
        self.assertIn("audio.position=[ AUX3 AUX5 AUX6 ]", capture)
        self.assertIn("stream.dont-remix=true", capture)
        self.assertIn('media.class="Audio/Source"', playback)
        self.assertIn('node.description="Interface Ch 4/6/7"', playback)
        self.assertIn("audio.position=[ AUX0 AUX1 AUX2 ]", playback)

    def test_uses_real_position_names(self):
        dev = pipewire.parse_devices(load("standard-profile.json"))[0]
        cmd = pipewire.loopback_command(dev, [1, 3], "x")
        self.assertIn("audio.position=[ FR RR ]", cmd[cmd.index("--capture-props") + 1])

    def test_quotes_description(self):
        dev = pipewire.parse_devices(load("pro-audio.json"))[1]
        cmd = pipewire.loopback_command(dev, [0], 'My "mic"')
        self.assertIn(r'node.description="My \"mic\""', cmd[cmd.index("--playback-props") + 1])

    def test_requires_channels(self):
        dev = pipewire.parse_devices(load("pro-audio.json"))[1]
        with self.assertRaises(ValueError):
            pipewire.loopback_command(dev, [], "x")

    def test_default_name_is_one_based(self):
        self.assertEqual(pipewire.default_virtual_name([3, 5, 6]), "Interface Ch 4/6/7")


if __name__ == "__main__":
    unittest.main()
