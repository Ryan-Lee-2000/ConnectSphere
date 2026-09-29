import { expect, test, type Page } from '@playwright/test';

const organiser = { email: 'developer@example.test', password: 'LocalDemo123!' };
const manager = { email: 'operations.manager@example.test', password: 'LocalDemo123!' };
const coordinator = { email: 'event.coordinator@example.test', password: 'LocalDemo123!' };

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
  await page.getByLabel('Purpose').fill('Clarification response browser check');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByRole('radio', { name: /AM · 7am–12pm/ }).check();
  await page.getByLabel('Expected attendance').fill('120');
  await page.getByRole('button', { name: 'Submit event request' }).click();
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
}

// TC-SPL-66-01 and TC-SPL-66-02
test('[TC-SPL-66-01] responsible organiser answers and the coordinator resumes review', async ({
  page,
}) => {
  const name = `E2E Clarification response ${Date.now()}`;

  await signIn(page, organiser, 'Event Organiser');
  await submitRequest(page, name);
  await signOut(page);

  // The manager assigns the request through the same permanent workflow used by the team.
  await signIn(page, manager);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  const queued = page.getByRole('row').filter({ hasText: name });
  await queued.getByRole('button', { name: `Assign coordinator to ${name}` }).click();
  await page.getByLabel('Event Coordinator').selectOption({ label: 'Casey Lim' });
  await page.getByRole('button', { name: 'Confirm assignment' }).click();
  await signOut(page);

  await signIn(page, coordinator);
  await page.getByRole('link', { name: 'My assigned events' }).click();
  await page.getByRole('row').filter({ hasText: name }).getByRole('link', { name }).click();
  await page.getByRole('button', { name: 'Begin review' }).click();
  await page.getByLabel('Clarification for the Event Organiser').fill(
    'Please confirm that attendance remains 120 people.',
  );
  await page.getByRole('button', { name: 'Request clarification' }).click();
  await expect(page.getByRole('cell', { name: 'Returned for clarification' })).toBeVisible();
  await signOut(page);

  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'My requests' }).click();
  const organiserRow = page.getByRole('row').filter({ hasText: name });
  await organiserRow.getByRole('button', { name: 'Respond to clarification' }).click();
  await expect(page.getByText('Please confirm that attendance remains 120 people.')).toBeVisible();
  await page.getByLabel('Your response').fill('Attendance remains 120 people.');
  await page.getByRole('button', { name: 'Send response' }).click();
  await expect(page.getByRole('row').filter({ hasText: name })).toContainText('Under review');
  await signOut(page);

  // The assigned coordinator remains responsible and sees the retained answer in history.
  await signIn(page, coordinator);
  await page.getByRole('link', { name: 'My assigned events' }).click();
  const resumed = page.getByRole('row').filter({ hasText: name });
  await expect(resumed).toContainText('Under review');
  await resumed.getByRole('link', { name }).click();
  await expect(page.getByText('Attendance remains 120 people.', { exact: true })).toBeVisible();
  await expect(page.getByText(/Response from/)).toBeVisible();
});
