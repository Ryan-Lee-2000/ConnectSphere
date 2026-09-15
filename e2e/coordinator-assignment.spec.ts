import { expect, test, type Page } from '@playwright/test';

const organiser = { email: 'developer@example.test', password: 'LocalDemo123!' };
const manager = { email: 'operations.manager@example.test', password: 'LocalDemo123!' };
const coordinatorName = 'Local Event Coordinator';

async function signIn(page: Page, account: { email: string; password: string }, role?: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(account.email);
  await page.getByLabel('Password').fill(account.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);

  if (role) {
    await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
  }
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
  await page.getByLabel('Purpose').fill('Coordinator assignment end-to-end check');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByLabel('Start time').fill('09:00');
  await page.getByLabel('End time').fill('11:30');
  await page.getByLabel('Expected attendance').fill('120');
  await page.getByRole('button', { name: 'Submit request' }).click();
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
}

test('TC-59-01, TC-60-01 and AC6: a submitted request is queued, assigned, and shown to its organiser', async ({
  page,
}) => {
  const name = `E2E Assignment ${Date.now()}`;

  // The organiser submits, and sees nobody is responsible yet.
  await signIn(page, organiser, 'Event Organiser');
  await submitRequest(page, name);
  await expect(page.getByRole('row').filter({ hasText: name })).toContainText('Not assigned yet');
  await signOut(page);

  // TC-59-01: the manager finds that request waiting in the queue.
  await signIn(page, manager);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  const queued = page.getByRole('row').filter({ hasText: name });
  await expect(queued).toBeVisible();

  // TC-60-01: assigning an active coordinator confirms and clears the request from the queue.
  await queued.getByRole('button', { name: `Assign coordinator to ${name}` }).click();
  await page.getByLabel('Event Coordinator').selectOption({ label: coordinatorName });
  await page.getByRole('button', { name: 'Confirm assignment' }).click();
  await expect(page.getByText(`${coordinatorName} is now responsible for ${name}.`)).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0);
  await signOut(page);

  // CS-E05-S2 AC6: the organiser sees who is responsible, and that review has begun.
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'My requests' }).click();
  const organiserRow = page.getByRole('row').filter({ hasText: name });
  await expect(organiserRow).toContainText('Under review');
  await expect(organiserRow).toContainText(coordinatorName);
});

test('TC-59-06: a role without Event Operations Manager is never offered the queue', async ({
  page,
}) => {
  await signIn(page, organiser, 'Event Organiser');

  await expect(page.getByRole('link', { name: 'Coordinator assignment' })).toHaveCount(0);

  // Reaching the path directly returns the organiser to their own workspace.
  await page.goto('/workspace/assignments');
  await expect(page.getByRole('heading', { name: 'Events awaiting a coordinator' })).toHaveCount(0);
});
