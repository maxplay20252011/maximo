/**
 * FRAN GLORIOSO — Vertical slice, Barrio Norte.
 *
 * Arma la escena, corre el loop y conecta entidades ↔ VFX ↔ HUD.
 * Cada sistema vive en su módulo; acá sólo se cablean.
 *
 * Mapa de la Especificación Visual Técnica sobre el código:
 *   §1  core/renderer.js      §7  vfx/combat-vfx.js + vfx/particles.js
 *   §2  core/lighting.js      §8  index.html (CSS) + ui/hud.js
 *   §3  config/palette.js     §9  world/buildings.js, world/props.js, este loop
 *   §4  render/materials.js   §10 config/quality.js + ui/options.js
 *   §5  render/toon.js        §11 dev/verify.js
 *   §6  render/textures.js    §12 entities/character.js
 */

import * as THREE from 'three';

import {
  instalarCapturaConsola, ejecutarChecklist, imprimirChecklist,
  mostrarPanelChecklist, ocultarPanelChecklist, panelVisible,
} from './dev/verify.js';
import { getDistrito } from './config/districts.js';
import { nivelInicial, preset, PRESUPUESTO, esMobile } from './config/quality.js';
import { crearRenderer, aplicarCalidad, ajustarViewport } from './core/renderer.js';
import { crearIluminacion, seguirConSol } from './core/lighting.js';
import { CamaraTerceraPersona } from './core/camera.js';
import { Entrada } from './core/input.js';
import { construirBarrioNorte } from './world/district-norte.js';
import { SPAWN_JUGADOR, SPAWNS_ENEMIGOS } from './world/layout.js';
import { SistemaParticulas } from './vfx/particles.js';
import { VFXCombate } from './vfx/combat-vfx.js';
import { Jugador } from './entities/player.js';
import { Enemigo } from './entities/enemy.js';
import { HUD } from './ui/hud.js';
import { MenuOpciones } from './ui/options.js';

// Se instala antes de construir el juego: los warnings de Three.js aparecen al
// crear materiales y texturas, no al importar los módulos.
instalarCapturaConsola();

/* ── Composición de oleadas ───────────────────────────────────────────────
 * El slice muestra los dos arquetipos y cómo se combinan: el Cadete presiona,
 * el Boxeador castiga si te quedás quieto.                                   */
const OLEADAS = [
  ['cadete', 'cadete'],
  ['cadete', 'cadete', 'boxeador'],
  ['cadete', 'cadete', 'cadete', 'boxeador', 'boxeador'],
];

class Juego {
  constructor() {
    this.canvas = document.getElementById('escena');
    this.distrito = getDistrito();
    this.nivel = nivelInicial();

    const { renderer, scene } = crearRenderer(this.canvas, this.distrito, this.nivel);
    this.renderer = renderer;
    this.scene = scene;

    this.camaraTP = new CamaraTerceraPersona(this.nivel);
    this.camera = this.camaraTP.camera;

    this.luces = crearIluminacion(scene, this.distrito, this.nivel);
    this.mundo = construirBarrioNorte(scene);

    this.particulas = new SistemaParticulas(scene, 800, preset(this.nivel).particulas);
    this.particulas.ajustarEscala(this.camera, this.renderer.domElement.height);
    this.vfx = new VFXCombate(scene, this.particulas);

    this.hud = new HUD();
    this.hud.setArma('Puños', 'comun', '✊');
    this.entrada = new Entrada(this.canvas);

    this.enemigos = [];
    this.oleada = 0;
    this.tSiguienteOleada = 0;
    this.estado = 'inicio';       // inicio | jugando | fin

    this.reloj = new THREE.Clock();
    this.fps = 0;
    this._frames = 0;
    this._acumFps = 0;
    this.stats = { calls: 0, triangles: 0 };

    this.crearJugador();
    this.cablearUI();
    this.cablearAtajos();

    addEventListener('resize', () => this.alRedimensionar());
    this.renderer.setAnimationLoop(() => this.frame());
  }

  /* ── Entidades ────────────────────────────────────────────────────────── */

  crearJugador() {
    this.jugador = new Jugador(this.scene, this.vfx, this.mundo.colisiones, SPAWN_JUGADOR);

    this.jugador.on('golpe', (enemigo, danio, critico) => {
      this.hud.numeroDanio(enemigo.centro.clone(), this.camera, danio, { critico });
    });

    this.jugador.on('danio', (cantidad) => {
      const p = this.jugador.posicion.clone();
      p.y += this.jugador.cuerpo.alto;
      this.hud.numeroDanio(p, this.camera, cantidad, { recibido: true });
    });

    this.jugador.on('muerte', () => this.terminar(false));
  }

  lanzarOleada() {
    const composicion = OLEADAS[Math.min(this.oleada, OLEADAS.length - 1)];
    // Pasada la última oleada escrita, se repite la más dura con un extra.
    const extra = Math.max(0, this.oleada - OLEADAS.length + 1);

    const tipos = [...composicion];
    for (let i = 0; i < extra; i++) tipos.push(i % 2 === 0 ? 'cadete' : 'boxeador');

    tipos.forEach((tipo, i) => {
      const base = SPAWNS_ENEMIGOS[(i + this.oleada) % SPAWNS_ENEMIGOS.length];
      const vuelta = Math.floor(i / SPAWNS_ENEMIGOS.length);
      const spawn = { x: base.x + vuelta * 2.5, z: base.z - vuelta * 2.5 };
      const e = new Enemigo(this.scene, tipo, spawn, this.vfx, this.mundo.colisiones);
      this.enemigos.push(e);
    });

    this.oleada++;
    this.hud.setEnemigos(this.enemigos.length);
  }

  /* ── UI ───────────────────────────────────────────────────────────────── */

  cablearUI() {
    this.opciones = new MenuOpciones(this.nivel, (nivel) => this.cambiarCalidad(nivel));

    document.getElementById('btn-jugar').addEventListener('click', () => this.empezar());
    document.getElementById('btn-reiniciar').addEventListener('click', () => location.reload());

    const toggleDebug = document.getElementById('toggle-debug');
    toggleDebug.addEventListener('click', () => {
      const visible = document.getElementById('debug').classList.toggle('visible');
      toggleDebug.setAttribute('aria-pressed', String(visible));
    });

    if (esMobile()) document.body.classList.add('tactil');
  }

  cablearAtajos() {
    this.entrada.atajo('KeyF', () => document.getElementById('debug').classList.toggle('visible'));
    this.entrada.atajo('Escape', () => this.opciones.alternar());
    this.entrada.atajo('KeyV', () => {
      if (panelVisible()) { ocultarPanelChecklist(); return; }
      const resultados = ejecutarChecklist(this);
      imprimirChecklist(resultados);
      mostrarPanelChecklist(resultados);
    });
  }

  empezar() {
    document.getElementById('inicio').classList.add('oculto');
    this.estado = 'jugando';
    this.reloj.getDelta();          // descarta el tiempo de la pantalla de inicio
    this.lanzarOleada();
  }

  terminar(victoria) {
    this.estado = 'fin';
    const fin = document.getElementById('fin');
    document.getElementById('fin-titulo').textContent = victoria ? 'Barrio despejado' : 'Te bajaron';
    document.getElementById('fin-texto').textContent = victoria
      ? `Aguantaste ${this.oleada} oleadas en el Barrio Norte.`
      : 'El Barrio Norte no perdona.';
    fin.classList.add('visible');
  }

  cambiarCalidad(nivel) {
    this.nivel = nivel;
    const q = aplicarCalidad({
      renderer: this.renderer, scene: this.scene, camera: this.camera, sol: this.luces.sun,
    }, nivel);
    this.particulas.setMultiplicador(q.particulas);
    this.particulas.ajustarEscala(this.camera, this.renderer.domElement.height);
  }

  alRedimensionar() {
    ajustarViewport(this.renderer, this.camera);
    this.particulas.ajustarEscala(this.camera, this.renderer.domElement.height);
  }

  /* ── Loop ─────────────────────────────────────────────────────────────── */

  frame() {
    // Clamp: si la pestaña estuvo en segundo plano, un dt gigante teletransporta
    // a todo el mundo a través de las paredes.
    const dt = Math.min(this.reloj.getDelta(), 0.05);

    if (this.estado === 'jugando' && !this.opciones.abierto) {
      this.actualizar(dt);
    }

    // Los VFX siguen aunque el jugador haya muerto: la disolución debe verse.
    if (this.estado !== 'inicio') {
      this.vfx.update(dt);
      this.particulas.update(dt);
      this.hud.update(dt, this.camera);
    }

    this.camaraTP.update(dt, this.jugador.posicion);
    seguirConSol(this.luces.sun, this.jugador.posicion);

    this.renderer.render(this.scene, this.camera);

    this.stats.calls = this.renderer.info.render.calls;
    this.stats.triangles = this.renderer.info.render.triangles;
    this.renderer.info.reset();

    this.medirFps();
  }

  actualizar(dt) {
    this.camaraTP.aplicarMirada(this.entrada.consumirMirada());
    this.jugador.update(dt, this.entrada, this.camaraTP, this.enemigos);

    for (const e of this.enemigos) e.update(dt, this.jugador, this.enemigos);

    // Los muertos siguen en la lista hasta que termina su disolución (§7).
    const vivos = this.enemigos.filter((e) => e.vivo);
    if (vivos.length !== this._ultimoConteo) {
      this._ultimoConteo = vivos.length;
      this.hud.setEnemigos(vivos.length);
    }

    if (vivos.length === 0) {
      this.tSiguienteOleada -= dt;
      if (this.tSiguienteOleada <= 0) {
        this.enemigos = [];
        this.tSiguienteOleada = 2.5;
        this.lanzarOleada();
      }
    } else {
      this.tSiguienteOleada = 2.5;
    }

    const { stats } = this.jugador;
    this.hud.setVida(this.jugador.vida, stats.vidaMax);
    this.hud.setEscudo(this.jugador.escudo, stats.escudoMax);
    this.hud.setStamina(this.jugador.stamina, stats.staminaMax);
  }

  /**
   * FPS medidos con reloj de pared, NO con el dt del loop: dt está topeado en
   * 0.05 s, así que por debajo de 20 FPS reales el dt miente y el contador
   * marcaría 20 fijo. Un medidor que no puede reportar "10 FPS" no sirve para
   * verificar el presupuesto de §9.
   */
  medirFps() {
    const ahora = performance.now();
    this._ultimoTick ??= ahora;
    this._frames++;
    this._acumFps += (ahora - this._ultimoTick) / 1000;
    this._ultimoTick = ahora;
    if (this._acumFps < 0.5) return;

    this.fps = Math.round(this._frames / this._acumFps);
    this._frames = 0;
    this._acumFps = 0;

    const panel = document.getElementById('debug');
    if (!panel.classList.contains('visible')) return;

    const objetivo = esMobile() ? PRESUPUESTO.fpsMobileMin : PRESUPUESTO.fpsDesktop;
    const clase = (valor, limite) => (valor <= limite ? 'bien' : 'mal');
    const nf = (n) => n.toLocaleString('es-AR');

    panel.innerHTML =
      `<span class="${this.fps >= objetivo ? 'bien' : 'mal'}">${this.fps} FPS</span>`
      + `  (objetivo ${objetivo})\n`
      + `<span class="${clase(this.stats.calls, PRESUPUESTO.drawCalls)}">`
      + `${this.stats.calls} draw calls</span> / ${PRESUPUESTO.drawCalls}\n`
      + `<span class="${clase(this.stats.triangles, PRESUPUESTO.triangulos)}">`
      + `${nf(this.stats.triangles)} tris</span> / ${nf(PRESUPUESTO.triangulos)}\n`
      + `${this.particulas.vivas} partículas · calidad ${this.nivel}`;
  }
}

const juego = new Juego();
// Handle de depuración: permite inspeccionar la escena desde la consola.
window.FRAN = juego;
