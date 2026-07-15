import { useState, useEffect, useCallback } from 'react';
import { parseSceneFrame, type SceneFrame } from '../types/sceneFrame';

const API = import.meta.env.VITE_API_URL || '';

type SceneTaskStatus = 'idle' | 'loading' | 'polling' | 'error';
export type GeneratedSceneStatus = 'queued' | 'running' | 'completed' | 'failed';

interface SceneTaskLocation {
  lat?: number;
  lon?: number;
  place_name?: string | null;
}

interface SceneTask {
  id?: string;
  sceneKey?: string;
  sceneName?: string;
  displayName?: string;
  status?: string;
  stage?: string;
  modelUrl?: string;
  createdAt?: string;
  location?: SceneTaskLocation | null;
  frame?: unknown;
}

export interface GeneratedSceneOption {
  taskId: string;
  sceneKey: string;
  label: string;
  modelPath: string;
  createdAt: string;
  status: GeneratedSceneStatus;
  stage?: string;
  ready: boolean;
  location?: {
    lat?: number;
    lon?: number;
    placeName?: string | null;
  };
  frame?: SceneFrame;
}

interface GeneratedScenesState {
  scenes: GeneratedSceneOption[];
  status: SceneTaskStatus;
  pollingTaskId: string | null;
  error: string | null;
}

export interface SceneMutationResult {
  ok: boolean;
  status: number;
  error?: string;
}

function getSceneLabel(task: SceneTask, taskId: string, sceneKey: string): string {
  return (
    task.displayName?.trim() ||
    task.location?.place_name?.trim() ||
    task.sceneName?.trim() ||
    sceneKey ||
    taskId
  );
}

function normalizeTask(task: SceneTask, ready = false): GeneratedSceneOption | null {
  const taskId = task.id?.trim();
  const sceneKey = task.sceneKey?.trim();
  const modelPath = task.modelUrl?.trim();
  const status = task.status ?? 'completed';

  if (!['queued', 'running', 'completed', 'failed'].includes(status) || !taskId || !sceneKey || !modelPath) {
    return null;
  }

  return {
    taskId,
    sceneKey,
    label: getSceneLabel(task, taskId, sceneKey),
    modelPath,
    createdAt: task.createdAt ?? '',
    status: status as GeneratedSceneStatus,
    stage: task.stage,
    ready,
    location: task.location
      ? {
          lat: task.location.lat,
          lon: task.location.lon,
          placeName: task.location.place_name ?? null,
        }
      : undefined,
    frame: parseSceneFrame(task.frame) ?? undefined,
  };
}

export function isSceneBuilding(scene: GeneratedSceneOption): boolean {
  return !scene.ready && scene.status !== 'failed';
}

export function getBuildLabel(scene: GeneratedSceneOption): string | null {
  if (scene.ready) return null;
  if (scene.status === 'queued') return '等待建立';
  if (scene.status === 'completed') return '準備場景中';
  if (scene.status === 'failed') return '建立失敗';
  return scene.stage === 'running_blender_generation' ? '正在建立 3D 場景' : '場景建立中';
}

async function fetchGeneratedSceneIndex(rebuildIndex: boolean): Promise<GeneratedSceneOption[]> {
  const res = await fetch(`${API}/api/generated-scenes${rebuildIndex ? '/refresh' : ''}`, {
    method: rebuildIndex ? 'POST' : 'GET',
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch generated scenes: ${res.statusText}`);
  }

  const payload = await res.json();
  const tasks = Array.isArray(payload?.scenes) ? payload.scenes as SceneTask[] : [];
  const scenes = tasks
    .map(task => normalizeTask(task, true))
    .filter((scene): scene is GeneratedSceneOption => scene?.status === 'completed');
  const loaded = await Promise.all(scenes.map(async (scene) => {
    if (scene.frame) return scene;
    try {
      const frameRes = await fetch(`${API}/generated-scenes/${scene.sceneKey}/scene_metadata.json`);
      if (!frameRes.ok) return scene;
      return { ...scene, frame: parseSceneFrame(await frameRes.json()) ?? undefined };
    } catch (_) {
      return scene;
    }
  }));
  return loaded.filter((scene): scene is GeneratedSceneOption & { frame: SceneFrame } => Boolean(scene.frame));
}

async function fetchSceneTasks(): Promise<SceneTask[]> {
  const res = await fetch(`${API}/api/scene-tasks`, { method: 'GET' });

  if (!res.ok) {
    throw new Error(`Failed to fetch scene tasks: ${res.statusText}`);
  }

  const payload = await res.json();
  return Array.isArray(payload?.tasks) ? payload.tasks as SceneTask[] : [];
}

export function useGeneratedScenes() {
  const [state, setState] = useState<GeneratedScenesState>({
    scenes: [],
    status: 'idle',
    pollingTaskId: null,
    error: null,
  });

  const refreshScenes = useCallback(async (options?: { rebuildIndex?: boolean }) => {
    setState(prev => ({
      ...prev,
      status: prev.pollingTaskId ? 'polling' : 'loading',
      error: null,
    }));

    try {
      const tasks = await fetchSceneTasks();
      const watchedTask = tasks.find(task => task.id === state.pollingTaskId);
      const scenes = await fetchGeneratedSceneIndex(
        Boolean(options?.rebuildIndex || watchedTask?.status === 'completed'),
      );
      const taskScenes = tasks
        .map(task => normalizeTask(task))
        .filter((scene): scene is GeneratedSceneOption => Boolean(scene));
      const completedIds = new Set(scenes.map(scene => scene.taskId));
      const visibleTaskScenes = taskScenes.filter(scene => !completedIds.has(scene.taskId));
      const nextPollingTaskId = visibleTaskScenes.find(isSceneBuilding)?.taskId ?? null;

      setState(prev => {
        return {
          scenes: [...visibleTaskScenes, ...scenes],
          status: nextPollingTaskId ? 'polling' : 'idle',
          pollingTaskId: nextPollingTaskId,
          error: null,
        };
      });
    } catch (err) {
      setState(prev => ({
        ...prev,
        status: 'error',
        error: err instanceof Error ? err.message : String(err),
      }));
    }
  }, [state.pollingTaskId]);

  useEffect(() => {
    void refreshScenes({ rebuildIndex: true });
  }, [refreshScenes]);

  useEffect(() => {
    if (!state.pollingTaskId) return;

    const interval = window.setInterval(() => {
      void refreshScenes();
    }, 1000);

    return () => window.clearInterval(interval);
  }, [refreshScenes, state.pollingTaskId]);

  const renameScene = useCallback(async (
    taskId: string,
    displayName: string,
    token: string,
  ): Promise<SceneMutationResult> => {
    try {
      const res = await fetch(`${API}/api/scene-tasks/${encodeURIComponent(taskId)}/display-name`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'X-Scene-Admin-Token': token,
        },
        body: JSON.stringify({ display_name: displayName }),
      });
      if (!res.ok) {
        return { ok: false, status: res.status, error: `更新場景名稱失敗 (${res.status})` };
      }
      await refreshScenes({ rebuildIndex: true });
      return { ok: true, status: res.status };
    } catch (_) {
      return { ok: false, status: 0, error: '無法連線至後端' };
    }
  }, [refreshScenes]);

  const deleteScene = useCallback(async (
    taskId: string,
    token: string,
  ): Promise<SceneMutationResult> => {
    try {
      const res = await fetch(`${API}/api/scene-tasks/${encodeURIComponent(taskId)}`, {
        method: 'DELETE',
        headers: { 'X-Scene-Admin-Token': token },
      });
      if (!res.ok) {
        return { ok: false, status: res.status, error: `刪除場景失敗 (${res.status})` };
      }
      await refreshScenes({ rebuildIndex: true });
      return { ok: true, status: res.status };
    } catch (_) {
      return { ok: false, status: 0, error: '無法連線至後端' };
    }
  }, [refreshScenes]);

  return {
    ...state,
    refreshScenes,
    renameScene,
    deleteScene,
  };
}
