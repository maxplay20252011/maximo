# FRAN GLORIOSO — Vertical Slice · Barrio Norte

Implementación de la **Especificación Visual Técnica** sobre geometría primitiva.
Los colores, materiales, luces, VFX y HUD son los definitivos; las formas no.

Three.js r160, ES modules, sin build step.

---

## Cómo correrlo

Los ES modules no cargan desde `file://`, hace falta un servidor estático:

```bash
cd fran-glorioso
python3 -m http.server 8000
# abrir http://localhost:8000
```

No hay `npm install` ni bundler. Three.js está versionado en `vendor/` (r160,
MIT, licencia incluida), así que arranca sin red.

Lo único que sí sale a internet son las tipografías de §8 (Inter y Roboto
Condensed, desde Google Fonts). Si no cargan, entran los fallbacks que la
propia spec define —`Segoe UI` / `system-ui` y `Arial Narrow`— y el HUD sigue
legible; sólo cambia la letra.

## Controles

| Acción | Teclado / mouse | Táctil |
|---|---|---|
| Mover | `WASD` / flechas | joystick (120 px) |
| Correr | `Shift` | joystick a fondo, o botón `CORRER` |
| Esquivar (i-frames) | `Espacio` | botón `ESQUIVAR` |
| Atacar | click izq. / `J` | botón `ATACAR` |
| Girar cámara | arrastrar | arrastrar en pantalla |
| Opciones | `Escape` / ⚙ | ⚙ |
| Panel de rendimiento | `F` | Opciones → Mostrar FPS |
| **Checklist §11** | `V` | — |

---

## Dónde vive cada sección de la spec

| § | Tema | Archivo |
|---|---|---|
| 1 | Renderer, cielo, fog | `src/core/renderer.js` |
| 2 | Iluminación (5 distritos) | `src/core/lighting.js` · `src/config/districts.js` |
| 3 | Paleta y cápsulas | `src/config/palette.js` |
| 4 | Materiales | `src/render/materials.js` |
| 5 | Cel-shading y outline | `src/render/toon.js` |
| 6 | Texturas procedurales | `src/render/textures.js` |
| 7 | VFX de combate | `src/vfx/combat-vfx.js` · `src/vfx/particles.js` |
| 8 | HUD | `index.html` (CSS) · `src/ui/hud.js` |
| 9 | Presupuesto, instancing, LOD | `src/world/buildings.js` · `src/world/props.js` · `src/main.js` |
| 10 | Niveles de calidad | `src/config/quality.js` · `src/ui/options.js` |
| 11 | Checklist de verificación | `src/dev/verify.js` |
| 12 | Costura para assets futuros | `src/entities/character.js` |

**Ningún color literal se escribe fuera de `palette.js`.** Si un hex no está en
esa tabla, no existe en el juego.

---

## Qué quedó implementado

**Escenario.** Barrio Norte de 150×150 m: 3×3 manzanas de 34 m con calles de
12 m, plaza central como arena de combate, 32 edificios, ~110 árboles, 36
faroles y 8 canteros. Colisión AABB con deslizamiento sobre paredes.

**Combate.** Fran con vida / escudo / stamina; ataque con cono frontal y
fijado suave de objetivo; esquive con 0.2 s de invulnerabilidad. Dos
arquetipos de enemigo con telegrafiado esquivable: **Cadete** (rápido, chico)
y **Boxeador** (lento, ancho, pega el doble). Oleadas crecientes.

**VFX (§7), con las duraciones exactas de la spec.** Impacto (0.15 s, flash
0.1 s, 8-12 partículas del color de rareza), muerte por disolución (0.6 s,
tinte blanco → escala y opacidad a 0 → 20-25 partículas ascendentes; sin
ragdoll y sin sangre), esquive (tinte `#7DB8FF` + estela de 3-4 fantasmas) y
polvo al correr.

**Performance medida** (Chromium, plaza con 3 enemigos):

| | baja | media | alta |
|---|---|---|---|
| Draw calls | 26 | 76 | 76 |
| Triángulos | 16.102 | 26.154 | 26.154 |

Presupuesto de §9: < 150 draw calls y < 150.000 triángulos. Sobra margen para
props, enemigos y armas. Todo lo repetido va en `InstancedMesh`; los 4
edificios que dan a la plaza usan `THREE.LOD` con los cortes de la spec (0 /
40 / 80 m).

**Checklist §11 ejecutable.** La tecla `V` corre las 11 comprobaciones contra
la escena viva (más 3 de presupuesto) y las imprime en pantalla y en consola.
Estado actual: **todo en verde**, con dos avisos esperados (ver abajo).

---

## Decisiones que tomé y conviene que revises

Cinco puntos donde la spec no alcanzaba para decidir sola. Ninguno cambia un
color declarado.

1. **Juntas de la vereda (§6).** El párrafo y la fórmula de repetición
   (`metros / 1.5`) piden una junta cada 1.5 m, pero el snippet recorre
   `i += 128` sobre un canvas de 256 y mete una junta extra al medio, dejando
   el paso real en 0.75 m. Seguí el paso declarado: un tile = una losa.

2. **Altura de Fran.** §3 fija `CapsuleGeometry(0.35, 1.0)` = **1.7 m**; §12
   dice que el modelo debe medir **~1.5 m** porque tiene 12 años. Usé la
   cápsula de §3 tal cual para el placeholder y guardé `alturaModelo: 1.5` en
   `palette.js` para cuando entre el `.glb`. **Decidí vos cuál manda.**

3. **Color de telegrafiado.** §7 no cubre el aviso previo al golpe enemigo.
   En vez de inventar un color reusé el rojo de peligro del HUD (`#D84343`,
   §8), que ya significa "daño" en toda la interfaz.

4. **Materiales de personaje por instancia.** §9 pide compartir materiales,
   pero los VFX de §7 mutan `emissive` y `opacity` por entidad: si el material
   fuera compartido, pegarle a un Cadete haría destellar a todos. El escenario
   sí comparte materiales; los personajes (que son pocos) no.

5. **Outline sin `clone()`.** §5 clona la geometría; la comparto entre cuerpo
   y contorno. El resultado en pantalla es idéntico y ahorra la mitad de la
   memoria de vértices por personaje.

### Aviso del checklist que no corregí a propósito

> ⚠️ El azul de Fran contrasta poco contra el cielo — ×1.66

`#3B7DD8` contra `#87A9C4` da contraste 1.66: son la misma familia de azul.
Contra el asfalto (×2.16) y la vereda (×3.17) está bien. **Lo salva el outline
de §5**: `#1A1A1A` contra el cielo da ×7.05, así que la silueta se recorta
igual y el peor caso del conjunto sube a ×2.16. Además, en tercera persona la
cámara casi siempre encuadra a Fran contra el piso. No toqué el color porque la
spec lo da por definitivo, pero si aparece una escena con Fran recortado contra
el cielo (un salto, una azotea), conviene revisarlo.

El otro aviso —"sombras desactivadas"— es el comportamiento correcto en
calidad **baja**, que es el default en mobile por §10.

---

## Cambiar primitivas por modelos 3D (§12)

Toda la costura está en **una** función: `loadCharacterModel()` en
`src/entities/character.js`. Devuelve siempre el mismo contrato
(`{ root, mesh, material, outline, radio, alto }`) con el **pivot en los pies**,
que es como van a venir los `.glb`. Dentro hay un bloque marcado
`BLOQUE A REEMPLAZAR POR EL .glb`: cargás el modelo ahí, lo escalás a
`spec.alturaModelo` y le aplicás `materialPersonaje`. Nada fuera de esa función
asume que el personaje es una cápsula.

## Qué falta

Sin animaciones (la pose la venden escalas del cuerpo), sin audio, sin armas
más allá de los puños —el sistema de rareza del HUD ya está cableado y
`RAREZA_HEX` ya tiñe las partículas de impacto—, y sin los otros cuatro
distritos: su luz, fog y paleta ya están en `districts.js` y `palette.js`, sólo
falta la geometría.

## Nota de alcance

El prompt del vertical slice no estaba en el repo, así que el diseño de juego
(oleadas, stats, IA, cadencia de combate) lo definí yo para que la spec visual
tuviera dónde aplicarse. Los números de gameplay están todos agrupados en
`STATS_FRAN` (`player.js`) y `TIPOS` (`enemy.js`) para que sean fáciles de
ajustar. Lo visual no lo inventé: sale de la spec, y donde no alcanzaba está
anotado arriba.
