import { expect, test } from '@playwright/test';

const multiRoleAccount = {
  email: 'developer@example.test',
  password: 'LocalDemo123!',
};

test('TC-CS-E01-S4-01 selects, switches, and remembers an assigned role for the browser session', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByLabel('Email address').fill(multiRoleAccount.email);
  await page.getByLabel('Password').fill(multiRoleAccount.password);
  await page.getByRole('button', { name: 'Sign in' }).click();

  await expect(page.getByRole('heading', { name: 'Which role are you working in?' })).toBeVisible();
  await expect(page.getByRole('button', { name: /Attendee/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Event Organiser/ })).toBeVisible();
  await page.getByRole('button', { name: /Event Organiser/ }).click();

  const roleSwitcher = page.getByRole('combobox', { name: 'Active role' });
  await expect(roleSwitcher).toHaveValue('event_organiser');
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => window.innerWidth),
  );
  await roleSwitcher.selectOption('attendee');
  await expect(roleSwitcher).toHaveValue('attendee');
  await expect(page.getByText('Access attendee services as they become available.')).toBeVisible();

  await page.reload();
  await expect(page.getByRole('combobox', { name: 'Active role' })).toHaveValue('attendee');
  await expect(page.getByRole('heading', { name: 'Which role are you working in?' })).toHaveCount(0);
});

test('TC-CS-E01-S4-02 refuses an unavailable direct page without changing the active role', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByLabel('Email address').fill(multiRoleAccount.email);
  await page.getByLabel('Password').fill(multiRoleAccount.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByRole('button', { name: /Attendee/ }).click();

  await page.goto('/workspace/venues');

  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole('combobox', { name: 'Active role' })).toHaveValue('attendee');
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Find the right space, faster.' })).toHaveCount(0);
});

test('TC-CS-E01-S4-03 keeps role selection and account actions usable at a narrow width', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('Email address').fill(multiRoleAccount.email);
  await page.getByLabel('Password').fill(multiRoleAccount.password);
  await page.getByRole('button', { name: 'Sign in' }).click();

  await page.getByRole('button', { name: /Event Organiser/ }).click();

  await expect(page.getByRole('combobox', { name: 'Active role' })).toBeInViewport();
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
