import { useState, useEffect, useCallback } from 'react';

const API = import.meta.env.VITE_API_URL || '';

interface GeneratedSceneState {
  taskId: string | null;
  status: 'idle' | 'polling' | 'completed' | 'failed';
  modelPath: string | null;
  sceneKey: string | null;
  sceneMetadata: Record<string, any> | null;
  pickedPlaceName: string | null;
  error: string | null;
}

/**
 * Hook to manage the lifecycle of a generated scene from map selection
 * - Monitors localStorage for new taskId
 * - Polls for completion
 * - Provides the GLB path when ready
 */
export function useGeneratedScene() {
  const [state, setState] = useState<GeneratedSceneState>({
    taskId: null,
    status: 'idle',
    modelPath: null,
    sceneKey: null,
    sceneMetadata: null,
    pickedPlaceName: null,
    error: null,
  });

  // Start polling for a task
  const startPolling = useCallback((taskId: string) => {
    setState(prev => ({
      ...prev,
      taskId,
      status: 'polling',
      error: null,
    }));
  }, []);

  // Clear the current generated scene
  const clearScene = useCallback(() => {
    setState({
      taskId: null,
      status: 'idle',
      modelPath: null,
      sceneKey: null,
      sceneMetadata: null,
      pickedPlaceName: null,
      error: null,
    });
    // Also clear localStorage
    localStorage.removeItem('recent-generated-scene-task-id');
    localStorage.removeItem('recent-generated-scene-place-name');
  }, []);

  // Listen for new taskId in localStorage (from map page)
  useEffect(() => {
    const handleStorageChange = () => {
      const taskId = localStorage.getItem('recent-generated-scene-task-id');
      const placeName = localStorage.getItem('recent-generated-scene-place-name');

      if (placeName && placeName !== state.pickedPlaceName) {
        setState(prev => ({
          ...prev,
          pickedPlaceName: placeName,
        }));
      }

      if (taskId && taskId !== state.taskId) {
        console.log('Detected new generated scene task:', taskId);
        startPolling(taskId);
      }
    };

    // Check on mount and when storage changes
    handleStorageChange();
    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, [state.taskId, state.pickedPlaceName, startPolling]);

  // Poll for task status
  useEffect(() => {
    if (state.status !== 'polling' || !state.taskId) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API}/api/scene-tasks/${state.taskId}`, {
          method: 'GET',
        });

        if (!res.ok) {
          throw new Error(`Failed to fetch task status: ${res.statusText}`);
        }

        const taskPayload = await res.json();
        const task = taskPayload?.task;
        const taskPlaceName = task?.location?.place_name ?? null;

        if (!task) {
          throw new Error('Task payload missing task field');
        }

        if (taskPlaceName && taskPlaceName !== state.pickedPlaceName) {
          setState(prev => ({
            ...prev,
            pickedPlaceName: taskPlaceName,
          }));
        }

        // Check if task is completed or failed
        if (task.status === 'completed') {
          // Try to load the scene metadata to confirm GLB exists
          const metadataRes = await fetch(
            `${API}/api/scene-tasks/${state.taskId}/metadata`,
            { method: 'GET' }
          );

          if (metadataRes.ok) {
            const metadataPayload = await metadataRes.json();
            const metadata = metadataPayload?.metadata ?? null;
            const sceneKey = task?.sceneKey ?? metadata?.scene_key ?? metadata?.sceneKey ?? null;
            const modelPath =
              task?.modelUrl ??
              metadata?.model_url ??
              metadata?.modelUrl ??
              (sceneKey
                ? `/generated-scenes/${sceneKey}/${sceneKey}.glb`
                : `/generated-scenes/generated/${state.taskId}/scene.glb`);

            setState(prev => ({
              ...prev,
              status: 'completed',
              modelPath,
              sceneKey,
              sceneMetadata: metadata,
              pickedPlaceName: taskPlaceName ?? prev.pickedPlaceName,
            }));
            clearInterval(interval);
          } else {
            throw new Error('Failed to fetch scene metadata');
          }
        } else if (task.status === 'failed') {
          setState(prev => ({
            ...prev,
            status: 'failed',
            error: task.error || 'Task failed without error message',
          }));
          clearInterval(interval);
        }
        // If still 'queued' or 'running', continue polling
      } catch (err) {
        setState(prev => ({
          ...prev,
          status: 'failed',
          error: err instanceof Error ? err.message : String(err),
        }));
        clearInterval(interval);
      }
    }, 1000); // Poll every 1 second

    return () => clearInterval(interval);
  }, [state.status, state.taskId]);

  return { ...state, startPolling, clearScene };
}
