"""Guardas anti-look-ahead (§2.2).

Contrato: toda lectura de datos historicos declara la fecha del dato que devuelve.
Si esa fecha es posterior al `as_of` vigente, `require_visible()` lanza
`LookAheadError` en vez de devolver el dato. No hay modo permisivo.

Sin `as_of()` activo el limite es la hora del reloj: en produccion tampoco se
puede leer el futuro, solo que el futuro empieza ahora.

Cada lectura queda en un log en memoria. `verify_no_lookahead()` lo recorre y
confirma que ningun acceso tuvo fecha posterior a su as_of; es lo que consume
`score backtest --verify-no-lookahead` (§C.5).
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Iterator

from core.clock import FrozenClock, format_utc, get_clock, set_clock


class LookAheadError(Exception):
    """Se pidio un dato con fecha posterior al as_of vigente."""


@dataclass(frozen=True)
class Access:
    """Un acceso a datos historicos, tal como quedo registrado."""

    kind: str          # 'price' | 'macro' | 'corporate_action' | ...
    label: str         # 'SPY@2022-02-24' | 'CPIAUCSL@2020-03-01' | ...
    data_ts: datetime  # momento en que el dato fue publico
    as_of_ts: datetime # limite vigente en ese momento

    @property
    def is_look_ahead(self) -> bool:
        return self.data_ts > self.as_of_ts


_state = threading.local()


def _stack() -> list[datetime]:
    if not hasattr(_state, "stack"):
        _state.stack = []
    return _state.stack


def _log() -> list[Access]:
    if not hasattr(_state, "log"):
        _state.log = []
    return _state.log


def current_as_of() -> datetime | None:
    """Limite vigente, o None si no hay `as_of()` activo."""
    stack = _stack()
    return stack[-1] if stack else None


def effective_as_of() -> datetime:
    """Limite efectivo: el `as_of()` vigente, o la hora del reloj."""
    return current_as_of() or get_clock().now()


@contextmanager
def as_of(timestamp: datetime | date | str) -> Iterator[datetime]:
    """Adentro de este contexto, cualquier acceso a datos con fecha posterior a
    `timestamp` lanza LookAheadError.

    Ademas congela el reloj: el codigo que adentro pregunte "que hora es" tiene
    que ver la hora de la simulacion, no la de la maquina. Sin esto, cualquier
    `evaluate_after = now() + 20d` calculado adentro del backtest saldria mal.

    Anidar solo permite achicar la ventana. Ampliarla adentro de un `as_of()`
    seria exactamente la trampa que este modulo existe para impedir.
    """
    moment = _coerce(timestamp)
    outer = current_as_of()
    if outer is not None and moment > outer:
        raise LookAheadError(
            f"as_of anidado mas amplio que el externo: {format_utc(moment)} > {format_utc(outer)}"
        )

    _stack().append(moment)
    previous_clock = set_clock(FrozenClock(moment))
    try:
        yield moment
    finally:
        set_clock(previous_clock)
        _stack().pop()


def require_visible(kind: str, label: str, data_ts: datetime | date | str) -> None:
    """Registra el acceso y falla si el dato todavia no era publico."""
    moment = _coerce(data_ts)
    boundary = effective_as_of()
    access = Access(kind=kind, label=label, data_ts=moment, as_of_ts=boundary)
    _log().append(access)
    if access.is_look_ahead:
        raise LookAheadError(
            f"look-ahead en {kind} {label}: el dato fue publico {format_utc(moment)}, "
            f"posterior al as_of {format_utc(boundary)}"
        )


def is_visible(data_ts: datetime | date | str) -> bool:
    """Version no explosiva, para filtrar en vez de fallar. No registra acceso."""
    return _coerce(data_ts) <= effective_as_of()


def visibility_cutoff_date() -> date:
    """Ultima fecha diaria cuyo cierre ya era publico bajo el as_of vigente.

    Un cierre diario se considera publico a las 23:59:59Z del mismo dia, asi que
    con as_of intradiario del dia D el ultimo cierre visible es el de D-1.
    """
    boundary = effective_as_of()
    if boundary.timetz() >= time(23, 59, 59, tzinfo=timezone.utc):
        return boundary.date()
    from datetime import timedelta

    return boundary.date() - timedelta(days=1)


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------


def access_log() -> list[Access]:
    return list(_log())


def clear_access_log() -> None:
    _log().clear()


@contextmanager
def recording() -> Iterator[list[Access]]:
    """Vacia el log, corre el bloque y deja disponible lo registrado."""
    clear_access_log()
    try:
        yield _log()
    finally:
        pass


def verify_no_lookahead(accesses: list[Access] | None = None) -> list[Access]:
    """Devuelve los accesos que miraron el futuro. Lista vacia = limpio."""
    return [a for a in (access_log() if accesses is None else accesses) if a.is_look_ahead]


# ---------------------------------------------------------------------------


def _coerce(value: datetime | date | str) -> datetime:
    """date -> fin del dia UTC (un dato diario es publico al cerrar el dia)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"timestamp naive: {value!r}. Se exige datetime aware en UTC.")
        return value.astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time(23, 59, 59), tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10:
            return _coerce(date.fromisoformat(text))
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    raise TypeError(f"no se puede interpretar como momento: {value!r}")
