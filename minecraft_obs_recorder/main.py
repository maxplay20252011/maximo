"""Punto de entrada: arranca la conexión a OBS, el watchdog de reconexión,
las hotkeys globales y la ventana de estado."""
from __future__ import annotations

import sys

from config import ConfigError, load_config
from hotkeys import HotkeyManager
from obs_client import OBSClient, OBSConnectionError
from recorder import Recorder
from ui import StatusUI
from utils import check_ffmpeg_available, setup_logging


def main() -> int:
    try:
        config = load_config("config.json")
    except ConfigError as e:
        print(f"Error de configuración: {e}", file=sys.stderr)
        return 1

    logger = setup_logging(config.logging.log_file)
    logger.info("Iniciando Grabador Minecraft - OBS")

    if not check_ffmpeg_available():
        logger.warning(
            "ffmpeg no se encontró en el PATH. La grabación funcionará igual, "
            "pero no se podrá generar el clip resumen. Instalá ffmpeg y agregalo al PATH."
        )

    obs_client = OBSClient(
        host=config.obs.host,
        port=config.obs.port,
        password=config.obs.password,
        scene_name=config.obs.scene_name,
        retry_interval_seconds=config.reconnect.retry_interval_seconds,
        max_retries=config.reconnect.max_retries,
    )

    try:
        obs_client.connect_once()
        if not obs_client.verify_scene_exists():
            logger.error(
                "La escena '%s' no existe en OBS. Corregí config.json o creá la escena "
                "antes de grabar. La app sigue abierta pero no permitirá iniciar grabaciones "
                "hasta corregir esto.",
                config.obs.scene_name,
            )
        obs_client.log_video_settings()
    except OBSConnectionError as e:
        logger.warning(
            "No se pudo conectar a OBS al arrancar (%s). Reintentando en background.", e
        )

    recorder = Recorder(config, obs_client)
    obs_client.start_watchdog()

    hotkeys = HotkeyManager(
        start_key=config.hotkeys.start,
        stop_key=config.hotkeys.stop,
        pause_resume_key=config.hotkeys.pause_resume,
        on_start=recorder.start,
        on_stop=recorder.stop,
        on_pause_resume=recorder.toggle_pause,
    )
    hotkeys.start()

    def on_exit() -> None:
        logger.info("Cerrando la aplicación...")
        hotkeys.stop()
        recorder.shutdown()
        obs_client.disconnect()

    ui = StatusUI(
        recorder=recorder,
        on_start=recorder.start,
        on_stop=recorder.stop,
        on_pause_resume=recorder.toggle_pause,
        on_reconnect=obs_client.request_manual_retry,
        on_exit=on_exit,
    )
    ui.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
