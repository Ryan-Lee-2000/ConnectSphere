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

// A booking holds real local venue time, so each run uses its own far-future date.
function isolatedDate() {
  const days = 400 + Math.floor(Math.random() * 3000);
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

// SPL-78 AC-1,3,5 Test-24
// SPL-78 AC-NA Test-25
test('TC-SPL-78-24 and TC-SPL-78-25: a coordinator withdraws a Requested booking, frees the venue and requests it again', async ({ page }) => {
  const name = `E2E Venue Withdrawal ${Date.now()}`;

  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('Venue booking withdrawal end-to-end check');
  await page.getByLabel('Proposed date').fill(isolatedDate());
  await page.getByRole('radio', { name: /AM · 7am–12pm/ }).check();
  await page.getByLabel('Expected attendance').fill('120');
  await page.getByRole('button', { name: 'Submit event request' }).click();
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
  await signOut(page);

  await signIn(page, manager);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  await page.getByRole('row').filter({ hasText: name }).getByRole('button', { name: `Assign coordinator to ${name}` }).click();
  await page.getByLabel('Event Coordinator').selectOption({ label: 'Casey Lim' });
  await page.getByRole('button', { name: 'Confirm assignment' }).click();
  await expect(page.getByText(`Casey Lim is now responsible for ${name}.`)).toBeVisible();
  await signOut(page);

  await signIn(page, coordinator);
  await page.getByRole('link', { name: 'My assigned events' }).click();
  await page.getByRole('row').filter({ hasText: name }).getByRole('link', { name }).click();
  await page.getByRole('button', { name: 'Begin review' }).click();
  await expect(page.getByText('Review started.')).toBeVisible();
  await page.getByRole('button', { name: 'Approve request' }).click();
  await expect(page.getByText('Request approved. Event planning can begin.')).toBeVisible();
  await page.getByRole('button', { name: 'Find venues', exact: true }).click();

  // TC-SPL-78-25: usable at phone width.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Search venues', exact: true }).click();
  const suitable = page.locator('.venue-availability__card').filter({ hasText: 'Suitable for this event' }).first();
  await expect(suitable).toBeVisible();
  const venueName = (await suitable.locator('strong').first().textContent())?.trim() ?? '';
  const venueCard = page.locator('.venue-availability__card').filter({ hasText: venueName });
  await suitable.click();
  await page.getByRole('button', { name: 'Request booking' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Booking requested' })).toBeVisible();
  await expect(venueCard).toHaveCount(0);

  // TC-SPL-78-24: the panel shows the Requested booking; withdraw it, by keyboard, after confirming.
  const panel = page.getByRole('region', { name: 'Venue booking request' });
  await expect(panel).toContainText(venueName);
  await expect(panel).toContainText('Status: Requested');
  await panel.getByRole('button', { name: 'Withdraw request' }).focus();
  await page.keyboard.press('Enter');
  await expect(panel.getByRole('group', { name: 'Confirm withdrawal' })).toBeVisible();
  await panel.getByRole('button', { name: 'Confirm withdrawal' }).focus();
  await page.keyboard.press('Enter');

  await expect(panel.getByRole('status')).toContainText('Request withdrawn');
  await expect(panel).toContainText('Status: Withdrawn');
  await expect(panel).toContainText('Withdrawn by Casey Lim');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);

  // AC3 and AC5: the venue is back in the refreshed search and can be requested again.
  await expect(venueCard).toHaveCount(1);
  await venueCard.click();
  await page.getByRole('button', { name: 'Request booking' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Booking requested' })).toBeVisible();
  await expect(panel).toContainText('Status: Requested');
});
