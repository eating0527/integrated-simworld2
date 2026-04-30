import { useMemo, useRef } from 'react';
import { useGLTF } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { NTPU_CONFIG } from '@/config/ntpu.config';
import * as THREE from 'three';
import { createUAVSceneInstance, spinPropellers } from './uavModel';

interface UAVProps {
  position: [number, number, number];
  scale?: number;
}

export function UAV({ position, scale = 10 }: UAVProps) {
  const groupRef = useRef<THREE.Group>(null);
  const { scene } = useGLTF(NTPU_CONFIG.uav.modelPath);

  const uavScene = useMemo(() => createUAVSceneInstance(scene), [scene]);

  useFrame((_state, delta) => {
    spinPropellers(uavScene.propellers, delta);
  });

  return (
    <group ref={groupRef} position={position} scale={scale}>
      <primitive object={uavScene.scene} />
      <pointLight intensity={0.3} distance={50} decay={2} color="#ffffff" position={[0, 2, 0]} />
    </group>
  );
}

useGLTF.preload(NTPU_CONFIG.uav.modelPath);
