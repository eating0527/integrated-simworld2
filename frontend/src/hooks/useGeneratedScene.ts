import { useState, useEffect, useCallback } from 'react';

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

  if (task.status !== 'completed' || !taskId || !sceneKey || !modelPath) {
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
  };
}

export function useGeneratedScenes() {
  const [state, setState] = useState<GeneratedScenesState>({
    scenes: [],
    status: 'idle',
    pollingTaskId: null,
    error: null,
  });

  const refreshScenes = useCallback(async () => {
    setState(prev => ({
      ...prev,
      status: prev.pollingTaskId ? 'polling' : 'loading',
      error: null,
    }));

    try {
      const res = await fetch(`${API}/api/scene-tasks`, { method: 'GET' });

      if (!res.ok) {
        throw new Error(`Failed to fetch scene tasks: ${res.statusText}`);
      }

      const payload = await res.json();
      const tasks = Array.isArray(payload?.tasks) ? payload.tasks as SceneTask[] : [];
      const scenes = tasks
        .map(normalizeTask)
        .filter((scene): scene is GeneratedSceneOption => Boolean(scene));

      setState(prev => {
        let pollingTaskId = prev.pollingTaskId;

        if (pollingTaskId) {
          const pollingTask = tasks.find(task => task.id === pollingTaskId);
          const completed = scenes.some(scene => scene.taskId === pollingTaskId);
          const stillPending = pollingTask?.status === 'queued' || pollingTask?.status === 'running';

          if (completed || (pollingTask && !stillPending)) {
            pollingTaskId = null;
          }
        }

        return {
          scenes,
          status: pollingTaskId ? 'polling' : 'idle',
          pollingTaskId,
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
  }, []);

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

    void refreshScenes();
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
