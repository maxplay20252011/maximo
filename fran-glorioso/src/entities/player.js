/**
 * FRAN GLORIOSO — Fran, el jugador.
 * Especificación Visual Técnica §3 (cápsula azul #3B7DD8) y §7 (VFX).
 *
 * El esquive tiene 0.2 s de invulnerabilidad y su feedback visual es
 * OBLIGATORIO por spec: mientras dure, Fran va tintado de #7DB8FF y deja
 * estela. Si el jugador no puede ver cuándo fue invulnerable, el sistema no
 * existe.
 */

import * as THREE from 'three';
import { loadCharacterModel } from './character.js';
import { VFX } from '../config/palette.js';

export const STATS_FRAN = {
  vidaMax: 100,
  escudoMax: 40,
  staminaMax: 100,

  velCaminar: 4.2,
  velCorrer: 7.0,
  giro: 14,                 // rad/s de alineación hacia la dirección de avance

  rollDuracion: 0.36,
  rollVelocidad: 11.5,
  rollIFrames: 0.20,        // §7
  rollStamina: 25,
  rollCooldown: 0.12,

  ataqueDuracion: 0.42,
  ataqueImpacto: 0.14,      // instante del frame de golpe
  ataqueAlcance: 2.15,
  ataqueArco: Math.PI * 0.6,
  ataqueDanio: 14,
  ataqueStamina: 12,

  staminaRegen: 28,
  staminaDemora: 0.55,
  correrCosto: 12,          // por segundo
};

const _adelante = new THREE.Vector3();
const _derecha = new THREE.Vector3();
const _dir = new THREE.Vector3();
const _punto = new THREE.Vector3();
const _mira = new THREE.Vector3();

export class Jugador {
  /**
   * @param {THREE.Scene} scene
   * @param {import('../vfx/combat-vfx.js').VFXCombate} vfx
   * @param {import('../world/collision.js').MundoColisiones} colisiones
   * @param {{x:number,z:number}} spawn
   */
  constructor(scene, vfx, colisiones, spawn) {
    this.scene = scene;
    this.vfx = vfx;
    this.colisiones = colisiones;

    this.cuerpo = loadCharacterModel('fran');
    this.cuerpo.root.position.set(spawn.x, 0, spawn.z);
    scene.add(this.cuerpo.root);

    this.stats = { ...STATS_FRAN };
    this.vida = this.stats.vidaMax;
    this.escudo = this.stats.escudoMax;
    this.stamina = this.stats.staminaMax;

    this.estado = 'idle';
    this.tEstado = 0;
    this.invulnerable = 0;
    this.cooldownRoll = 0;
    this.sinGastar = 0;
    this.golpeAplicado = false;
    this.dirRoll = new THREE.Vector3(0, 0, 1);
    this.tPolvo = 0;
    this.rareza = 'comun';       // mano limpia; el color de impacto sale de acá

    /** @type {{golpe:Function[], danio:Function[], muerte:Function[]}} */
    this.eventos = { golpe: [], danio: [], muerte: [] };
  }

  get posicion() { return this.cuerpo.root.position; }
  get vivo() { return this.estado !== 'muerto'; }

  on(evento, fn) { this.eventos[evento].push(fn); return this; }
  _emitir(evento, ...args) { for (const fn of this.eventos[evento]) fn(...args); }

  /* ── Ciclo ────────────────────────────────────────────────────────────── */

  update(dt, entrada, camara, enemigos) {
    if (this.estado === 'muerto') return;

    this.tEstado += dt;
    this.invulnerable = Math.max(0, this.invulnerable - dt);
    this.cooldownRoll = Math.max(0, this.cooldownRoll - dt);
    this.sinGastar += dt;

    camara.baseMovimiento(_adelante, _derecha);
    _dir.copy(_adelante).multiplyScalar(entrada.mover.y)
      .addScaledVector(_derecha, entrada.mover.x);
    const quiereMover = _dir.lengthSq() > 0.0001;
    if (quiereMover) _dir.normalize();

    // Esquive: corta cualquier otra acción, es la herramienta defensiva.
    if (entrada.consumirEsquive() && this.puedeRodar()) {
      this.rodar(quiereMover ? _dir : this.frente(_punto));
    }

    if (entrada.consumirAtaque() && this.puedeAtacar()) {
      this.atacar(enemigos, _adelante);
    }

    switch (this.estado) {
      case 'rodando':   this.pasoRoll(dt); break;
      case 'atacando':  this.pasoAtaque(dt, enemigos, quiereMover ? _dir : null); break;
      default:          this.pasoLibre(dt, entrada, _dir, quiereMover); break;
    }

    this.regenerarStamina(dt);
    this.colisiones.resolver(this.posicion, this.cuerpo.radio);
  }

  frente(out) {
    return out.set(0, 0, 1).applyQuaternion(this.cuerpo.root.quaternion);
  }

  /* ── Movimiento libre ─────────────────────────────────────────────────── */

  pasoLibre(dt, entrada, dir, quiereMover) {
    if (this.estado !== 'idle') this.estado = 'idle';
    if (!quiereMover) return;

    const corriendo = entrada.correr && this.stamina > 1;
    const vel = corriendo ? this.stats.velCorrer : this.stats.velCaminar;

    if (corriendo) {
      this.stamina = Math.max(0, this.stamina - this.stats.correrCosto * dt);
      this.sinGastar = 0;
    }

    this.posicion.addScaledVector(dir, vel * dt);
    this.encarar(dir, dt);

    // §7: polvo al correr, color del distrito.
    this.tPolvo -= dt;
    if (corriendo && this.tPolvo <= 0) {
      this.tPolvo = 0.16;
      this.vfx.polvo(this.posicion, VFX.polvoNorte);
    }
  }

  encarar(dir, dt) {
    const objetivo = Math.atan2(dir.x, dir.z);
    const actual = this.cuerpo.root.rotation.y;
    let delta = objetivo - actual;
    while (delta > Math.PI) delta -= Math.PI * 2;
    while (delta < -Math.PI) delta += Math.PI * 2;
    this.cuerpo.root.rotation.y = actual + delta * Math.min(1, this.stats.giro * dt);
  }

  /* ── Esquive ──────────────────────────────────────────────────────────── */

  puedeRodar() {
    return this.estado !== 'rodando'
      && this.cooldownRoll <= 0
      && this.stamina >= this.stats.rollStamina;
  }

  rodar(dir) {
    this.estado = 'rodando';
    this.tEstado = 0;
    this.dirRoll.copy(dir).setY(0).normalize();
    this.stamina -= this.stats.rollStamina;
    this.sinGastar = 0;
    this.invulnerable = this.stats.rollIFrames;
    this.cuerpo.root.rotation.y = Math.atan2(this.dirRoll.x, this.dirRoll.z);

    this.vfx.esquive(this.cuerpo, this.stats.rollIFrames);
    this.vfx.polvo(this.posicion, VFX.polvoNorte);
  }

  pasoRoll(dt) {
    const k = this.tEstado / this.stats.rollDuracion;
    if (k >= 1) {
      this.estado = 'idle';
      this.cooldownRoll = this.stats.rollCooldown;
      this.cuerpo.root.scale.set(1, 1, 1);
      return;
    }
    // Impulso que decae: arranque explosivo, salida controlada.
    const vel = this.stats.rollVelocidad * (1 - k * k);
    this.posicion.addScaledVector(this.dirRoll, vel * dt);

    // Achatarse a mitad del rodado vende el movimiento sin animación real.
    const agacharse = Math.sin(k * Math.PI);
    this.cuerpo.root.scale.set(1 + agacharse * 0.12, 1 - agacharse * 0.3, 1 + agacharse * 0.12);
  }

  /* ── Ataque ───────────────────────────────────────────────────────────── */

  puedeAtacar() {
    return this.estado === 'idle' && this.stamina >= this.stats.ataqueStamina;
  }

  /**
   * @param {Array} enemigos
   * @param {THREE.Vector3} dirCamara  hacia dónde mira la cámara, en el plano XZ
   */
  atacar(enemigos, dirCamara) {
    this.estado = 'atacando';
    this.tEstado = 0;
    this.golpeAplicado = false;
    this.stamina -= this.stats.ataqueStamina;
    this.sinGastar = 0;

    // Fijado suave del objetivo. Sin esto, pegar parado es una lotería: el
    // enemigo orbita alrededor de Fran, que sigue mirando a donde caminó por
    // última vez, y los golpes salen por el costado.
    const objetivo = this.objetivoDeAtaque(enemigos, dirCamara);
    if (objetivo) {
      _mira.subVectors(objetivo.posicion, this.posicion).setY(0);
      this.cuerpo.root.rotation.y = Math.atan2(_mira.x, _mira.z);
    } else if (dirCamara) {
      this.cuerpo.root.rotation.y = Math.atan2(dirCamara.x, dirCamara.z);
    }
  }

  /**
   * El enemigo vivo más cercano dentro del alcance y por delante de la cámara.
   * El margen es chico a propósito: asiste la puntería, no apunta por el jugador.
   */
  objetivoDeAtaque(enemigos, dirCamara) {
    const margen = this.stats.ataqueAlcance + 0.6;
    let mejor = null;
    let mejorDist = Infinity;

    for (const e of enemigos) {
      if (!e.vivo) continue;
      const dx = e.posicion.x - this.posicion.x;
      const dz = e.posicion.z - this.posicion.z;
      const dist = Math.hypot(dx, dz);
      if (dist > margen + e.cuerpo.radio || dist >= mejorDist) continue;

      // Sólo cuenta lo que está por delante de la cámara (±100°).
      if (dirCamara && dist > 0.001) {
        const cos = (dx * dirCamara.x + dz * dirCamara.z) / dist;
        if (cos < Math.cos(THREE.MathUtils.degToRad(100))) continue;
      }
      mejor = e;
      mejorDist = dist;
    }
    return mejor;
  }

  pasoAtaque(dt, enemigos, dirDeseada) {
    if (dirDeseada) this.encarar(dirDeseada, dt * 0.35);   // corrección leve al apuntar

    if (!this.golpeAplicado && this.tEstado >= this.stats.ataqueImpacto) {
      this.golpeAplicado = true;
      this.resolverGolpe(enemigos);
    }

    // Estocada corta hacia adelante mientras dura el golpe.
    const k = this.tEstado / this.stats.ataqueDuracion;
    if (k < 0.5) {
      this.frente(_punto);
      this.posicion.addScaledVector(_punto, 2.6 * dt * (1 - k * 2));
    }

    if (this.tEstado >= this.stats.ataqueDuracion) this.estado = 'idle';
  }

  resolverGolpe(enemigos) {
    this.frente(_punto);
    const { ataqueAlcance, ataqueArco, ataqueDanio } = this.stats;

    for (const e of enemigos) {
      if (!e.vivo) continue;
      const dx = e.posicion.x - this.posicion.x;
      const dz = e.posicion.z - this.posicion.z;
      const dist = Math.hypot(dx, dz);
      if (dist > ataqueAlcance + e.cuerpo.radio) continue;

      // Cono frontal: pegar de espaldas no cuenta.
      const cos = (dx * _punto.x + dz * _punto.z) / (dist || 1);
      if (cos < Math.cos(ataqueArco / 2)) continue;

      const critico = Math.random() < 0.18;
      const danio = Math.round(ataqueDanio * (critico ? 1.9 : 1) * (0.9 + Math.random() * 0.2));
      e.recibirDanio(danio, this.rareza);
      this._emitir('golpe', e, danio, critico);
    }
  }

  /* ── Daño y stamina ───────────────────────────────────────────────────── */

  recibirDanio(cantidad) {
    if (!this.vivo) return false;
    if (this.invulnerable > 0) return false;    // i-frames del esquive

    let restante = cantidad;
    if (this.escudo > 0) {
      const absorbido = Math.min(this.escudo, restante);
      this.escudo -= absorbido;
      restante -= absorbido;
    }
    this.vida = Math.max(0, this.vida - restante);

    this.vfx.flash(this.cuerpo);
    this._emitir('danio', cantidad);

    if (this.vida <= 0) {
      this.estado = 'muerto';
      this.vfx.muerte(this.cuerpo, this.cuerpo.material.color.getHex(), () => {
        this.cuerpo.root.visible = false;
      });
      this._emitir('muerte');
    }
    return true;
  }

  regenerarStamina(dt) {
    if (this.sinGastar < this.stats.staminaDemora) return;
    this.stamina = Math.min(this.stats.staminaMax, this.stamina + this.stats.staminaRegen * dt);
  }
}
