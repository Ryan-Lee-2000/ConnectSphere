import { expect, test } from '@playwright/test';
import { existsSync } from 'node:fs';
import { loadEnvFile } from 'node:process';

if (existsSync('frontend/.env.local')) loadEnvFile('frontend/.env.local');

const password = process.env.VITE_LOCAL_DEMO_PASSWORD ?? 'LocalDemo123!';
const coordinatorEmail =
  process.env.VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL ?? 'event.coordinator@example.test';

// Keep recorded runs readable: reviewers should have time to see each major UI state.
const visiblePause = (page: import('@playwright/test').Page) => page.waitForTimeout(1_000);

async function signInAsCoordinator(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(coordinatorEmail);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
}

// SPL-90 AC-2/3 / TC-SPL-90-012: browser journey proves the coordinator-facing editor uses
// the event date and reveals consultation evidence before any persistent requirement is saved.
test('coordinator opens the equipment editor and sees essentiality consultation fields', async ({ page }) => {
  await signInAsCoordinator(page);
  await visiblePause(page);
  await page.goto('/workspace/assigned-events/2/equipment-requirements');

  await expect(page.getByRole('heading', { name: 'Equipment requirements' })).toBeVisible();
  await visiblePause(page);
  await page.getByRole('button', { name: 'Add requirement' }).click();
  await expect(page.getByRole('heading', { name: 'Add equipment to this event' })).toBeVisible();
  await visiblePause(page);

  const startDate = page.getByLabel('Required from Event date');
  const endDate = page.getByLabel('Required until Event date');
  await expect(startDate).toBeDisabled();
  await expect(endDate).toBeDisabled();

  await page.getByRole('radio', { name: 'Essential', exact: true }).check();
  await expect(page.getByLabel('Consulted Technical Support Staff Required')).toBeVisible();
  await expect(page.getByLabel('Decision note Required')).toBeVisible();
  await expect(page.getByText('Keep this Undecided until you have consulted Technical Support. Essential requirements later contribute to event readiness.')).toBeVisible();
  await visiblePause(page);

  // Cancel deliberately: the regression journey must not create user-facing test records.
  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('button', { name: 'Add requirement' })).toBeVisible();
  await visiblePause(page);
});
