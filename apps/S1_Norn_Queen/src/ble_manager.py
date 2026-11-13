"""Adapter Qt dla BleCore: callbacki z wątku asyncio zamieniane na sygnały."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ble_core import (  # noqa: F401  (reeksport stałych stanu)
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_DISCONNECTED,
    STATE_DISCONNECTING,
    STATE_ERROR,
    BleCore,
)


class BleManager(QObject):
    state_changed = Signal(str, str, str)  # adres, stan, szczegóły
    status_received = Signal(str, object)  # adres, bytes (powiadomienie ze statusem)
    log = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._core = BleCore(
            on_state=self.state_changed.emit,
            on_status=self.status_received.emit,
            on_log=self.log.emit,
        )

    def connect_device(self, address: str, write_uuid: str, status_uuid: str | None) -> None:
        self._core.connect_device(address, write_uuid, status_uuid)

    def disconnect_device(self, address: str) -> None:
        self._core.disconnect_device(address)

    def send(self, data: bytes) -> None:
        self._core.send(data)

    def shutdown(self) -> None:
        self._core.shutdown()
