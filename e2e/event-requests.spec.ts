import { expect, test, type Page } from '@playwright/test';

const organiser = { email: 'developer@example.test', password: 'LocalDemo123!' };
const coordinator = { email: 'event.coordinator@example.test', password: 'LocalDemo123!' };

async function signIn(
  page: Page,
  account: { email: string; password: string },
  role?: string,
) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(account.email);
  await page.getByLabel('Password').fill(account.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);

  // An account holding more than one role picks one before entering (CS-E01-S4). The roles
  // load asynchronously, so let the click auto-wait rather than probing for the chooser.
  if (role) {
    await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
    await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
  }
}

function uniqueName() {
  return `E2E Submission ${Date.now()}`;
}

test('TC-CS-E03-S5-10 an organiser submits from the interface and sees a confirmation', async ({
  page,
}) => {
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'Event requests' }).click();
  await expect(page.getByRole('heading', { name: 'Submit an event request' })).toBeVisible();

  const name = uniqueName();
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('Brief partners on the roadmap');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByLabel('Start time').fill('09:00');
  await page.getByLabel('End time').fill('11:30');
  await page.getByLabel('Expected attendance').fill('120');
  await page.getByRole('button', { name: 'Submit request' }).click();

  // CS-E07-S1 AC7 takes the organiser to their requests once the submission succeeds, so the
  // confirmation is now the request appearing there rather than a panel on this page.
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
  const row = page.getByRole('row').nth(1);
  await expect(row).toContainText(name);
  await expect(row).toContainText('Submitted');
  await expect(row).toContainText('EVT-');
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('TC-CS-E03-S5-11 a role that may not submit is not offered the control', async ({ page }) => {
  await signIn(page, coordinator);

  // The nav never offers an action the server would refuse.
  await expect(page.getByRole('link', { name: 'Event requests' })).toHaveCount(0);

  // Reaching the page directly does not present the submit control either.
  await page.goto('/workspace/event-requests');
  await expect(page.getByRole('button', { name: 'Submit request' })).toHaveCount(0);

  // And the operation itself is refused by the server.
  const refused = await page.evaluate(async () => {
    const response = await fetch('/api/event-requests', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Should not be stored' }),
    });
    return response.status;
  });
  expect([401, 403]).toContain(refused);
});

test('TC-CS-E03-S5-12 a refused submission names every missing field, and TC-13 the error clears', async ({
  page,
}) => {
  await signIn(page, organiser, 'Event Organiser');
  await page.goto('/workspace/event-requests');

  await page.getByRole('button', { name: 'Submit request' }).click();

  const error = page.getByRole('alert');
  await expect(error).toContainText('Complete the required fields before submitting.');
  for (const label of [
    'Event name',
    'Purpose',
    'Proposed date',
    'Start time',
    'End time',
    'Expected attendance',
  ]) {
    await expect(error).toContainText(label);
  }
  await expect(page.getByRole('status')).toHaveCount(0);

  // TC-CS-E03-S5-13: correcting the submission clears the earlier error.
  const name = uniqueName();
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('Brief partners on the roadmap');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByLabel('Start time').fill('09:00');
  await page.getByLabel('End time').fill('11:30');
  await page.getByLabel('Expected attendance').fill('120');
  await page.getByRole('button', { name: 'Submit request' }).click();

  // The earlier error is gone, and the corrected submission lands on My requests (CS-E07-S1).
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
  await expect(page.getByRole('row').nth(1)).toContainText(name);
  await expect(page.getByRole('alert')).toHaveCount(0);
});
