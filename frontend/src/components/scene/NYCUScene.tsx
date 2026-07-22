import { useMemo } from 'react';
import { useGLTF } from '@react-three/drei';
import { NYCU_CONFIG } from '@/config/nycu.config';
import * as THREE from 'three';

export function NYCUScene() {
  const { scene } = useGLTF(NYCU_CONFIG.scene.modelPath);

  const processedScene = useMemo(() => {
    const cloned = scene.clone(true);
    cloned.traverse((obj: THREE.Object3D) => {
      if ((obj as THREE.Mesh).isMesh) {
        const mesh = obj as THREE.Mesh;
        mesh.castShadow = true;
        mesh.receiveShadow = true;

        const upgrade = (mat: THREE.Material) => {
          if (mat instanceof THREE.MeshBasicMaterial) {
            const n = new THREE.MeshStandardMaterial({ color: mat.color, map: mat.map });
            mat.dispose();
            return n;
          }
          return mat;
        };

        if (Array.isArray(mesh.material)) {
          mesh.material = mesh.material.map(upgrade) as THREE.Material[];
        } else {
          mesh.material = upgrade(mesh.material);
        }
      }
    });
    return cloned;
  }, [scene]);

  return (
    <group position={NYCU_CONFIG.scene.position}>
      <primitive object={processedScene} scale={NYCU_CONFIG.scene.scale} />
    </group>
  );
}
