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

// SPL-79 AC-1,2,3,6 Test-21
// SPL-79 AC-NA Test-22
test('TC-SPL-79-21 and TC-SPL-79-22: the event page shows the current status, history and earlier request', async ({ page }) => {
  const name = `E2E Venue Status ${Date.now()}`;

  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('Venue booking status end-to-end check');
  await page.getByLabel('Proposed date').fill(isolatedDate());
  await page.getByRole('radio', { name: /AM · 7am–12pm/ }).check();
  // Two venues fit 60 guests, allowing this journey to prove an earlier withdrawn request and
  // a separate current request without relying on the catalogue card's collapse animation.
  await page.getByLabel('Expected attendance').fill('60');
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

  // AC6 on screen: an event in Planning with nothing requested yet says so.
  await page.goto(eventUrl);
  const eventPanel = page.getByRole('region', { name: 'Venue booking request' });
  await expect(eventPanel).toContainText('No venue-booking request has been made for this event yet.');

  // Request a venue, withdraw it, then request a venue again (SPL-77, SPL-78).
  await page.getByRole('button', { name: 'Find venues', exact: true }).click();
  await page.getByRole('button', { name: 'Search venues', exact: true }).click();
  const suitable = page.locator('.venue-availability__card').filter({ hasText: 'Suitable for this event' });
  const firstVenue = (await suitable.first().locator('strong').first().textContent())?.trim() ?? '';
  await suitable.first().click();
  await page.getByRole('button', { name: 'Request booking' }).click();
  const searchPanel = page.getByRole('region', { name: 'Venue booking request' });
  await expect(searchPanel).toContainText('Status: Requested');
  await searchPanel.getByRole('button', { name: 'Withdraw request' }).click();
  await searchPanel.getByRole('button', { name: 'Confirm withdrawal' }).click();
  await expect(searchPanel).toContainText('Status: Withdrawn');
  // The history refreshes in place after the withdrawal.
  await expect(searchPanel.getByRole('list', { name: 'History' })).toContainText('Withdrawn');
  // Return to the event before a replacement search. This is the normal coordinator flow and
  // remounts the details panel after withdrawal instead of retaining an in-flight layout lookup.
  await page.goto(eventUrl);
  await page.getByRole('button', { name: 'Find venues', exact: true }).click();
  await page.getByRole('button', { name: 'Search venues', exact: true }).click();
  const replacementVenue = page.locator('.venue-availability__card').filter({ hasText: 'Suitable for this event' }).nth(1);
  const replacementName = (await replacementVenue.locator('strong').first().textContent())?.trim() ?? '';
  await expect(replacementVenue).toBeVisible();
  await replacementVenue.click();
  const replacementDetail = page.locator('.venue-availability__detail').filter({ hasText: replacementName });
  await expect(replacementDetail).toBeVisible();
  await replacementDetail.getByRole('button', { name: 'Request booking' }).click();
  await expect(searchPanel).toContainText('Status: Requested');

  // TC-SPL-79-22: the event page, at phone width.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(eventUrl);
  await expect(eventPanel).toContainText('Status: Requested');
  const history = eventPanel.getByRole('list', { name: 'History' });
  await expect(history.getByRole('listitem')).toHaveCount(1);
  await expect(history).toContainText('Requested');
  await expect(history).toContainText('Casey Lim');
  const earlier = eventPanel.getByRole('list', { name: 'Earlier requests' });
  await expect(earlier).toContainText(firstVenue);
  await expect(earlier).toContainText('Withdrawn');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  // Keyboard: the panel's Withdraw action is reachable from focus.
  await eventPanel.getByRole('button', { name: 'Withdraw request' }).focus();
  await expect(eventPanel.getByRole('button', { name: 'Withdraw request' })).toBeFocused();
});
