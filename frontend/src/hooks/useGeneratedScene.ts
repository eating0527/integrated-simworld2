import { useState, useEffect, useCallback } from 'react';
import { parseSceneFrame, type SceneFrame } from '../types/sceneFrame';

const API = import.meta.env.VITE_API_URL || '';
const RECENT_TASK_ID_KEY = 'recent-generated-scene-task-id';

type SceneTaskStatus = 'idle' | 'loading' | 'polling' | 'error';

interface SceneTaskLocation {
  lat?: number;
  lon?: number;
  place_name?: string | null;
}

interface SceneTask {
  id?: string;
  sceneKey?: string;
  sceneName?: string;
  status?: string;
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

function getSceneLabel(task: SceneTask, taskId: string, sceneKey: string): string {
  return (
    task.location?.place_name?.trim() ||
    task.sceneName?.trim() ||
    sceneKey ||
    taskId
  );
}

function normalizeTask(task: SceneTask): GeneratedSceneOption | null {
  const taskId = task.id?.trim();
  const sceneKey = task.sceneKey?.trim();
  const modelPath = task.modelUrl?.trim();

  if ((task.status && task.status !== 'completed') || !taskId || !sceneKey || !modelPath) {
    return null;
  }

  return {
    taskId,
    sceneKey,
    label: getSceneLabel(task, taskId, sceneKey),
    modelPath,
    createdAt: task.createdAt ?? '',
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
    .map(normalizeTask)
    .filter((scene): scene is GeneratedSceneOption => Boolean(scene));
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
      let scenes = await fetchGeneratedSceneIndex(Boolean(options?.rebuildIndex));
      let nextPollingTaskId = state.pollingTaskId;

      if (nextPollingTaskId) {
        const completed = scenes.some(scene => scene.taskId === nextPollingTaskId);

        if (completed) {
          nextPollingTaskId = null;
        } else {
          const tasks = await fetchSceneTasks();
          const pollingTask = tasks.find(task => task.id === nextPollingTaskId);
          const stillPending = pollingTask?.status === 'queued' || pollingTask?.status === 'running';

          if (pollingTask?.status === 'completed') {
            scenes = await fetchGeneratedSceneIndex(true);
            nextPollingTaskId = null;
          } else if (pollingTask && !stillPending) {
            nextPollingTaskId = null;
          }
        }
      }

      setState(prev => {
        return {
          scenes,
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

  const watchTask = useCallback((taskId: string) => {
    setState(prev => ({
      ...prev,
      pollingTaskId: taskId,
      status: 'polling',
      error: null,
    }));
  }, []);

  useEffect(() => {
    const recentTaskId = localStorage.getItem(RECENT_TASK_ID_KEY);
    if (recentTaskId) {
      watchTask(recentTaskId);
    }

    void refreshScenes({ rebuildIndex: true });
  }, [refreshScenes, watchTask]);

  useEffect(() => {
    const handleStorageChange = (event: StorageEvent) => {
      if (event.key !== RECENT_TASK_ID_KEY || !event.newValue) return;
      watchTask(event.newValue);
      void refreshScenes();
    };

    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, [refreshScenes, watchTask]);

  useEffect(() => {
    if (!state.pollingTaskId) return;

    const interval = window.setInterval(() => {
      void refreshScenes();
    }, 1000);

    return () => window.clearInterval(interval);
  }, [refreshScenes, state.pollingTaskId]);

  return {
    ...state,
    refreshScenes,
    watchTask,
  };
}
