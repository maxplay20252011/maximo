/**
 * FRAN GLORIOSO — Checklist de verificación visual.
 * Especificación Visual Técnica §11, ejecutable.
 *
 * La spec dice "antes de dar por terminado cualquier paso, verificá". Un
 * checklist en papel se saltea; uno que corre en el juego (tecla V) no. Cada
 * ítem del §11 tiene acá su comprobación real contra la escena viva.
 *
 * Devuelve tres estados: ok / aviso / falla. El aviso existe porque algunos
 * ítems son de grado (contraste, presupuesto) y no binarios.
 */

import * as THREE from 'three';
import { PERSONAJES, NORTE, OUTLINE_COLOR } from '../config/palette.js';
import { PRESUPUESTO, esMobile } from '../config/quality.js';

/* ── Captura de consola: hay que instalarla ANTES de crear nada ─────────── */

const capturados = { warn: [], error: [] };

export function instalarCapturaConsola() {
  for (const nivel of ['warn', 'error']) {
    const original = console[nivel].bind(console);
    console[nivel] = (...args) => {
      capturados[nivel].push(args.map(String).join(' '));
      original(...args);
    };
  }
  addEventListener('error', (e) => {
    if (e.message) capturados.error.push(e.message);
  });
}

/* ── Utilidades de color ────────────────────────────────────────────────── */

function luminancia(hex) {
  const c = new THREE.Color(hex);          // ColorManagement ya lo deja en lineal
  return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
}

/** Contraste WCAG entre dos colores (1 = idénticos, 21 = negro contra blanco). */
function contraste(a, b) {
  const la = luminancia(a), lb = luminancia(b);
  const [alto, bajo] = la > lb ? [la, lb] : [lb, la];
  return (alto + 0.05) / (bajo + 0.05);
}

function matiz(hex) {
  const c = new THREE.Color(hex);
  const hsl = { h: 0, s: 0, l: 0 };
  c.getHSL(hsl);
  return hsl.h * 360;
}

function distanciaMatiz(a, b) {
  const d = Math.abs(matiz(a) - matiz(b)) % 360;
  return d > 180 ? 360 - d : d;
}

/* ── Checklist ──────────────────────────────────────────────────────────── */

const OK = (texto, detalle) => ({ estado: 'ok', texto, detalle });
const AVISO = (texto, detalle) => ({ estado: 'aviso', texto, detalle });
const FALLA = (texto, detalle) => ({ estado: 'falla', texto, detalle });

/**
 * @param {Object} ctx
 * @param {THREE.WebGLRenderer} ctx.renderer
 * @param {THREE.Scene} ctx.scene
 * @param {THREE.Camera} ctx.camera
 * @param {Object} ctx.jugador
 * @param {Array} ctx.enemigos
 */
export function ejecutarChecklist(ctx) {
  const { renderer, scene, jugador, enemigos } = ctx;
  const r = [];

  /* 1 — El cielo tiene color (celeste), no es gris ni negro */
  {
    const cielo = new THREE.Color();
    renderer.getClearColor(cielo);
    const hsl = { h: 0, s: 0, l: 0 };
    cielo.getHSL(hsl);
    r.push(hsl.s > 0.08 && hsl.l > 0.1
      ? OK('Cielo con color', `#${cielo.getHexString()} · sat ${(hsl.s * 100) | 0}%`)
      : FALLA('Cielo gris o negro', `#${cielo.getHexString()} · sat ${(hsl.s * 100) | 0}%`));
  }

  /* 2 — Al menos 2 luces en la escena (ambient + directional) */
  {
    const luces = [];
    scene.traverse((o) => { if (o.isLight) luces.push(o.type); });
    const tieneAmbiental = luces.some((t) => t.includes('Ambient') || t.includes('Hemisphere'));
    const tieneDireccional = luces.some((t) => t.includes('Directional'));
    r.push(luces.length >= 2 && tieneAmbiental && tieneDireccional
      ? OK(`${luces.length} luces en escena`, luces.join(', '))
      : FALLA('Faltan luces', luces.join(', ') || 'ninguna'));
  }

  /* 3 — Los objetos proyectan sombra sobre el suelo */
  {
    let emisores = 0;
    scene.traverse((o) => { if ((o.isMesh || o.isInstancedMesh) && o.castShadow) emisores++; });
    const activas = renderer.shadowMap.enabled;
    if (!activas) {
      r.push(AVISO('Sombras desactivadas', 'esperado en calidad "baja" (§10)'));
    } else {
      r.push(emisores > 0
        ? OK(`${emisores} objetos proyectan sombra`)
        : FALLA('Ningún objeto tiene castShadow'));
    }
  }

  /* 4 — El suelo recibe sombra */
  {
    const suelo = scene.getObjectByName('calzada');
    r.push(suelo?.receiveShadow
      ? OK('El suelo recibe sombra')
      : FALLA('La calzada no tiene receiveShadow'));
  }

  /* 5 — Los personajes tienen castShadow */
  {
    const cuerpos = [jugador, ...enemigos].filter(Boolean);
    const sinSombra = cuerpos.filter((e) => !e.cuerpo?.mesh?.castShadow);
    r.push(sinSombra.length === 0
      ? OK(`${cuerpos.length} personajes proyectan sombra`)
      : FALLA(`${sinSombra.length} personajes sin castShadow`));
  }

  /* 6 — Sin warnings de textura faltante en la consola */
  {
    const sospechosos = capturados.warn.filter((m) => /textur|texture|map|material/i.test(m));
    r.push(sospechosos.length === 0
      ? OK('Sin warnings de textura')
      : FALLA(`${sospechosos.length} warnings de textura`, sospechosos[0]?.slice(0, 90)));
  }

  /* 7 — Sin errores 404 de .glb/.gltf (usamos primitivas: no debería haber ninguno) */
  {
    const recursos = performance.getEntriesByType?.('resource') ?? [];
    const modelos = recursos.filter((e) => /\.(glb|gltf)(\?|$)/i.test(e.name));
    r.push(modelos.length === 0
      ? OK('Cero pedidos de modelos 3D', 'el slice corre sobre primitivas (§12)')
      : AVISO(`${modelos.length} pedidos de .glb/.gltf`, modelos[0].name));
  }

  /* 8 — El personaje es distinguible del fondo por color.
   *     Se mide contra los tres fondos reales del Barrio Norte, y se cuenta el
   *     outline: #1A1A1A al 5% (§5) es justamente lo que separa la silueta
   *     cuando el cuerpo y el fondo comparten familia de color.               */
  {
    const fran = PERSONAJES.fran.color;
    const fondos = { cielo: 0x87A9C4, asfalto: NORTE.calle, vereda: NORTE.vereda };

    let peorCuerpo = Infinity, cual = '';
    let peorSilueta = Infinity;
    for (const [nombre, hex] of Object.entries(fondos)) {
      const c = contraste(fran, hex);
      if (c < peorCuerpo) { peorCuerpo = c; cual = nombre; }
      // La silueta se lee si el cuerpo O el contorno separan del fondo.
      peorSilueta = Math.min(peorSilueta, Math.max(c, contraste(OUTLINE_COLOR, hex)));
    }

    const detalle = `cuerpo ×${peorCuerpo.toFixed(2)} contra ${cual}`
      + ` · con outline ×${peorSilueta.toFixed(2)}`;
    r.push(peorSilueta >= 1.8
      ? OK('Fran se distingue del fondo', detalle)
      : FALLA('Fran se confunde con el fondo', detalle));

    if (peorSilueta >= 1.8 && peorCuerpo < 1.8) {
      r.push(AVISO('El azul de Fran contrasta poco contra el cielo',
        `×${peorCuerpo.toFixed(2)} — lo resuelve el outline de §5, no el color`));
    }
  }

  /* 9 — Los enemigos son distinguibles entre sí por color y tamaño.
   *     Se evalúa la TABLA de §3 completa, no sólo los que hay en pantalla:
   *     un par confundible tiene que saltar aunque esa oleada no lo spawnee.  */
  {
    const tipos = Object.keys(PERSONAJES);
    const problemas = [];
    for (let i = 0; i < tipos.length; i++) {
      for (let j = i + 1; j < tipos.length; j++) {
        const a = PERSONAJES[tipos[i]], b = PERSONAJES[tipos[j]];
        const dh = distanciaMatiz(a.color, b.color);
        const dr = Math.abs(a.capsula.radio - b.capsula.radio);
        if (dh < 25 && dr < 0.05) problemas.push(`${tipos[i]}/${tipos[j]}`);
      }
    }
    const enEscena = [...new Set(enemigos.map((e) => e.tipo))];
    r.push(problemas.length === 0
      ? OK(`${tipos.length} personajes diferenciados`,
        `en escena ahora: ${enEscena.join(', ') || 'ninguno'}`)
      : FALLA('Personajes confundibles', problemas.join(', ')));
  }

  /* 10 — El HUD se lee sobre cualquier fondo */
  {
    const muestra = document.querySelector('#hud .txt');
    const barra = document.querySelector('#vida');
    const sombra = muestra ? getComputedStyle(muestra).textShadow : 'none';
    const fondo = barra ? getComputedStyle(barra).backgroundColor : 'transparent';
    const tieneSombra = sombra && sombra !== 'none';
    const tieneFondo = /rgba?\(/.test(fondo) && !/, *0\)$/.test(fondo);
    r.push(tieneSombra && tieneFondo
      ? OK('HUD con sombra de texto y fondo propio')
      : FALLA('HUD sin contraste garantizado',
        `sombra: ${tieneSombra} · fondo: ${fondo}`));
  }

  /* 11 — En mobile, los botones táctiles no se superponen con el HUD */
  {
    if (!document.body.classList.contains('tactil')) {
      r.push(OK('Sin controles táctiles activos', 'no aplica en este dispositivo'));
    } else {
      // Se comparan TODOS los elementos pulsables contra TODOS los informativos:
      // el engranaje también es un botón, y en pantallas angostas es el que se
      // come la barra de vida.
      const pulsables = ['joystick', 'botones', 'engranaje'];
      const informativos = ['hud', 'objetivo'];
      const choques = [];
      for (const idA of pulsables) {
        const a = document.getElementById(idA);
        if (!a || a.offsetParent === null) continue;
        for (const idB of informativos) {
          const b = document.getElementById(idB);
          if (b && solapan(a.getBoundingClientRect(), b.getBoundingClientRect())) {
            choques.push(`${idA}↔${idB}`);
          }
        }
      }
      r.push(choques.length === 0
        ? OK('Controles táctiles sin solapar el HUD')
        : FALLA(`${choques.length} solapamientos`, choques.join(', ')));
    }
  }

  /* Extra — Presupuesto de performance (§9).
   * Se lee el snapshot que el loop guarda tras cada render: `renderer.info`
   * ya viene reseteado para el frame siguiente y devolvería 0.              */
  {
    const { calls, triangles } = ctx.stats ?? renderer.info.render;
    const dc = calls <= PRESUPUESTO.drawCalls;
    const tri = triangles <= PRESUPUESTO.triangulos;
    const detalle = `${calls} draw calls · ${triangles.toLocaleString('es-AR')} triángulos`;
    r.push(dc && tri ? OK('Dentro del presupuesto de §9', detalle)
      : AVISO('Presupuesto de §9 excedido', detalle));
  }

  /* Extra — Una sola luz con sombra (§9) */
  {
    let conSombra = 0;
    scene.traverse((o) => { if (o.isLight && o.castShadow) conSombra++; });
    r.push(conSombra <= PRESUPUESTO.lucesConSombra
      ? OK(`${conSombra} luz con sombra`, `máximo ${PRESUPUESTO.lucesConSombra} (§9)`)
      : FALLA(`${conSombra} luces con sombra`, `el máximo es ${PRESUPUESTO.lucesConSombra}`));
  }

  /* Extra — Resolución de textura dentro del límite de plataforma (§9) */
  {
    const limite = esMobile() ? PRESUPUESTO.texturaMaxMobile : PRESUPUESTO.texturaMaxDesktop;
    let maxLado = 0;
    scene.traverse((o) => {
      const mats = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
      for (const m of mats) {
        const img = m.map?.image;
        if (img) maxLado = Math.max(maxLado, img.width, img.height);
      }
    });
    r.push(maxLado <= limite
      ? OK(`Texturas ≤ ${limite}px`, maxLado ? `mayor: ${maxLado}px` : 'sin texturas')
      : FALLA(`Textura de ${maxLado}px`, `el límite acá es ${limite}px`));
  }

  return r;
}

function solapan(a, b) {
  return !(a.right < b.left || a.left > b.right || a.bottom < b.top || a.top > b.bottom);
}

/** Imprime el checklist en consola con el formato de la spec. */
export function imprimirChecklist(resultados) {
  const icono = { ok: '✅', aviso: '⚠️', falla: '❌' };
  const fallas = resultados.filter((x) => x.estado === 'falla').length;
  const avisos = resultados.filter((x) => x.estado === 'aviso').length;

  console.group(`§11 Checklist de verificación visual — ${resultados.length - fallas - avisos}/${resultados.length} OK`);
  for (const x of resultados) {
    console.log(`${icono[x.estado]} ${x.texto}${x.detalle ? `  — ${x.detalle}` : ''}`);
  }
  console.groupEnd();
  return { fallas, avisos };
}

/**
 * Panel en pantalla con el resultado del checklist (tecla V).
 * Lleva estilos inline a propósito: es una herramienta de desarrollo y no debe
 * ensuciar el CSS del HUD (§8), que es contrato de diseño.
 */
export function mostrarPanelChecklist(resultados) {
  document.getElementById('fg-checklist')?.remove();

  const icono = { ok: '✅', aviso: '⚠️', falla: '❌' };
  const panel = document.createElement('div');
  panel.id = 'fg-checklist';
  panel.style.cssText = `
    position:fixed;inset:auto 16px 16px auto;z-index:60;max-width:min(440px,92vw);
    max-height:70vh;overflow:auto;background:rgba(18,22,28,.94);color:#fff;
    border:2px solid rgba(255,255,255,.3);border-radius:10px;padding:14px 16px;
    font:12px/1.6 'Inter','Segoe UI',system-ui,sans-serif;`;

  const fallas = resultados.filter((x) => x.estado === 'falla').length;
  const avisos = resultados.filter((x) => x.estado === 'aviso').length;

  const titulo = document.createElement('div');
  titulo.style.cssText = 'font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin-bottom:10px;font-size:11px;';
  titulo.textContent = `§11 Checklist — ${resultados.length - fallas - avisos} ok · ${avisos} avisos · ${fallas} fallas`;
  panel.appendChild(titulo);

  for (const x of resultados) {
    const fila = document.createElement('div');
    fila.style.cssText = 'margin-bottom:5px;display:flex;gap:7px;align-items:flex-start;';
    fila.innerHTML = `<span>${icono[x.estado]}</span><span>${x.texto}`
      + (x.detalle ? `<span style="opacity:.55"> — ${x.detalle}</span>` : '')
      + '</span>';
    panel.appendChild(fila);
  }

  const pie = document.createElement('div');
  pie.style.cssText = 'margin-top:10px;opacity:.5;font-size:11px;';
  pie.textContent = 'V para cerrar';
  panel.appendChild(pie);

  document.body.appendChild(panel);
}

export function ocultarPanelChecklist() {
  document.getElementById('fg-checklist')?.remove();
}

export function panelVisible() {
  return !!document.getElementById('fg-checklist');
}
