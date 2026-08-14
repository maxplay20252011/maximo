/**
 * FRAN GLORIOSO — Biblioteca de materiales del escenario.
 * Especificación Visual Técnica §4.
 *
 * §9 exige compartir materiales entre objetos del mismo tipo (no crear uno por
 * mesh). Por eso esto es una biblioteca cacheada: pedir dos veces el mismo
 * material devuelve la MISMA instancia.
 *
 * Los personajes NO usan esta biblioteca: van con MeshToonMaterial propio (§5).
 */

import * as THREE from 'three';
import { NORTE, SUR, ESTE } from '../config/palette.js';
import {
  crearTexturaAsfalto, crearTexturaVereda, crearTexturaLadrillo,
  crearTexturaFachada, conRepeticion,
} from './textures.js';

const cache = new Map();

function memo(clave, fabrica) {
  if (!cache.has(clave)) cache.set(clave, fabrica());
  return cache.get(clave);
}

/** Material base para edificios: superficie mate, poco brillo. */
export function materialEdificio(color = NORTE.fachadaPrincipal) {
  return memo(`edificio:${color}`, () => new THREE.MeshStandardMaterial({
    color,
    roughness: 0.85,
    metalness: 0.0,
    flatShading: false,
  }));
}

/** Edificio con revoque texturado (fachadas visibles de cerca). */
export function materialFachadaTexturada(color, ancho, alto) {
  return memo(`fachadaTex:${color}:${ancho}x${alto}`, () => new THREE.MeshStandardMaterial({
    color: 0xFFFFFF,
    map: conRepeticion(crearTexturaFachada(color), ancho, alto, 'fachada'),
    roughness: 0.85,
    metalness: 0.0,
  }));
}

/** Metal / óxido (Barrio Sur, Oeste). */
export function materialMetal(color = SUR.oxido) {
  return memo(`metal:${color}`, () => new THREE.MeshStandardMaterial({
    color,
    roughness: 0.6,
    metalness: 0.7,
  }));
}

/** Vidrio (Barrio Este, Central). */
export function materialVidrio(color = ESTE.vidrio) {
  return memo(`vidrio:${color}`, () => new THREE.MeshStandardMaterial({
    color,
    roughness: 0.1,
    metalness: 0.9,
    transparent: true,
    opacity: 0.7,
  }));
}

/** Neón / LED emisivo (Barrio Este): brilla sin necesitar luz externa. */
export function materialNeon(color = ESTE.azulElectrico) {
  return memo(`neon:${color}`, () => new THREE.MeshStandardMaterial({
    color,
    emissive: color,
    emissiveIntensity: 2.0,
    roughness: 0.4,
  }));
}

/** Asfalto / calle. */
export function materialAsfalto(ancho = 150, largo = 150) {
  return memo(`asfalto:${ancho}x${largo}`, () => new THREE.MeshStandardMaterial({
    color: 0xFFFFFF,
    map: conRepeticion(crearTexturaAsfalto(), ancho, largo, 'asfalto'),
    roughness: 0.95,
    metalness: 0.0,
  }));
}

/** Vereda: hormigón peinado claro. */
export function materialVereda(ancho = 34, largo = 34) {
  return memo(`vereda:${ancho}x${largo}`, () => new THREE.MeshStandardMaterial({
    color: 0xFFFFFF,
    map: conRepeticion(crearTexturaVereda(), ancho, largo, 'vereda'),
    roughness: 0.9,
    metalness: 0.0,
  }));
}

/** Ladrillo visto (Sur / Oeste). */
export function materialLadrillo(color, ancho, alto) {
  return memo(`ladrillo:${color}:${ancho}x${alto}`, () => new THREE.MeshStandardMaterial({
    color: 0xFFFFFF,
    map: conRepeticion(crearTexturaLadrillo(color), ancho, alto, 'ladrillo'),
    roughness: 0.9,
    metalness: 0.0,
  }));
}

/** Superficie mate genérica sin textura (techos, canteros, marcos). */
export function materialMate(color) {
  return memo(`mate:${color}`, () => new THREE.MeshStandardMaterial({
    color,
    roughness: 0.85,
    metalness: 0.0,
  }));
}

/** Vegetación con flatShading: lee mejor como low-poly. */
export function materialVegetacion(color = NORTE.vegetacion) {
  return memo(`veg:${color}`, () => new THREE.MeshStandardMaterial({
    color,
    roughness: 0.9,
    metalness: 0.0,
    flatShading: true,
  }));
}

export function disposeMateriales() {
  for (const m of cache.values()) {
    m.map?.dispose();
    m.dispose();
  }
  cache.clear();
}

/** Para el verificador §11: cuántos materiales únicos vive la escena. */
export function conteoMateriales() { return cache.size; }
