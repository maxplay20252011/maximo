/**
 * FRAN GLORIOSO — Iluminación.
 * Especificación Visual Técnica §2. Sin esto todo se ve gris/negro.
 *
 * Presupuesto §9: máximo UNA luz con sombra (la direccional del sol).
 */

import * as THREE from 'three';
import { preset } from '../config/quality.js';

export function crearIluminacion(scene, distrito, nivel) {
  const q = preset(nivel);

  // Luz ambiental: ilumina todo de forma pareja, evita sombras 100% negras.
  const ambient = new THREE.AmbientLight(distrito.ambient.color, distrito.ambient.intensidad);
  scene.add(ambient);

  // Luz direccional: simula el sol, genera las sombras. Única luz con castShadow.
  const sun = new THREE.DirectionalLight(distrito.sol.color, distrito.sol.intensidad);
  sun.position.set(50, 80, 30);
  sun.castShadow = q.sombras;
  sun.shadow.mapSize.width = q.shadowMapSize;
  sun.shadow.mapSize.height = q.shadowMapSize;
  sun.shadow.camera.near = 0.5;
  sun.shadow.camera.far = 200;
  sun.shadow.camera.left = -60;
  sun.shadow.camera.right = 60;
  sun.shadow.camera.top = 60;
  sun.shadow.camera.bottom = -60;
  sun.shadow.bias = -0.0006;         // corta el shadow acne en superficies planas grandes
  sun.shadow.normalBias = 0.02;
  scene.add(sun);
  scene.add(sun.target);

  // Luz de relleno: suaviza el lado opuesto al sol, evita contraste excesivo.
  const fill = new THREE.HemisphereLight(
    distrito.relleno.cielo, distrito.relleno.suelo, distrito.relleno.intensidad,
  );
  scene.add(fill);

  return { ambient, sun, fill };
}

/**
 * Mantiene el volumen de sombra centrado en el jugador.
 * El shadow camera cubre 120×120 m; el mundo mide 150×150, así que seguir al
 * jugador es lo que evita que las sombras se corten en los bordes del barrio.
 */
export function seguirConSol(sun, objetivo) {
  sun.target.position.copy(objetivo);
  sun.position.set(objetivo.x + 50, objetivo.y + 80, objetivo.z + 30);
  sun.target.updateMatrixWorld();
}
