"""Wersja konsolowa (CLI) Norn Queen – bez GUI, działa także przez SSH.

Od razu łączy się z urządzeniami BLE z config/devices.json i z kamerą, a następnie steruje
urządzeniami na podstawie gestów. Błędy są zgłaszane na stderr, a kod wyjścia jest niezerowy.
Zatrzymanie: Ctrl+C (wysyła STOP i rozłącza urządzenia).
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

from ble_core import STATE_ERROR, BleCore
from camera_core import CameraError, GestureCamera, probe_cameras
from common import DEVICES_FILE, MODELS_DIR, char_uuid, find_models, load_devices
from gestures import CMD_STOP, COMMAND_NAMES, CommandTracker, build_frame

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_DEVICES = 2
EXIT_LOST_DEVICES = 3


class CliError(Exception):
    """Błąd krytyczny CLI: komunikat trafia na stderr, a proces kończy się kodem EXIT_ERROR."""


def info(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def error(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] BŁĄD: {msg}", file=sys.stderr, flush=True)


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("opcje CLI (z --cmd / --cli)")
    group.add_argument("--camera", help="indeks (np. 0) lub ścieżka (np. /dev/video0) kamery; domyślnie pierwsza znaleziona")
    group.add_argument("--model", help="ścieżka do modelu .task lub nazwa względem assets/models; domyślnie pierwszy znaleziony")
    group.add_argument("--hands", type=int, default=2, help="maksymalna liczba dłoni (domyślnie 2)")
    group.add_argument("--min-score", type=float, default=0.4, help="minimalna pewność gestu 0-1 (domyślnie 0.4)")
    group.add_argument("--speed", type=int, default=200, help="prędkość 0-255 wysyłana w ramce (domyślnie 200)")
    group.add_argument("--no-stop-on-lost", dest="stop_lost", action="store_false",
                       help="nie wysyłaj STOP, gdy nie widać dłoni")


def resolve_model(arg: str | None) -> Path:
    if arg:
        for candidate in (Path(arg), MODELS_DIR / arg):
            if candidate.is_file():
                return candidate
        raise CliError(f"Nie znaleziono modelu: {arg}")
    models = find_models()
    if not models:
        raise CliError(f"Brak modeli .task w {MODELS_DIR}")
    return models[0]


def resolve_camera(arg: str | None) -> tuple[object, str]:
    if arg is not None:
        source = int(arg) if arg.isdigit() else arg
        return source, f"Kamera {arg}"
    info("Szukanie kamer…")
    cameras = probe_cameras()
    if not cameras:
        raise CliError("Nie znaleziono kamer")
    return cameras[0]


def run(args: argparse.Namespace) -> int:
    try:
        return _run(args)
    except CliError as exc:
        error(str(exc))
        return EXIT_ERROR


def _run(args: argparse.Namespace) -> int:
    if not 0 <= args.speed <= 255:
        raise CliError("--speed musi być w zakresie 0-255")

    try:
        devices = load_devices()
    except Exception as exc:  # noqa: BLE001
        raise CliError(f"Nie można wczytać {DEVICES_FILE}: {exc}") from exc
    if not devices:
        raise CliError(f"Brak urządzeń w {DEVICES_FILE}")

    model = resolve_model(args.model)
    source, label = resolve_camera(args.camera)

    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    if hasattr(signal, "SIGHUP"):  # zamknięcie sesji SSH
        signal.signal(signal.SIGHUP, lambda *_: stop_event.set())

    errors: dict[str, str] = {}

    def on_state(addr: str, state: str, detail: str) -> None:
        if state == STATE_ERROR:
            errors[addr] = detail

    def on_log(msg: str) -> None:
        if "błąd połączenia" not in msg:  # ten błąd raportujemy niżej w podsumowaniu połączeń
            info(msg)

    ble = BleCore(on_state=on_state, on_log=on_log)
    camera: GestureCamera | None = None
    last_sent: tuple[int, int] | None = None
    code = EXIT_OK
    try:
        # Łączenie BLE trwa w tle, a w międzyczasie ładujemy model i otwieramy kamerę.
        pending = {}
        for dev in devices:
            addr = dev["address"]
            write_uuid = char_uuid(dev, "write")
            if not write_uuid:
                error(f"{dev.get('name', addr)} ({addr}): brak charakterystyki typu 'write' w konfiguracji")
                continue
            info(f"Łączenie z {dev.get('name', addr)} ({addr})…")
            pending[addr] = (dev, ble.connect_device(addr, write_uuid, char_uuid(dev, "read")))

        info(f"Uruchamianie kamery: {label}, model: {model.name}")
        camera_error = None
        try:
            camera = GestureCamera(source, label, model, args.hands, args.min_score, draw=False)
        except CameraError as exc:
            camera_error = str(exc)

        connected = 0
        for addr, (dev, fut) in pending.items():
            try:
                ok = fut.result()
            except Exception as exc:  # noqa: BLE001
                ok = False
                error(f"{addr}: {exc}")
            name = dev.get("name", addr)
            if ok:
                connected += 1
                info(f"Połączono: {name} ({addr})")
            else:
                reason = f": {errors[addr]}" if addr in errors else ""
                error(f"Nie udało się połączyć z {name} ({addr}){reason}")

        if camera_error:
            error(camera_error)
            return EXIT_ERROR
        if connected == 0:
            error("Nie połączono z żadnym urządzeniem Bluetooth")
            return EXIT_NO_DEVICES

        info(f"Gotowe: urządzenia {connected}/{len(devices)}, kamera {label}. Ctrl+C kończy pracę.")

        tracker = CommandTracker()
        known_connected = connected
        while not stop_event.is_set():
            camera.min_score = args.min_score
            try:
                _frame, stats = camera.read()
            except CameraError as exc:
                error(str(exc))
                code = EXIT_ERROR
                break

            now_connected = ble.connected_count()
            if now_connected == 0:
                error("Utracono połączenie ze wszystkimi urządzeniami")
                code = EXIT_LOST_DEVICES
                break
            if now_connected > known_connected:
                last_sent = None  # nowo połączone urządzenie dostanie aktualne polecenie
            known_connected = now_connected

            cmd = tracker.update(stats["gesture"], stats["hands"], args.stop_lost)
            if cmd is not None and last_sent != (cmd, args.speed):
                last_sent = (cmd, args.speed)
                frame = build_frame(cmd, args.speed)
                ble.send(frame)
                info(
                    f"Gest: {stats['raw_gesture']} → {COMMAND_NAMES[cmd]}, "
                    f"ramka {' '.join(f'{b:02X}' for b in frame)}"
                )
    finally:
        if camera is not None:
            camera.close()
        if last_sent is not None and last_sent[0] != CMD_STOP and ble.connected_count() > 0:
            ble.send(build_frame(CMD_STOP, args.speed))
            time.sleep(0.3)  # pozwól wysłać STOP zanim rozłączymy urządzenia
        ble.shutdown()
        info("Zakończono")
    return code
