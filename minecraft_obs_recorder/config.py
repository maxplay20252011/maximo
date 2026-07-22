"""Carga y validación del archivo de configuración config.json."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Se lanza cuando config.json falta, tiene un campo inválido o falta un campo requerido."""


@dataclass
class ObsConfig:
    host: str
    port: int
    password: str
    scene_name: str


@dataclass
class HotkeysConfig:
    start: str
    stop: str
    pause_resume: str


@dataclass
class OutputConfig:
    base_dir: str
    min_free_space_gb: float


@dataclass
class ClipConfig:
    enabled: bool
    duration_seconds: int


@dataclass
class LoggingConfig:
    log_file: str
    session_log_file: str


@dataclass
class ReconnectConfig:
    retry_interval_seconds: float
    max_retries: int


@dataclass
class AppConfig:
    obs: ObsConfig
    hotkeys: HotkeysConfig
    output: OutputConfig
    clip: ClipConfig
    logging: LoggingConfig
    reconnect: ReconnectConfig


# Estructura mínima requerida: (ruta, tipo esperado)
_REQUIRED_FIELDS = [
    ("obs.host", str),
    ("obs.port", int),
    ("obs.password", str),
    ("obs.scene_name", str),
    ("hotkeys.start", str),
    ("hotkeys.stop", str),
    ("hotkeys.pause_resume", str),
    ("output.base_dir", str),
    ("output.min_free_space_gb", (int, float)),
    ("clip.enabled", bool),
    ("clip.duration_seconds", int),
    ("logging.log_file", str),
    ("logging.session_log_file", str),
    ("reconnect.retry_interval_seconds", (int, float)),
    ("reconnect.max_retries", int),
]


def _get_nested(data: dict, dotted_path: str):
    node = data
    for part in dotted_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None, False
        node = node[part]
    return node, True


def _validate_raw(data: dict) -> None:
    faltantes = []
    tipo_incorrecto = []
    for dotted_path, expected_type in _REQUIRED_FIELDS:
        value, found = _get_nested(data, dotted_path)
        if not found:
            faltantes.append(dotted_path)
            continue
        if not isinstance(value, expected_type):
            tipo_incorrecto.append(f"{dotted_path} (se esperaba {expected_type})")

    if faltantes or tipo_incorrecto:
        partes = []
        if faltantes:
            partes.append("Campos faltantes: " + ", ".join(faltantes))
        if tipo_incorrecto:
            partes.append("Campos con tipo inválido: " + ", ".join(tipo_incorrecto))
        raise ConfigError(
            "config.json inválido.\n" + "\n".join(partes) +
            "\nRevisá config.example.json como referencia."
        )

    hotkeys = data["hotkeys"]
    valores = [hotkeys["start"].lower(), hotkeys["stop"].lower(), hotkeys["pause_resume"].lower()]
    if len(set(valores)) != len(valores):
        raise ConfigError(
            "Las hotkeys de start/stop/pause_resume no pueden ser iguales entre sí: "
            f"{valores}"
        )

    if data["output"]["min_free_space_gb"] < 0:
        raise ConfigError("output.min_free_space_gb no puede ser negativo.")

    if data["clip"]["duration_seconds"] <= 0:
        raise ConfigError("clip.duration_seconds debe ser mayor a 0.")

    if data["reconnect"]["max_retries"] <= 0:
        raise ConfigError("reconnect.max_retries debe ser mayor a 0.")


def load_config(path: str | Path = "config.json") -> AppConfig:
    """Lee y valida config.json. Lanza ConfigError con un mensaje claro si algo falta."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"No se encontró '{path}'. Copiá 'config.example.json' a 'config.json' "
            "y completá los valores (host/password de OBS, carpeta de salida, etc.)."
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(f"'{path}' no es un JSON válido: {e}") from e

    _validate_raw(data)

    # Intenta crear la carpeta de salida ya en esta etapa para fallar temprano
    # si la ruta es inválida (ej: letra de unidad inexistente en Windows).
    try:
        os.makedirs(data["output"]["base_dir"], exist_ok=True)
    except OSError as e:
        raise ConfigError(
            f"No se pudo crear/acceder a la carpeta de salida '{data['output']['base_dir']}': {e}"
        ) from e

    return AppConfig(
        obs=ObsConfig(**data["obs"]),
        hotkeys=HotkeysConfig(**data["hotkeys"]),
        output=OutputConfig(**data["output"]),
        clip=ClipConfig(**data["clip"]),
        logging=LoggingConfig(**data["logging"]),
        reconnect=ReconnectConfig(**data["reconnect"]),
    )
