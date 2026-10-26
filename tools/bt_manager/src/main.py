#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BT Manager – PySide6 + Bleak

Funkcje:
  * skanowanie urządzeń Bluetooth Low Energy (nazwa, adres, RSSI, TX power,
    reklamowane UUID usług, manufacturer data, service data),
  * łączenie / rozłączanie z urządzeniem,
  * przeglądanie drzewa GATT (usługi -> charakterystyki -> deskryptory),
  * odczyt charakterystyk, subskrypcja powiadomień (notify / indicate),
  * wysyłanie danych (write / write-without-response) z edytorem HEX
    binarnego payloadu (edycja bajt po bajcie, wklejanie HEX, tekst -> bajty,
    wczytywanie/zapis pliku, dzielenie na pakiety).

Instalacja:
    pip install PySide6 bleak

Uruchomienie:
    python main.py

Uwaga: obsługiwane jest Bluetooth Low Energy (BLE/GATT). Klasyczny
Bluetooth (BR/EDR, RFCOMM/SPP) nie jest obsługiwany przez bibliotekę Bleak.
"""
from __future__ import annotations

import asyncio
import re
import sys
import threading
import time
from datetime import datetime

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QRegularExpression,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFontDatabase,
    QKeySequence,
    QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStyledItemDelegate,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from bleak import BleakClient, BleakScanner
    from bleak.uuids import uuidstr_to_str
except ImportError:  # pragma: no cover
    print("Brak biblioteki 'bleak'. Zainstaluj ją poleceniem:  pip install bleak")
    sys.exit(1)


BYTES_PER_ROW = 16
MAX_FILE_SIZE = 1024 * 1024  # 1 MiB


# --------------------------------------------------------------------------- #
#  Pomocnicze funkcje
# --------------------------------------------------------------------------- #
def hex_str(data: bytes, sep: str = " ") -> str:
    return sep.join(f"{b:02X}" for b in data)


def ascii_str(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def uuid_name(u: str) -> str:
    """Nazwa znanego UUID (Bluetooth SIG) lub pusty string."""
    try:
        name = uuidstr_to_str(u)
    except Exception:
        return ""
    if not name or name.lower() == "unknown":
        return ""
    return name


def parse_hex(text: str) -> bytes:
    """Parsuje HEX w dowolnym popularnym formacie:
    'DE AD BE EF', 'DEADBEEF', '0xDE,0xAD', 'de:ad:be:ef' ...
    Pojedyncza cyfra w tokenie jest dopełniana zerem z lewej ('1 2' -> 01 02).
    """
    parts = []
    for tok in re.split(r"[\s,;:\-]+", text.strip()):
        if not tok:
            continue
        if tok[:2].lower() == "0x":
            tok = tok[2:]
        if not tok:
            raise ValueError("Pusty token HEX")
        if not re.fullmatch(r"[0-9A-Fa-f]+", tok):
            raise ValueError(f"Niepoprawny token HEX: {tok!r}")
        if len(tok) % 2:
            tok = "0" + tok
        parts.append(tok)
    return bytes.fromhex("".join(parts))


# --------------------------------------------------------------------------- #
#  Worker BLE – własna pętla asyncio w osobnym wątku
# --------------------------------------------------------------------------- #
class BleWorker(QObject):
    device_seen = Signal(object)          # dict
    scan_state = Signal(bool)
    connected = Signal(str, object, int)  # adres, lista usług, MTU
    disconnected = Signal()
    log = Signal(str)
    error = Signal(str)
    notification = Signal(int, object)    # handle, bytes
    read_done = Signal(int, object)       # handle, bytes
    write_done = Signal(int, int, int)    # handle, liczba bajtów, liczba pakietów
    notify_state = Signal(int, bool)

    def __init__(self) -> None:
        super().__init__()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="ble-loop", daemon=True)
        self._thread.start()
        self._scanner: BleakScanner | None = None
        self._client: BleakClient | None = None
        self._devices: dict[str, object] = {}
        self._notifying: set[int] = set()

    # ---- infrastruktura ---------------------------------------------------
    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro, what: str) -> None:
        asyncio.run_coroutine_threadsafe(self._guard(coro, what), self._loop)

    async def _guard(self, coro, what: str) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"{what}: {exc}")

    def _require_client(self) -> BleakClient:
        if self._client is None or not self._client.is_connected:
            raise RuntimeError("Brak aktywnego połączenia")
        return self._client

    # ---- API wywoływane z wątku GUI --------------------------------------
    def start_scan(self) -> None:
        self._submit(self._start_scan(), "Skanowanie")

    def stop_scan(self) -> None:
        self._submit(self._stop_scan(), "Zatrzymanie skanowania")

    def connect_device(self, address: str) -> None:
        self._submit(self._connect(address), "Łączenie")

    def disconnect_device(self) -> None:
        self._submit(self._disconnect(), "Rozłączanie")

    def read(self, handle: int) -> None:
        self._submit(self._read(handle), "Odczyt")

    def write(self, handle: int, data: bytes, response: bool, chunk: int) -> None:
        self._submit(self._write(handle, data, response, chunk), "Zapis")

    def set_notify(self, handle: int, enable: bool) -> None:
        self._submit(self._set_notify(handle, enable), "Powiadomienia")

    def shutdown(self) -> None:
        fut = asyncio.run_coroutine_threadsafe(self._cleanup(), self._loop)
        try:
            fut.result(timeout=4)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    # ---- korutyny (wątek asyncio) ----------------------------------------
    async def _cleanup(self) -> None:
        try:
            await self._stop_scan()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._disconnect()
        except Exception:  # noqa: BLE001
            pass

    def _on_adv(self, device, adv) -> None:
        self._devices[device.address] = device
        info = {
            "address": device.address,
            "name": adv.local_name or device.name or "",
            "rssi": adv.rssi,
            "tx_power": adv.tx_power,
            "uuids": list(adv.service_uuids or []),
            "manufacturer": {k: bytes(v) for k, v in (adv.manufacturer_data or {}).items()},
            "service_data": {k: bytes(v) for k, v in (adv.service_data or {}).items()},
        }
        self.device_seen.emit(info)

    async def _start_scan(self) -> None:
        if self._scanner is not None:
            return
        scanner = BleakScanner(detection_callback=self._on_adv, scanning_mode="active")
        try:
            await scanner.start()
        except Exception:
            self.scan_state.emit(False)
            raise
        self._scanner = scanner
        self.scan_state.emit(True)
        self.log.emit("Skanowanie rozpoczęte")

    async def _stop_scan(self) -> None:
        scanner, self._scanner = self._scanner, None
        if scanner is not None:
            try:
                await scanner.stop()
            finally:
                self.scan_state.emit(False)
                self.log.emit("Skanowanie zatrzymane")

    def _on_disconnected(self, client) -> None:
        if client is self._client:
            self._client = None
            self._notifying.clear()
            self.disconnected.emit()
            self.log.emit("Rozłączono")

    async def _connect(self, address: str) -> None:
        await self._disconnect()
        await self._stop_scan()  # skanowanie podczas łączenia bywa problematyczne
        target = self._devices.get(address) or address
        client = BleakClient(
            target,
            disconnected_callback=self._on_disconnected,
            timeout=15.0,
            winrt={"use_cached_services": False},  # Windows: nie używaj starego cache GATT
        )
        try:
            await client.connect()
        except Exception as exc:  # noqa: BLE001
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            msg = str(exc)
            low = msg.lower()
            if "service" in low and ("not be found" in low or "cannot" in low or "not found" in low):
                raise RuntimeError(
                    f"{msg}\n\n"
                    "To urządzenie nie udostępnia serwera GATT przez Bluetooth Low Energy "
                    "(typowe dla urządzeń Classic: słuchawki, głośniki, część telefonów, "
                    "które reklamują się w BLE, ale nie mają dostępnych usług). "
                    "Ta aplikacja łączy się tylko z urządzeniami BLE z serwerem GATT."
                ) from exc
            raise
        self._client = client
        try:
            mtu = int(getattr(client, "mtu_size", 23) or 23)
        except Exception:  # noqa: BLE001
            mtu = 23
        self.connected.emit(address, self._dump_services(client), mtu)

    async def _disconnect(self) -> None:
        client = self._client
        if client is None:
            return
        try:
            for h in list(self._notifying):
                try:
                    await client.stop_notify(h)
                except Exception:  # noqa: BLE001
                    pass
            await client.disconnect()
        finally:
            if self._client is client:  # callback mógł nie zadziałać
                self._client = None
                self._notifying.clear()
                self.disconnected.emit()

    @staticmethod
    def _dump_services(client: BleakClient) -> list[dict]:
        result = []
        for s in client.services:
            chars = []
            for c in s.characteristics:
                chars.append(
                    {
                        "uuid": c.uuid,
                        "handle": c.handle,
                        "description": c.description,
                        "properties": list(c.properties),
                        "descriptors": [
                            {"uuid": d.uuid, "handle": d.handle, "description": d.description}
                            for d in c.descriptors
                        ],
                    }
                )
            result.append(
                {
                    "uuid": s.uuid,
                    "handle": s.handle,
                    "description": s.description,
                    "characteristics": chars,
                }
            )
        return result

    async def _read(self, handle: int) -> None:
        client = self._require_client()
        data = await client.read_gatt_char(handle)
        self.read_done.emit(handle, bytes(data))

    async def _write(self, handle: int, data: bytes, response: bool, chunk: int) -> None:
        client = self._require_client()
        if chunk and chunk > 0:
            parts = [data[i : i + chunk] for i in range(0, len(data), chunk)]
        else:
            parts = [data]
        for part in parts:
            await client.write_gatt_char(handle, part, response=response)
        self.write_done.emit(handle, len(data), len(parts))

    async def _set_notify(self, handle: int, enable: bool) -> None:
        client = self._require_client()
        if enable:
            await client.start_notify(
                handle, lambda _sender, d, h=handle: self.notification.emit(h, bytes(d))
            )
            self._notifying.add(handle)
        else:
            await client.stop_notify(handle)
            self._notifying.discard(handle)
        self.notify_state.emit(handle, enable)


# --------------------------------------------------------------------------- #
#  Edytor HEX
# --------------------------------------------------------------------------- #
class HexModel(QAbstractTableModel):
    """Model: kolumny 0..15 = bajty HEX, kolumny 16..31 = ten sam bajt jako ASCII.
    Zawsze istnieje dodatkowa pusta komórka na końcu – edycja jej dopisuje bajt."""

    changed = Signal()
    COLS = BYTES_PER_ROW * 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._data = bytearray()

    # ---- API ----
    def bytes(self) -> bytes:
        return bytes(self._data)

    def length(self) -> int:
        return len(self._data)

    def byte_at(self, pos: int) -> int:
        return self._data[pos]

    def pos(self, index: QModelIndex) -> int:
        return index.row() * BYTES_PER_ROW + index.column() % BYTES_PER_ROW

    def set_bytes(self, data: bytes) -> None:
        self.beginResetModel()
        self._data = bytearray(data)
        self.endResetModel()
        self.changed.emit()

    def insert_at(self, pos: int, data: bytes) -> None:
        pos = max(0, min(pos, len(self._data)))
        self.beginResetModel()
        self._data[pos:pos] = data
        self.endResetModel()
        self.changed.emit()

    def delete_positions(self, positions) -> None:
        drop = set(positions)
        if not drop:
            return
        self.beginResetModel()
        self._data = bytearray(b for i, b in enumerate(self._data) if i not in drop)
        self.endResetModel()
        self.changed.emit()

    # ---- QAbstractTableModel ----
    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._data) // BYTES_PER_ROW + 1

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else self.COLS

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
        )

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self.pos(index)
        ascii_col = index.column() >= BYTES_PER_ROW
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if p >= len(self._data):
                return ""
            b = self._data[p]
            if ascii_col:
                if 32 <= b < 127:
                    return chr(b)
                return "" if role == Qt.ItemDataRole.EditRole else "·"
            return f"{b:02X}"
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.BackgroundRole and ascii_col:
            return QBrush(QColor(128, 128, 128, 28))
        if role == Qt.ItemDataRole.ToolTipRole and p < len(self._data):
            b = self._data[p]
            return f"offset {p} (0x{p:X})\nHEX 0x{b:02X} | DEC {b} | BIN {b:08b}"
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        text = str(value)
        if index.column() >= BYTES_PER_ROW:
            if len(text) != 1:
                return False
            try:
                byte = text.encode("latin-1")[0]
            except UnicodeEncodeError:
                return False
        else:
            text = text.strip()
            if not re.fullmatch(r"[0-9A-Fa-f]{1,2}", text):
                return False
            byte = int(text, 16)

        p = self.pos(index)
        if p >= len(self._data):
            self._grow(p + 1)
        self._data[p] = byte
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, self.COLS - 1))
        self.changed.emit()
        return True

    def _grow(self, new_len: int) -> None:
        old_rows = self.rowCount()
        new_rows = new_len // BYTES_PER_ROW + 1
        if new_rows > old_rows:
            self.beginInsertRows(QModelIndex(), old_rows, new_rows - 1)
            self._data.extend(b"\x00" * (new_len - len(self._data)))
            self.endInsertRows()
        else:
            self._data.extend(b"\x00" * (new_len - len(self._data)))

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return f"{section:02X}" if section < BYTES_PER_ROW else f"{section - BYTES_PER_ROW:X}"
            return f"{section * BYTES_PER_ROW:08X}"
        return None


class ByteDelegate(QStyledItemDelegate):
    """Edytor komórki: 2 cyfry HEX albo 1 znak ASCII; po wpisaniu skacze do następnej."""

    def createEditor(self, parent, option, index):
        ed = QLineEdit(parent)
        ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row, col = index.row(), index.column()
        if col >= BYTES_PER_ROW:
            limit = 1
            ed.setMaxLength(1)
        else:
            limit = 2
            ed.setMaxLength(2)
            ed.setValidator(
                QRegularExpressionValidator(QRegularExpression("[0-9A-Fa-f]{0,2}"), ed)
            )
        ed.textEdited.connect(
            lambda t, e=ed, r=row, c=col, n=limit: self._advance(e, r, c) if len(t) >= n else None
        )
        return ed

    def _advance(self, editor, row: int, col: int) -> None:
        self.commitData.emit(editor)
        self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        base = BYTES_PER_ROW if col >= BYTES_PER_ROW else 0
        nc, nr = col + 1, row
        if nc >= base + BYTES_PER_ROW:
            nc, nr = base, row + 1
        QTimer.singleShot(0, lambda: self._edit(nr, nc))

    def _edit(self, row: int, col: int) -> None:
        view = self.parent()
        model = view.model()
        if row < model.rowCount():
            idx = model.index(row, col)
            view.setCurrentIndex(idx)
            view.edit(idx)


class HexTableView(QTableView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.AnyKeyPressed
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.verticalHeader().setDefaultSectionSize(24)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().setDefaultSectionSize(26)

    def setModel(self, model) -> None:  # noqa: N802
        super().setModel(model)
        for c in range(model.columnCount()):
            self.setColumnWidth(c, 27 if c < BYTES_PER_ROW else 18)

    def selected_positions(self) -> list[int]:
        m = self.model()
        out = set()
        for idx in self.selectedIndexes():
            p = m.pos(idx)
            if p < m.length():
                out.add(p)
        return sorted(out)

    def current_pos(self) -> int:
        m = self.model()
        idx = self.currentIndex()
        if idx.isValid():
            return min(m.pos(idx), m.length())
        return m.length()

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        m = self.model()
        if ev.matches(QKeySequence.StandardKey.Copy):
            ps = self.selected_positions()
            if ps:
                QApplication.clipboard().setText(hex_str(bytes(m.byte_at(p) for p in ps)))
            return
        if ev.matches(QKeySequence.StandardKey.Paste):
            try:
                data = parse_hex(QApplication.clipboard().text())
            except ValueError:
                return
            m.insert_at(self.current_pos(), data)
            return
        if ev.key() == Qt.Key.Key_Delete:
            m.delete_positions(self.selected_positions())
            return
        super().keyPressEvent(ev)


class HexEditorWidget(QWidget):
    """Edytor binarnego payloadu: siatka HEX/ASCII + linia HEX + tekst -> bajty."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._line_updating = False
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

        self.model = HexModel(self)
        self.view = HexTableView(self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(ByteDelegate(self.view))
        self.view.setToolTip(
            "Kliknij komórkę i wpisz 2 cyfry HEX (lub znak w części ASCII).\n"
            "Ctrl+C – kopiuj zaznaczone bajty jako HEX, Ctrl+V – wstaw HEX ze schowka,\n"
            "Delete – usuń zaznaczone bajty. Pusta komórka na końcu dopisuje bajt."
        )

        # linia HEX
        self.line = QLineEdit()
        self.line.setFont(mono)
        self.line.setPlaceholderText("HEX, np.: DE AD BE EF  |  0xDE,0xAD  |  deadbeef")
        self.lbl_size = QLabel("0 B")
        self.lbl_size.setMinimumWidth(110)
        line_row = QHBoxLayout()
        line_row.addWidget(QLabel("HEX:"))
        line_row.addWidget(self.line, 1)
        line_row.addWidget(self.lbl_size)

        # tekst -> bajty
        self.txt = QLineEdit()
        self.txt.setPlaceholderText("Tekst, który zostanie zamieniony na bajty")
        self.cmb_enc = QComboBox()
        for label, codec in (("UTF-8", "utf-8"), ("ASCII", "ascii"), ("Latin-1", "latin-1"), ("UTF-16 LE", "utf-16-le")):
            self.cmb_enc.addItem(label, codec)
        self.cmb_term = QComboBox()
        for label, value in (("bez końcówki", b""), ("+ \\n", b"\n"), ("+ \\r\\n", b"\r\n"), ("+ \\0", b"\x00")):
            self.cmb_term.addItem(label, value)
        self.btn_txt_replace = QPushButton("Zastąp")
        self.btn_txt_append = QPushButton("Dołącz")
        txt_row = QHBoxLayout()
        txt_row.addWidget(QLabel("Tekst:"))
        txt_row.addWidget(self.txt, 1)
        txt_row.addWidget(self.cmb_enc)
        txt_row.addWidget(self.cmb_term)
        txt_row.addWidget(self.btn_txt_replace)
        txt_row.addWidget(self.btn_txt_append)

        # przyciski narzędziowe
        self.btn_clear = QPushButton("Wyczyść")
        self.btn_insert = QPushButton("Wstaw 00")
        self.btn_delete = QPushButton("Usuń zaznaczone")
        self.btn_copy = QPushButton("Kopiuj HEX")
        self.btn_load = QPushButton("Wczytaj plik…")
        self.btn_save = QPushButton("Zapisz plik…")
        tools = QHBoxLayout()
        for b in (self.btn_clear, self.btn_insert, self.btn_delete, self.btn_copy, self.btn_load, self.btn_save):
            tools.addWidget(b)
        tools.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(tools)
        lay.addWidget(self.view, 1)
        lay.addLayout(line_row)
        lay.addLayout(txt_row)

        # sygnały
        self.model.changed.connect(self._on_model_changed)
        self.line.textEdited.connect(self._on_line_edited)
        self.line.editingFinished.connect(self._on_line_finished)
        self.btn_clear.clicked.connect(lambda: self.model.set_bytes(b""))
        self.btn_insert.clicked.connect(lambda: self.model.insert_at(self.view.current_pos(), b"\x00"))
        self.btn_delete.clicked.connect(lambda: self.model.delete_positions(self.view.selected_positions()))
        self.btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(hex_str(self.model.bytes())))
        self.btn_load.clicked.connect(self._load_file)
        self.btn_save.clicked.connect(self._save_file)
        self.btn_txt_replace.clicked.connect(lambda: self._apply_text(replace=True))
        self.btn_txt_append.clicked.connect(lambda: self._apply_text(replace=False))
        self.txt.returnPressed.connect(lambda: self._apply_text(replace=True))

        self._on_model_changed()

    # ---- API ----
    def payload(self) -> bytes:
        return self.model.bytes()

    def set_payload(self, data: bytes) -> None:
        self.model.set_bytes(data)

    # ---- wewnętrzne ----
    def _set_line_error(self, err: bool) -> None:
        self.line.setStyleSheet("QLineEdit { border: 1px solid #d33; }" if err else "")

    def _on_model_changed(self) -> None:
        n = self.model.length()
        self.lbl_size.setText(f"{n} B (0x{n:X})")
        if not self._line_updating:
            self.line.blockSignals(True)
            self.line.setText(hex_str(self.model.bytes()))
            self.line.blockSignals(False)
            self._set_line_error(False)
        self.changed.emit()

    def _on_line_edited(self, text: str) -> None:
        try:
            data = parse_hex(text)
        except ValueError:
            self._set_line_error(True)
            return
        self._set_line_error(False)
        self._line_updating = True
        try:
            self.model.set_bytes(data)
        finally:
            self._line_updating = False

    def _on_line_finished(self) -> None:
        if self.line.styleSheet():  # niepoprawny HEX – zostaw do poprawy
            return
        self.line.blockSignals(True)
        self.line.setText(hex_str(self.model.bytes()))
        self.line.blockSignals(False)

    def _apply_text(self, replace: bool) -> None:
        text = self.txt.text()
        codec = self.cmb_enc.currentData()
        term = self.cmb_term.currentData()
        try:
            data = text.encode(codec) + term
        except UnicodeEncodeError as exc:
            QMessageBox.warning(self, "Kodowanie", f"Nie można zakodować tekstu jako {codec}:\n{exc}")
            return
        if replace:
            self.model.set_bytes(data)
        else:
            self.model.insert_at(self.model.length(), data)

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Wczytaj plik binarny")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read(MAX_FILE_SIZE + 1)
        except OSError as exc:
            QMessageBox.warning(self, "Plik", str(exc))
            return
        if len(data) > MAX_FILE_SIZE:
            QMessageBox.warning(self, "Plik", f"Plik jest większy niż {MAX_FILE_SIZE // 1024} KiB – wczytano początek.")
            data = data[:MAX_FILE_SIZE]
        self.model.set_bytes(data)

    def _save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Zapisz payload")
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(self.model.bytes())
        except OSError as exc:
            QMessageBox.warning(self, "Plik", str(exc))


# --------------------------------------------------------------------------- #
#  Okno główne
# --------------------------------------------------------------------------- #
DEV_COLS = ["Nazwa", "Adres", "RSSI [dBm]", "TX power", "Usługi (UUID)", "Manufacturer data", "Ostatnio"]
UR = Qt.ItemDataRole.UserRole


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BT Manager")
        self.resize(1550, 920)
        self.mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

        self.worker = BleWorker()
        self._dev_items: dict[str, QTableWidgetItem] = {}
        self._dev_info: dict[str, dict] = {}
        self._pending: set[str] = set()
        self._details_cache = ""
        self._char_items: dict[int, QTreeWidgetItem] = {}
        self._values: dict[int, bytes] = {}
        self._subscribed: set[int] = set()
        self._cur_char: dict | None = None
        self._connected_addr: str | None = None
        self._connecting = False
        self._scanning = False
        self._sort_state: tuple[int, Qt.SortOrder] = (-1, Qt.SortOrder.AscendingOrder)

        self._build_ui()
        self._wire()
        self._refresh_ui()

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(250)
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.start()

        QTimer.singleShot(400, self.worker.start_scan)

    # ---- budowa UI ---------------------------------------------------------
    def _build_ui(self) -> None:
        root = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(root)

        # ===== LEWA STRONA: urządzenia + log =====
        left = QSplitter(Qt.Orientation.Vertical)

        dev_box = QGroupBox("Urządzenia BLE")
        dv = QVBoxLayout(dev_box)

        top = QHBoxLayout()
        self.btn_scan = QPushButton("Skanuj")
        self.edit_filter = QLineEdit()
        self.edit_filter.setPlaceholderText("Filtr: nazwa / adres / UUID")
        self.edit_filter.setClearButtonEnabled(True)
        self.chk_named = QCheckBox("Ukryj bez nazwy")
        self.btn_clear_list = QPushButton("Wyczyść listę")
        top.addWidget(self.btn_scan)
        top.addWidget(self.edit_filter, 1)
        top.addWidget(self.chk_named)
        top.addWidget(self.btn_clear_list)
        dv.addLayout(top)

        self.table = QTableWidget(0, len(DEV_COLS))
        self.table.setHorizontalHeaderLabels(DEV_COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionsClickable(True)
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, w in enumerate((170, 150, 80, 70, 200, 200, 70)):
            self.table.setColumnWidth(i, w)
        dv.addWidget(self.table, 1)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setFont(self.mono)
        self.details.setMaximumHeight(170)
        self.details.setPlaceholderText("Zaznacz urządzenie, aby zobaczyć szczegóły reklamy BLE")
        dv.addWidget(self.details)

        conn = QHBoxLayout()
        self.btn_connect = QPushButton("Połącz")
        self.btn_disconnect = QPushButton("Rozłącz")
        self.lbl_status = QLabel("Rozłączono")
        conn.addWidget(self.btn_connect)
        conn.addWidget(self.btn_disconnect)
        conn.addWidget(self.lbl_status, 1)
        dv.addLayout(conn)

        log_box = QGroupBox("Log")
        lv = QVBoxLayout(log_box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(self.mono)
        self.log_view.setMaximumBlockCount(5000)
        btn_clear_log = QPushButton("Wyczyść log")
        btn_clear_log.clicked.connect(self.log_view.clear)
        lv.addWidget(self.log_view, 1)
        lv.addWidget(btn_clear_log, 0, Qt.AlignmentFlag.AlignRight)

        left.addWidget(dev_box)
        left.addWidget(log_box)
        left.setSizes([640, 260])

        # ===== PRAWA STRONA: GATT + wysyłanie =====
        right = QSplitter(Qt.Orientation.Vertical)

        gatt_box = QGroupBox("Usługi i charakterystyki GATT")
        gv = QVBoxLayout(gatt_box)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Element", "UUID", "Handle", "Właściwości", "Wartość"])
        self.tree.setFont(self.mono)
        gv.addWidget(self.tree, 1)
        act = QHBoxLayout()
        self.btn_read = QPushButton("Odczytaj")
        self.btn_notify = QPushButton("Powiadomienia (notify/indicate)")
        self.btn_notify.setCheckable(True)
        self.btn_to_editor = QPushButton("Wartość → edytor")
        act.addWidget(self.btn_read)
        act.addWidget(self.btn_notify)
        act.addWidget(self.btn_to_editor)
        act.addStretch(1)
        gv.addLayout(act)

        send_box = QGroupBox("Wysyłanie danych – edytor HEX")
        sv = QVBoxLayout(send_box)
        self.lbl_target = QLabel("Cel: (wybierz charakterystykę w drzewie GATT)")
        sv.addWidget(self.lbl_target)
        self.hex = HexEditorWidget()
        sv.addWidget(self.hex, 1)

        opts = QHBoxLayout()
        self.chk_response = QCheckBox("Write with response")
        self.chk_response.setChecked(True)
        self.chk_chunk = QCheckBox("Dziel na pakiety po")
        self.spin_chunk = QSpinBox()
        self.spin_chunk.setRange(1, 512)
        self.spin_chunk.setValue(20)
        self.spin_chunk.setSuffix(" B")
        self.btn_send = QPushButton("Wyślij  (Ctrl+Enter)")
        self.btn_send.setShortcut("Ctrl+Return")
        self.btn_send.setStyleSheet("font-weight: bold;")
        opts.addWidget(self.chk_response)
        opts.addSpacing(12)
        opts.addWidget(self.chk_chunk)
        opts.addWidget(self.spin_chunk)
        opts.addStretch(1)
        opts.addWidget(self.btn_send)
        sv.addLayout(opts)

        right.addWidget(gatt_box)
        right.addWidget(send_box)
        right.setSizes([380, 520])

        root.addWidget(left)
        root.addWidget(right)
        root.setSizes([700, 850])

    def _wire(self) -> None:
        w = self.worker
        w.device_seen.connect(self._on_device_seen)
        w.scan_state.connect(self._on_scan_state)
        w.connected.connect(self._on_connected)
        w.disconnected.connect(self._on_disconnected)
        w.log.connect(self._log)
        w.error.connect(self._on_error)
        w.notification.connect(self._on_notification)
        w.read_done.connect(self._on_read)
        w.write_done.connect(self._on_write)
        w.notify_state.connect(self._on_notify_state)

        self.btn_scan.clicked.connect(self._toggle_scan)
        self.btn_clear_list.clicked.connect(self._clear_devices)
        self.edit_filter.textChanged.connect(self._apply_filter)
        self.chk_named.toggled.connect(self._apply_filter)
        self.table.itemSelectionChanged.connect(self._on_dev_selected)
        self.table.cellDoubleClicked.connect(lambda *_: self._connect_clicked())
        self.table.horizontalHeader().sectionClicked.connect(self._sort_by)
        self.btn_connect.clicked.connect(self._connect_clicked)
        self.btn_disconnect.clicked.connect(self._disconnect_clicked)

        self.tree.currentItemChanged.connect(self._on_tree_selected)
        self.btn_read.clicked.connect(self._read_clicked)
        self.btn_notify.clicked.connect(self._notify_clicked)
        self.btn_to_editor.clicked.connect(self._to_editor)
        self.btn_send.clicked.connect(self._send_clicked)

    # ---- log ---------------------------------------------------------------
    def _log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_view.appendPlainText(f"[{ts}] {msg}")

    def _on_error(self, msg: str) -> None:
        self._log(f"BŁĄD: {msg}")
        if self._connecting:
            self._connecting = False
            self.worker.start_scan()  # łączenie zatrzymało skanowanie – wznów je
            QMessageBox.warning(self, "Błąd połączenia", msg)
        self._refresh_ui()

    # ---- skanowanie / lista urządzeń ---------------------------------------
    def _toggle_scan(self) -> None:
        if self._scanning:
            self.worker.stop_scan()
        else:
            self.worker.start_scan()

    def _on_scan_state(self, on: bool) -> None:
        self._scanning = on
        self._refresh_ui()

    def _on_device_seen(self, info: dict) -> None:
        addr = info["address"]
        cur = self._dev_info.setdefault(
            addr,
            {"address": addr, "name": "", "rssi": None, "tx_power": None,
             "uuids": [], "manufacturer": {}, "service_data": {}, "seen": 0.0},
        )
        if info["name"]:
            cur["name"] = info["name"]
        cur["rssi"] = info["rssi"]
        if info["tx_power"] is not None:
            cur["tx_power"] = info["tx_power"]
        for u in info["uuids"]:
            if u not in cur["uuids"]:
                cur["uuids"].append(u)
        cur["manufacturer"].update(info["manufacturer"])
        cur["service_data"].update(info["service_data"])
        cur["seen"] = time.time()
        self._pending.add(addr)

    def _flush(self) -> None:
        if not self._pending:
            return
        pending, self._pending = self._pending, set()
        self.table.setUpdatesEnabled(False)
        try:
            for addr in pending:
                self._upsert_row(addr)
        finally:
            self.table.setUpdatesEnabled(True)
        sel = self._selected_addr()
        if sel in pending:
            self._show_details(sel)

    def _row_visible(self, info: dict) -> bool:
        if self.chk_named.isChecked() and not info["name"]:
            return False
        t = self.edit_filter.text().strip().lower()
        if not t:
            return True
        hay = " ".join([info["name"], info["address"], *info["uuids"]]).lower()
        return t in hay

    def _upsert_row(self, addr: str) -> None:
        info = self._dev_info[addr]
        item = self._dev_items.get(addr)
        if item is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for c in range(len(DEV_COLS)):
                self.table.setItem(row, c, QTableWidgetItem())
            item = self.table.item(row, 0)
            item.setData(UR, addr)
            self._dev_items[addr] = item
        row = self.table.row(item)

        uuids_txt = ", ".join(uuid_name(u) or u for u in info["uuids"])
        manuf_txt = "; ".join(f"0x{k:04X}: {hex_str(v)}" for k, v in info["manufacturer"].items())
        if len(manuf_txt) > 60:
            manuf_txt = manuf_txt[:60] + "…"
        cells = [
            info["name"] or "<brak nazwy>",
            addr,
            info["rssi"],
            info["tx_power"] if info["tx_power"] is not None else "",
            uuids_txt,
            manuf_txt,
            datetime.fromtimestamp(info["seen"]).strftime("%H:%M:%S"),
        ]
        for c, val in enumerate(cells):
            it = self.table.item(row, c)
            it.setData(Qt.ItemDataRole.DisplayRole, val)
        self.table.item(row, 4).setToolTip("\n".join(f"{u}  {uuid_name(u)}" for u in info["uuids"]))
        self.table.setRowHidden(row, not self._row_visible(info))

    def _apply_filter(self) -> None:
        for addr, item in self._dev_items.items():
            self.table.setRowHidden(self.table.row(item), not self._row_visible(self._dev_info[addr]))

    def _clear_devices(self) -> None:
        self.table.setRowCount(0)
        self._dev_items.clear()
        self._dev_info.clear()
        self._pending.clear()
        self.details.clear()
        self._details_cache = ""
        self._refresh_ui()

    def _sort_by(self, col: int) -> None:
        last_col, last_order = self._sort_state
        order = (
            Qt.SortOrder.DescendingOrder
            if col == last_col and last_order == Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )
        self._sort_state = (col, order)
        self.table.sortItems(col, order)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().setSortIndicator(col, order)

    def _selected_addr(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(UR)

    def _on_dev_selected(self) -> None:
        addr = self._selected_addr()
        if addr:
            self._show_details(addr)
        self._refresh_ui()

    def _show_details(self, addr: str | None) -> None:
        if not addr or addr not in self._dev_info:
            return
        i = self._dev_info[addr]
        lines = [
            f"Nazwa:      {i['name'] or '<brak>'}",
            f"Adres:      {addr}",
            f"RSSI:       {i['rssi']} dBm",
            f"TX power:   {i['tx_power'] if i['tx_power'] is not None else '-'}",
            "Reklamowane usługi:",
        ]
        lines += [f"  {u}  {uuid_name(u)}" for u in i["uuids"]] or ["  -"]
        lines.append("Manufacturer data:")
        lines += [f"  0x{k:04X}: {hex_str(v)}" for k, v in i["manufacturer"].items()] or ["  -"]
        lines.append("Service data:")
        lines += [f"  {k}: {hex_str(v)}" for k, v in i["service_data"].items()] or ["  -"]
        text = "\n".join(lines)
        if text != self._details_cache:
            self._details_cache = text
            self.details.setPlainText(text)

    # ---- połączenie --------------------------------------------------------
    def _connect_clicked(self) -> None:
        addr = self._selected_addr()
        if not addr or self._connected_addr or self._connecting:
            return
        self._connecting = True
        self._log(f"Łączenie z {addr} …")
        self._refresh_ui()
        self.worker.connect_device(addr)

    def _disconnect_clicked(self) -> None:
        self.worker.disconnect_device()

    def _on_connected(self, addr: str, services: list, mtu: int) -> None:
        self._connecting = False
        self._connected_addr = addr
        self._log(f"Połączono z {addr} (MTU {mtu})")
        self.spin_chunk.setValue(max(1, min(512, mtu - 3)))
        self._populate_tree(services)
        self._refresh_ui()

    def _on_disconnected(self) -> None:
        self._connecting = False
        self._connected_addr = None
        self._subscribed.clear()
        self._values.clear()
        self._cur_char = None
        self.tree.clear()
        self._char_items.clear()
        self.worker.start_scan()  # po rozłączeniu wznów skanowanie
        self._refresh_ui()

    # ---- drzewo GATT -------------------------------------------------------
    @staticmethod
    def _nice(desc: str | None) -> str:
        return desc if desc and desc.lower() != "unknown" else "(nieznana / własna)"

    def _populate_tree(self, services: list[dict]) -> None:
        self.tree.clear()
        self._char_items.clear()
        bold = self.tree.font()
        bold.setBold(True)
        for s in services:
            si = QTreeWidgetItem([f"Usługa: {self._nice(s['description'])}", s["uuid"], f"0x{s['handle']:04X}", "", ""])
            si.setFont(0, bold)
            self.tree.addTopLevelItem(si)
            for c in s["characteristics"]:
                ci = QTreeWidgetItem(
                    [f"Charakterystyka: {self._nice(c['description'])}", c["uuid"],
                     f"0x{c['handle']:04X}", ", ".join(c["properties"]), ""]
                )
                ci.setData(0, UR, {"handle": c["handle"], "props": c["properties"],
                                   "uuid": c["uuid"], "name": self._nice(c["description"])})
                si.addChild(ci)
                self._char_items[c["handle"]] = ci
                for d in c["descriptors"]:
                    di = QTreeWidgetItem(
                        [f"Deskryptor: {self._nice(d['description'])}", d["uuid"], f"0x{d['handle']:04X}", "", ""]
                    )
                    ci.addChild(di)
        self.tree.expandAll()
        for col in range(4):
            self.tree.resizeColumnToContents(col)

    def _on_tree_selected(self, current, _previous) -> None:
        data = current.data(0, UR) if current else None
        self._cur_char = data if isinstance(data, dict) else None
        self._refresh_ui()

    @staticmethod
    def _short_value(data: bytes) -> str:
        shown = hex_str(data[:16]) + (" …" if len(data) > 16 else "")
        return f"{shown}  | {ascii_str(data[:16])}"

    def _store_value(self, handle: int, data: bytes) -> None:
        self._values[handle] = data
        item = self._char_items.get(handle)
        if item:
            item.setText(4, self._short_value(data))
        if self._cur_char and self._cur_char["handle"] == handle:
            self.btn_to_editor.setEnabled(True)

    # ---- operacje GATT -----------------------------------------------------
    def _read_clicked(self) -> None:
        if self._cur_char:
            self.worker.read(self._cur_char["handle"])

    def _on_read(self, handle: int, data: bytes) -> None:
        self._store_value(handle, data)
        self._log(f"← READ   [0x{handle:04X}] {len(data)} B: {hex_str(data)}  | {ascii_str(data)}")

    def _notify_clicked(self, checked: bool) -> None:
        if self._cur_char:
            self.worker.set_notify(self._cur_char["handle"], checked)

    def _on_notify_state(self, handle: int, on: bool) -> None:
        if on:
            self._subscribed.add(handle)
        else:
            self._subscribed.discard(handle)
        self._log(f"Powiadomienia [0x{handle:04X}]: {'włączone' if on else 'wyłączone'}")
        self._refresh_ui()

    def _on_notification(self, handle: int, data: bytes) -> None:
        self._store_value(handle, data)
        self._log(f"← NOTIFY [0x{handle:04X}] {len(data)} B: {hex_str(data)}  | {ascii_str(data)}")

    def _to_editor(self) -> None:
        if self._cur_char and self._cur_char["handle"] in self._values:
            self.hex.set_payload(self._values[self._cur_char["handle"]])

    def _send_clicked(self) -> None:
        if not self._cur_char:
            return
        data = self.hex.payload()
        if not data:
            QMessageBox.information(self, "Wysyłanie", "Payload jest pusty – wpisz bajty w edytorze HEX.")
            return
        chunk = self.spin_chunk.value() if self.chk_chunk.isChecked() else 0
        self.worker.write(self._cur_char["handle"], data, self.chk_response.isChecked(), chunk)

    def _on_write(self, handle: int, n: int, parts: int) -> None:
        data = self.hex.payload()
        extra = f" ({parts} pakiet(y))" if parts > 1 else ""
        self._log(f"→ WRITE  [0x{handle:04X}] {n} B{extra}: {hex_str(data[:64])}{' …' if len(data) > 64 else ''}")

    # ---- stan UI -----------------------------------------------------------
    def _refresh_ui(self) -> None:
        connected = self._connected_addr is not None
        has_dev = self._selected_addr() is not None

        self.btn_scan.setText("Zatrzymaj skanowanie" if self._scanning else "Skanuj")
        self.btn_connect.setEnabled(has_dev and not connected and not self._connecting)
        self.btn_disconnect.setEnabled(connected or self._connecting)
        if self._connecting:
            self.lbl_status.setText("Łączenie…")
        elif connected:
            name = self._dev_info.get(self._connected_addr, {}).get("name") or ""
            self.lbl_status.setText(f"Połączono: {name} [{self._connected_addr}]")
        else:
            self.lbl_status.setText("Rozłączono")

        ch = self._cur_char if connected else None
        props = set(ch["props"]) if ch else set()
        handle = ch["handle"] if ch else None
        can_write = bool({"write", "write-without-response"} & props)

        self.btn_read.setEnabled("read" in props)
        can_notify = bool({"notify", "indicate"} & props)
        self.btn_notify.setEnabled(can_notify)
        self.btn_notify.blockSignals(True)
        self.btn_notify.setChecked(handle in self._subscribed)
        self.btn_notify.blockSignals(False)
        self.btn_to_editor.setEnabled(handle in self._values)
        self.btn_send.setEnabled(can_write)

        both = "write" in props and "write-without-response" in props
        self.chk_response.setEnabled(both)
        if can_write and not both:
            self.chk_response.setChecked("write" in props)

        if ch:
            self.lbl_target.setText(
                f"Cel: {ch['name']}  |  UUID {ch['uuid']}  |  handle 0x{ch['handle']:04X}  |  {', '.join(ch['props'])}"
            )
        elif connected:
            self.lbl_target.setText("Cel: wybierz charakterystykę w drzewie GATT")
        else:
            self.lbl_target.setText("Cel: (brak połączenia)")

    # ---- zamknięcie --------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self._flush_timer.stop()
        self.worker.shutdown()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()