"""Wątek kamery: przechwytywanie obrazu, rozpoznawanie gestów (MediaPipe) i listowanie kamer."""

from __future__ import annotations

import glob
import os
import pathlib
import platform
import time
from pathlib import Path
from typing import List, Sequence, Tuple

os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")  # ukryj ostrzeżenia przy próbkowaniu nieistniejących kamer

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

MAX_CAMERAS = 10

# Topologia 21 punktów dłoni MediaPipe.
HAND_CONNECTIONS: List[Tuple[int, int]] = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
]


def open_camera(source) -> cv2.VideoCapture:
    if platform.system() == "Windows" and isinstance(source, int):
        capture = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(source)
        return capture
    return cv2.VideoCapture(source)


def _linux_camera_name(dev: str) -> str:
    try:
        name = pathlib.Path(dev).name
        return pathlib.Path(f"/sys/class/video4linux/{name}/name").read_text().strip()
    except Exception:  # noqa: BLE001
        return ""


def probe_cameras(max_cameras: int = MAX_CAMERAS) -> list[tuple[object, str]]:
    """Zwraca listę (źródło, etykieta) dostępnych kamer."""
    found: list[tuple[object, str]] = []
    if platform.system() == "Windows":
        for i in range(max_cameras):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                found.append((i, f"Kamera {i}"))
            cap.release()
    else:
        for dev in sorted(glob.glob("/dev/video*")):
            cap = cv2.VideoCapture(dev)
            if cap.isOpened():
                name = _linux_camera_name(dev)
                found.append((dev, f"{dev} ({name})" if name else dev))
            cap.release()
    return found


class CameraScanner(QThread):
    done = Signal(object)  # list[(źródło, etykieta)]

    def run(self) -> None:
        self.done.emit(probe_cameras())


def draw_landmarks(frame_bgr, hand_landmarks: Sequence) -> None:
    height, width = frame_bgr.shape[:2]
    points = [(int(lm.x * width), int(lm.y * height)) for lm in hand_landmarks]
    for p in points:
        cv2.circle(frame_bgr, p, 3, (60, 220, 60), -1)
    for a, b in HAND_CONNECTIONS:
        if a < len(points) and b < len(points):
            cv2.line(frame_bgr, points[a], points[b], (255, 210, 80), 2)


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
            options = vision.GestureRecognizerOptions(
                base_options=python.BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=vision.RunningMode.IMAGE,
                num_hands=self.max_hands,
            )
            recognizer = vision.GestureRecognizer.create_from_options(options)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Nie można załadować modelu: {exc}")
            return

        cap = open_camera(self.source)
        if not cap.isOpened():
            cap.release()
            recognizer.close()
            self.failed.emit(f"Nie można otworzyć kamery: {self.label}")
            return

        try:
            backend = cap.getBackendName()
        except Exception:  # noqa: BLE001
            backend = "?"
        reported_fps = cap.get(cv2.CAP_PROP_FPS)

        fps = 0.0
        prev = time.perf_counter()
        try:
            while not self.isInterruptionRequested():
                ok, frame_bgr = cap.read()
                if not ok:
                    self.failed.emit("Brak obrazu z kamery.")
                    break

                rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                t0 = time.perf_counter()
                result = recognizer.recognize(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                inference_ms = (time.perf_counter() - t0) * 1000.0

                hands = len(result.hand_landmarks or [])
                for lms in result.hand_landmarks or []:
                    draw_landmarks(frame_bgr, lms)

                # Najpewniejszy gest spośród wszystkich wykrytych dłoni.
                best = None
                best_hand = None
                for i, cats in enumerate(result.gestures or []):
                    if cats and (best is None or cats[0].score > best.score):
                        best, best_hand = cats[0], i
                handedness = ""
                if best_hand is not None and result.handedness and best_hand < len(result.handedness):
                    h = result.handedness[best_hand]
                    handedness = h[0].category_name if h else ""

                now = time.perf_counter()
                inst = 1.0 / max(now - prev, 1e-6)
                prev = now
                fps = inst if fps == 0.0 else 0.9 * fps + 0.1 * inst

                gesture = None
                if best is not None and best.category_name != "None" and best.score >= self.min_score:
                    gesture = best.category_name

                h, w = frame_bgr.shape[:2]
                self.stats.emit(
                    {
                        "width": w,
                        "height": h,
                        "channels": frame_bgr.shape[2] if frame_bgr.ndim == 3 else 1,
                        "fps": fps,
                        "reported_fps": reported_fps,
                        "backend": backend,
                        "inference_ms": inference_ms,
                        "hands": hands,
                        "gesture": gesture,
                        "raw_gesture": best.category_name if best else None,
                        "score": best.score if best else 0.0,
                        "handedness": handedness,
                    }
                )

                out_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                image = QImage(out_rgb.data, w, h, out_rgb.strides[0], QImage.Format.Format_RGB888)
                self.frame_ready.emit(image.copy())
        finally:
            cap.release()
            recognizer.close()
