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

  if (role) {
    await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
    await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
  }
}

async function submitRequest(page: Page, name: string) {
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('Brief partners on the roadmap');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByLabel('Start time').fill('09:00');
  await page.getByLabel('End time').fill('11:30');
  await page.getByLabel('Expected attendance').fill('120');
  await page.getByRole('button', { name: 'Submit request' }).click();
}

function uniqueName() {
  return `E2E Status ${Date.now()}`;
}

test('TC-CS-E07-S1-17 and -18 a submission lands on My requests with the new request on top', async ({
  page,
}) => {
  await signIn(page, organiser, 'Event Organiser');

  // An earlier request exists, so "on top" is a real ordering rather than the only row.
  await page.getByRole('link', { name: 'Event requests' }).click();
  await submitRequest(page, `${uniqueName()} first`);
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);

  const newest = `${uniqueName()} newest`;
  await page.getByRole('link', { name: 'Event requests' }).click();
  await submitRequest(page, newest);

  // TC-17: the organiser arrives here without navigating themselves.
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
  await expect(page.getByRole('heading', { name: 'The status of my events' })).toBeVisible();

  // TC-18: the request just submitted is visible, at the top of the table.
  const firstRow = page.getByRole('row').nth(1);
  await expect(firstRow).toContainText(newest);
  await expect(firstRow).toContainText('Submitted');
  await expect(firstRow).toContainText('waiting to be picked up for review');
});

test('TC-CS-E07-S1-19 a refused submission does not move the organiser on', async ({ page }) => {
  await signIn(page, organiser, 'Event Organiser');
  await page.goto('/workspace/event-requests');

  await page.getByRole('button', { name: 'Submit request' }).click();

  await expect(page.getByRole('alert')).toContainText(
    'Complete the required fields before submitting.',
  );
  await expect(page).toHaveURL(/\/workspace\/event-requests$/);
  await expect(page.getByRole('heading', { name: 'Submit an event request' })).toBeVisible();
});

test('TC-CS-E07-S1-20 and -22 another role is neither offered the view nor served it', async ({
  page,
}) => {
  await signIn(page, coordinator);

  // A coordinator may read event requests through the API, and is still not offered this view.
  await expect(page.getByRole('link', { name: 'My requests' })).toHaveCount(0);

  await page.goto('/workspace/my-requests');
  await expect(page.getByRole('heading', { name: 'The status of my events' })).toHaveCount(0);
  await expect(page.getByRole('table')).toHaveCount(0);
});

test('TC-CS-E07-S1-23 and -24 the navigation opens the view and returns to it', async ({
  page,
}) => {
  await signIn(page, organiser, 'Event Organiser');

  // TC-23: the entry is offered and opens the view.
  await page.getByRole('link', { name: 'My requests' }).click();
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
  await expect(page.getByRole('heading', { name: 'The status of my events' })).toBeVisible();

  // TC-24: leaving and returning needs no submission, and the view survives a refresh.
  await page.getByRole('link', { name: 'Overview' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await page.getByRole('link', { name: 'My requests' }).click();
  await expect(page.getByRole('heading', { name: 'The status of my events' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'The status of my events' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Submit request' })).toHaveCount(0);
});

test('TC-CS-E07-S1-25 the navigation entry follows the active role', async ({ page }) => {
  // developer@example.test holds Event Organiser and Attendee (CS-E01-S4).
  await signIn(page, organiser, 'Event Organiser');
  await expect(page.getByRole('link', { name: 'My requests' })).toBeVisible();

  await page.getByLabel('Active role').selectOption('attendee');
  await expect(page.getByRole('link', { name: 'My requests' })).toHaveCount(0);

  await page.getByLabel('Active role').selectOption('event_organiser');
  await expect(page.getByRole('link', { name: 'My requests' })).toBeVisible();
});

test('TC-CS-E07-S1-26 the view holds together at a 390 x 844 viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'My requests' }).click();
  await expect(page.getByRole('heading', { name: 'The status of my events' })).toBeVisible();

  const overflows = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
  );
  expect(overflows).toBe(false);
});
