"""Main window and tray icon."""

import shlex
import subprocess
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton,
    QSizePolicy, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget,
)

from . import pipewire
from .settings import Settings, autostart_enabled, set_autostart

GRID_COLUMNS = 4

STATUS_COLORS = {"active": "#2e9d4f", "stopped": "#8a8a8a", "error": "#d03b3b"}


def dot_icon(color: str, size: int = 64) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    base = QIcon.fromTheme("audio-input-microphone")
    if not base.isNull():
        p.drawPixmap(0, 0, base.pixmap(size, size))
        r = size // 3
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(size - r, size - r, r, r)
    else:
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(4, 4, size - 8, size - 8)
    p.end()
    return QIcon(pm)


class ChannelCell(QWidget):
    def __init__(self, index: int, position: str, on_change):
        super().__init__()
        self.index = index
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        self.check = QCheckBox(f"{index + 1:>2}")
        self.check.setToolTip(f"Physical channel {index + 1} (PipeWire: {position})")
        self.check.toggled.connect(on_change)
        self.name = QLineEdit()
        self.name.setPlaceholderText("name")
        self.name.setMaximumWidth(110)
        self.name.textChanged.connect(on_change)
        lay.addWidget(self.check)
        lay.addWidget(self.name)


class MainWindow(QMainWindow):
    def __init__(self, include_virtual: bool = False, exec_line: str = ""):
        super().__init__()
        self.setWindowTitle("Channel Picker")
        self.setWindowIcon(QIcon.fromTheme("audio-input-microphone"))
        self.include_virtual = include_virtual
        self.exec_line = exec_line
        self.settings = Settings()
        self.loopback = pipewire.Loopback()
        self.devices: list[pipewire.Device] = []
        self.cells: list[ChannelCell] = []
        self.applied: tuple | None = None   # (node_name, channels, name) currently running
        self._loading = False
        self.quitting = False

        self._build()
        self._build_tray()
        self.refresh_devices()
        if self.settings["custom_name"]:
            self.auto_name.setChecked(False)
            self.name_edit.setText(self.settings["custom_name"])
        self._reload_presets()

        self.watchdog = QTimer(self, interval=1000, timeout=self._check_process)
        self.watchdog.start()

        if self.settings["active"] and self.current_device():
            self.apply()
        self._update_status()

    # ---------- layout ----------
    def _build(self):
        central = QWidget()
        root = QVBoxLayout(central)

        row = QHBoxLayout()
        row.addWidget(QLabel("Input device:"))
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.device_combo.currentIndexChanged.connect(self._device_changed)
        row.addWidget(self.device_combo)
        refresh = QToolButton()
        refresh.setIcon(QIcon.fromTheme("view-refresh"))
        refresh.setText("⟳")
        refresh.setToolTip("Re-scan devices")
        refresh.clicked.connect(self.refresh_devices)
        row.addWidget(refresh)
        root.addLayout(row)

        self.banner = QFrame()
        self.banner.setFrameShape(QFrame.Shape.StyledPanel)
        bl = QHBoxLayout(self.banner)
        bl.addWidget(QLabel("⚠ This device is not in the “Pro Audio” profile."))
        bl.addStretch()
        switch = QPushButton("Switch to Pro Audio")
        switch.clicked.connect(self._switch_profile)
        bl.addWidget(switch)
        self.banner.hide()
        root.addWidget(self.banner)

        self.no_device = QLabel("No multichannel input found. Plug in the interface and press ⟳.")
        self.no_device.hide()
        root.addWidget(self.no_device)

        self.channel_box = QGroupBox("Channels")
        cb = QVBoxLayout(self.channel_box)
        tools = QHBoxLayout()
        tools.addStretch()
        for text, state in (("All", True), ("None", False)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, s=state: self._set_all(s))
            tools.addWidget(b)
        cb.addLayout(tools)
        self.grid = QGridLayout()
        cb.addLayout(self.grid)
        root.addWidget(self.channel_box)

        row = QHBoxLayout()
        row.addWidget(QLabel("Virtual input name:"))
        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._name_edited)
        row.addWidget(self.name_edit)
        self.auto_name = QCheckBox("auto")
        self.auto_name.setChecked(True)
        self.auto_name.toggled.connect(self._auto_toggled)
        row.addWidget(self.auto_name)
        root.addLayout(row)

        self.result = QLabel()
        self.result.setWordWrap(True)
        root.addWidget(self.result)

        row = QHBoxLayout()
        row.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.preset_combo.activated.connect(self._preset_chosen)
        row.addWidget(self.preset_combo)
        save = QPushButton("Save…")
        save.clicked.connect(self._save_preset)
        row.addWidget(save)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_preset)
        row.addWidget(self.delete_btn)
        root.addLayout(row)

        self.autostart = QCheckBox("Start at login (minimised) and restore the last selection")
        self.autostart.setChecked(autostart_enabled())
        self.autostart.toggled.connect(self._autostart_toggled)
        root.addWidget(self.autostart)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(line)

        row = QHBoxLayout()
        self.status_dot = QLabel("●")
        row.addWidget(self.status_dot)
        self.status = QLabel()
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.stop_btn)
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.apply)
        row.addWidget(self.apply_btn)
        root.addLayout(row)

        self.setCentralWidget(central)

    def _build_tray(self):
        self.tray = QSystemTrayIcon(dot_icon(STATUS_COLORS["stopped"]), self)
        self.tray_menu = QMenu()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self._rebuild_tray_menu()

    def _rebuild_tray_menu(self):
        m = self.tray_menu
        m.clear()
        m.addAction("Show", self._show)
        presets = self.settings["presets"]
        if presets:
            sub = m.addMenu("Presets")
            for name in sorted(presets):
                sub.addAction(name, lambda n=name: (self._load_preset(n), self.apply()))
        m.addSeparator()
        act = QAction("Stop virtual input", m)
        act.triggered.connect(self.stop)
        act.setEnabled(self.loopback.running)
        m.addAction(act)
        m.addAction("Quit", self.quit)

    # ---------- devices & channels ----------
    def current_device(self) -> pipewire.Device | None:
        i = self.device_combo.currentIndex()
        return self.devices[i] if 0 <= i < len(self.devices) else None

    def refresh_devices(self):
        current = self.current_device()
        preferred = current.node_name if current else self.settings["last_device"]
        try:
            self.devices = pipewire.list_capture_devices(self.include_virtual)
        except (OSError, subprocess.CalledProcessError, ValueError) as e:
            self.devices = []
            self._set_error(f"Could not query PipeWire: {e}")
        self.devices.sort(key=lambda d: (-d.channels, d.description))
        default = pipewire.pick_default(self.devices, preferred)
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for d in self.devices:
            self.device_combo.addItem(d.label)
            self.device_combo.setItemData(self.device_combo.count() - 1, d.node_name,
                                          Qt.ItemDataRole.ToolTipRole)
        self.device_combo.blockSignals(False)
        if default:
            self.device_combo.setCurrentIndex(self.devices.index(default))
        self._device_changed()

    def _device_changed(self, *_):
        self._store_channel_names()
        dev = self.current_device()
        self.no_device.setVisible(dev is None)
        self.channel_box.setEnabled(dev is not None)
        self.banner.setVisible(bool(dev and dev.needs_pro_audio))
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.cells = []
        if dev:
            self._loading = True
            names = self.settings["channel_names"].get(dev.node_name, {})
            selected = set(self.settings["selection"].get(dev.node_name, []))
            for i in range(dev.channels):
                cell = ChannelCell(i, dev.positions[i], self._selection_changed)
                cell.name.setText(names.get(str(i), ""))
                cell.check.setChecked(i in selected)
                self.grid.addWidget(cell, i // GRID_COLUMNS, i % GRID_COLUMNS)
                self.cells.append(cell)
            self._loading = False
            self.settings["last_device"] = dev.node_name
        self._selection_changed()

    def selected_channels(self) -> list[int]:
        return [c.index for c in self.cells if c.check.isChecked()]

    def _set_all(self, state: bool):
        self._loading = True
        for c in self.cells:
            c.check.setChecked(state)
        self._loading = False
        self._selection_changed()

    def _store_channel_names(self):
        if not self.cells or not self.settings["last_device"]:
            return
        names = {str(c.index): c.name.text().strip() for c in self.cells if c.name.text().strip()}
        self.settings["channel_names"][self.settings["last_device"]] = names

    def _selection_changed(self, *_):
        if self._loading:
            return
        dev = self.current_device()
        chans = self.selected_channels()
        if dev:
            self.settings["selection"][dev.node_name] = chans
            self._store_channel_names()
        if self.auto_name.isChecked():
            self.name_edit.setText(pipewire.default_virtual_name(chans) if chans else "")
        if chans:
            parts = []
            for out, c in enumerate(chans, 1):
                label = self.cells[c].name.text().strip()
                parts.append(f"{out}←Ch {c + 1}" + (f" {label}" if label else ""))
            self.result.setText(f"<b>Result:</b> {len(chans)}-channel input &nbsp; " + " · ".join(parts))
        else:
            self.result.setText("<b>Result:</b> select at least one channel")
        self._update_status()

    def _name_edited(self, _):
        self.auto_name.setChecked(False)

    def _auto_toggled(self, on: bool):
        self.name_edit.setEnabled(True)
        if on:
            self._selection_changed()

    def virtual_name(self) -> str:
        return self.name_edit.text().strip() or pipewire.default_virtual_name(self.selected_channels())

    def _switch_profile(self):
        dev = self.current_device()
        if not dev or not dev.card_name:
            return
        try:
            pipewire.switch_to_pro_audio(dev.card_name)
        except (OSError, subprocess.CalledProcessError) as e:
            QMessageBox.warning(self, "Channel Picker", f"Could not switch profile:\n{getattr(e, 'stderr', e)}")
            return
        # node names change with the profile; give WirePlumber a moment
        QTimer.singleShot(1000, self.refresh_devices)

    # ---------- virtual input ----------
    def apply(self):
        dev = self.current_device()
        chans = self.selected_channels()
        if not dev or not chans:
            return
        name = self.virtual_name()
        wanted = (dev.node_name, tuple(chans), name)
        if self.loopback.running and self.applied == wanted:
            return
        was_running = self.loopback.running
        old_count = len(self.applied[1]) if self.applied else None
        self.loopback.start(pipewire.loopback_command(dev, chans, name))
        self.applied = wanted
        self.settings["active"] = True
        self.settings["custom_name"] = None if self.auto_name.isChecked() else name
        self.settings.save()
        if was_running and old_count != len(chans):
            self.tray.showMessage(
                "Channel Picker",
                f"The virtual input now has {len(chans)} channels. "
                "Recording apps may need to re-select it.",
                QSystemTrayIcon.MessageIcon.Information, 5000)
        # pw-loopback fails fast on bad arguments; check shortly after start
        QTimer.singleShot(500, self._check_process)
        self._update_status()

    def stop(self):
        self.loopback.stop()
        self.applied = None
        self.settings["active"] = False
        self.settings.save()
        self._update_status()

    def _check_process(self):
        if self.applied is None:
            return
        err = self.loopback.exit_error()
        if err:
            self.applied = None
            self._set_error(err)
            self._rebuild_tray_menu()

    def _set_error(self, text: str):
        self.status_dot.setStyleSheet(f"color: {STATUS_COLORS['error']}")
        self.status.setText(f"Error — {text}")
        self.tray.setIcon(dot_icon(STATUS_COLORS["error"]))
        self.tray.setToolTip("Channel Picker: error")

    def _update_status(self):
        dev = self.current_device()
        chans = self.selected_channels()
        if self.loopback.running and self.applied:
            _, achans, aname = self.applied
            pending = self.applied != (dev.node_name if dev else None, tuple(chans), self.virtual_name())
            state, text = "active", f"Active — “{aname}” ({len(achans)} ch)"
            if pending:
                text += " · changes not applied yet"
        else:
            state, text = "stopped", "Stopped"
        self.status_dot.setStyleSheet(f"color: {STATUS_COLORS[state]}")
        self.status.setText(text)
        self.tray.setIcon(dot_icon(STATUS_COLORS[state]))
        self.tray.setToolTip(f"Channel Picker: {text}")
        self.apply_btn.setEnabled(bool(dev and chans))
        self.stop_btn.setEnabled(self.loopback.running)
        self._rebuild_tray_menu()

    # ---------- presets ----------
    def _reload_presets(self, select: str | None = None):
        self.preset_combo.clear()
        self.preset_combo.addItem("—")
        for name in sorted(self.settings["presets"]):
            self.preset_combo.addItem(name)
        if select:
            self.preset_combo.setCurrentText(select)
        self.delete_btn.setEnabled(self.preset_combo.currentIndex() > 0)
        self._rebuild_tray_menu()

    def _save_preset(self):
        dev = self.current_device()
        if not dev:
            return
        current = self.preset_combo.currentText() if self.preset_combo.currentIndex() > 0 else ""
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:", text=current)
        name = name.strip()
        if not ok or not name:
            return
        self.settings["presets"][name] = {
            "device": dev.node_name,
            "channels": self.selected_channels(),
            "custom_name": None if self.auto_name.isChecked() else self.virtual_name(),
        }
        self.settings.save()
        self._reload_presets(name)

    def _delete_preset(self):
        name = self.preset_combo.currentText()
        if self.preset_combo.currentIndex() > 0 and name in self.settings["presets"]:
            del self.settings["presets"][name]
            self.settings.save()
            self._reload_presets()

    def _preset_chosen(self, index: int):
        self.delete_btn.setEnabled(index > 0)
        if index > 0:
            self._load_preset(self.preset_combo.currentText())

    def _load_preset(self, name: str):
        p = self.settings["presets"].get(name)
        if not p:
            return
        for i, d in enumerate(self.devices):
            if d.node_name == p["device"]:
                self.device_combo.setCurrentIndex(i)
                break
        else:
            self._set_error(f"Preset “{name}”: device {p['device']} is not available")
            return
        self._loading = True
        for c in self.cells:
            c.check.setChecked(c.index in p["channels"])
        self._loading = False
        self.auto_name.setChecked(p.get("custom_name") is None)
        if p.get("custom_name"):
            self.name_edit.setText(p["custom_name"])
        self._selection_changed()
        self.preset_combo.setCurrentText(name)

    # ---------- window / tray ----------
    def _autostart_toggled(self, on: bool):
        set_autostart(on, self.exec_line)

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.hide() if self.isVisible() else self._show()

    def _show(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if not self.quitting and self.tray.isVisible():
            # keep the virtual input alive in the tray
            self._store_channel_names()
            self.settings.save()
            self.hide()
            event.ignore()
            return
        self._shutdown()
        event.accept()

    def quit(self):
        self.quitting = True
        self._shutdown()
        QApplication.quit()

    def _shutdown(self):
        self._store_channel_names()
        # remember whether it was running so autostart can restore it
        self.settings["active"] = self.loopback.running
        self.settings.save()
        self.loopback.stop()


def default_exec_line() -> str:
    launcher = Path(__file__).resolve().parent.parent / "channel-picker"
    return shlex.quote(str(launcher))
