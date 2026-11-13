"""Ścieżki i konfiguracja współdzielone przez wersję GUI i CLI (bez Qt)."""

from __future__ import annotations

import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DEVICES_FILE = APP_DIR / "config" / "devices.json"
MODELS_DIR = APP_DIR.parent.parent / "assets" / "models"


def load_devices() -> list[dict]:
    with open(DEVICES_FILE, encoding="utf-8") as f:
        return json.load(f)


def char_uuid(device: dict, kind: str) -> str | None:
    for ch in device.get("chars", []):
        if ch.get("type") == kind:
            return ch.get("uuid")
    return None


def find_models() -> list[Path]:
    return sorted(MODELS_DIR.rglob("*.task")) if MODELS_DIR.exists() else []
