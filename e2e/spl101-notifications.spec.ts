import { expect, test, type Page } from '@playwright/test';

const organiser = { email: 'developer@example.test', password: 'LocalDemo123!' };
const manager = { email: 'operations.manager@example.test', password: 'LocalDemo123!' };
const coordinator = { email: 'event.coordinator@example.test', password: 'LocalDemo123!' };
const coordinatorName = 'Casey Lim';

async function signIn(page: Page, account: { email: string; password: string }, role?: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(account.email);
  await page.getByLabel('Password').fill(account.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  if (role) await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

async function submitRequest(page: Page, name: string) {
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('SPL-101 notification inbox end-to-end check');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByRole('radio', { name: /AM · 7am–12pm/ }).check();
  await page.getByLabel('Expected attendance').fill('80');
  await page.getByRole('button', { name: 'Submit event request' }).click();
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
}

// QA-SPL-101-041: the recorded manual flow for SPL-101 (notification inbox).
test('QA-SPL-101-041: an assignment notifies the coordinator, who sees, reads and opens it; others do not see it', async ({
  page,
}) => {
  const stamp = Date.now();
  const first = `E2E Notice A ${stamp}`;
  const second = `E2E Notice B ${stamp}`;

  // Two organiser submissions, so ordering can be checked later.
  await signIn(page, organiser, 'Event Organiser');
  await submitRequest(page, first);
  await submitRequest(page, second);
  await signOut(page);

  // The manager assigns the first request, then the second.
  await signIn(page, manager);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  for (const name of [first, second]) {
    await page.getByRole('button', { name: `Assign coordinator to ${name}` }).click();
    await page.locator('form.assignment-panel').getByLabel('Event Coordinator').selectOption({ label: coordinatorName });
    await page.getByRole('button', { name: 'Confirm assignment' }).click();
    await expect(page.getByText(`${coordinatorName} is now responsible for ${name}.`)).toBeVisible();
  }
  await signOut(page);

  // AC: the coordinator's inbox shows both notices, newest first, unread, linked to the event.
  await signIn(page, coordinator);
  await page.getByRole('link', { name: 'Notifications' }).click();
  await expect(page.getByRole('heading', { name: 'Notifications' })).toBeVisible();
  const items = page.locator('.notifications__item');
  await expect(items.nth(0)).toContainText(`You have been assigned to ${second}.`);
  await expect(items.nth(1)).toContainText(`You have been assigned to ${first}.`);
  await expect(items.nth(0)).toHaveClass(/notifications__item--unread/);
  const unreadBefore = Number(await page.locator('.notifications__count strong').innerText());
  expect(unreadBefore).toBeGreaterThanOrEqual(2);

  // Marking one notice read lowers the unread count by one and keeps the notice in the list.
  await page.getByRole('button', { name: `Mark as read: You have been assigned to ${second}.` }).click();
  await expect(page.locator('.notifications__count strong')).toHaveText(String(unreadBefore - 1));
  await expect(items.nth(0)).not.toHaveClass(/notifications__item--unread/);

  // Mark all read clears the count.
  await page.getByRole('button', { name: 'Mark all as read' }).click();
  await expect(page.locator('.notifications__count strong')).toHaveText('0');

  // Read state survives a reload (stored by the server, not the browser).
  await page.reload();
  await page.getByRole('link', { name: 'Notifications' }).click();
  await expect(page.locator('.notifications__count strong')).toHaveText('0');

  // The event link opens the event the notice is about.
  await page.getByRole('link', { name: second }).first().click();
  await expect(page).toHaveURL(/\/workspace\/assigned-events\/\d+$/);
  await signOut(page);

  // Privacy: the organiser never sees the coordinator's notices.
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'Notifications' }).click();
  await expect(page.getByRole('heading', { name: 'Notifications' })).toBeVisible();
  await expect(page.getByText(`You have been assigned to ${second}.`)).toHaveCount(0);
  await expect(page.getByText(`You have been assigned to ${first}.`)).toHaveCount(0);
});
