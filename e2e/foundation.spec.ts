import { test, expect } from '@playwright/test';
import { loadEnvFile } from 'node:process';

loadEnvFile('.env');
test('foundation connects browser, API, database and local Auth', async ({ page, request }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'ConnectSphere' })).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('API and database connected.');
  const anonymous = await request.get('/api/session');
  expect(anonymous.status()).toBe(401);
  const api = process.env.SUPABASE_URL!;
  expect(new URL(api).hostname).toMatch(/^(127\.0\.0\.1|localhost)$/);
  const login = await request.post(`${api}/auth/v1/token?grant_type=password`, {
    headers: { apikey: process.env.SUPABASE_PUBLISHABLE_KEY! },
    data: { email: 'developer@example.test', password: 'LocalDemo123!' },
  });
  expect(login.ok()).toBeTruthy();
  const session = await login.json();
  const identity = await request.get('/api/session', {
    headers: { Authorization: `Bearer ${session.access_token}` },
  });
  expect(identity.status()).toBe(200);
  expect((await identity.json()).user_id).toBe(session.user.id);
});
