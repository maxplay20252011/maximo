# Totem Aleatorio (Datapack para Minecraft Java 1.20.1)

Datapack vanilla (sin mods) que elige al azar **un bloque del catálogo del
juego** (367 bloques distintos: piedras, minerales, maderas, bloques de
colores, bloques funcionales, etc.). A partir de ese momento, **cada vez
que hagas clic derecho sobre ese tipo de bloque** en el mundo, ocurre:

- La **animación de partículas** del Totem of Undying (`totem_of_undying`).
- El **mismo sonido** que al usar un totem (`item.totem.use`).
- Un **texto grande en el centro de la pantalla** con el **nombre del
  bloque elegido** (igual que el título que aparece al usar un totem),
  y un subtítulo "Bloque Totémico".

## Instalación

1. Copia la carpeta `totem_datapack` dentro de la carpeta `datapacks` de tu
   mundo:
   `<carpeta_del_mundo>/datapacks/totem_datapack`
2. Dentro del mundo, ejecuta:
   ```
   /reload
   ```
   (o crea el mundo con el datapack ya copiado antes de entrar).
3. Verás un mensaje en el chat confirmando que el datapack se cargó y
   cuántos bloques tiene el catálogo.

## Uso

1. Ejecuta:
   ```
   /function totem:choose
   ```
   Esto elige un bloque al azar del catálogo y lo anuncia en el chat
   (ej: "Bloque elegido: Bloque de Esmeralda").
2. (Opcional) Consigue una copia del bloque elegido con:
   ```
   /function totem:give
   ```
3. Coloca ese bloque en el mundo y haz **clic derecho** sobre él. Se
   reproducirá la animación de partículas, el sonido del totem y su
   nombre aparecerá en grande en el centro de la pantalla.
4. Puedes volver a elegir otro bloque en cualquier momento repitiendo el
   paso 1. El efecto solo se activa con el bloque actualmente elegido
   (los demás bloques del mundo no hacen nada especial).

Nota: el efecto se aplica al **tipo de bloque** elegido (no a un bloque
concreto ya colocado), así que también se activará si haces clic derecho
sobre ese mismo tipo de bloque generado de forma natural en el mundo.
Hay un pequeño cooldown de medio segundo por jugador para evitar que el
efecto se dispare varias veces con un solo clic.

## Estructura técnica (por si quieres editarlo)

- `data/totem/functions/load.mcfunction` — se ejecuta al cargar el
  datapack (`#minecraft:load`); crea los scoreboards y avisa por chat.
- `data/totem/functions/choose.mcfunction` — elige un índice
  pseudoaleatorio (basado en el tiempo de partida) dentro del catálogo.
- `data/totem/functions/announce.mcfunction` / `give.mcfunction` /
  `check_all.mcfunction` — listas generadas (una línea por cada uno de
  los 367 bloques) para anunciar, dar o comprobar el bloque elegido.
- `data/totem/advancements/trigger.json` — logro interno (criterio
  `minecraft:item_used_on_block`) que detecta cuándo un jugador
  interactúa con cualquier bloque.
- `data/totem/functions/detect.mcfunction` /
  `mark_found.mcfunction` — hacen un "rayo" desde los ojos del jugador
  para encontrar el bloque exacto al que apunta.
- `data/totem/functions/effect.mcfunction` /
  `effect_tick2.mcfunction` — reproducen las partículas y el sonido del
  totem (en dos ráfagas para que se note más la animación).

Todo el datapack fue generado con un script que arma el catálogo de
bloques por categorías (piedras, minerales, maderas de cada tipo,
bloques de los 16 colores, bloques funcionales, etc.), así que puedes
ampliar la lista fácilmente si quieres añadir más bloques.
