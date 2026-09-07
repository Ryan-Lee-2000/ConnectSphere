import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { App } from './App';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('shows confirmed connectivity from the API', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'ok' }) }));
  render(<App />);
  expect(await screen.findByText('API and database connected.')).toBeTruthy();
});
it('does not report success when the API is unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
  render(<App />);
  expect(await screen.findByText(/Connection unavailable/)).toBeTruthy();
});
