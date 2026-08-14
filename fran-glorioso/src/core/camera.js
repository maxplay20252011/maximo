/**
 * FRAN GLORIOSO — Cámara en tercera persona.
 *
 * `far` sale de §10 (`distanciaRender`) y el fog cierra antes, así el jugador
 * nunca ve aparecer geometría en el borde del frustum.
 */

import * as THREE from 'three';
import { preset } from '../config/quality.js';

const PITCH_MIN = -0.12;
const PITCH_MAX = 0.95;

export class CamaraTerceraPersona {
  constructor(nivel) {
    const q = preset(nivel);
    this.camera = new THREE.PerspectiveCamera(
      55, window.innerWidth / window.innerHeight, 0.1, q.distanciaRender + 50,
    );
    this.yaw = 0;
    this.pitch = 0.42;
    this.distancia = 7.2;
    this.alturaObjetivo = 1.35;
    this.sensibilidad = 0.0045;

    this._deseada = new THREE.Vector3();
    this._foco = new THREE.Vector3();
    this.camera.position.set(0, 6, 10);
  }

  aplicarMirada(delta) {
    this.yaw -= delta.x * this.sensibilidad;
    this.pitch = THREE.MathUtils.clamp(
      this.pitch + delta.y * this.sensibilidad, PITCH_MIN, PITCH_MAX,
    );
  }

  /** Dirección de avance proyectada al plano XZ: el movimiento es relativo a la cámara. */
  baseMovimiento(adelante, derecha) {
    adelante.set(-Math.sin(this.yaw), 0, -Math.cos(this.yaw));
    derecha.set(Math.cos(this.yaw), 0, -Math.sin(this.yaw));
  }

  update(dt, objetivo) {
    this._foco.set(objetivo.x, objetivo.y + this.alturaObjetivo, objetivo.z);

    const horiz = Math.cos(this.pitch) * this.distancia;
    this._deseada.set(
      this._foco.x + Math.sin(this.yaw) * horiz,
      this._foco.y + Math.sin(this.pitch) * this.distancia,
      this._foco.z + Math.cos(this.yaw) * horiz,
    );
    this._deseada.y = Math.max(this._deseada.y, 0.9);   // no meterse bajo el asfalto

    // Suavizado independiente del framerate.
    const k = 1 - Math.exp(-14 * dt);
    this.camera.position.lerp(this._deseada, k);
    this.camera.lookAt(this._foco);
  }
}
