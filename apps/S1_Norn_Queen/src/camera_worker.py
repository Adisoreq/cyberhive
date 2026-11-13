"""Wątki Qt dla GUI: przechwytywanie obrazu z rozpoznawaniem gestów i listowanie kamer."""

from __future__ import annotations

from pathlib import Path

import cv2
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from camera_core import CameraError, GestureCamera, probe_cameras


class CameraScanner(QThread):
    done = Signal(object)  # list[(źródło, etykieta)]

    def run(self) -> None:
        self.done.emit(probe_cameras())


class CameraWorker(QThread):
    frame_ready = Signal(QImage)
    stats = Signal(dict)
    failed = Signal(str)

    def __init__(self, source, label: str, model_path: Path, max_hands: int, min_score: float) -> None:
        super().__init__()
        self.source = source
        self.label = label
        self.model_path = Path(model_path)
        self.max_hands = max_hands
        self.min_score = min_score  # można zmieniać w trakcie pracy

    def run(self) -> None:
        try:
            camera = GestureCamera(self.source, self.label, self.model_path, self.max_hands, self.min_score)
        except CameraError as exc:
            self.failed.emit(str(exc))
            return

        try:
            while not self.isInterruptionRequested():
                camera.min_score = self.min_score
                try:
                    frame_bgr, stats = camera.read()
                except CameraError as exc:
                    self.failed.emit(str(exc))
                    break

                self.stats.emit(stats)
                out_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                image = QImage(
                    out_rgb.data, stats["width"], stats["height"], out_rgb.strides[0], QImage.Format.Format_RGB888
                )
                self.frame_ready.emit(image.copy())
        finally:
            camera.close()
