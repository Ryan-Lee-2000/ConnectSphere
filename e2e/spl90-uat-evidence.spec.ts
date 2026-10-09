import { expect, test, type Page } from '@playwright/test';
import { existsSync } from 'node:fs';
import { loadEnvFile } from 'node:process';

if (existsSync('frontend/.env.local')) loadEnvFile('frontend/.env.local');

const password = process.env.VITE_LOCAL_DEMO_PASSWORD ?? 'LocalDemo123!';
const coordinatorEmail =
  process.env.VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL ?? 'event.coordinator@example.test';

// A one-second pause after each observable step makes the video usable as UAT evidence,
// instead of racing through the actions faster than a reviewer can inspect them.
const evidencePause = (page: Page) => page.waitForTimeout(1_000);

async function signInAsCoordinator(page: Page) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(coordinatorEmail);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await evidencePause(page);
}

// SPL-90 UAT: records happy, unhappy and boundary outcomes without leaving a permanent
// demonstration line. scripts/cleanup_e2e_venues.py removes the marker after the run.
test('TC-SPL-90-UAT-01 records a readable equipment-planning walkthrough', async ({ page }) => {
  test.setTimeout(60_000);
  const marker = `E2E UAT equipment requirement ${Date.now()}`;

  await signInAsCoordinator(page);
  await page.goto('/workspace/assigned-events/2/equipment-requirements');
  await expect(page.getByRole('heading', { name: 'Equipment requirements' })).toBeVisible();
  await evidencePause(page);

  // AC1/AC2 happy path: add a catalogue-backed line; dates come from the one-day event.
  await page.getByRole('button', { name: 'Add requirement' }).click();
  await expect(page.getByRole('heading', { name: 'Add equipment to this event' })).toBeVisible();
  await evidencePause(page);

  const catalogue = page.getByLabel('Catalogue equipment Required');
  await catalogue.selectOption({ index: 1 });
  await page.getByLabel('Technical notes Optional').fill(marker);
  const quantity = page.getByLabel('Quantity Required');
  await expect(page.getByLabel('Required from Event date')).toBeDisabled();
  await expect(page.getByLabel('Required until Event date')).toBeDisabled();
  await evidencePause(page);

  // AC2 unhappy boundary: the native number control rejects zero before any record is saved.
  await quantity.fill('0');
  await expect(quantity).toHaveJSProperty('validity.valid', false);
  await evidencePause(page);

  // AC3 unhappy path: Essential visibly requires both consultation inputs before a decision.
  await quantity.fill('2');
  await page.getByRole('radio', { name: 'Essential', exact: true }).check();
  const consultant = page.getByLabel('Consulted Technical Support Staff Required');
  const decisionNote = page.getByLabel('Decision note Required');
  await expect(consultant).toBeVisible();
  await expect(decisionNote).toBeVisible();
  await expect(consultant).toHaveJSProperty('validity.valid', false);
  await evidencePause(page);

  // AC3 happy path: record a valid consultation, then persist the requested requirement.
  await consultant.selectOption({ index: 1 });
  await decisionNote.fill('Confirmed with Technical Support for UAT evidence.');
  await page.getByRole('button', { name: 'Add requirement' }).click();
  await expect(page.getByText('Equipment requirement added.')).toBeVisible();
  await expect(page.getByText(marker)).toBeVisible();
  await expect(page.locator('.equipment-requirements__facts dd').filter({ hasText: 'Essential' })).toBeVisible();
  await evidencePause(page);

  // AC1 persistence: a refresh retains the same line and its organiser-history wording.
  await page.reload();
  await expect(page.getByText(marker)).toBeVisible();
  await expect(page.getByText('Organiser wording:')).toBeVisible();
  await evidencePause(page);

  // AC4 happy path: removal takes the line out of active planning but keeps traceable history.
  page.once('dialog', dialog => dialog.accept());
  const requirement = page.locator('.equipment-requirements__card').filter({ hasText: marker });
  await requirement.getByRole('button', { name: 'Remove' }).click();
  await expect(page.getByText('Equipment requirement removed from active planning.')).toBeVisible();
  await evidencePause(page);
  await page.getByRole('button', { name: /Show removed requirements/ }).click();
  await expect(page.locator('.equipment-requirements__removed li span').last()).toHaveText('Removed from active planning');
  await evidencePause(page);
});
