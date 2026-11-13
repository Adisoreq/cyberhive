"""Mapowanie gestów MediaPipe na ramki wysyłane do Termagant A (zob. apps/C1_Termagant_A/include/Commands.h)."""

from __future__ import annotations

CMD_STOP = 0
CMD_FWD = 1
CMD_BWD = 2
CMD_LEFT = 3
CMD_RIGHT = 4
CMD_AUTO = 5

COMMAND_NAMES = {
    CMD_STOP: "STOP",
    CMD_FWD: "PRZÓD",
    CMD_BWD: "TYŁ",
    CMD_LEFT: "LEWO",
    CMD_RIGHT: "PRAWO",
    CMD_AUTO: "AUTO",
}

GESTURE_COMMANDS = {
    "Closed_Fist": CMD_STOP,
    "Open_Palm": CMD_STOP,
    "Pointing_Up": CMD_FWD,
    "Thumb_Down": CMD_BWD,
    "Victory": CMD_LEFT,
    "ILoveYou": CMD_RIGHT,
    "Thumb_Up": CMD_AUTO,
}


def build_frame(command: int, speed: int) -> bytes:
    """Ramka: [0] = komenda (tryb), [1] = prędkość 0-255."""
    return bytes([command & 0xFF, max(0, min(255, speed))])
