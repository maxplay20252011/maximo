# Grabador Minecraft - OBS

Automatiza grabación de partidas de Minecraft controlando OBS Studio vía
`obs-websocket` v5: hotkeys globales, nomenclatura/organización de archivos,
clip resumen post-grabación y un panel de estado en tiempo real.

## Requisitos previos en OBS (antes de tocar el código)

- **OBS Studio 28 o superior** (verificado contra la última estable, 32.2.0).
  A partir de la versión 28, `obs-websocket` v5 viene **incluido de fábrica** —
  no hace falta instalar ningún plugin aparte. Si tenés OBS 27 o anterior,
  actualizá OBS en vez de instalar el plugin viejo (que habla el protocolo v4,
  incompatible con este proyecto).
- Habilitar el servidor: `Herramientas > WebSocket Server Settings` →
  tildar "Enable WebSocket server". Ahí mismo click en "Show Connect Info"
  para ver/generar la contraseña (o "Regenerate" si querés una nueva). Anotá
  host (normalmente `localhost`), puerto (por defecto `4455`) y password.
- Crear (o identificar) la **escena** que vas a usar para grabar Minecraft y
  poner su nombre exacto en `config.json` (`obs.scene_name`).
- Configurar la resolución/FPS de salida en OBS (`Configuración > Video`) en
  1080p60 o superior — esto se configura en OBS, no en este script. El script
  loguea la config activa al arrancar y avisa (sin bloquear) si está por
  debajo de eso.

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy config.example.json config.json
```

Editá `config.json` con tu host/puerto/password de OBS, la carpeta de salida,
el nombre de la escena y (opcional) las hotkeys.

## Cómo correr

```bash
python main.py
```

Se abre una ventana de estado (podés minimizarla a la bandeja del sistema).
Hotkeys por defecto: **F9** iniciar, **F10** detener, **F11** pausar/reanudar.

## Decisiones de librerías (verificadas en julio 2026, no asumidas)

- **`obsws-python`** en vez de `obs-websocket-py`: esta última no tiene
  releases en más de un año y solo habla el protocolo v4. `obsws-python`
  tiene releases activos (1.8.0, julio 2025) y soporta v5 nativamente.
- **`pynput`** en vez de `keyboard`: `keyboard` no tiene un release en PyPI
  desde **marzo de 2020** (abandonada de hecho), aunque muchos tutoriales la
  recomienden por comodidad de API. `pynput` tiene releases activos hasta
  mayo de 2026. Se prioriza mantenimiento vigente sobre comodidad.
- **`pystray`** para el ícono de bandeja: su último release en PyPI es de
  2023, pero es la librería estándar del ecosistema y no hay alternativa
  mejor mantenida hoy para esto; se considera estable/madura, no abandonada.

## Cómo funciona el flujo

1. Al arrancar, se conecta a OBS y valida que la escena configurada exista.
   Si OBS no está abierto, la app igual arranca y reintenta en background
   (cada 5s, hasta 12 intentos por defecto; después espera un reintento
   manual desde el botón "Reconectar OBS").
2. F9 valida que no haya grabación en curso y que haya espacio en disco
   suficiente, cambia a la escena configurada y arranca la grabación.
3. F10 detiene la grabación, espera a que OBS termine de flushear el archivo,
   lo renombra a `minecraft_{fecha}_{hora}_{duración}.mkv` y lo mueve a
   `<carpeta_salida>/YYYY-MM/`.
4. En paralelo (sin bloquear una nueva grabación) se genera un clip resumen
   de los últimos N segundos con `ffmpeg -c copy` (instantáneo, sin
   recodificar) y se agrega una fila a `sessions.csv` con fecha, hora,
   duración, tamaño y nombre de archivo.
5. El estado también se sincroniza si la grabación se para/pausa desde la
   propia UI de OBS (no solo desde las hotkeys de este programa).

### Sobre la precisión del clip resumen

`ffmpeg -sseof -N -i input -c copy output` no recodifica, así que es
prácticamente instantáneo, pero el punto de corte se ajusta al keyframe más
cercano *anterior* al punto pedido — el clip puede empezar unos segundos
antes de lo solicitado. El desvío depende del intervalo de keyframes
configurado en OBS (por defecto 2s, lo cual da un desvío máximo de ~2s). Si
necesitás precisión al frame hay que recodificar, perdiendo la ventaja de
"instantáneo".

## Casos de error cubiertos

- **OBS cerrado / servicio caído**: reconexión automática con backoff fijo;
  tras agotar los reintentos, la app queda esperando un reintento manual sin
  crashear.
- **Password incorrecta**: falla la conexión con un error claro en el log;
  no crashea, reintenta según el mismo mecanismo de arriba.
- **Disco lleno / por debajo del umbral**: no se permite iniciar grabación,
  se loguea el espacio libre real.
- **ffmpeg no encontrado en PATH**: se loguea un warning al arrancar y se
  omite solo la generación del clip (la grabación funciona igual).
- **Hotkey en conflicto**: si el registro de hotkeys globales falla (por
  permisos o conflicto con otra app), se loguea el error sin crashear; el
  resto de la app (botones de la UI) sigue funcionando.
- **Grabación en curso**: ningún error de post-procesamiento, UI o
  reconexión puede detener una grabación activa; los errores se loguean y
  se contienen en su propio hilo.

## Estructura

```
config.py        # dataclasses + validación de config.json
utils.py         # logging, espacio en disco, detección de ffmpeg, nombres
obs_client.py     # conexión obsws-python, reconexión con backoff, eventos
recorder.py       # máquina de estados de grabación
postprocess.py    # clip ffmpeg + log CSV de sesiones (en background)
hotkeys.py        # hotkeys globales con pynput
ui.py             # ventana tkinter + bandeja del sistema
main.py           # arranque y wiring
```
