import { expect, test, type Page } from '@playwright/test';

const password = 'LocalDemo123!';
const technicalSupport = 'technical.support@example.test';
const organiser = 'developer@example.test';

// Keep each visible state on screen long enough for a reviewer to read the labels, values and
// outcome in the captured video. This evidence test intentionally favours readability over speed.
const evidencePause = (page: Page) => page.waitForTimeout(2_000);

test.use({ video: 'on' });

async function signIn(page: Page, email: string, role?: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  if (role) await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

// SPL-97 UAT: revalidation success and failure, bounded partial reservation, and role boundary.
test('TC-SPL-97-UAT-01 records equipment reservation and revalidation evidence', async ({ page }) => {
  test.setTimeout(90_000);

  await signIn(page, technicalSupport);
  await page.getByRole('link', { name: 'Equipment availability' }).click();
  await expect(page.getByRole('heading', { name: 'Equipment availability' })).toBeVisible();
  await evidencePause(page);

  // AC4 happy path: feasible retained units clear Review Required and become Reserved.
  const feasibleReview = page.locator('.equipment-availability__card').filter({
    has: page.getByRole('heading', { name: 'E2E SPL-97 Feasible Microphone' }),
    hasText: 'E2E SPL-97 Feasible review',
  });
  await feasibleReview.scrollIntoViewIfNeeded();
  await expect(feasibleReview.getByText('Review required', { exact: true })).toBeVisible();
  await expect(feasibleReview.getByText('5 of 5 units held')).toBeVisible();
  await evidencePause(page);
  const feasibleRevalidate = feasibleReview.getByRole('button', { name: 'Revalidate availability' });
  await feasibleRevalidate.scrollIntoViewIfNeeded();
  await evidencePause(page);
  await feasibleRevalidate.click();
  await expect(feasibleReview.getByText('Reserved', { exact: true })).toBeVisible();
  await expect(feasibleReview.getByText('Fully covered')).toBeVisible();
  await evidencePause(page);

  // AC4 unhappy path: infeasible retained units remain Review Required and show a refusal.
  const infeasibleReview = page.locator('.equipment-availability__card').filter({
    has: page.getByRole('heading', { name: 'E2E SPL-97 Infeasible Presentation Kit' }),
    hasText: 'E2E SPL-97 Infeasible review',
  });
  await infeasibleReview.scrollIntoViewIfNeeded();
  await expect(infeasibleReview.getByText('Review required', { exact: true })).toBeVisible();
  await expect(infeasibleReview.getByText('5 of 5 units held')).toBeVisible();
  await evidencePause(page);
  const infeasibleRevalidate = infeasibleReview.getByRole('button', { name: 'Revalidate availability' });
  await infeasibleRevalidate.scrollIntoViewIfNeeded();
  await evidencePause(page);
  await infeasibleRevalidate.click();
  await expect(infeasibleReview.getByRole('alert')).toContainText('no longer feasible');
  await expect(infeasibleReview.getByText('Review required', { exact: true })).toBeVisible();
  await evidencePause(page);

  // AC1/AC2/AC3: reserve only the feasible ten units of a twelve-unit requirement.
  const partial = page.locator('.equipment-availability__card').filter({
    has: page.getByRole('heading', { name: 'E2E SPL-97 Partial Display Plinth' }),
    hasText: 'E2E SPL-97 Partial reservation',
  });
  await partial.scrollIntoViewIfNeeded();
  await expect(partial.getByText('Stock is short by 2')).toBeVisible();
  await expect(partial.getByText('0 of 12 units held')).toBeVisible();
  await evidencePause(page);
  const quantity = partial.getByLabel('Units to reserve');
  await quantity.scrollIntoViewIfNeeded();
  await quantity.fill('10');
  await evidencePause(page);
  const reserve = partial.getByRole('button', { name: 'Reserve units' });
  await reserve.scrollIntoViewIfNeeded();
  await evidencePause(page);
  await reserve.click();
  await expect(partial.getByText('Partially reserved', { exact: true })).toBeVisible();
  await expect(partial.getByText('10 of 12 units held')).toBeVisible();
  await expect(partial.getByText('2 units still required')).toBeVisible();
  await expect(partial.getByRole('button', { name: 'No units available' })).toBeDisabled();
  await evidencePause(page);

  // AC3 permission boundary: organisers cannot access Technical Support reservation controls.
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  await signIn(page, organiser, 'Event Organiser');
  await expect(page.getByRole('link', { name: 'Equipment availability' })).toHaveCount(0);
  await evidencePause(page);
  await page.goto('/workspace/equipment-availability');
  await expect(page).toHaveURL(/\/workspace$/);
  await evidencePause(page);
});
