"""Okno główne Norn Queen: urządzenia BLE, kamery, podgląd i sterowanie gestami."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ble_manager import (
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_DISCONNECTED,
    STATE_DISCONNECTING,
    STATE_ERROR,
    BleManager,
)
from camera_worker import CameraScanner, CameraWorker
from gestures import CMD_STOP, COMMAND_NAMES, GESTURE_COMMANDS, build_frame

APP_DIR = Path(__file__).resolve().parent.parent
DEVICES_FILE = APP_DIR / "config" / "devices.json"
MODELS_DIR = APP_DIR.parent.parent / "assets" / "models"

STABLE_FRAMES = 4  # tyle kolejnych klatek z tym samym poleceniem zanim zostanie wysłane

STATE_TEXT = {
    STATE_DISCONNECTED: "Rozłączono",
    STATE_CONNECTING: "Łączenie…",
    STATE_CONNECTED: "Połączono",
    STATE_DISCONNECTING: "Rozłączanie…",
    STATE_ERROR: "Błąd",
}
STATE_COLOR = {
    STATE_DISCONNECTED: "#888888",
    STATE_CONNECTING: "#d89a00",
    STATE_CONNECTED: "#1a9c3a",
    STATE_DISCONNECTING: "#d89a00",
    STATE_ERROR: "#c62828",
}

COL_NAME, COL_ADDR, COL_STATE, COL_STATUS, COL_ACTION = range(5)


def load_devices() -> list[dict]:
    with open(DEVICES_FILE, encoding="utf-8") as f:
        return json.load(f)


def char_uuid(device: dict, kind: str) -> str | None:
    for ch in device.get("chars", []):
        if ch.get("type") == kind:
            return ch.get("uuid")
    return None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Norn Queen")
        self.resize(1280, 760)

        self.ble = BleManager()
        self.camera: CameraWorker | None = None
        self.scanner: CameraScanner | None = None
        self.devices: list[dict] = []
        self.rows: dict[str, int] = {}
        self.states: dict[str, str] = {}
        self.cameras: list[tuple[object, str]] = []

        self._candidate: int | None = None
        self._candidate_count = 0
        self._active_cmd: int | None = None
        self._last_sent: tuple[int, int] | None = None

        self._build_ui()
        self._load_devices()
        self._load_models()

        self.ble.state_changed.connect(self._on_device_state)
        self.ble.status_received.connect(self._on_device_status)
        self.ble.log.connect(self._log)

        self._refresh_cameras()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([460, 820])
        self.setCentralWidget(splitter)

    def _build_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        dev_box = QGroupBox("Urządzenia Bluetooth")
        dev_layout = QVBoxLayout(dev_box)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Nazwa", "Adres", "Stan", "Status", ""])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_ADDR, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_STATE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_ACTION, QHeaderView.ResizeMode.ResizeToContents)
        dev_layout.addWidget(self.table)

        btns = QHBoxLayout()
        self.btn_connect_all = QPushButton("Połącz wszystkie")
        self.btn_disconnect_all = QPushButton("Rozłącz wszystkie")
        self.btn_connect_all.clicked.connect(self._connect_all)
        self.btn_disconnect_all.clicked.connect(self._disconnect_all)
        btns.addWidget(self.btn_connect_all)
        btns.addWidget(self.btn_disconnect_all)
        dev_layout.addLayout(btns)
        layout.addWidget(dev_box, 1)

        cam_box = QGroupBox("Kamery")
        cam_layout = QVBoxLayout(cam_box)
        self.cam_list = QListWidget()
        self.cam_list.itemSelectionChanged.connect(self._update_camera_buttons)
        self.cam_list.itemDoubleClicked.connect(lambda _i: self._start_camera())
        cam_layout.addWidget(self.cam_list)

        form = QFormLayout()
        self.combo_model = QComboBox()
        self.spin_hands = QSpinBox()
        self.spin_hands.setRange(1, 4)
        self.spin_hands.setValue(2)
        self.spin_score = QDoubleSpinBox()
        self.spin_score.setRange(0.0, 1.0)
        self.spin_score.setSingleStep(0.05)
        self.spin_score.setValue(0.4)
        self.spin_score.valueChanged.connect(self._on_min_score)
        form.addRow("Model:", self.combo_model)
        form.addRow("Maks. liczba dłoni:", self.spin_hands)
        form.addRow("Min. pewność gestu:", self.spin_score)
        cam_layout.addLayout(form)

        cam_btns = QHBoxLayout()
        self.btn_refresh = QPushButton("Odśwież")
        self.btn_start = QPushButton("Uruchom")
        self.btn_stop = QPushButton("Zamknij")
        self.btn_refresh.clicked.connect(self._refresh_cameras)
        self.btn_start.clicked.connect(self._start_camera)
        self.btn_stop.clicked.connect(self._stop_camera)
        for b in (self.btn_refresh, self.btn_start, self.btn_stop):
            cam_btns.addWidget(b)
        cam_layout.addLayout(cam_btns)
        layout.addWidget(cam_box, 1)

        return panel

    def _build_right(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        self.video = QLabel("Kamera wyłączona")
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setMinimumSize(320, 240)
        self.video.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.video.setStyleSheet("background:#111; color:#aaa;")
        layout.addWidget(self.video, 1)

        stats_row = QHBoxLayout()

        img_box = QGroupBox("Obraz")
        img_form = QFormLayout(img_box)
        self.lbl_cam = QLabel("—")
        self.lbl_res = QLabel("—")
        self.lbl_fps = QLabel("—")
        self.lbl_backend = QLabel("—")
        img_form.addRow("Kamera:", self.lbl_cam)
        img_form.addRow("Rozdzielczość:", self.lbl_res)
        img_form.addRow("FPS (przetwarzanie / kamera):", self.lbl_fps)
        img_form.addRow("Backend:", self.lbl_backend)
        stats_row.addWidget(img_box)

        model_box = QGroupBox("Model")
        model_form = QFormLayout(model_box)
        self.lbl_model = QLabel("—")
        self.lbl_infer = QLabel("—")
        self.lbl_hands = QLabel("—")
        self.lbl_gesture = QLabel("—")
        self.lbl_score = QLabel("—")
        model_form.addRow("Model:", self.lbl_model)
        model_form.addRow("Czas inferencji:", self.lbl_infer)
        model_form.addRow("Wykryte dłonie:", self.lbl_hands)
        model_form.addRow("Gest:", self.lbl_gesture)
        model_form.addRow("Pewność:", self.lbl_score)
        stats_row.addWidget(model_box)

        send_box = QGroupBox("Sterowanie")
        send_form = QFormLayout(send_box)
        self.chk_send = QCheckBox("Wysyłaj ramki do połączonych urządzeń")
        self.chk_send.setChecked(True)
        self.chk_stop_lost = QCheckBox("STOP gdy brak dłoni")
        self.chk_stop_lost.setChecked(True)
        self.slider_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_speed.setRange(0, 255)
        self.slider_speed.setValue(200)
        self.lbl_speed = QLabel("200")
        self.slider_speed.valueChanged.connect(lambda v: self.lbl_speed.setText(str(v)))
        speed_row = QHBoxLayout()
        speed_row.addWidget(self.slider_speed, 1)
        speed_row.addWidget(self.lbl_speed)
        self.lbl_command = QLabel("—")
        self.lbl_frame = QLabel("—")
        send_form.addRow(self.chk_send)
        send_form.addRow(self.chk_stop_lost)
        send_form.addRow("Prędkość:", speed_row)
        send_form.addRow("Polecenie:", self.lbl_command)
        send_form.addRow("Ostatnia ramka:", self.lbl_frame)
        stats_row.addWidget(send_box)

        layout.addLayout(stats_row)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setMaximumHeight(110)
        layout.addWidget(self.log_view)

        return panel

    # --------------------------------------------------------------- dane
    def _log(self, msg: str) -> None:
        self.log_view.appendPlainText(f"[{datetime.now():%H:%M:%S}] {msg}")

    def _load_devices(self) -> None:
        try:
            self.devices = load_devices()
        except Exception as exc:  # noqa: BLE001
            self._log(f"Nie można wczytać {DEVICES_FILE}: {exc}")
            self.devices = []

        self.table.setRowCount(len(self.devices))
        for row, dev in enumerate(self.devices):
            addr = dev["address"]
            self.rows[addr] = row
            self.states[addr] = STATE_DISCONNECTED
            self.table.setItem(row, COL_NAME, QTableWidgetItem(dev.get("name", "")))
            self.table.setItem(row, COL_ADDR, QTableWidgetItem(addr))
            self.table.setItem(row, COL_STATE, QTableWidgetItem())
            self.table.setItem(row, COL_STATUS, QTableWidgetItem(""))
            btn = QPushButton()
            btn.clicked.connect(lambda _c=False, a=addr: self._toggle_device(a))
            self.table.setCellWidget(row, COL_ACTION, btn)
            self._render_state(addr, STATE_DISCONNECTED, "")

    def _load_models(self) -> None:
        models = sorted(MODELS_DIR.rglob("*.task")) if MODELS_DIR.exists() else []
        for path in models:
            self.combo_model.addItem(str(path.relative_to(MODELS_DIR)), path)
        if not models:
            self._log(f"Brak modeli .task w {MODELS_DIR}")
        self._update_camera_buttons()

    def _device(self, addr: str) -> dict:
        return next(d for d in self.devices if d["address"] == addr)

    # ------------------------------------------------------- urządzenia BLE
    def _render_state(self, addr: str, state: str, detail: str) -> None:
        row = self.rows[addr]
        item = self.table.item(row, COL_STATE)
        item.setToolTip(detail)
        item.setText(STATE_TEXT[state])
        item.setForeground(Qt.GlobalColor.white)
        item.setBackground(QColor(STATE_COLOR[state]))
        if state == STATE_ERROR or detail:
            self.table.item(row, COL_STATUS).setText(detail)
        btn: QPushButton = self.table.cellWidget(row, COL_ACTION)
        busy = state in (STATE_CONNECTING, STATE_DISCONNECTING)
        btn.setEnabled(not busy)
        btn.setText("Rozłącz" if state == STATE_CONNECTED else "Połącz")

    def _on_device_state(self, addr: str, state: str, detail: str) -> None:
        if addr not in self.rows:
            return
        self.states[addr] = state
        if state == STATE_CONNECTED:
            self.table.item(self.rows[addr], COL_STATUS).setText("")
            self._last_sent = None  # nowo połączone urządzenie dostanie aktualne polecenie
        self._render_state(addr, state, detail)

    def _on_device_status(self, addr: str, data: bytes) -> None:
        if addr not in self.rows or len(data) < 2:
            return
        text = f"tryb: {COMMAND_NAMES.get(data[0], data[0])}, prędkość: {data[1]}"
        self.table.item(self.rows[addr], COL_STATUS).setText(text)

    def _toggle_device(self, addr: str) -> None:
        if self.states.get(addr) == STATE_CONNECTED:
            self.ble.disconnect_device(addr)
        else:
            self._connect_device(addr)

    def _connect_device(self, addr: str) -> None:
        dev = self._device(addr)
        write_uuid = char_uuid(dev, "write")
        if not write_uuid:
            self._log(f"{addr}: brak charakterystyki typu 'write' w konfiguracji")
            return
        self.ble.connect_device(addr, write_uuid, char_uuid(dev, "read"))

    def _connect_all(self) -> None:
        for dev in self.devices:
            if self.states.get(dev["address"]) in (STATE_DISCONNECTED, STATE_ERROR):
                self._connect_device(dev["address"])

    def _disconnect_all(self) -> None:
        for addr, state in self.states.items():
            if state == STATE_CONNECTED:
                self.ble.disconnect_device(addr)

    # --------------------------------------------------------------- kamery
    def _refresh_cameras(self) -> None:
        if self.camera is not None or (self.scanner is not None and self.scanner.isRunning()):
            return
        self.cam_list.clear()
        self.cam_list.addItem("Szukanie kamer…")
        self.scanner = CameraScanner()
        self.scanner.done.connect(self._on_cameras_found)
        self.scanner.start()
        self._update_camera_buttons()

    def _on_cameras_found(self, cameras: list) -> None:
        self.cameras = cameras
        self.cam_list.clear()
        for _src, label in cameras:
            self.cam_list.addItem(label)
        if cameras:
            self.cam_list.setCurrentRow(0)
        else:
            self._log("Nie znaleziono kamer")
        self.scanner = None
        self._update_camera_buttons()

    def _update_camera_buttons(self) -> None:
        running = self.camera is not None
        scanning = self.scanner is not None
        has_sel = bool(self.cameras) and self.cam_list.currentRow() >= 0 and not scanning
        self.btn_start.setEnabled(has_sel and not running and self.combo_model.count() > 0)
        self.btn_stop.setEnabled(running)
        self.btn_refresh.setEnabled(not running and not scanning)
        self.cam_list.setEnabled(not running and not scanning)
        self.combo_model.setEnabled(not running)
        self.spin_hands.setEnabled(not running)

    def _start_camera(self) -> None:
        row = self.cam_list.currentRow()
        if self.camera is not None or row < 0 or row >= len(self.cameras):
            return
        source, label = self.cameras[row]
        model_path = self.combo_model.currentData()
        if model_path is None:
            return

        worker = CameraWorker(source, label, model_path, self.spin_hands.value(), self.spin_score.value())
        worker.frame_ready.connect(self._on_frame)
        worker.stats.connect(self._on_stats)
        worker.failed.connect(self._on_camera_failed)
        worker.finished.connect(self._on_camera_finished)
        self.camera = worker
        self.lbl_cam.setText(label)
        self.lbl_model.setText(f"{self.combo_model.currentText()} (maks. dłoni: {self.spin_hands.value()})")
        self._reset_gesture_state()
        worker.start()
        self._log(f"Uruchomiono kamerę: {label}")
        self._update_camera_buttons()

    def _stop_camera(self) -> None:
        worker = self.camera
        if worker is None:
            return
        worker.requestInterruption()
        self.btn_stop.setEnabled(False)

    def _on_camera_failed(self, msg: str) -> None:
        self._log(msg)

    def _on_camera_finished(self) -> None:
        worker, self.camera = self.camera, None
        if worker is not None:
            worker.deleteLater()
        self.video.clear()
        self.video.setText("Kamera wyłączona")
        for lbl in (self.lbl_cam, self.lbl_res, self.lbl_fps, self.lbl_backend, self.lbl_model,
                    self.lbl_infer, self.lbl_hands, self.lbl_gesture, self.lbl_score, self.lbl_command):
            lbl.setText("—")
        # po zatrzymaniu kamery nie zostawiamy robotów w ruchu
        if self.chk_send.isChecked() and self._last_sent is not None and self._last_sent[0] != CMD_STOP:
            self._send(CMD_STOP)
        self._reset_gesture_state()
        self._log("Kamera zatrzymana")
        self._update_camera_buttons()

    def _on_min_score(self, value: float) -> None:
        if self.camera is not None:
            self.camera.min_score = value

    def _on_frame(self, image: QImage) -> None:
        pix = QPixmap.fromImage(image).scaled(
            self.video.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation
        )
        self.video.setPixmap(pix)

    # ------------------------------------------------- statystyki i gesty
    def _on_stats(self, s: dict) -> None:
        self.lbl_res.setText(f"{s['width']} × {s['height']} px, {s['channels']} kan.")
        reported = f"{s['reported_fps']:.0f}" if s["reported_fps"] else "?"
        self.lbl_fps.setText(f"{s['fps']:.1f} / {reported}")
        self.lbl_backend.setText(str(s["backend"]))
        self.lbl_infer.setText(f"{s['inference_ms']:.1f} ms")
        self.lbl_hands.setText(str(s["hands"]))
        raw = s["raw_gesture"]
        if raw is None:
            self.lbl_gesture.setText("brak")
        else:
            suffix = f" ({s['handedness']})" if s["handedness"] else ""
            below = "" if s["gesture"] else " – poniżej progu"
            self.lbl_gesture.setText(f"{raw}{suffix}{below}")
        self.lbl_score.setText(f"{s['score']:.2f}")

        self._update_command(s)

    def _reset_gesture_state(self) -> None:
        self._candidate = None
        self._candidate_count = 0
        self._active_cmd = None
        self._last_sent = None

    def _update_command(self, s: dict) -> None:
        cmd = GESTURE_COMMANDS.get(s["gesture"]) if s["gesture"] else None
        if cmd is None and s["hands"] == 0 and self.chk_stop_lost.isChecked():
            cmd = CMD_STOP

        if cmd is not None:
            if cmd == self._candidate:
                self._candidate_count += 1
            else:
                self._candidate, self._candidate_count = cmd, 1
            if self._candidate_count >= STABLE_FRAMES:
                self._active_cmd = cmd
        else:
            self._candidate, self._candidate_count = None, 0

        if self._active_cmd is not None:
            self.lbl_command.setText(COMMAND_NAMES[self._active_cmd])
            if self.chk_send.isChecked():
                self._send(self._active_cmd)

    def _send(self, cmd: int) -> None:
        speed = self.slider_speed.value()
        if self._last_sent == (cmd, speed):
            return
        self._last_sent = (cmd, speed)
        frame = build_frame(cmd, speed)
        self.lbl_frame.setText(" ".join(f"{b:02X}" for b in frame))
        self.ble.send(frame)
        self._log(f"Ramka {self.lbl_frame.text()} ({COMMAND_NAMES[cmd]}, prędkość {speed})")

    # --------------------------------------------------------------- zamykanie
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.camera is not None:
            self.camera.requestInterruption()
            self.camera.wait(3000)
        if self.scanner is not None:
            self.scanner.wait(5000)
        self.ble.shutdown()
        super().closeEvent(event)
