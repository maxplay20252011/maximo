/**
 * FRAN GLORIOSO — Cel-shading.
 * Especificación Visual Técnica §5: low-poly + toon.
 *
 * REGLA DE LA SPEC: outline SÓLO en personajes, enemigos, vehículos e ítems
 * interactuables. Los edificios NO llevan outline — así el jugador distingue
 * de un vistazo qué es interactivo y qué es escenario.
 */

import * as THREE from 'three';
import { OUTLINE_COLOR, OUTLINE_SCALE } from '../config/palette.js';

let gradientMap = null;

/** Gradiente de 3 bandas: sombra / medio / luz. */
export function getGradientMap() {
  if (gradientMap) return gradientMap;

  gradientMap = new THREE.DataTexture(
    new Uint8Array([0, 128, 255]),   // 3 niveles de luz
    3, 1,
    THREE.RedFormat,
  );
  gradientMap.needsUpdate = true;
  gradientMap.minFilter = THREE.NearestFilter;
  gradientMap.magFilter = THREE.NearestFilter;
  gradientMap.generateMipmaps = false;  // 3×1 no tiene mipmaps que generar
  return gradientMap;
}

/**
 * Material toon para un personaje.
 * Cada personaje recibe su PROPIA instancia: los VFX de §7 (flash de impacto,
 * disolución de muerte, tinte de esquive) mutan emissive/opacity por entidad.
 * El material compartido de §9 aplica al escenario, no a los personajes.
 */
export function materialPersonaje(color) {
  return new THREE.MeshToonMaterial({
    color,
    gradientMap: getGradientMap(),
  });
}

let outlineMaterial = null;

/** Material de contorno compartido: es idéntico para todas las entidades. */
export function getOutlineMaterial() {
  if (!outlineMaterial) {
    outlineMaterial = new THREE.MeshBasicMaterial({
      color: OUTLINE_COLOR,
      side: THREE.BackSide,
    });
  }
  return outlineMaterial;
}

/**
 * Contorno por geometría duplicada invertida (la técnica recomendada por la
 * spec por performance en mobile: sin post-proceso, sin segundo render target).
 *
 * Se agrega como hijo de la mesh para que herede pose y escala — clave para la
 * disolución de muerte (§7), donde el contorno debe encogerse con el cuerpo.
 */
export function agregarOutline(mesh) {
  const outline = new THREE.Mesh(mesh.geometry, getOutlineMaterial());
  outline.scale.multiplyScalar(OUTLINE_SCALE);   // 5% más grande
  outline.castShadow = false;                    // el contorno no proyecta sombra
  outline.receiveShadow = false;
  outline.matrixAutoUpdate = false;
  outline.updateMatrix();
  outline.name = 'outline';
  mesh.add(outline);
  return outline;
}
