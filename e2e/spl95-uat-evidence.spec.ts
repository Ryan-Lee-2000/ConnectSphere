import { expect, test, type Page } from '@playwright/test';

const password = 'LocalDemo123!';
const technicalSupport = 'technical.support@example.test';
const organiser = 'developer@example.test';

// Deliberately pause after each meaningful state so the evidence recording is readable for a
// reviewer. These pauses do not affect the product; they only make the UAT walkthrough visible.
const evidencePause = (page: Page) => page.waitForTimeout(2_000);

async function signIn(page: Page, email: string, role?: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  if (role) await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

// SPL-95 UAT: a read-only, staff-only availability assessment. The locally seeded scenarios
// show both a satisfiable requirement and a real stock shortfall without creating test records.
test('TC-SPL-95-10 records availability, shortfall, and read-only access evidence', async ({ page }) => {
  test.setTimeout(60_000);

  await signIn(page, technicalSupport);
  await page.getByRole('link', { name: 'Equipment availability' }).click();
  await expect(page.getByRole('heading', { name: 'Equipment availability' })).toBeVisible();
  await evidencePause(page);

  // AC1 happy path: the commitment period and currently feasible quantity are visible. SPL-97
  // adds the reservation controls; this SPL-95 evidence only assesses the state and does not act.
  const retreat = page.locator('.equipment-availability__card').filter({
    has: page.getByRole('heading', { name: 'Wireless Microphone' }),
    hasText: 'Northstar Leadership Retreat',
  });
  // Explicitly bring each card into the recorded viewport. Assertions alone can pass against an
  // off-screen element, which made the earlier evidence video appear to remain at the page top.
  await retreat.scrollIntoViewIfNeeded();
  await expect(retreat.getByRole('heading', { name: 'Wireless Microphone' })).toBeVisible();
  await expect(retreat.getByText('19 Oct 2026 – 20 Oct 2026')).toBeVisible();
  await expect(retreat.getByText('Requested', { exact: true })).toBeVisible();
  await expect(retreat.getByText('0 of 6 units held')).toBeVisible();
  await expect(retreat.getByText('6 units to arrange')).toBeVisible();
  await evidencePause(page);

  // AC2/AC3 unhappy path: this line is partially reserved, so the remaining uncovered quantity
  // is visible alongside bounded zero availability rather than a negative stock value. The UI
  // deliberately hides calculation-only fields such as busiest day and stock basis.
  const studio = page.locator('.equipment-availability__card').filter({ hasText: 'Civic Arts Open Studio' });
  await studio.scrollIntoViewIfNeeded();
  await expect(studio.getByRole('heading', { name: 'Display Plinth Set' })).toBeVisible();
  await expect(studio.getByText('2 units still required')).toBeVisible();
  await expect(studio.getByText('Available to reserve', { exact: true })).toBeVisible();
  await expect(studio.getByText('0', { exact: true })).toBeVisible();
  await expect(studio.getByText('Shortfall')).toBeVisible();
  await expect(studio.getByText('2', { exact: true })).toBeVisible();
  await expect(studio.getByText('Busiest day')).toHaveCount(0);
  await expect(studio.getByText('Stock basis')).toHaveCount(0);
  await evidencePause(page);

  // AC4: this assessment evidence makes no reservation; SPL-97 owns the action controls.
  await page.locator('.equipment-availability__list').scrollIntoViewIfNeeded();
  await expect(page.getByRole('button', { name: 'Reserve units' }).first()).toBeVisible();
  await evidencePause(page);
  await signOut(page);

  // AC4 permission boundary: an organiser cannot enter the Technical Support availability workspace.
  await signIn(page, organiser, 'Event Organiser');
  await expect(page.getByRole('link', { name: 'Equipment availability' })).toHaveCount(0);
  await page.goto('/workspace/equipment-availability');
  await expect(page).toHaveURL(/\/workspace$/);
  await evidencePause(page);
});
