import { expect, test, type Page } from '@playwright/test';

// SPL-131 recorded UAT, TC-SPL-131-58. Real local Auth and the seeded fixture "E2E SPL-131
// Leadership Summit" (Planning, 150 attendees, theatre, Projector, no venue yet). One scripted step
// per acceptance criterion, in the written order, each captioned on screen at a 390px phone width.
// The local app runs with 15-minute timing off, so bookings use the event's saved PM slot; the
// per-booking start/end times of AC2 are proved by the API cases TC-SPL-131-09/10/19/26 instead.

const password = 'LocalDemo123!';
const coordinator = 'event.coordinator@example.test';
const venueStaff = 'venue.staff@example.test';
const lead = 'operations.manager@example.test';
const eventName = 'E2E SPL-131 Leadership Summit';
const hall = 'E2E SPL-131 Grand Hall';
const studio = 'E2E SPL-131 Breakout Studio';

test.use({ video: 'on', viewport: { width: 390, height: 844 } });

// Keep each visible state on screen long enough to read in the captured video.
const evidencePause = (page: Page) => page.waitForTimeout(1_800);

async function caption(page: Page, text: string) {
  await page.evaluate(message => {
    let banner = document.getElementById('uat-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'uat-caption';
      banner.setAttribute('aria-hidden', 'true');
      Object.assign(banner.style, {
        position: 'fixed', left: '8px', right: '8px', bottom: '8px', zIndex: '2147483647', padding: '10px 12px',
        borderRadius: '8px', background: 'rgba(16, 32, 56, 0.92)', color: '#fff', font: '600 14px/1.35 system-ui',
        pointerEvents: 'none',
      });
      document.body.appendChild(banner);
    }
    banner.textContent = message;
  }, text);
  await evidencePause(page);
}

async function signIn(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

async function openEvent(page: Page) {
  await page.getByRole('link', { name: 'My assigned events' }).click();
  await page.getByRole('link', { name: eventName }).click();
  await expect(page.getByRole('heading', { name: eventName })).toBeVisible();
}

async function search(page: Page, attendance: string) {
  await page.getByLabel('Expected attendance').fill(attendance);
  await page.getByRole('button', { name: 'Search venues' }).click();
  await expect(page.getByLabel('Available venue results')).toBeVisible();
}

const arrangement = (page: Page, venue: string) =>
  page.getByRole('list', { name: 'Venue bookings' }).getByRole('article', { name: venue });

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test('TC-SPL-131-58 one event holds, checks and changes several independent venue bookings', async ({ page }) => {
  test.setTimeout(240_000);
  let eventPath = '';

  await test.step('AC1: the assigned coordinator requests the plenary hall for the whole event', async () => {
    await signIn(page, coordinator);
    await openEvent(page);
    eventPath = new URL(page.url()).pathname;
    await caption(page, 'AC1: Leadership Summit (150, Planning) has no venue yet');
    await page.getByRole('button', { name: 'Find venues' }).click();
    await search(page, '150');
    await page.getByRole('button', { name: new RegExp(hall) }).click();
    await caption(page, `AC1: request ${hall} for all 150 attendees`);
    await page.getByRole('button', { name: 'Request booking' }).click();
    await expect(page.getByText(`Booking requested for ${hall}.`)).toBeVisible();
    await expect(arrangement(page, hall)).toBeVisible();
  });

  await test.step('AC2/AC3: a breakout is checked on its own attendee count, layout and facilities', async () => {
    await caption(page, 'AC2: search for a 20-person breakout - attendance stays 150 on the event');
    await search(page, '20');
    await page.getByRole('button', { name: new RegExp(studio) }).click();
    const attendees = page.getByLabel('Attendees in this venue');
    await expect(attendees).toHaveValue('20');
    await caption(page, 'AC3 (refused): 41 attendees - no layout at the studio holds them');
    await attendees.fill('41');
    await expect(page.getByText(`No layout at ${studio} holds 41 guests, so it cannot be requested.`)).toBeVisible();
    await evidencePause(page);
    await caption(page, 'AC2 (refused): more than the event\'s 150 attendees is not allowed');
    await attendees.fill('151');
    await expect(page.getByText('Enter between 1 and 150 attendees for this venue.')).toBeVisible();
    await evidencePause(page);
    await attendees.fill('20');
    await page.getByLabel('Booking layout').selectOption('classroom');
    await expect(page.getByRole('checkbox', { name: 'Projector' })).toBeChecked();
    await caption(page, 'AC2/AC3: 20 of the 150 attendees, classroom for 30, own facilities - capacities never added');
    await page.getByRole('button', { name: 'Request booking' }).click();
    await expect(page.getByText(`Booking requested for ${studio}.`)).toBeVisible();
    await expectNoHorizontalOverflow(page);
  });

  await test.step('AC4/AC5: the hall is no longer offered to this event for the same time', async () => {
    await search(page, '20');
    await caption(page, 'AC5: the event already holds the hall at this time, so it is not offered again');
    await expect(page.getByRole('button', { name: new RegExp(hall) })).toHaveCount(0);
    await expect(arrangement(page, hall).getByText('Status: Requested')).toBeVisible();
    await evidencePause(page);
  });

  await test.step('AC8/AC9: the event page lists both bookings, first booking first, each with history', async () => {
    await page.goto(eventPath);
    await expect(page.getByText('Venue bookings · 2')).toBeVisible();
    const items = page.getByRole('list', { name: 'Venue bookings' }).getByRole('article');
    await expect(items.nth(0)).toContainText(hall);
    await expect(items.nth(0)).toContainText('150 attendees');
    await expect(items.nth(1)).toContainText(studio);
    await expect(items.nth(1)).toContainText('20 attendees');
    await items.nth(0).scrollIntoViewIfNeeded();
    await caption(page, 'AC8/AC9: both bookings, oldest first, each with venue, attendees, status and history');
    await expect(page.getByRole('list', { name: `History of ${studio} booking` })).toContainText('Requested');
    await signOut(page);
  });

  await test.step('AC8/AC6: Venue Staff see two separate requests and approve only the hall', async () => {
    await signIn(page, venueStaff);
    await page.getByRole('link', { name: 'Booking requests' }).click();
    const rows = page.getByRole('row').filter({ hasText: eventName });
    await expect(rows).toHaveCount(2);
    await caption(page, 'AC8: Venue Staff review each venue request as its own item');
    await rows.filter({ hasText: hall }).getByRole('button', { name: `Review the booking request for ${eventName}` }).click();
    await page.getByRole('button', { name: 'Approve booking' }).click();
    await page.getByRole('button', { name: 'Confirm approval' }).click();
    await expect(page.getByText('Approved', { exact: false }).first()).toBeVisible();
    await caption(page, 'AC6: approving the hall changes only the hall');
    await signOut(page);
  });

  await test.step('AC7/AC6: the coordinator cancels the hall with a reason; the studio is unchanged', async () => {
    await signIn(page, coordinator);
    await page.goto(eventPath);
    await expect(page.getByRole('heading', { name: eventName, exact: true })).toBeVisible({ timeout: 30_000 });
    const hallCard = arrangement(page, hall);
    await expect(hallCard.getByText('Status: Approved')).toBeVisible();
    await hallCard.getByRole('button', { name: 'Cancel booking' }).click();
    await caption(page, 'AC7 (refused): a blank reason is not accepted');
    await hallCard.getByLabel('Cancellation reason').fill('   ');
    await hallCard.getByRole('button', { name: 'Confirm cancellation' }).click();
    await expect(hallCard.getByRole('alert')).toHaveText('Give a reason for cancelling this venue booking.');
    await evidencePause(page);
    await hallCard.getByLabel('Cancellation reason').fill('Plenary moved to the auditorium.');
    await caption(page, 'AC7: cancel the approved hall with a reason');
    await hallCard.getByRole('button', { name: 'Confirm cancellation' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'booking cancelled' })).toBeVisible();
    await expect(arrangement(page, hall).getByText('Status: Cancelled')).toBeVisible();
    await expect(page.getByRole('list', { name: `History of ${hall} booking` })).toContainText('Plenary moved to the auditorium.');
    await expect(page.getByRole('list', { name: `History of ${hall} booking` })).toContainText('Casey Lim');
    await expect(arrangement(page, studio).getByText('Status: Requested')).toBeVisible();
    await arrangement(page, hall).scrollIntoViewIfNeeded();
    await caption(page, 'AC7/AC6: history records the reason, who and when; the studio keeps its request');
    await expectNoHorizontalOverflow(page);
    await signOut(page);
  });

  await test.step('AC10: the Event Coordinator Lead cannot manage the event\'s venue bookings', async () => {
    await signIn(page, lead);
    await expect(page.getByRole('link', { name: 'My assigned events' })).toHaveCount(0);
    await page.goto(eventPath);
    await expect(page.getByRole('list', { name: 'Venue bookings' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Cancel booking' })).toHaveCount(0);
    await caption(page, 'AC10 (refused): the Lead has no assigned-event view and no booking actions');
  });
});
