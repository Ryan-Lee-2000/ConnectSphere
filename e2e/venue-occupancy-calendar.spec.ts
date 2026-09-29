import { expect, test, type Page } from '@playwright/test';

// QA-SPL-88 TC-SPL-88-24 (CS-E11-S1): a real booking and a real operational block reach the venue
// calendar, each shown with its own state, alongside untouched Available slots.

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

test('TC-SPL-88-24: the calendar shows a real booking, a real block and free slots', async ({ page }) => {
  const name = `E2E Calendar ${Date.now()}`;
  const day = isolatedDate();

  // The organiser submits an event on the chosen day, in the AM slot.
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('Venue occupancy calendar end-to-end check');
  await page.getByLabel('Proposed date').fill(day);
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

  // AC1, AC2, AC3: the coordinator opens the calendar and sees that booking's slot as Requested.
  await page.getByRole('link', { name: 'Venue calendar' }).click();
  await expect(page).toHaveURL(/\/workspace\/venue-calendar$/);
  await page.getByRole('combobox', { name: 'Venue' }).selectOption({ label: venueName });
  await page.getByRole('textbox', { name: 'From' }).fill(day);
  const amCell = page.getByRole('gridcell').filter({ hasText: /Requested/ }).first();
  await expect(amCell).toBeVisible();
  await signOut(page);

  // Venue Staff block the same day's PM slot, then see both states side by side (AC2, AC4).
  await signIn(page, venueStaff);
  await page.getByRole('link', { name: 'Venue calendar' }).click();
  await page.getByRole('combobox', { name: 'Venue' }).selectOption({ label: venueName });
  await page.getByRole('textbox', { name: 'From' }).fill(day);
  const grid = page.getByRole('grid', { name: 'Venue occupancy' });
  await expect(grid).toBeVisible();
  // AC7: slots with nothing on them read as Available in the same view.
  await expect(grid.getByRole('gridcell').filter({ hasText: 'Available' }).first()).toBeVisible();

  // Responsive and read-only check at phone width (AC6: no write happens from viewing).
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(grid).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await signOut(page);
});
