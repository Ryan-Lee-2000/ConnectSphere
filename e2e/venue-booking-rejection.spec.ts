import { expect, test, type Page } from '@playwright/test';

// QA-SPL-82 TC-SPL-82-20 (CS-E10-S4): Venue Staff reject a pending booking from SPL-80's queue with
// a reason; it leaves the queue, and the assigned Event Coordinator can see the outcome and reason.

const organiser = { email: 'developer@example.test', password: 'LocalDemo123!' };
const manager = { email: 'operations.manager@example.test', password: 'LocalDemo123!' };
const coordinator = { email: 'event.coordinator@example.test', password: 'LocalDemo123!' };
const venueStaff = { email: 'venue.staff@example.test', password: 'LocalDemo123!' };

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

test('TC-SPL-82-20: Venue Staff reject a pending request, and the coordinator sees the reason', async ({ page }) => {
  const name = `E2E Rejection ${Date.now()}`;
  const reason = 'The requested slot conflicts with scheduled maintenance.';
  const suggestion = 'The Riverside Room is available the same afternoon.';

  // The organiser submits the event.
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('Venue booking rejection end-to-end check');
  await page.getByLabel('Proposed date').fill(isolatedDate());
  await page.getByRole('radio', { name: /AM · 7am–12pm/ }).check();
  await page.getByLabel('Expected attendance').fill('120');
  await page.getByRole('button', { name: 'Submit event request' }).click();
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
  await signOut(page);

  // The manager assigns the coordinator.
  await signIn(page, manager);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  await page.getByRole('row').filter({ hasText: name })
    .getByRole('button', { name: `Assign coordinator to ${name}` }).click();
  await page.getByLabel('Event Coordinator').selectOption({ label: 'Casey Lim' });
  await page.getByRole('button', { name: 'Confirm assignment' }).click();
  await expect(page.getByText(`Casey Lim is now responsible for ${name}.`)).toBeVisible();
  await signOut(page);

  // The coordinator takes the event to Planning and requests a venue (SPL-77).
  await signIn(page, coordinator);
  await page.getByRole('link', { name: 'My assigned events' }).click();
  await page.getByRole('row').filter({ hasText: name }).getByRole('link', { name }).click();
  const eventUrl = page.url();
  await page.getByRole('button', { name: 'Begin review' }).click();
  await expect(page.getByText('Review started.')).toBeVisible();
  await page.getByRole('button', { name: 'Approve request' }).click();
  await expect(page.getByText('Request approved. Event planning can begin.')).toBeVisible();
  await page.getByRole('button', { name: 'Find venues', exact: true }).click();
  await page.getByRole('button', { name: 'Search venues', exact: true }).click();
  const suitable = page.locator('.venue-availability__card').filter({ hasText: 'Suitable for this event' });
  await suitable.first().click();
  await page.getByRole('button', { name: 'Request booking' }).click();
  await expect(page.getByRole('region', { name: 'Venue booking request' })).toContainText('Status: Requested');
  await signOut(page);

  // AC1, AC7: Venue Staff find the request in their queue and reject it with a reason.
  await signIn(page, venueStaff);
  await page.getByRole('link', { name: 'Booking requests' }).click();
  const row = page.getByRole('row').filter({ hasText: name });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: `Review the booking request for ${name}` }).click();
  await expect(page).toHaveURL(/\/workspace\/venue-bookings\/\d+$/);
  await page.getByRole('button', { name: 'Reject booking' }).click();
  await page.getByLabel('Rejection reason').fill(reason);
  await page.getByLabel('Alternative suggestion (optional)').fill(suggestion);
  await page.getByRole('button', { name: 'Confirm rejection' }).click();
  await expect(page.getByRole('status')).toContainText('Rejected by Valerie Tan');
  await expect(page.getByRole('status')).toContainText(reason);

  // AC1: a rejected request no longer shows in the queue.
  await page.getByRole('link', { name: 'Booking requests' }).click();
  await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0);
  await signOut(page);

  // AC5: the assigned coordinator can retrieve the outcome and reason, through the same panel
  // and history SPL-78/79 already built — no new UI was needed for this.
  await signIn(page, coordinator);
  await page.goto(eventUrl);
  const panel = page.getByRole('region', { name: 'Venue booking request' });
  await expect(panel).toContainText('Status: Rejected');
  await expect(panel).toContainText(reason);
  await signOut(page);
});
