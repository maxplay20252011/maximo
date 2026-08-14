/**
 * FRAN GLORIOSO — Renderer y escena.
 * Especificación Visual Técnica §1 (configuración base) y §10 (calidad).
 */

import * as THREE from 'three';
import { preset } from '../config/quality.js';

/**
 * Crea renderer + escena con el cielo y la niebla del distrito.
 * `antialias` sólo puede fijarse al crear el contexto WebGL: se toma del nivel
 * inicial y cambiarlo en caliente exige recargar (la UI de opciones lo avisa).
 */
export function crearRenderer(canvas, distrito, nivel) {
  const q = preset(nivel);

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: q.antialias,
    powerPreference: 'high-performance',
  });

  renderer.setClearColor(distrito.cielo);       // cielo del distrito, NUNCA gris por defecto
  renderer.shadowMap.enabled = q.sombras;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, q.pixelRatio));
  renderer.setSize(window.innerWidth, window.innerHeight, false);
  renderer.info.autoReset = false;              // reseteamos a mano para medir draw calls

  const scene = new THREE.Scene();
  // Niebla atmosférica: mismo color que el cielo, así el borde del mundo se funde.
  scene.fog = new THREE.Fog(distrito.fog.color, q.fogNear, q.fogFar);

  return { renderer, scene };
}

/** Aplica un nivel de calidad a renderer/escena/cámara ya creados (§10). */
export function aplicarCalidad({ renderer, scene, camera, sol }, nivel) {
  const q = preset(nivel);

  renderer.shadowMap.enabled = q.sombras;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, q.pixelRatio));

  if (sol) {
    sol.castShadow = q.sombras;
    if (q.sombras && sol.shadow.mapSize.width !== q.shadowMapSize) {
      sol.shadow.mapSize.set(q.shadowMapSize, q.shadowMapSize);
      sol.shadow.map?.dispose();
      sol.shadow.map = null;                    // fuerza recrear el shadow map
    }
  }

  scene.fog.near = q.fogNear;
  scene.fog.far = q.fogFar;

  camera.far = q.distanciaRender + 50;          // el fog cierra antes que el far plane
  camera.updateProjectionMatrix();

  return q;
}

export function ajustarViewport(renderer, camera) {
  const w = window.innerWidth;
  const h = window.innerHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h, false);
}
