import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PhotoViewer } from './PhotoViewer';

const photo = { url: '/uploads/a.jpg', timestamp: '20260307_163115', filename: 'a&b.jpg' };

describe('PhotoViewer', () => {
  beforeEach(() => { vi.stubGlobal('confirm', vi.fn(() => true)); vi.stubGlobal('alert', vi.fn()); });
  afterEach(() => { vi.restoreAllMocks(); });

  it('exposes header and card semantics and restores focus', async () => {
    render(<PhotoViewer photos={[photo]} />);
    const header = screen.getByRole('button', { name: /照片/ });
    expect(header).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(header);
    expect(header).toHaveAttribute('aria-expanded', 'true');
    const card = screen.getByRole('button', { name: '開啟照片 a&b.jpg' });
    fireEvent.click(card);
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByRole('button', { name: '關閉照片' })).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(card).toHaveFocus());
  });

  it('closes only on backdrop click and deletes encoded filename after success', async () => {
    const onDelete = vi.fn();
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true }) })));
    render(<PhotoViewer photos={[photo]} onDelete={onDelete} />);
    fireEvent.click(screen.getByRole('button', { name: /照片/ }));
    fireEvent.click(screen.getByRole('button', { name: '開啟照片 a&b.jpg' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.click(screen.getByText('a&b.jpg'));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    fireEvent.click(dialog);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '刪除照片 a&b.jpg' }));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith('a&b.jpg'));
    expect(fetch).toHaveBeenCalledWith('/api/delete-photo/a%26b.jpg', { method: 'DELETE' });
  });

  it('does not delete on non-ok response', async () => {
    const onDelete = vi.fn();
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve({ success: false }) })));
    render(<PhotoViewer photos={[photo]} onDelete={onDelete} />);
    fireEvent.click(screen.getByRole('button', { name: /照片/ }));
    fireEvent.click(screen.getByRole('button', { name: '刪除照片 a&b.jpg' }));
    await waitFor(() => expect(onDelete).not.toHaveBeenCalled());
  });
});
