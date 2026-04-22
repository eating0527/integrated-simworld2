import * as THREE from 'three'
import * as SkeletonUtils from 'three/examples/jsm/utils/SkeletonUtils.js'

export interface UAVPropeller {
    node: THREE.Object3D
    direction: 1 | -1
}

export interface UAVSceneInstance {
    scene: THREE.Object3D
    propellers: UAVPropeller[]
}

const PROPELLER_SPIN_SPEED = 48
const PROPELLER_NODE_NAME = /^prop_([1-4])_jnt(?:[._]?\d+)*$/i

function getPropellerIndex(name: string): number | null {
    const match = PROPELLER_NODE_NAME.exec(name)
    return match ? Number(match[1]) : null
}

function ensureStandardMaterial(material: THREE.Material): THREE.Material {
    if (
        material instanceof THREE.MeshStandardMaterial ||
        material instanceof THREE.MeshPhysicalMaterial
    ) {
        return material
    }

    const stdMaterial = new THREE.MeshStandardMaterial()
    stdMaterial.name = material.name
    stdMaterial.transparent = material.transparent
    stdMaterial.opacity = material.opacity
    stdMaterial.side = material.side
    stdMaterial.alphaTest = material.alphaTest

    if ('color' in material && (material as any).color instanceof THREE.Color) {
        stdMaterial.color.copy((material as any).color)
    }
    if ('map' in material) {
        stdMaterial.map = (material as any).map
    }

    return stdMaterial
}

export function prepareUAVScene(scene: THREE.Object3D) {
    scene.traverse((obj: THREE.Object3D) => {
        if (!(obj as THREE.Mesh).isMesh) return

        const mesh = obj as THREE.Mesh
        mesh.castShadow = true
        mesh.receiveShadow = true

        if (Array.isArray(mesh.material)) {
            mesh.material = mesh.material.map((mat) =>
                ensureStandardMaterial(mat)
            )
        } else {
            mesh.material = ensureStandardMaterial(mesh.material)
        }
    })
}

export function collectUAVPropellers(scene: THREE.Object3D): UAVPropeller[] {
    const byIndex = new Map<number, THREE.Object3D>()

    scene.traverse((obj: THREE.Object3D) => {
        const index = getPropellerIndex(obj.name)
        if (index !== null && !byIndex.has(index)) {
            byIndex.set(index, obj)
        }
    })

    return [1, 2, 3, 4].flatMap((index) => {
        const node = byIndex.get(index)
        if (!node) return []
        return [
            {
                node,
                direction: index % 2 === 0 ? -1 : 1,
            } satisfies UAVPropeller,
        ]
    })
}

export function createUAVSceneInstance(scene: THREE.Object3D): UAVSceneInstance {
    const cloned = SkeletonUtils.clone(scene) as THREE.Object3D
    prepareUAVScene(cloned)
    return {
        scene: cloned,
        propellers: collectUAVPropellers(cloned),
    }
}

export function spinPropellers(propellers: UAVPropeller[], delta: number) {
    const step = PROPELLER_SPIN_SPEED * delta
    propellers.forEach(({ node, direction }) => {
        node.rotateY(step * direction)
    })
}

export function createClipWithoutPropellerTracks(
    clip: THREE.AnimationClip
): THREE.AnimationClip {
    const tracks = clip.tracks.filter((track) => {
        const nodeName = track.name.split('.')[0]
        return getPropellerIndex(nodeName) === null
    })
    return new THREE.AnimationClip(clip.name, clip.duration, tracks, clip.blendMode)
}
