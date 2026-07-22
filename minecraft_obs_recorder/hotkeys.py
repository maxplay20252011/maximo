"""Hotkeys globales usando pynput (mantenida activamente; `keyboard` no tiene
releases desde 2020 y se considera abandonada)."""
from __future__ import annotations

import logging
from typing import Callable

from pynput import keyboard

logger = logging.getLogger("minecraft_recorder")


def _to_pynput_format(hotkey: str) -> str:
    """Convierte 'f9' -> '<f9>'. Soporta teclas simples de función (F1-F24)."""
    hotkey = hotkey.strip().lower()
    if hotkey.startswith("<") and hotkey.endswith(">"):
        return hotkey
    return f"<{hotkey}>"


class HotkeyManager:
    def __init__(self, start_key: str, stop_key: str, pause_resume_key: str,
                 on_start: Callable[[], None], on_stop: Callable[[], None],
                 on_pause_resume: Callable[[], None]):
        self._mapping = {
            _to_pynput_format(start_key): on_start,
            _to_pynput_format(stop_key): on_stop,
            _to_pynput_format(pause_resume_key): on_pause_resume,
        }
        self._listener: keyboard.GlobalHotKeys | None = None

    def start(self) -> None:
        try:
            self._listener = keyboard.GlobalHotKeys(self._mapping)
            self._listener.start()
            logger.info("Hotkeys registradas: %s", list(self._mapping.keys()))
        except Exception:
            logger.exception(
                "No se pudieron registrar las hotkeys globales (posible conflicto "
                "con otra aplicación o permisos insuficientes en Windows)."
            )

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
