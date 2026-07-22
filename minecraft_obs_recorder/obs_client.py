"""Cliente de OBS: conexión vía obsws-python (obs-websocket v5), reconexión con backoff
y suscripción a eventos para mantener el estado sincronizado con la realidad de OBS
(por si alguien graba/para desde la propia UI de OBS y no desde nuestros hotkeys)."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import obsws_python as obs

logger = logging.getLogger("minecraft_recorder")


class OBSConnectionError(Exception):
    pass


class OBSClient:
    def __init__(self, host: str, port: int, password: str, scene_name: str,
                 retry_interval_seconds: float = 5.0, max_retries: int = 12):
        self.host = host
        self.port = port
        self.password = password
        self.scene_name = scene_name
        self.retry_interval_seconds = retry_interval_seconds
        self.max_retries = max_retries

        self._req: Optional[obs.ReqClient] = None
        self._evt: Optional[obs.EventClient] = None
        self._lock = threading.RLock()
        self._connected = False

        # Callbacks externos (los conecta recorder.py)
        self.on_connected: Optional[Callable[[], None]] = None
        self.on_disconnected: Optional[Callable[[str], None]] = None
        self.on_record_state_changed: Optional[Callable[[object], None]] = None
        self.on_manual_retry_needed: Optional[Callable[[], None]] = None

        self._stop_watchdog = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None
        self._manual_retry_event = threading.Event()

    # ---------- Conexión ----------

    def connect_once(self) -> None:
        """Intenta conectar una sola vez. Lanza OBSConnectionError si falla."""
        with self._lock:
            try:
                self._req = obs.ReqClient(
                    host=self.host, port=self.port, password=self.password, timeout=5
                )
                self._evt = obs.EventClient(
                    host=self.host, port=self.port, password=self.password, timeout=5
                )
                self._evt.callback.register(self._handle_record_state_changed)
                self._connected = True
            except Exception as e:
                self._connected = False
                raise OBSConnectionError(str(e)) from e

    def is_connected(self) -> bool:
        return self._connected

    def _handle_record_state_changed(self, data) -> None:
        if self.on_record_state_changed:
            try:
                self.on_record_state_changed(data)
            except Exception:
                logger.exception("Error en callback on_record_state_changed")

    def verify_scene_exists(self) -> bool:
        """Verifica que la escena configurada exista en OBS."""
        resp = self._req.get_scene_list()
        nombres = [s["sceneName"] for s in resp.scenes]
        existe = self.scene_name in nombres
        if not existe:
            logger.error(
                "La escena '%s' configurada en config.json no existe en OBS. Escenas disponibles: %s",
                self.scene_name, nombres,
            )
        return existe

    def log_video_settings(self) -> None:
        """Loguea la resolución/fps activa en OBS para poder auditar que se está grabando en 1080p60+."""
        try:
            resp = self._req.get_video_settings()
            fps = resp.fps_numerator / resp.fps_denominator
            logger.info(
                "Config. de video en OBS: %sx%s @ %.2f fps (base %sx%s)",
                resp.output_width, resp.output_height, fps, resp.base_width, resp.base_height,
            )
            if resp.output_height < 1080 or fps < 59.9:
                logger.warning(
                    "La resolución/fps activa en OBS (%sx%s@%.2f) está por debajo del mínimo "
                    "recomendado (1080p60). Esto se configura en OBS, no en este script.",
                    resp.output_width, resp.output_height, fps,
                )
        except Exception:
            logger.exception("No se pudo obtener la configuración de video de OBS")

    # ---------- Requests de grabación ----------

    def get_record_status(self):
        return self._req.get_record_status()

    def start_record(self):
        self._req.set_current_program_scene(self.scene_name)
        self._req.start_record()

    def stop_record(self):
        return self._req.stop_record()

    def pause_record(self):
        self._req.pause_record()

    def resume_record(self):
        self._req.resume_record()

    # ---------- Reconexión con backoff ----------

    def start_watchdog(self) -> None:
        """Arranca un thread en background que monitorea la conexión y reintenta con backoff:
        cada retry_interval_seconds, hasta max_retries veces, y después espera un disparo manual."""
        self._stop_watchdog.clear()
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def stop_watchdog(self) -> None:
        self._stop_watchdog.set()
        self._manual_retry_event.set()

    def request_manual_retry(self) -> None:
        """Se llama desde la UI/hotkey para forzar un intento de reconexión inmediato."""
        self._manual_retry_event.set()

    def _watchdog_loop(self) -> None:
        while not self._stop_watchdog.is_set():
            if self.is_connected():
                # Chequeo liviano de salud de la conexión.
                try:
                    self._req.get_version()
                except Exception as e:
                    logger.warning("Se perdió la conexión con OBS: %s", e)
                    self._connected = False
                    if self.on_disconnected:
                        self.on_disconnected(str(e))
                time.sleep(2)
                continue

            # Desconectado: intentar reconectar con backoff fijo.
            intentos = 0
            while intentos < self.max_retries and not self._stop_watchdog.is_set():
                intentos += 1
                logger.info(
                    "Intentando reconectar a OBS (%s/%s)...", intentos, self.max_retries
                )
                try:
                    self.connect_once()
                    logger.info("Reconectado a OBS.")
                    if self.on_connected:
                        self.on_connected()
                    break
                except OBSConnectionError:
                    self._stop_watchdog.wait(self.retry_interval_seconds)

            if not self.is_connected() and not self._stop_watchdog.is_set():
                logger.error(
                    "No se pudo reconectar a OBS tras %s intentos. Esperando reintento manual "
                    "(botón 'Reconectar' en la UI).", self.max_retries
                )
                if self.on_manual_retry_needed:
                    self.on_manual_retry_needed()
                self._manual_retry_event.clear()
                self._manual_retry_event.wait()  # se destraba con request_manual_retry() o stop_watchdog()

    def disconnect(self) -> None:
        self.stop_watchdog()
        with self._lock:
            try:
                if self._evt:
                    self._evt.disconnect()
            except Exception:
                pass
            try:
                if self._req:
                    self._req.disconnect()
            except Exception:
                pass
            self._connected = False
