"""Reloj inyectable (§1).

Version minima: solo lo que la Tarea 1 necesita para no llamar a `datetime.now()`
en el codigo de backup y de migraciones. La Tarea 2 (§2) extiende este modulo con
`as_of()` y las guardas anti-look-ahead; el contrato de `Clock` no cambia.

Regla: ningun modulo llama a `datetime.now()` directamente. Todos piden la hora a
un `Clock`. En tests se reemplaza por `FrozenClock`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Protocol

# Formato canonico persistido en SQLite. Coincide con los CHECK ... GLOB del schema.
UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DATE_FORMAT = "%Y-%m-%d"


class Clock(Protocol):
    """Fuente de tiempo. Siempre devuelve datetimes aware en UTC."""

    def now(self) -> datetime: ...


class SystemClock:
    """Reloj real. Unico lugar del sistema donde se consulta la hora de la maquina."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FrozenClock:
    """Reloj congelado para tests y para el flag global `--as-of`."""

    def __init__(self, fixed: datetime) -> None:
        if fixed.tzinfo is None:
            raise ValueError("FrozenClock exige un datetime aware (UTC)")
        self._fixed = fixed.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._fixed

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        self._fixed = self._fixed + timedelta(seconds=seconds)


_clock: Clock = SystemClock()


def get_clock() -> Clock:
    return _clock


def set_clock(clock: Clock) -> Clock:
    """Reemplaza el reloj global. Devuelve el anterior, para restaurarlo."""
    global _clock
    previous, _clock = _clock, clock
    return previous


def now() -> datetime:
    return _clock.now()


def format_utc(moment: datetime) -> str:
    """datetime aware -> 'YYYY-MM-DDTHH:MM:SSZ'. Rechaza naive: un timestamp sin
    zona es la puerta de entrada del look-ahead silencioso (§2)."""
    if moment.tzinfo is None:
        raise ValueError("timestamp naive: se exige datetime aware en UTC")
    return moment.astimezone(timezone.utc).strftime(UTC_FORMAT)


def parse_utc(value: str) -> datetime:
    return datetime.strptime(value, UTC_FORMAT).replace(tzinfo=timezone.utc)


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def utc_now_str() -> str:
    return format_utc(now())
