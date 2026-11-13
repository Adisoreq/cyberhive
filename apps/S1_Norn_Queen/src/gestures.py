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
    # Piesc
    "Closed_Fist": CMD_STOP,

    # Otwarta dłoń / piatka
    "Open_Palm": CMD_AUTO,

    # Kciuk w górę / w dół
    "Thumb_Up": CMD_FWD,
    "Thumb_Down": CMD_BWD,

    # Wskazujący w górę
    "Pointing_Up": CMD_LEFT,

    # 2 wskazujące
    "Victory": CMD_RIGHT,
}


STABLE_FRAMES = 4  # tyle kolejnych klatek z tym samym poleceniem zanim zostanie wysłane


def build_frame(command: int, speed: int) -> bytes:
    """Ramka: [0] = komenda (tryb), [1] = prędkość 0-255."""
    return bytes([command & 0xFF, max(0, min(255, speed))])


class CommandTracker:
    """Zamienia strumień gestów na polecenie aktywne dopiero po STABLE_FRAMES identycznych klatkach."""

    def __init__(self, stable_frames: int = STABLE_FRAMES) -> None:
        self.stable_frames = stable_frames
        self.reset()

    def reset(self) -> None:
        self._candidate: int | None = None
        self._count = 0
        self.active: int | None = None

    def update(self, gesture: str | None, hands: int, stop_when_lost: bool = True) -> int | None:
        cmd = GESTURE_COMMANDS.get(gesture) if gesture else None
        if cmd is None and hands == 0 and stop_when_lost:
            cmd = CMD_STOP

        if cmd is not None:
            if cmd == self._candidate:
                self._count += 1
            else:
                self._candidate, self._count = cmd, 1
            if self._count >= self.stable_frames:
                self.active = cmd
        else:
            self._candidate, self._count = None, 0
        return self.active
