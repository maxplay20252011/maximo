# Motor de mapeo noticias → exposición de activos

Clasifica eventos noticiosos, los compara contra un archivo histórico de episodios
análogos con resultados medidos, y produce un mapa de exposiciones probables con
incertidumbre explícita.

**No emite señales de trading ni recomendaciones.** La especificación completa está
en `MOTOR-NOTICIAS.md` / `CLAUDE.md`; este archivo solo explica cómo correrlo.

---

## Estado: 4 de 13 tareas

| # | Tarea | Estado |
|---|---|---|
| 1 | Schema y migraciones | Hecha |
| 2 | Point-in-time y guardas anti-look-ahead | Hecha · **las 4 guardas de §2.2 pasan** |
| 3 | Clasificador de régimen | Hecha |
| 4 | Corpus semilla, outcomes y autodetección | Hecha |
| 5 | Matcher de análogos | Pendiente · **checkpoint crítico** |
| 6 | Evaluación y estadística | Pendiente |
| 7-8 | Ingesta, dedup y clasificación | Pendiente |
| 9-13 | Narrativa, scoring, conectores, dashboard, operación | Pendiente |

**Nada está verificado contra datos de mercado reales.** Todo lo que pasa hoy pasa
sobre series sintéticas construidas para que la respuesta correcta se sepa de
antemano. Es suficiente para probar la lógica; no dice nada sobre el mundo.

---

## Instalación

Requiere Python 3.11 o superior. No hace falta nada más.

```bash
git clone <repo> && cd news-engine
./setup.sh
```

El script crea el entorno virtual, instala dependencias, crea la base, corre los
tests y verifica las guardas anti-look-ahead. Es idempotente.

En Windows, o si preferís a mano:

```bash
python3.11 -m venv .venv
.venv/bin/activate            # Windows: .venv\Scripts\activate
pip install pydantic typer httpx pyyaml python-dotenv rich pytest freezegun
python run.py db init
python -m pytest tests/ -q
python run.py pit verify
```

Tiene que terminar con `4/4 guardas pasan`. Si falla alguna, no sigas: §0 dice que
se frena todo.

---

## Ver que funciona, sin red ni credenciales

```bash
./setup.sh --demo          # o: python run.py demo
```

Corre la cadena entera —precios → regímenes → corpus → outcomes → autodetección—
sobre **datos inventados**, en una base aparte (`data/demo.db`). El archivo real
no se toca.

```
precios sinteticos   180774 cierres
macro sintetica      22164 observaciones con vintages
regimenes            69 episodios · 187 cambios descartados
corpus semilla       26 eventos · market_state 86%
outcomes             NO_BENCHMARK 260 · OK 468
autodeteccion        93 candidatos, 0 promovidos
```

**Los números de la demo no significan nada.** Los precios son un paseo aleatorio
con semilla fija. Sirve para ver que las piezas encajan, nada más.

Para explorarla:

```bash
python run.py --db data/demo.db regimes timeline
python run.py --db data/demo.db seed stats
```

---

## Ponerlo a andar con datos reales

Necesita salida a internet y una API key gratuita de FRED
(se obtiene en el momento registrándose en el sitio de FRED).

```bash
echo "FRED_API_KEY=tu_key" >> .env

python run.py pit load-prices --from 2005-01-01          # ~33 activos, EOD
python run.py pit load-macro  --vintages --from 2005-01-01
python run.py pit coverage                               # qué quedó cargado

python run.py regimes build --from 2007-01-01
python run.py regimes timeline

python run.py seed load
python run.py seed reassign-regimes
python run.py seed outcomes --all
python run.py seed stats

python run.py doctor
```

Los precios arrancan en 2005 y no en 2007 a propósito: el percentil de volatilidad
usa una ventana móvil de 5 años, así que para clasificar régimen desde 2007 hacen
falta datos desde 2002 en el ideal, y desde 2005 como mínimo aceptable.

### Verificación a ojo — esto es lo que falta

Ningún test puede reemplazarla:

- `regimes timeline` tiene que dar `CRISIS` en 2008-09, `LOW` en 2017, `ZIRP` en
  2021, `HIKING` + `ELEVATED` en 2022-23.
- Los outcomes de `ukraine-invasion-2022` a 5 días tienen que mostrar energía y oro
  arriba, Europa abajo.
- Los candidatos de `seed autodetect` tienen que caer en fechas reconocibles.

Si algo de eso no da, hay un problema real y conviene encontrarlo antes de seguir.

---

## Diagnóstico

```bash
python run.py doctor          # qué anda, qué falta, qué comando corregirlo
python run.py doctor --red    # además prueba las fuentes
python run.py healthcheck     # para cron: exit 1 si algo está roto
```

`PENDIENTE` no es una falla: marca una etapa todavía no construida o no corrida.
Un sistema a medio hacer que reporta todo verde miente igual que uno roto.

---

## Comandos

```bash
# base
python run.py db init | migrate | status [--deep] | backup | reset --confirm

# point-in-time (§2)
python run.py pit load-prices [--from] [--to] [--only SPY,VIX] [--dry-run] [--incremental]
python run.py pit load-macro --vintages [--series CPIAUCSL,DGS10]
python run.py pit check --date 2022-02-24                # market_state de esa fecha
python run.py pit check --series CPIAUCSL --date 2020-03-01 --vintage
python run.py pit coverage
python run.py pit verify                                 # las 4 guardas de §2.2

# regímenes (§4)
python run.py regimes build [--from] [--incremental] [--rebuild]
python run.py regimes timeline | current
python run.py regimes check --date 2008-09-15            # con los insumos usados

# corpus (§6)
python run.py seed load | reassign-regimes | stats
python run.py seed outcomes --all | --event-id lehman-2008
python run.py seed autodetect --from 2010-01-01
python run.py seed review --limit 20

# operación
python run.py doctor | healthcheck | demo
```

Flags globales: `--db PATH`, `--config DIR`, `--as-of TIMESTAMP` (congela el reloj
para depurar en una fecha histórica), `--verbose`.

---

## Configuración

| Archivo | Qué define |
|---|---|
| `config/thresholds.yaml` | **Todos** los umbrales numéricos: régimen, histéresis, autodetección, outcomes |
| `config/universe.yaml` | Activos, símbolos de la fuente, benchmarks, campos del `market_state` |
| `config/seed_events.yaml` | Los 26 episodios históricos del corpus |
| `.env` | Credenciales. Nunca va al repo |

Ningún umbral vive en código. Si querés cambiar cuándo un régimen es `CRISIS` o
cuántas semanas tiene que durar un cambio para contar como episodio, se toca
`thresholds.yaml`.

---

## Cómo está armado

```
core/     db.py (SQLite + migraciones) · clock.py (reloj inyectable) · doctor.py
pit/      guards.py (as_of y anti-look-ahead) · prices.py · macro.py · market_state.py
classify/ regime.py · event_types.py
history/  seed.py (corpus) · outcomes.py (medición) · archive.py (autodetección)
tests/    106 tests
```

Tres reglas que atraviesan todo el código:

1. **Nadie llama a `datetime.now()`.** Todo pide la hora a `core.clock`, que en
   tests se reemplaza por un reloj congelado.
2. **Toda lectura histórica declara la fecha del dato.** Si es posterior al `as_of`
   vigente, `pit.guards` lanza `LookAheadError` en vez de devolverlo.
3. **Lo que falta se declara.** Un dato que no está queda en `NULL` y aparece
   listado, nunca se estima ni se rellena con el último valor conocido.

---

## Problemas frecuentes

**`4/4 guardas pasan` no aparece** → no sigas. Es el criterio de muerte de §0.

**`pit load-prices` devuelve 403 o timeouts** → stooq limita por volumen. Bajá el
rango (`--from 2015-01-01`) o cargá por tandas con `--only`.

**`load-macro` dice que falta FRED_API_KEY** → falta la línea en `.env`. Sin
credencial no hay vintages, y sin vintages el análisis histórico usa datos
revisados, que es la trampa que describe §2.1(b).

**`regimes build` dice `0 episodios`** → no hay precios ni macro cargados. El
comando lista qué dimensión falta en cada fecha.

**Los outcomes salen todos `MISSING`** → lo mismo: faltan precios.

**La base creció demasiado** → `python run.py db backup` y después limpiar
`raw_news` viejo según §C.7.
