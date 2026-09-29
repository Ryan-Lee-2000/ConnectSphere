import { expect, test, type Page } from '@playwright/test';

const organiser = { email: 'developer@example.test', password: 'LocalDemo123!' };
const manager = { email: 'operations.manager@example.test', password: 'LocalDemo123!' };
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
  if (role) await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

test('TC-SPL-69-14 an assigned coordinator records and retains a withdrawal', async ({ page }) => {
  const name = `E2E Withdrawal ${Date.now()}`;
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);

  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('Withdrawal end-to-end check');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByRole('radio', { name: /AM · 7am–12pm/ }).check();
  await page.getByLabel('Expected attendance').fill('40');
  await page.getByRole('button', { name: 'Submit event request' }).click();
  await signOut(page);

  await signIn(page, manager);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  const queued = page.getByRole('row').filter({ hasText: name });
  await queued.getByRole('button', { name: `Assign coordinator to ${name}` }).click();
  await page.getByLabel('Event Coordinator').selectOption({ label: 'Casey Lim' });
  await page.getByRole('button', { name: 'Confirm assignment' }).click();
  await expect(page.getByText(`Casey Lim is now responsible for ${name}.`)).toBeVisible();
  await signOut(page);

  await signIn(page, coordinator);
  await page.getByRole('link', { name: 'My assigned events' }).click();
  await page.getByRole('row').filter({ hasText: name }).getByRole('link', { name }).click();
  await page.getByRole('button', { name: 'Record withdrawal' }).click();
  await page.getByLabel('Withdrawal note (optional)').fill('Organiser withdrew by email.');
  await page.getByRole('button', { name: 'Confirm withdrawal' }).click();

  await expect(
    page.getByText('Withdrawal recorded. This request will not be reviewed further.'),
  ).toBeVisible();
  await expect(page.getByRole('cell', { name: 'Withdrawn' })).toBeVisible();
  await expect(page.getByRole('row', { name: /Withdrawal recorded by/ })).toContainText('Casey Lim');
  await expect(page.getByRole('row', { name: /Withdrawal note/ })).toContainText(
    'Organiser withdrew by email.',
  );
  await expect(page.getByRole('button', { name: 'Begin review' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Record withdrawal' })).toHaveCount(0);
});
