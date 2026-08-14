/**
 * FRAN GLORIOSO — Props del Barrio Norte: árboles, faroles, canteros.
 * Especificación Visual Técnica §3 (vegetación #4A7A3C, aberturas #1A1A1A) y §9.
 *
 * Todo instanciado: los props son el objeto repetido por excelencia y son los
 * primeros que revientan el presupuesto de 150 draw calls si se hacen a mano.
 */

import * as THREE from 'three';
import { NORTE } from '../config/palette.js';
import { materialMate, materialVegetacion } from '../render/materials.js';

const dummy = new THREE.Object3D();

/** Copas low-poly + troncos, en dos InstancedMesh (2 draw calls para ~100 árboles). */
export function crearArboles(scene, arboles) {
  const grupo = new THREE.Group();
  grupo.name = 'arboles';

  const geoTronco = new THREE.CylinderGeometry(0.16, 0.24, 2.4, 6);
  const troncos = new THREE.InstancedMesh(geoTronco, materialMate(NORTE.detalleMadera), arboles.length);
  troncos.castShadow = true;
  troncos.receiveShadow = true;

  // Icosaedro detail 0 = 20 caras: la copa más barata que igual lee como copa.
  const geoCopa = new THREE.IcosahedronGeometry(1.45, 0);
  const copas = new THREE.InstancedMesh(geoCopa, materialVegetacion(NORTE.vegetacion), arboles.length);
  copas.castShadow = true;
  copas.receiveShadow = true;

  arboles.forEach((a, i) => {
    const s = a.escala ?? 1;

    dummy.position.set(a.x, (2.4 * s) / 2, a.z);
    dummy.rotation.set(0, 0, 0);
    dummy.scale.set(s, s, s);
    dummy.updateMatrix();
    troncos.setMatrixAt(i, dummy.matrix);

    dummy.position.set(a.x, 2.4 * s + 0.9 * s, a.z);
    dummy.rotation.set(0, (i * 1.7) % Math.PI, 0);   // rotar cada copa: rompe la repetición
    dummy.scale.set(s, s * 0.85, s);
    dummy.updateMatrix();
    copas.setMatrixAt(i, dummy.matrix);
  });
  troncos.instanceMatrix.needsUpdate = true;
  copas.instanceMatrix.needsUpdate = true;

  grupo.add(troncos, copas);
  scene.add(grupo);
  return grupo;
}

/** Faroles de esquina: poste + luminaria. Sin luz real — §9 permite 1 sola luz con sombra. */
export function crearFaroles(scene, faroles) {
  const grupo = new THREE.Group();
  grupo.name = 'faroles';
  const mat = materialMate(NORTE.aberturas);

  const geoPoste = new THREE.CylinderGeometry(0.08, 0.12, 4.2, 6);
  const postes = new THREE.InstancedMesh(geoPoste, mat, faroles.length);
  postes.castShadow = true;

  const geoLuz = new THREE.BoxGeometry(0.44, 0.3, 0.9);
  const luces = new THREE.InstancedMesh(geoLuz, mat, faroles.length);
  luces.castShadow = true;

  faroles.forEach((f, i) => {
    dummy.scale.set(1, 1, 1);
    dummy.rotation.set(0, 0, 0);
    dummy.position.set(f.x, 2.1, f.z);
    dummy.updateMatrix();
    postes.setMatrixAt(i, dummy.matrix);

    dummy.position.set(f.x, 4.25, f.z);
    dummy.updateMatrix();
    luces.setMatrixAt(i, dummy.matrix);
  });
  postes.instanceMatrix.needsUpdate = true;
  luces.instanceMatrix.needsUpdate = true;

  grupo.add(postes, luces);
  scene.add(grupo);
  return grupo;
}

/**
 * Canteros de la plaza: son la cobertura del combate, así que sí llevan collider.
 * Base de hormigón + relleno verde; los que tienen `arbol` reciben un árbol encima.
 */
export function crearCanteros(scene, canteros, colisiones) {
  const grupo = new THREE.Group();
  grupo.name = 'canteros';

  const geo = new THREE.BoxGeometry(1, 1, 1);
  const bases = new THREE.InstancedMesh(geo, materialMate(NORTE.vereda), canteros.length);
  bases.castShadow = true;
  bases.receiveShadow = true;

  const verdes = new THREE.InstancedMesh(geo, materialVegetacion(NORTE.vegetacion), canteros.length);
  verdes.receiveShadow = true;

  canteros.forEach((c, i) => {
    dummy.rotation.set(0, 0, 0);

    dummy.position.set(c.x, c.h / 2, c.z);
    dummy.scale.set(c.w, c.h, c.d);
    dummy.updateMatrix();
    bases.setMatrixAt(i, dummy.matrix);

    dummy.position.set(c.x, c.h + 0.04, c.z);
    dummy.scale.set(c.w - 0.5, 0.12, c.d - 0.5);
    dummy.updateMatrix();
    verdes.setMatrixAt(i, dummy.matrix);

    colisiones.agregarCaja(c.x, c.z, c.w, c.d);
  });
  bases.instanceMatrix.needsUpdate = true;
  verdes.instanceMatrix.needsUpdate = true;

  grupo.add(bases, verdes);
  scene.add(grupo);

  // crearArboles ya cuelga su propio grupo de la escena.
  const conArbol = canteros.filter((c) => c.arbol).map((c) => ({ x: c.x, z: c.z, escala: 1.15 }));
  if (conArbol.length) crearArboles(scene, conArbol);

  return grupo;
}
