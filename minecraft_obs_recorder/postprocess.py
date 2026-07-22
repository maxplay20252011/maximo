"""Post-procesamiento posterior a una grabación: clip resumen con ffmpeg y log de sesiones.

Se ejecuta siempre en un thread separado para no bloquear el inicio de una
grabación nueva apenas se corta la anterior.
"""
from __future__ import annotations

import csv
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils import check_ffmpeg_available, check_ffprobe_available

logger = logging.getLogger("minecraft_recorder")


@dataclass
class SessionRecord:
    fecha: str
    hora_inicio: str
    duracion_seg: float
    tamano_bytes: int
    nombre_archivo: str
    clip_generado: bool


def _probe_duration_seconds(video_path: Path) -> Optional[float]:
    ffprobe = check_ffprobe_available()
    if not ffprobe:
        return None
    try:
        resultado = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True, timeout=15, check=True,
        )
        return float(resultado.stdout.strip())
    except Exception:
        logger.warning("No se pudo obtener la duración del video con ffprobe (%s)", video_path)
        return None


def generate_summary_clip(video_path: Path, clip_duration_seconds: int) -> Optional[Path]:
    """Genera un clip de los últimos N segundos usando stream copy (sin recodificar).

    Nota: al usar -c copy, el punto de corte se ajusta al keyframe más cercano,
    por lo que el clip puede empezar unos segundos antes de lo solicitado
    (el desvío depende del intervalo de keyframes configurado en OBS).
    """
    ffmpeg = check_ffmpeg_available()
    if not ffmpeg:
        logger.warning("ffmpeg no está en el PATH: se omite la generación del clip resumen.")
        return None

    if not video_path.exists():
        logger.error("No se puede generar clip: no existe el archivo %s", video_path)
        return None

    duracion_total = _probe_duration_seconds(video_path)
    duracion_pedida = clip_duration_seconds
    if duracion_total is not None and duracion_total < clip_duration_seconds:
        duracion_pedida = max(1, int(duracion_total) - 1)

    clip_path = video_path.with_name(f"{video_path.stem}_clip.mp4")
    comando = [
        ffmpeg, "-y",
        "-sseof", f"-{duracion_pedida}",
        "-i", str(video_path),
        "-c", "copy",
        str(clip_path),
    ]
    try:
        subprocess.run(comando, capture_output=True, text=True, timeout=60, check=True)
        logger.info("Clip resumen generado: %s", clip_path)
        return clip_path
    except subprocess.CalledProcessError as e:
        logger.error("ffmpeg falló generando el clip resumen: %s", e.stderr)
        return None
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg tardó demasiado generando el clip resumen (timeout).")
        return None
    except Exception:
        logger.exception("Error inesperado generando el clip resumen")
        return None


def append_session_log(log_path: Path, record: SessionRecord) -> None:
    """Agrega una fila al CSV de historial de sesiones (crea el archivo con headers si no existe)."""
    existe = log_path.exists()
    try:
        with open(log_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not existe:
                writer.writerow([
                    "fecha", "hora_inicio", "duracion_segundos", "tamano_bytes",
                    "nombre_archivo", "clip_generado",
                ])
            writer.writerow([
                record.fecha, record.hora_inicio, record.duracion_seg,
                record.tamano_bytes, record.nombre_archivo, record.clip_generado,
            ])
    except Exception:
        logger.exception("No se pudo escribir en el log de sesiones (%s)", log_path)


def process_finished_recording(video_path: Path, start_time: datetime, duration_seconds: float,
                                clip_enabled: bool, clip_duration_seconds: int,
                                session_log_path: Path) -> None:
    """Corre todo el post-procesamiento de una grabación ya renombrada. Pensado para
    invocarse dentro de un thread; ningún error acá debe propagarse hacia arriba."""
    try:
        tamano_bytes = video_path.stat().st_size if video_path.exists() else 0

        clip_generado = False
        if clip_enabled:
            clip_path = generate_summary_clip(video_path, clip_duration_seconds)
            clip_generado = clip_path is not None

        record = SessionRecord(
            fecha=start_time.strftime("%Y-%m-%d"),
            hora_inicio=start_time.strftime("%H:%M:%S"),
            duracion_seg=round(duration_seconds, 1),
            tamano_bytes=tamano_bytes,
            nombre_archivo=video_path.name,
            clip_generado=clip_generado,
        )
        append_session_log(session_log_path, record)
        logger.info("Post-procesamiento completo para %s", video_path.name)
    except Exception:
        logger.exception("Error en el post-procesamiento de %s", video_path)
