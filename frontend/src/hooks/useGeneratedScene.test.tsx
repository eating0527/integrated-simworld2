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
        label: '台北 101',
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
});
