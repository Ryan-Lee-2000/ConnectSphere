import { test, expect, type Page } from '@playwright/test';
import { loadEnvFile } from 'node:process';

loadEnvFile('.env');

const validAccount = {
  email: 'developer@example.test',
  password: 'LocalDemo123!',
};

const invalidCredentialsMessage =
  "We couldn't sign you in with those credentials. Check your details and try again.";

async function signIn(page: Page, email: string, password: string) {
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
}

test('TC-CS-E01-S1A-01 valid credentials establish a verified session', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();

  await signIn(page, validAccount.email, validAccount.password);

  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed' })).toBeVisible();
  await expect(page.getByRole('alert')).toHaveCount(0);

  await page.reload();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed' })).toBeVisible();
});

test('TC-CS-E01-S1A-02 invalid credential partitions receive the same response', async ({ page }) => {
  await page.goto('/');

  await signIn(page, 'missing@example.test', validAccount.password);
  const unknownEmailMessage = await page.getByRole('alert').textContent();
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed' })).toHaveCount(0);
  await page.goto('/workspace');
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();

  await page.goto('/');
  await signIn(page, validAccount.email, 'wrong-password');
  const incorrectPasswordMessage = await page.getByRole('alert').textContent();
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed' })).toHaveCount(0);
  await page.goto('/workspace');
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();

  expect(unknownEmailMessage).toBe(invalidCredentialsMessage);
  expect(incorrectPasswordMessage).toBe(invalidCredentialsMessage);
  expect(incorrectPasswordMessage).toBe(unknownEmailMessage);
  expect(unknownEmailMessage).not.toContain('missing@example.test');
  expect(incorrectPasswordMessage).not.toContain(validAccount.email);
  expect(incorrectPasswordMessage).not.toContain('wrong-password');
});

test('TC-CS-E01-S1A-03 direct protected-page access is denied without a session', async ({ page }) => {
  await page.goto('/workspace');

  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed' })).toHaveCount(0);
  await expect(page.getByText('Your session has been verified.')).toHaveCount(0);
});

test('TC-CS-E01-S1A-04 protected API rejects a request with no authentication header', async ({
  request,
}) => {
  const response = await request.get('/api/session');
  const body = await response.json();

  expect(response.status()).toBe(401);
  expect(body).toEqual({ error: 'Sign in to continue.' });
});

test('TC-CS-E01-S1A-05 protected API rejects malformed and invalid authentication', async ({
  request,
}) => {
  const attempts = [
    { authorization: 'Basic abc', expectedError: 'Sign in to continue.' },
    { authorization: 'Bearer invalid-token', expectedError: 'Session expired or invalid.' },
  ];

  for (const { authorization, expectedError } of attempts) {
    const response = await request.get('/api/session', {
      headers: { Authorization: authorization },
    });
    const body = await response.json();

    expect(response.status()).toBe(401);
    expect(body).toEqual({ error: expectedError });
  }
});

test('TC-CS-E01-S1A-06 a server-rejected stored session cannot expose the workspace', async ({
  page,
}) => {
  await page.goto('/');
  await signIn(page, validAccount.email, validAccount.password);
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed' })).toBeVisible();

  await page.route('**/api/session', async route => {
    await route.fulfill({
      status: 401,
      contentType: 'application/json',
      body: JSON.stringify({ error: 'Session expired or invalid.' }),
    });
  });
  await page.reload();

  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed' })).toHaveCount(0);
  await expect(page.getByText('Your session has been verified.')).toHaveCount(0);
});

test('TC-CS-E01-S1A-07 session-verification outage fails closed after authentication', async ({
  page,
}) => {
  await page.goto('/');
  await page.route('**/api/session', async route => {
    await route.abort('connectionfailed');
  });

  await signIn(page, validAccount.email, validAccount.password);

  await expect(page.getByRole('alert')).toHaveText(
    "We couldn't reach the sign-in service. Check your connection and try again.",
  );
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed' })).toHaveCount(0);
  await expect(page.getByText('Your session has been verified.')).toHaveCount(0);
});
