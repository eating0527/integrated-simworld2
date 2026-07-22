import { useMemo } from 'react';
import { useGLTF } from '@react-three/drei';
import { NTPU_CONFIG } from '@/config/ntpu.config';
import * as THREE from 'three';

export function NTPUScene() {
  const { scene } = useGLTF(NTPU_CONFIG.scene.modelPath);

  const processedScene = useMemo(() => {
    const cloned = scene.clone(true);
    cloned.traverse((obj: THREE.Object3D) => {
      if ((obj as THREE.Mesh).isMesh) {
        const mesh = obj as THREE.Mesh;
        mesh.castShadow = true;
        mesh.receiveShadow = true;

        // 把 MeshBasicMaterial 升級為 MeshStandardMaterial，才能接受燈光
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
    <group position={NTPU_CONFIG.scene.position}>
      <primitive object={processedScene} scale={NTPU_CONFIG.scene.scale} />
    </group>
  );
}
