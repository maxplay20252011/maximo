/**
 * FRAN GLORIOSO — Costura de personajes (primitiva ⇄ modelo 3D).
 * Especificación Visual Técnica §3 (cápsulas), §5 (toon + outline), §12 (assets futuros).
 *
 * §12 pide que cambiar de primitiva a modelo sea tocar UNA función. Ésa es
 * `loadCharacterModel()`: devuelve siempre el mismo contrato
 *   { root, mesh, material, outline, radio, alto }
 * con el PIVOT EN LOS PIES (root.position.y = 0 apoya al personaje en el piso),
 * que es exactamente cómo van a venir los .glb.
 */

import * as THREE from 'three';
import { PERSONAJES } from '../config/palette.js';
import { materialPersonaje, agregarOutline } from '../render/toon.js';

/**
 * Cápsula con el fallback que pide §3: THREE.CapsuleGeometry necesita r142+.
 * Si no existe, cae a BoxGeometry(0.7, 1.7, 0.5) como placeholder.
 */
function geometriaCapsula(radio, largo) {
  if (typeof THREE.CapsuleGeometry === 'function') {
    return new THREE.CapsuleGeometry(radio, largo, 4, 12);
  }
  console.warn('[FG] CapsuleGeometry no disponible (Three.js < r142): usando BoxGeometry.');
  return new THREE.BoxGeometry(0.7, 1.7, 0.5);
}

/**
 * Construye el cuerpo visual de un personaje.
 *
 * PARA MIGRAR A .glb: reemplazar SÓLO el bloque marcado abajo por la carga del
 * modelo, escalarlo a `spec.alturaModelo` y aplicar `materialPersonaje` a sus
 * meshes. Nada fuera de esta función asume que el personaje es una cápsula.
 *
 * @param {'fran'|'cadete'|'boxeador'|'aliado'} tipo
 * @param {{color?: number}} [override]
 */
export function loadCharacterModel(tipo, override = {}) {
  const spec = PERSONAJES[tipo];
  if (!spec) throw new Error(`Personaje desconocido: ${tipo}`);

  const color = override.color ?? spec.color;
  const { radio, largo } = spec.capsula;
  const alto = largo + radio * 2;

  const root = new THREE.Group();          // pivot en los pies
  root.name = `personaje:${tipo}`;

  /* ── BLOQUE A REEMPLAZAR POR EL .glb (§12) ─────────────────────────────── */
  const geometria = geometriaCapsula(radio, largo);
  const material = materialPersonaje(color);
  const mesh = new THREE.Mesh(geometria, material);
  mesh.position.y = alto / 2;              // centro de la cápsula sobre los pies
  mesh.castShadow = true;                  // §11: los personajes proyectan sombra
  mesh.receiveShadow = true;
  root.add(mesh);
  /* ── FIN DEL BLOQUE ───────────────────────────────────────────────────── */

  // §5: outline SÓLO en personajes/enemigos/vehículos/ítems, nunca en edificios.
  const outline = agregarOutline(mesh);

  // Marcador de frente: sin animaciones todavía, es lo único que dice hacia
  // dónde mira el personaje. Hereda el color base oscurecido.
  const visor = new THREE.Mesh(
    new THREE.BoxGeometry(radio * 1.1, 0.14, 0.12),
    new THREE.MeshToonMaterial({ color: 0x1A1A1A }),
  );
  visor.position.set(0, alto - radio * 0.9, radio * 0.95);
  visor.castShadow = false;
  root.add(visor);

  return { root, mesh, material, outline, radio, alto, spec };
}

/** Libera la geometría/material propios de un personaje. */
export function disposeCharacter(cuerpo) {
  cuerpo.mesh.geometry.dispose();
  cuerpo.material.dispose();
  cuerpo.root.traverse((o) => {
    if (o.isMesh && o !== cuerpo.mesh && o !== cuerpo.outline) {
      o.geometry.dispose();
      o.material.dispose();
    }
  });
}
