import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { useGeneratedScenes } from './useGeneratedScene';

function jsonResponse(body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }));
}

describe('useGeneratedScenes', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('shows a newly created scene immediately while it is building', async () => {
    vi.stubGlobal('localStorage', { getItem: () => null });
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/api/scene-tasks')) {
        return jsonResponse({
          tasks: [{
            id: 'task-pending',
            sceneKey: 'T-PENDING',
            sceneName: 'picked_scene',
            displayName: '永久顯示名稱',
            status: 'running',
            stage: 'running_blender_generation',
            modelUrl: '/generated-scenes/T-PENDING/T-PENDING.glb',
            createdAt: '2026-07-15T09:00:00',
            location: { place_name: '台北 101' },
          }],
        });
      }
      if (url.includes('/api/generated-scenes')) return jsonResponse({ scenes: [] });
      throw new Error(`Unexpected request: ${url}`);
    }));

    const { result, unmount } = renderHook(() => useGeneratedScenes());

    await waitFor(() => expect(result.current.scenes).toEqual([
      expect.objectContaining({
        taskId: 'task-pending',
        label: '永久顯示名稱',
        status: 'running',
      }),
    ]));
    expect(result.current.status).toBe('polling');
    unmount();
  });

  it('keeps a completed task disabled until its scene is ready', async () => {
    let taskStatus = 'running';
    vi.stubGlobal('localStorage', { getItem: () => 'task-pending' });
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/api/scene-tasks')) {
        return jsonResponse({
          tasks: [{
            id: 'task-pending',
            sceneKey: 'T-PENDING',
            sceneName: 'picked_scene',
            status: taskStatus,
            modelUrl: '/generated-scenes/T-PENDING/T-PENDING.glb',
            createdAt: '2026-07-15T09:00:00',
            location: { place_name: '台北 101' },
          }],
        });
      }
      if (url.includes('/api/generated-scenes')) return jsonResponse({ scenes: [] });
      throw new Error(`Unexpected request: ${url}`);
    }));

    const { result, unmount } = renderHook(() => useGeneratedScenes());
    await waitFor(() => expect(result.current.status).toBe('polling'));

    taskStatus = 'completed';
    await act(async () => {
      await result.current.refreshScenes();
    });

    expect(result.current.scenes).toEqual([
      expect.objectContaining({ taskId: 'task-pending', status: 'completed' }),
    ]);
    expect(result.current.status).toBe('polling');
    unmount();
  });

  it('keeps every failed scene visible so it can be deleted', async () => {
    vi.stubGlobal('localStorage', { getItem: () => null });
    vi.stubGlobal('fetch', vi.fn((input: string | URL | Request) => {
      const url = String(input);
      if (url.endsWith('/api/scene-tasks')) {
        return jsonResponse({
          tasks: [
            {
              id: 'task-failed-old',
              sceneKey: 'T-FAILED0001',
              sceneName: '舊失敗場景',
              status: 'failed',
              modelUrl: '/generated-scenes/T-FAILED0001/T-FAILED0001.glb',
            },
            {
              id: 'task-failed-new',
              sceneKey: 'T-FAILED0002',
              sceneName: '新失敗場景',
              status: 'failed',
              modelUrl: '/generated-scenes/T-FAILED0002/T-FAILED0002.glb',
            },
          ],
        });
      }
      if (url.includes('/api/generated-scenes')) return jsonResponse({ scenes: [] });
      throw new Error(`Unexpected request: ${url}`);
    }));

    const { result } = renderHook(() => useGeneratedScenes());

    await waitFor(() => expect(result.current.scenes.map(scene => scene.taskId)).toEqual([
      'task-failed-old',
      'task-failed-new',
    ]));
  });

  it('renames a scene with the admin token and refreshes the persistent label', async () => {
    vi.stubGlobal('localStorage', { getItem: () => null });
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/display-name')) return jsonResponse({ task: {} });
      if (url.endsWith('/api/scene-tasks')) return jsonResponse({ tasks: [] });
      if (url.includes('/api/generated-scenes')) return jsonResponse({ scenes: [] });
      throw new Error(`Unexpected request: ${url} ${init?.method}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useGeneratedScenes());
    await waitFor(() => expect(result.current.status).toBe('idle'));

    await act(async () => {
      expect(await result.current.renameScene('task / 1', '新名稱', 'secret')).toEqual({ ok: true, status: 200 });
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/scene-tasks/task%20%2F%201/display-name',
      expect.objectContaining({
        method: 'PATCH',
        headers: expect.objectContaining({ 'X-Scene-Admin-Token': 'secret' }),
        body: JSON.stringify({ display_name: '新名稱' }),
      }),
    );
  });
});
