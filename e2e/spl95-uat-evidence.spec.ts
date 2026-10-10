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

  // AC1 happy path: the commitment period is visible and includes D-1 collection.
  const summit = page.locator('.equipment-availability__card').filter({ hasText: 'Community Partnership Summit' });
  // Explicitly bring each card into the recorded viewport. Assertions alone can pass against an
  // off-screen element, which made the earlier evidence video appear to remain at the page top.
  await summit.scrollIntoViewIfNeeded();
  await expect(summit.getByRole('heading', { name: 'Presentation Kit' })).toBeVisible();
  await expect(summit.getByText('23 Oct 2026 – 25 Oct 2026')).toBeVisible();
  await expect(summit.getByText('Available', { exact: true })).toBeVisible();
  await evidencePause(page);

  // AC2/AC3 unhappy path: insufficient pooled stock produces a bounded zero availability and a
  // concrete shortfall rather than a negative number. The UI deliberately hides calculation-only
  // fields such as busiest day and stock basis.
  const studio = page.locator('.equipment-availability__card').filter({ hasText: 'Civic Arts Open Studio' });
  await studio.scrollIntoViewIfNeeded();
  await expect(studio.getByRole('heading', { name: 'Display Plinth Set' })).toBeVisible();
  await expect(studio.getByText('2 short', { exact: true })).toBeVisible();
  await expect(studio.getByText('Available to reserve')).toBeVisible();
  await expect(studio.getByText('0', { exact: true })).toBeVisible();
  await expect(studio.getByText('Shortfall')).toBeVisible();
  await expect(studio.getByText('2', { exact: true })).toBeVisible();
  await expect(studio.getByText('Busiest day')).toHaveCount(0);
  await expect(studio.getByText('Stock basis')).toHaveCount(0);
  await evidencePause(page);

  // AC4: assessment is informational only; SPL-97 will own the future reservation action.
  await page.locator('.equipment-availability__list').scrollIntoViewIfNeeded();
  await expect(page.getByRole('button', { name: /reserve/i })).toHaveCount(0);
  await evidencePause(page);
  await signOut(page);

  // AC4 permission boundary: an organiser cannot enter the Technical Support availability workspace.
  await signIn(page, organiser, 'Event Organiser');
  await expect(page.getByRole('link', { name: 'Equipment availability' })).toHaveCount(0);
  await page.goto('/workspace/equipment-availability');
  await expect(page).toHaveURL(/\/workspace$/);
  await evidencePause(page);
});
