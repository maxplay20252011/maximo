"""Máquina de estados de la grabación: arrancar, parar, pausar/reanudar.

Mantiene el estado sincronizado con los eventos reales de OBS (no solo con lo
que dispararon nuestros propios hotkeys), y dispara el post-procesamiento en
un thread aparte para no bloquear el inicio de una grabación nueva.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

import postprocess
from config import AppConfig
from obs_client import OBSClient
from utils import (
    build_recording_filename,
    has_enough_disk_space,
    month_subfolder,
)

logger = logging.getLogger("minecraft_recorder")


class RecordingState(Enum):
    DESCONECTADO = "Desconectado"
    DETENIDO = "Detenido"
    GRABANDO = "Grabando"
    PAUSADO = "Pausado"


@dataclass
class RecorderStatus:
    state: RecordingState
    elapsed_seconds: float
    free_space_gb: float
    last_file: Optional[str]


class Recorder:
    def __init__(self, config: AppConfig, obs_client: OBSClient):
        self.config = config
        self.obs = obs_client
        self._lock = threading.RLock()

        self.state = RecordingState.DESCONECTADO
        self._start_time: Optional[datetime] = None
        self._pause_started_at: Optional[float] = None
        self._paused_accum_seconds = 0.0
        self.last_file: Optional[str] = None

        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="postproc")

        self.obs.on_connected = self._on_obs_connected
        self.obs.on_disconnected = self._on_obs_disconnected
        self.obs.on_record_state_changed = self._on_obs_record_state_changed

    # ---------- Callbacks de conexión ----------

    def _on_obs_connected(self) -> None:
        with self._lock:
            if self.state == RecordingState.DESCONECTADO:
                self.state = RecordingState.DETENIDO
        logger.info("[%s] Conectado a OBS.", self._ts())

    def _on_obs_disconnected(self, motivo: str) -> None:
        with self._lock:
            self.state = RecordingState.DESCONECTADO
        logger.warning("[%s] Desconectado de OBS: %s", self._ts(), motivo)

    def _on_obs_record_state_changed(self, data) -> None:
        """Sincroniza nuestro estado interno si la grabación cambió desde la UI de OBS."""
        try:
            output_state = getattr(data, "output_state", "")
            with self._lock:
                if output_state == "OBS_WEBSOCKET_OUTPUT_STARTED" and self.state != RecordingState.GRABANDO:
                    self.state = RecordingState.GRABANDO
                    if self._start_time is None:
                        self._start_time = datetime.now()
                    logger.info("[%s] OBS notificó inicio de grabación (evento externo).", self._ts())
                elif output_state == "OBS_WEBSOCKET_OUTPUT_PAUSED":
                    self.state = RecordingState.PAUSADO
                elif output_state == "OBS_WEBSOCKET_OUTPUT_RESUMED":
                    self.state = RecordingState.GRABANDO
                elif output_state == "OBS_WEBSOCKET_OUTPUT_STOPPED" and self.state in (
                    RecordingState.GRABANDO, RecordingState.PAUSADO
                ):
                    output_path = getattr(data, "output_path", None)
                    logger.info("[%s] OBS notificó fin de grabación (evento externo).", self._ts())
                    self._finalize_recording(output_path)
        except Exception:
            logger.exception("Error procesando evento RecordStateChanged")

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---------- Acciones públicas (hotkeys / UI) ----------

    def start(self) -> None:
        with self._lock:
            if self.state == RecordingState.DESCONECTADO:
                logger.warning("[%s] No se puede grabar: sin conexión a OBS.", self._ts())
                return
            if self.state in (RecordingState.GRABANDO, RecordingState.PAUSADO):
                logger.warning("[%s] Ya hay una grabación en curso, se ignora F9.", self._ts())
                return

            ok, libre_gb = has_enough_disk_space(
                self.config.output.base_dir, self.config.output.min_free_space_gb
            )
            if not ok:
                logger.error(
                    "[%s] Espacio en disco insuficiente (%.1f GB libres, mínimo %.1f GB). "
                    "No se inicia la grabación.",
                    self._ts(), libre_gb, self.config.output.min_free_space_gb,
                )
                return

            try:
                if not self.obs.verify_scene_exists():
                    logger.error(
                        "[%s] No se inicia: la escena '%s' no existe en OBS.",
                        self._ts(), self.config.obs.scene_name,
                    )
                    return
                self.obs.log_video_settings()
                self.obs.start_record()
            except Exception:
                logger.exception("[%s] Error al iniciar la grabación en OBS", self._ts())
                return

            self._start_time = datetime.now()
            self._paused_accum_seconds = 0.0
            self._pause_started_at = None
            self.state = RecordingState.GRABANDO
            logger.info("[%s] Grabación iniciada.", self._ts())

    def stop(self) -> None:
        with self._lock:
            if self.state not in (RecordingState.GRABANDO, RecordingState.PAUSADO):
                logger.warning("[%s] No hay grabación en curso para detener.", self._ts())
                return
            try:
                resp = self.obs.stop_record()
                output_path = getattr(resp, "output_path", None)
            except Exception:
                logger.exception("[%s] Error al detener la grabación en OBS", self._ts())
                return

            self._finalize_recording(output_path)

    def toggle_pause(self) -> None:
        with self._lock:
            if self.state == RecordingState.GRABANDO:
                try:
                    self.obs.pause_record()
                    self.state = RecordingState.PAUSADO
                    self._pause_started_at = time.monotonic()
                    logger.info("[%s] Grabación pausada.", self._ts())
                except Exception:
                    logger.exception("[%s] Error al pausar la grabación", self._ts())
            elif self.state == RecordingState.PAUSADO:
                try:
                    self.obs.resume_record()
                    if self._pause_started_at is not None:
                        self._paused_accum_seconds += time.monotonic() - self._pause_started_at
                        self._pause_started_at = None
                    self.state = RecordingState.GRABANDO
                    logger.info("[%s] Grabación reanudada.", self._ts())
                except Exception:
                    logger.exception("[%s] Error al reanudar la grabación", self._ts())
            else:
                logger.warning("[%s] No hay grabación en curso para pausar/reanudar.", self._ts())

    # ---------- Finalización y post-procesamiento ----------

    def _finalize_recording(self, obs_output_path: Optional[str]) -> None:
        """Renombra el archivo grabado por OBS al formato final y dispara el
        post-procesamiento en background. Nunca debe bloquear ni tirar excepción hacia arriba."""
        start_time = self._start_time or datetime.now()
        duracion = self._compute_duration_seconds()

        self.state = RecordingState.DETENIDO
        self._start_time = None
        self._pause_started_at = None
        self._paused_accum_seconds = 0.0

        if not obs_output_path:
            logger.error(
                "[%s] OBS no informó la ruta del archivo grabado; no se puede renombrar.",
                self._ts(),
            )
            return

        try:
            origen = Path(obs_output_path)
            destino_dir = month_subfolder(self.config.output.base_dir, start_time)
            nombre_final = build_recording_filename(start_time, duracion, extension=origen.suffix.lstrip(".") or "mkv")
            destino = destino_dir / nombre_final

            self._wait_until_file_ready(origen)
            origen.rename(destino)
            self.last_file = str(destino)
            logger.info("[%s] Grabación guardada como %s", self._ts(), destino)
        except Exception:
            logger.exception("[%s] Error renombrando/moviendo el archivo grabado", self._ts())
            return

        self._executor.submit(
            postprocess.process_finished_recording,
            destino,
            start_time,
            duracion,
            self.config.clip.enabled,
            self.config.clip.duration_seconds,
            Path(self.config.logging.session_log_file),
        )

    @staticmethod
    def _wait_until_file_ready(path: Path, timeout: float = 10.0) -> None:
        """Espera a que OBS termine de flushear el archivo (tamaño estable) antes de moverlo."""
        inicio = time.monotonic()
        ultimo_tamano = -1
        while time.monotonic() - inicio < timeout:
            if not path.exists():
                time.sleep(0.2)
                continue
            tamano = path.stat().st_size
            if tamano == ultimo_tamano:
                return
            ultimo_tamano = tamano
            time.sleep(0.3)

    def _compute_duration_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        total = (datetime.now() - self._start_time).total_seconds()
        pausado = self._paused_accum_seconds
        if self._pause_started_at is not None:
            pausado += time.monotonic() - self._pause_started_at
        return max(0.0, total - pausado)

    # ---------- Estado para la UI ----------

    def get_status(self) -> RecorderStatus:
        with self._lock:
            elapsed = self._compute_duration_seconds() if self._start_time else 0.0
            _, libre_gb = has_enough_disk_space(self.config.output.base_dir, 0)
            return RecorderStatus(
                state=self.state,
                elapsed_seconds=elapsed,
                free_space_gb=libre_gb,
                last_file=self.last_file,
            )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)
