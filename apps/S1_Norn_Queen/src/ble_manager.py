"""Zarządzanie wieloma połączeniami BLE (Bleak) we własnej pętli asyncio w osobnym wątku."""

from __future__ import annotations

import asyncio
import threading

from PySide6.QtCore import QObject, Signal

from bleak import BleakClient

STATE_DISCONNECTED = "disconnected"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"
STATE_DISCONNECTING = "disconnecting"
STATE_ERROR = "error"


class BleManager(QObject):
    state_changed = Signal(str, str, str)  # adres, stan, szczegóły
    status_received = Signal(str, object)  # adres, bytes (powiadomienie ze statusem)
    log = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="ble-loop", daemon=True)
        self._thread.start()
        self._clients: dict[str, BleakClient] = {}
        self._write_uuid: dict[str, str] = {}
        self._pending: dict[str, bytes] = {}
        self._sending: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro) -> None:
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ---- API wywoływane z wątku GUI ---------------------------------------
    def connect_device(self, address: str, write_uuid: str, status_uuid: str | None) -> None:
        self._submit(self._connect(address, write_uuid, status_uuid))

    def disconnect_device(self, address: str) -> None:
        self._submit(self._disconnect(address))

    def send(self, data: bytes) -> None:
        """Wysyła ramkę do wszystkich połączonych urządzeń (zawsze najnowsza ramka wygrywa)."""
        self._loop.call_soon_threadsafe(self._enqueue, data)

    def shutdown(self) -> None:
        fut = asyncio.run_coroutine_threadsafe(self._cleanup(), self._loop)
        try:
            fut.result(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    # ---- korutyny (wątek asyncio) -----------------------------------------
    async def _cleanup(self) -> None:
        for address in list(self._clients):
            await self._disconnect(address)

    async def _connect(self, address: str, write_uuid: str, status_uuid: str | None) -> None:
        if address in self._clients:
            return
        self.state_changed.emit(address, STATE_CONNECTING, "")
        client = BleakClient(
            address,
            disconnected_callback=lambda c, a=address: self._on_disconnected(a, c),
            timeout=15.0,
            winrt={"use_cached_services": False},
        )
        try:
            await client.connect()
            if client.services.get_characteristic(write_uuid) is None:
                raise RuntimeError(f"Brak charakterystyki zapisu {write_uuid}")
        except Exception as exc:  # noqa: BLE001
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.state_changed.emit(address, STATE_ERROR, str(exc))
            self.log.emit(f"{address}: błąd połączenia: {exc}")
            return

        self._clients[address] = client
        self._write_uuid[address] = write_uuid

        if status_uuid and client.services.get_characteristic(status_uuid) is not None:
            try:
                await client.start_notify(
                    status_uuid, lambda _s, data, a=address: self.status_received.emit(a, bytes(data))
                )
            except Exception as exc:  # noqa: BLE001
                self.log.emit(f"{address}: brak powiadomień statusu: {exc}")

        self.state_changed.emit(address, STATE_CONNECTED, "")
        self.log.emit(f"{address}: połączono")

    async def _disconnect(self, address: str) -> None:
        client = self._clients.pop(address, None)
        self._write_uuid.pop(address, None)
        self._pending.pop(address, None)
        if client is None:
            return
        self.state_changed.emit(address, STATE_DISCONNECTING, "")
        try:
            await client.disconnect()
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"{address}: błąd rozłączania: {exc}")
        self.state_changed.emit(address, STATE_DISCONNECTED, "")
        self.log.emit(f"{address}: rozłączono")

    def _on_disconnected(self, address: str, client: BleakClient) -> None:
        # Rozłączenie zainicjowane przez nas usuwa klienta wcześniej – tu obsługujemy utratę łączności.
        if self._clients.get(address) is client:
            self._clients.pop(address, None)
            self._write_uuid.pop(address, None)
            self._pending.pop(address, None)
            self.state_changed.emit(address, STATE_DISCONNECTED, "Utracono połączenie")
            self.log.emit(f"{address}: utracono połączenie")

    def _enqueue(self, data: bytes) -> None:
        for address in list(self._clients):
            self._pending[address] = data
            if address not in self._sending:
                self._sending.add(address)
                task = self._loop.create_task(self._drain(address))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _drain(self, address: str) -> None:
        try:
            while address in self._pending:
                data = self._pending.pop(address)
                client = self._clients.get(address)
                uuid = self._write_uuid.get(address)
                if client is None or uuid is None:
                    break
                try:
                    await client.write_gatt_char(uuid, data, response=False)
                except Exception as exc:  # noqa: BLE001
                    self.log.emit(f"{address}: błąd zapisu: {exc}")
        finally:
            self._sending.discard(address)
