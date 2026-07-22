"""Utilidades varias: logging, espacio en disco, detección de ffmpeg, nombres de archivo."""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_file: str) -> logging.Logger:
    """Configura logging a archivo (con rotación) y a consola."""
    logger = logging.getLogger("minecraft_recorder")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formato = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formato)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formato)
    logger.addHandler(console_handler)

    return logger


def check_ffmpeg_available() -> str | None:
    """Devuelve la ruta de ffmpeg en PATH, o None si no está disponible."""
    return shutil.which("ffmpeg")


def check_ffprobe_available() -> str | None:
    return shutil.which("ffprobe")


def free_space_gb(path: str) -> float:
    """Espacio libre en GB del disco donde vive `path` (crea la carpeta si no existe)."""
    Path(path).mkdir(parents=True, exist_ok=True)
    total, used, free = shutil.disk_usage(path)
    return free / (1024 ** 3)


def has_enough_disk_space(path: str, min_gb: float) -> tuple[bool, float]:
    libre = free_space_gb(path)
    return libre >= min_gb, libre


def format_duration(seconds: float) -> str:
    """Convierte segundos a formato HHhMMmSSs, ej: 01h23m45s."""
    seconds = int(round(seconds))
    horas, resto = divmod(seconds, 3600)
    minutos, segs = divmod(resto, 60)
    return f"{horas:02d}h{minutos:02d}m{segs:02d}s"


def month_subfolder(base_dir: str, when: datetime | None = None) -> Path:
    """Devuelve (y crea) la subcarpeta del mes YYYY-MM dentro de base_dir."""
    when = when or datetime.now()
    carpeta = Path(base_dir) / when.strftime("%Y-%m")
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def build_recording_filename(start_time: datetime, duration_seconds: float, extension: str = "mkv") -> str:
    """Genera el nombre final: minecraft_{fecha}_{hora}_{duracion}.{ext}"""
    fecha = start_time.strftime("%Y-%m-%d")
    hora = start_time.strftime("%H-%M-%S")
    duracion = format_duration(duration_seconds)
    return f"minecraft_{fecha}_{hora}_{duracion}.{extension}"
