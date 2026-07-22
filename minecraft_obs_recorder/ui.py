"""Ventana de estado con tkinter, con opción de minimizar a la bandeja del sistema
(pystray). Es la única pieza que corre en el hilo principal (mainloop de tkinter)."""
from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from PIL import Image, ImageDraw

import pystray

from recorder import Recorder, RecordingState
from utils import format_duration

logger = logging.getLogger("minecraft_recorder")

_COLOR_POR_ESTADO = {
    RecordingState.DESCONECTADO: "#9e9e9e",
    RecordingState.DETENIDO: "#424242",
    RecordingState.GRABANDO: "#d32f2f",
    RecordingState.PAUSADO: "#f9a825",
}


def _build_tray_image(color: str = "#d32f2f") -> Image.Image:
    """Genera un ícono simple (círculo de color) sin depender de un archivo externo."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


class StatusUI:
    def __init__(self, recorder: Recorder, on_start: Callable[[], None],
                 on_stop: Callable[[], None], on_pause_resume: Callable[[], None],
                 on_reconnect: Callable[[], None], on_exit: Callable[[], None]):
        self.recorder = recorder
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_pause_resume = on_pause_resume
        self.on_reconnect = on_reconnect
        self.on_exit = on_exit

        self._tray_icon: pystray.Icon | None = None
        self._tray_thread: threading.Thread | None = None

        self.root = tk.Tk()
        self.root.title("Grabador Minecraft - OBS")
        self.root.geometry("360x260")
        self.root.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)

        self._build_widgets()
        self._schedule_update()

    def _build_widgets(self) -> None:
        pad = {"padx": 10, "pady": 6}

        self.lbl_estado = ttk.Label(self.root, text="Estado: -", font=("Segoe UI", 13, "bold"))
        self.lbl_estado.pack(anchor="w", **pad)

        self.lbl_tiempo = ttk.Label(self.root, text="Tiempo grabado: 00h00m00s")
        self.lbl_tiempo.pack(anchor="w", **pad)

        self.lbl_disco = ttk.Label(self.root, text="Espacio libre: - GB")
        self.lbl_disco.pack(anchor="w", **pad)

        self.lbl_ultimo = ttk.Label(self.root, text="Último archivo: -", wraplength=330)
        self.lbl_ultimo.pack(anchor="w", **pad)

        botones = ttk.Frame(self.root)
        botones.pack(fill="x", **pad)

        ttk.Button(botones, text="Iniciar (F9)", command=self.on_start).grid(row=0, column=0, padx=4, pady=4)
        ttk.Button(botones, text="Detener (F10)", command=self.on_stop).grid(row=0, column=1, padx=4, pady=4)
        ttk.Button(botones, text="Pausar/Reanudar (F11)", command=self.on_pause_resume).grid(
            row=1, column=0, columnspan=2, padx=4, pady=4
        )
        ttk.Button(botones, text="Reconectar OBS", command=self.on_reconnect).grid(
            row=2, column=0, columnspan=2, padx=4, pady=4
        )

        ttk.Button(self.root, text="Minimizar a bandeja", command=self._minimize_to_tray).pack(
            anchor="e", padx=10, pady=(0, 10)
        )

    def _schedule_update(self) -> None:
        self._refresh()
        self.root.after(1000, self._schedule_update)

    def _refresh(self) -> None:
        status = self.recorder.get_status()
        color = _COLOR_POR_ESTADO.get(status.state, "#000000")
        self.lbl_estado.configure(text=f"Estado: {status.state.value}", foreground=color)
        self.lbl_tiempo.configure(text=f"Tiempo grabado: {format_duration(status.elapsed_seconds)}")
        self.lbl_disco.configure(text=f"Espacio libre: {status.free_space_gb:.1f} GB")
        self.lbl_ultimo.configure(text=f"Último archivo: {status.last_file or '-'}")

        if self._tray_icon is not None:
            self._tray_icon.icon = _build_tray_image(color)

    # ---------- Bandeja del sistema ----------

    def _minimize_to_tray(self) -> None:
        self.root.withdraw()
        if self._tray_icon is None:
            menu = pystray.Menu(
                pystray.MenuItem("Mostrar", self._restore_from_tray, default=True),
                pystray.MenuItem("Salir", self._exit_from_tray),
            )
            self._tray_icon = pystray.Icon(
                "minecraft_recorder", _build_tray_image(), "Grabador Minecraft - OBS", menu
            )
            self._tray_thread = threading.Thread(target=self._tray_icon.run, daemon=True)
            self._tray_thread.start()

    def _restore_from_tray(self, icon=None, item=None) -> None:
        self.root.after(0, self.root.deiconify)

    def _exit_from_tray(self, icon=None, item=None) -> None:
        if self._tray_icon is not None:
            self._tray_icon.stop()
            self._tray_icon = None
        self.root.after(0, self._on_close)

    def _on_close(self) -> None:
        self.on_exit()
        self.root.quit()

    def run(self) -> None:
        self.root.mainloop()
