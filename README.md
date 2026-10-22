# Channel Picker

A small Qt app for picking channels from a multichannel USB audio interface, e.g. channels 4, 6 and 7 of 16.
It exposes them as a new PipeWire input such as **"Interface Ch 4/6/7"** with 3 channels.
Any recording app (Audacity, OBS, a browser…) can then record from that input.

It uses no kernel driver and no PipeWire config files. The app runs `pw-loopback` for as long as it
is running, and keeps doing so when minimised to the system tray.

## Install

```sh
sudo apt install python3-pyqt6        # Kubuntu 24.04 and 26.04
```

`pw-dump`, `pw-loopback` and `pactl` come with Kubuntu's default PipeWire setup.

To get a menu entry (optional), use this command. It assumes the project lives in `/opt/dev/audio`;
otherwise, change `Exec=` in the file first:

```sh
cp channel-picker.desktop ~/.local/share/applications/
```

## Use

```sh
./channel-picker
```

1. **Input device:** the 16-channel input is preselected. After that, the app remembers the last one you used.
   If the app reports that the interface isn't in the *Pro Audio* profile, click **Switch to Pro Audio**.
2. Tick the channels. Numbers are 1-based, as printed on the hardware, and you can give each channel a name.
3. **Apply.** The *Result* line shows how channels map: input channel 1 of the new device ← physical channel 4, and so on.
4. Closing the window keeps the virtual input alive in the tray. Use **Quit** in the tray menu to remove it.

Presets save device, channels and name, and can be applied from the tray menu as well.
**Start at login** adds `~/.config/autostart/channel-picker.desktop`, which starts the app minimised and
restores the input that was active when the app was last quit.

Changing the *number* of channels recreates the virtual input. Recording apps may then need to
re-select it, so choose your channels before you start recording.

Settings are stored in `~/.config/channel-picker/settings.json`.

## Development

```sh
python3 -m unittest discover -s tests        # no Qt needed
tools/fake-interface.sh                       # creates fake 16 ch + 4 ch sources
./channel-picker --include-virtual            # lists non-ALSA sources as well
pw-link -l                                    # check routing (or use qpwgraph)
tools/fake-interface.sh stop
```
