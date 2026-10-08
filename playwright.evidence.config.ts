import { defineConfig } from '@playwright/test';
import base from './playwright.config';

// Opt-in local documentation run; ordinary test/CI settings stay unchanged.
const baseURL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173';
const target = new URL(baseURL);
if (!['localhost', '127.0.0.1', '[::1]'].includes(target.hostname)) {
  throw new Error('Evidence recording requires a local test environment.');
}

export default defineConfig(base, {
  outputDir: 'artifacts/e2e-evidence/results',
  timeout: 60_000,
  use: {
    ...base.use,
    baseURL,
    video: 'on',
    trace: 'on',
    screenshot: 'on',
  },
  reporter: [
    ['list'],
    ['html', { outputFolder: 'artifacts/e2e-evidence/report', open: 'never' }],
  ],
});
