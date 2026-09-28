import { expect, test, type Page } from '@playwright/test';

const organiser = { email: 'developer@example.test', password: 'LocalDemo123!' };
const manager = { email: 'operations.manager@example.test', password: 'LocalDemo123!' };
const coordinator = { email: 'event.coordinator@example.test', password: 'LocalDemo123!' };
const venueStaff = { email: 'venue.staff@example.test', password: 'LocalDemo123!' };
const NOTE = 'Confirmed with the hall manager';

async function signIn(page: Page, account: { email: string; password: string }, role?: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(account.email);
  await page.getByLabel('Password').fill(account.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  // Each sign-in verifies the session with Supabase; five in one journey need a wider wait.
  await expect(page).toHaveURL(/\/workspace$/, { timeout: 15_000 });
  if (role) await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible({ timeout: 15_000 });
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

test('TC-SPL-81-24 and TC-SPL-81-25: Venue Staff approve a request and the coordinator sees it', async ({ page }) => {
  // Five sign-ins across four roles: longer than the default budget for one journey.
  test.setTimeout(180_000);
  const name = `E2E Venue Approval ${Date.now()}`;

  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('Venue booking approval end-to-end check');
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
  const eventUrl = page.url();
  await page.getByRole('button', { name: 'Begin review' }).click();
  await expect(page.getByText('Review started.')).toBeVisible();
  await page.getByRole('button', { name: 'Approve request' }).click();
  await expect(page.getByText('Request approved. Event planning can begin.')).toBeVisible();
  await page.goto(eventUrl);
  await expect(page.getByRole('button', { name: 'Find venues', exact: true })).toBeVisible({ timeout: 15_000 });
  await page.getByRole('button', { name: 'Find venues', exact: true }).click();
  await page.getByRole('button', { name: 'Search venues', exact: true }).click();
  const suitable = page.locator('.venue-availability__card').filter({ hasText: 'Suitable for this event' });
  const venue = (await suitable.first().locator('strong').first().textContent())?.trim() ?? '';
  await suitable.first().click();
  const created = page.waitForResponse(response => response.request().method() === 'POST'
    && /\/api\/event-requests\/\d+\/venue-bookings$/.test(new URL(response.url()).pathname));
  await page.getByRole('button', { name: 'Request booking' }).click();
  const bookingId = (await (await created).json()).booking.id as number;
  await expect(page.getByRole('region', { name: 'Venue booking request' })).toContainText('Status: Requested');
  await signOut(page);

  // TC-SPL-81-25: the review page at phone width, operated by keyboard.
  await signIn(page, venueStaff);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/workspace/venue-bookings/${bookingId}`);
  // A direct page load re-runs the session and role checks before the page renders.
  await expect(page.getByRole('heading', { name: 'Review venue-booking request' })).toBeVisible({ timeout: 15_000 });
  const details = page.getByRole('list', { name: 'Request details' });
  await expect(details).toContainText(name);
  await expect(details).toContainText(venue);
  await expect(details).toContainText('Casey Lim');
  await expect(details).toContainText('Requested');
  await page.getByLabel('Approval note (optional)').fill(NOTE);
  await page.getByRole('button', { name: 'Approve booking' }).focus();
  await page.keyboard.press('Enter');
  await page.getByRole('button', { name: 'Confirm approval' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('status')).toContainText('Approved by Valerie Tan');
  await expect(details).toContainText('Approved');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await signOut(page);

  // The coordinator sees the outcome in the SPL-79 history.
  await page.setViewportSize({ width: 1280, height: 800 });
  await signIn(page, coordinator);
  await page.goto(eventUrl);
  const panel = page.getByRole('region', { name: 'Venue booking request' });
  await expect(panel).toContainText('Status: Approved', { timeout: 15_000 });
  const history = panel.getByRole('list', { name: 'History' });
  await expect(history.getByRole('listitem')).toHaveCount(2, { timeout: 15_000 });
  await expect(history.getByRole('listitem').nth(1)).toContainText('Approved');
  await expect(history.getByRole('listitem').nth(1)).toContainText('Valerie Tan');
  await expect(history.getByRole('listitem').nth(1)).toContainText(NOTE);
});
