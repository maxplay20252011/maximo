/**
 * FRAN GLORIOSO — Niveles de calidad gráfica.
 * Especificación Visual Técnica §9 (presupuesto de performance) y §10 (presets).
 *
 * Default recomendado por la spec: si es mobile, arrancar en "baja".
 * "Mejor un juego fluido desde el primer segundo que uno bonito con lag."
 */

export const CALIDAD = {
  baja: {
    sombras: false,
    shadowMapSize: 512,      // irrelevante con sombras apagadas, pero evita undefined
    distanciaRender: 50,
    fogNear: 25, fogFar: 60,
    pixelRatio: 1,
    antialias: false,
    particulas: 0.5,         // multiplicador de cantidad
  },
  media: {
    sombras: true,
    shadowMapSize: 1024,
    distanciaRender: 80,
    fogNear: 45, fogFar: 110,
    pixelRatio: 1.5,
    antialias: true,
    particulas: 1.0,
  },
  alta: {
    sombras: true,
    shadowMapSize: 2048,
    distanciaRender: 120,
    fogNear: 70, fogFar: 180,
    pixelRatio: 2,
    antialias: true,
    particulas: 1.5,
  },
};

export const NIVELES = ['baja', 'media', 'alta'];

/** §9/§10 — presupuesto declarado, usado por el verificador (§11) y el overlay de debug. */
export const PRESUPUESTO = {
  fpsDesktop: 60,
  fpsMobileMin: 30,
  drawCalls: 150,
  triangulos: 150_000,
  texturaMaxMobile: 512,
  texturaMaxDesktop: 1024,
  lucesConSombra: 1,
};

const CLAVE_LS = 'franglorioso.calidad';

/** Detección de mobile: userAgent + ancho de pantalla + puntero grueso. */
export function esMobile() {
  if (typeof navigator === 'undefined') return false;
  const ua = /Android|iPhone|iPad|iPod|Opera Mini|IEMobile|Mobile|Silk/i.test(navigator.userAgent);
  const angosto = window.innerWidth < 900;
  const tactil = window.matchMedia?.('(pointer: coarse)').matches ?? false;
  return ua || (angosto && tactil);
}

/** Nivel inicial: preferencia guardada, si no "baja" en mobile / "alta" en desktop. */
export function nivelInicial() {
  const guardado = localStorage.getItem(CLAVE_LS);
  if (guardado && NIVELES.includes(guardado)) return guardado;
  return esMobile() ? 'baja' : 'alta';
}

export function guardarNivel(nivel) {
  if (NIVELES.includes(nivel)) localStorage.setItem(CLAVE_LS, nivel);
}

export function preset(nivel) {
  return CALIDAD[nivel] ?? CALIDAD.media;
}

/** Límite de textura procedural según plataforma (§9). */
export function maxTextura() {
  return esMobile() ? PRESUPUESTO.texturaMaxMobile : PRESUPUESTO.texturaMaxDesktop;
}
