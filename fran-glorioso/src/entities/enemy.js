/**
 * FRAN GLORIOSO — Enemigos del vertical slice.
 * Especificación Visual Técnica §3 (Cadete rojo, Boxeador naranja) y §7 (VFX).
 *
 * §11 pide que los enemigos se distingan entre sí por color Y por tamaño: el
 * Cadete es más chico y rápido (cápsula 0.32) y el Boxeador más ancho y lento
 * (0.42). Nunca dos enemigos con el mismo par color/silueta.
 *
 * El único color que no figura literal en la spec es el del telegrafiado de
 * ataque: se reusa el rojo de peligro del HUD (#D84343, §8) en vez de inventar
 * uno nuevo.
 */

import * as THREE from 'three';
import { loadCharacterModel } from './character.js';
import { PERSONAJES } from '../config/palette.js';

const TELEGRAFIA = 0xD84343;    // §8 --vida: el rojo de peligro ya establecido

export const TIPOS = {
  cadete: {
    vida: 45,
    velocidad: 4.6,
    danio: 8,
    alcance: 1.75,
    telegrafia: 0.45,
    recuperacion: 0.35,
    cooldown: 1.05,
    aggro: 26,
    separacion: 1.5,
  },
  boxeador: {
    vida: 95,
    velocidad: 3.2,
    danio: 18,
    alcance: 2.05,
    telegrafia: 0.75,
    recuperacion: 0.55,
    cooldown: 1.8,
    aggro: 22,
    separacion: 1.9,
  },
};

const _dir = new THREE.Vector3();
const _sep = new THREE.Vector3();
const _punto = new THREE.Vector3();

export class Enemigo {
  constructor(scene, tipo, spawn, vfx, colisiones) {
    this.tipo = tipo;
    this.scene = scene;
    this.vfx = vfx;
    this.colisiones = colisiones;
    this.stats = { ...TIPOS[tipo] };

    this.cuerpo = loadCharacterModel(tipo);
    this.cuerpo.root.position.set(spawn.x, 0, spawn.z);
    // Red de seguridad: si el punto de spawn quedó dentro de un cantero o una
    // pared, sale ahora y no de un empujón visible en el primer frame.
    colisiones.resolver(this.cuerpo.root.position, this.cuerpo.radio);
    scene.add(this.cuerpo.root);

    this.colorBase = PERSONAJES[tipo].color;
    this.vida = this.stats.vida;
    this.vidaMax = this.stats.vida;
    this.estado = 'patrulla';       // patrulla | persigue | telegrafia | golpea | recupera | muerto
    this.tEstado = 0;
    this.cooldown = 0;
    this.golpeAplicado = false;
    /** @type {{golpe:Function[], muerte:Function[]}} */
    this.eventos = { golpe: [], muerte: [] };
  }

  get posicion() { return this.cuerpo.root.position; }
  get vivo() { return this.estado !== 'muerto'; }
  /** Punto medio del torso: dónde nacen las partículas de impacto (§7). */
  get centro() { return _punto.copy(this.posicion).setY(this.cuerpo.alto * 0.6); }

  on(evento, fn) { this.eventos[evento].push(fn); return this; }
  _emitir(evento, ...args) { for (const fn of this.eventos[evento]) fn(...args); }

  update(dt, jugador, otros) {
    if (!this.vivo) return;

    this.tEstado += dt;
    this.cooldown = Math.max(0, this.cooldown - dt);

    if (!jugador.vivo) {
      this.estado = 'patrulla';
      return;
    }

    _dir.subVectors(jugador.posicion, this.posicion).setY(0);
    const dist = _dir.length();
    if (dist > 0.0001) _dir.divideScalar(dist);

    switch (this.estado) {
      case 'patrulla':
        if (dist < this.stats.aggro && !this.colisiones.hayObstaculo(this.posicion, jugador.posicion)) {
          this.estado = 'persigue';
          this.tEstado = 0;
        }
        break;

      case 'persigue': {
        this.encarar(_dir, dt);
        const alcance = this.stats.alcance + jugador.cuerpo.radio;
        if (dist <= alcance && this.cooldown <= 0) {
          this.estado = 'telegrafia';
          this.tEstado = 0;
          this.tintar(true);
        } else {
          this.posicion.addScaledVector(_dir, this.stats.velocidad * dt);
          this.separarDe(otros, dt);
        }
        break;
      }

      case 'telegrafia':
        this.encarar(_dir, dt * 0.4);            // ya casi no corrige: se puede esquivar
        if (this.tEstado >= this.stats.telegrafia) {
          this.estado = 'golpea';
          this.tEstado = 0;
          this.golpeAplicado = false;
          this.tintar(false);
        }
        break;

      case 'golpea':
        if (!this.golpeAplicado) {
          this.golpeAplicado = true;
          this.resolverGolpe(jugador, dist);
        }
        if (this.tEstado >= 0.12) {
          this.estado = 'recupera';
          this.tEstado = 0;
        }
        break;

      case 'recupera':
        if (this.tEstado >= this.stats.recuperacion) {
          this.estado = 'persigue';
          this.tEstado = 0;
          this.cooldown = this.stats.cooldown;
        }
        break;
    }

    this.colisiones.resolver(this.posicion, this.cuerpo.radio);
    this.separarDelJugador(jugador);
    this.animarPose();
  }

  /**
   * Cuerpos que no se atraviesan.
   * Sin esto el enemigo termina DENTRO de Fran, y ahí el cono frontal del
   * ataque deja de dar: el objetivo queda a los costados o a la espalda y los
   * golpes pasan de largo aunque el jugador lo tenga pegado encima.
   *
   * El reparto 70/30 deja que Fran empuje enemigos (se siente bien) sin que un
   * Boxeador lo pueda arrastrar por la plaza.
   */
  separarDelJugador(jugador) {
    const minima = this.cuerpo.radio + jugador.cuerpo.radio;
    _sep.subVectors(this.posicion, jugador.posicion).setY(0);
    let d = _sep.length();

    if (d < 0.0001) {                       // superpuestos exactos: desempatar
      _sep.set(Math.cos(this.tEstado * 7), 0, Math.sin(this.tEstado * 7));
      d = 0.0001;
    }
    if (d >= minima) return;

    _sep.divideScalar(d);
    const empuje = minima - d;
    this.posicion.addScaledVector(_sep, empuje * 0.7);

    if (jugador.vivo) {
      jugador.posicion.addScaledVector(_sep, -empuje * 0.3);
      // El empujón puede meter a Fran en una pared: se corrige en el acto.
      this.colisiones.resolver(jugador.posicion, jugador.cuerpo.radio);
    }
  }

  /** Sin animaciones todavía: la pose la vende la escala del cuerpo. */
  animarPose() {
    const r = this.cuerpo.root;
    if (this.estado === 'telegrafia') {
      const k = Math.min(1, this.tEstado / this.stats.telegrafia);
      r.scale.set(1 + k * 0.1, 1 - k * 0.12, 1 + k * 0.1);   // se agacha antes de pegar
    } else if (this.estado === 'golpea') {
      r.scale.set(0.94, 1.1, 0.94);                          // se estira al golpear
    } else {
      r.scale.lerp(_sep.set(1, 1, 1), 0.25);
    }
  }

  encarar(dir, dt) {
    const objetivo = Math.atan2(dir.x, dir.z);
    const actual = this.cuerpo.root.rotation.y;
    let delta = objetivo - actual;
    while (delta > Math.PI) delta -= Math.PI * 2;
    while (delta < -Math.PI) delta += Math.PI * 2;
    this.cuerpo.root.rotation.y = actual + delta * Math.min(1, 9 * dt);
  }

  /** Empuje suave entre enemigos: sin esto se apilan en un solo punto. */
  separarDe(otros, dt) {
    for (const o of otros) {
      if (o === this || !o.vivo) continue;
      _sep.subVectors(this.posicion, o.posicion).setY(0);
      const d = _sep.length();
      const minimo = this.stats.separacion + o.stats.separacion * 0.5;
      if (d > 0.001 && d < minimo) {
        this.posicion.addScaledVector(_sep.divideScalar(d), (minimo - d) * 4 * dt);
      }
    }
  }

  resolverGolpe(jugador, dist) {
    const alcance = this.stats.alcance + jugador.cuerpo.radio + 0.35;
    if (dist > alcance) return;                  // el jugador salió del rango a tiempo
    jugador.recibirDanio(this.stats.danio);
  }

  /** Tinte de telegrafiado: mismo mecanismo que el flash de §7, otro color. */
  tintar(activo) {
    const mat = this.cuerpo.material;
    mat.userData.tintado = activo;
    if (activo) {
      mat.emissive.setHex(TELEGRAFIA);
      mat.emissiveIntensity = 0.55;
    } else if (!mat.userData.flasheando) {
      mat.emissiveIntensity = 0;
      mat.emissive.setHex(0x000000);
    }
  }

  /**
   * @param {number} cantidad
   * @param {string|null} rareza  rareza del arma, define el color de las partículas (§7)
   */
  recibirDanio(cantidad, rareza = null) {
    if (!this.vivo) return;

    this.vida -= cantidad;
    this.vfx.impacto(this.centro, this.cuerpo, rareza);

    if (this.vida <= 0) {
      this.vida = 0;
      this.morir();
    } else if (this.estado === 'patrulla') {
      this.estado = 'persigue';                  // pegarle de sorpresa igual lo activa
      this.tEstado = 0;
    }
  }

  morir() {
    this.estado = 'muerto';
    this.tintar(false);
    this._emitir('muerte', this);
    // §7: disolución de 0.6 s, no ragdoll.
    this.vfx.muerte(this.cuerpo, this.colorBase, () => {
      this.scene.remove(this.cuerpo.root);
    });
  }
}
