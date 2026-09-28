import { expect, test, type Page } from '@playwright/test';

// QA-SPL-80 TC-SPL-80-18 (CS-E10-S2): a requested booking reaches Venue Staff's queue and opens
// for review, with the event information a booking decision needs.

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

test('TC-SPL-80-18: a requested booking reaches the Venue Staff queue and opens for review', async ({ page }) => {
  const name = `E2E Pending Requests ${Date.now()}`;
  const purpose = 'Pending booking queue end-to-end check';

  // The organiser submits the event.
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill(purpose);
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
  const venueName = (await suitable.first().locator('strong').first().textContent())?.trim() ?? '';
  await suitable.first().click();
  await page.getByRole('button', { name: 'Request booking' }).click();
  await expect(page.getByRole('region', { name: 'Venue booking request' })).toContainText('Status: Requested');
  await signOut(page);

  // AC1, AC2: Venue Staff find the request waiting in their queue.
  await signIn(page, venueStaff);
  await page.getByRole('link', { name: 'Booking requests' }).click();
  await expect(page).toHaveURL(/\/workspace\/booking-requests$/);
  const row = page.getByRole('row').filter({ hasText: name });
  await expect(row).toBeVisible();
  await expect(row).toContainText(venueName);
  await expect(row).toContainText('Casey Lim');

  // AC3: opening the request shows the event information a booking decision needs.
  await row.getByRole('button', { name: `Review the booking request for ${name}` }).click();
  await expect(page).toHaveURL(/\/workspace\/venue-bookings\/\d+$/);
  const eventDetails = page.getByRole('list', { name: 'Event details' });
  await expect(eventDetails).toContainText(purpose);
  await expect(eventDetails).toContainText('120');
  // AC4: nothing attendee-facing reaches this page.
  await expect(page.locator('body')).not.toContainText('registration');

  // Responsive and keyboard check at phone width.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/workspace/booking-requests');
  await expect(page.getByRole('row').filter({ hasText: name })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  const review = page.getByRole('row').filter({ hasText: name })
    .getByRole('button', { name: `Review the booking request for ${name}` });
  await review.focus();
  await expect(review).toBeFocused();
  await signOut(page);

  // AC5: once the coordinator withdraws it, the request leaves the queue. The queue is
  // operator-wide, so this asserts that this request is gone rather than that the queue is
  // empty — other specs leave their own pending requests behind in the same database.
  await signIn(page, coordinator);
  await page.goto(eventUrl);
  const panel = page.getByRole('region', { name: 'Venue booking request' });
  await panel.getByRole('button', { name: 'Withdraw request' }).click();
  await panel.getByRole('button', { name: 'Confirm withdrawal' }).click();
  await expect(panel).toContainText('Status: Withdrawn');
  await signOut(page);

  await signIn(page, venueStaff);
  await page.getByRole('link', { name: 'Booking requests' }).click();
  await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0);
});
