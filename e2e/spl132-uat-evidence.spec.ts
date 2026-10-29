import { expect, test, type Page } from '@playwright/test';

// SPL-132 recorded UAT, QA-SPL-132-200. Real local Auth and the fixture from
// scripts/prepare_e2e_spl132.py: "E2E SPL-132 Coastal Forum", Confirmed for 10 Mar 2031 (PM), with
// Approved bookings at its Harbour Hall, Breakout Studio and Garden Terrace, and two free rooms for
// replacements. Skipped unless SPL132_EVENT_ID names that fixture, so the ordinary suite never runs
// it. The local app uses slot timing, so the blocks and bookings are the PM slot.

const eventId = process.env.SPL132_EVENT_ID;
test.skip(!eventId, 'Requires the isolated SPL-132 real-Auth fixture.');
test.use({ video: { mode: 'on', size: { width: 1920, height: 1080 } }, viewport: { width: 1920, height: 1080 } });

const password = 'LocalDemo123!';
const coordinator = 'event.coordinator@example.test';
const venueStaff = 'venue.staff@example.test';
const organiser = 'developer@example.test';
const eventName = 'E2E SPL-132 Coastal Forum';
const hall = 'E2E SPL-132 Harbour Hall';
const studio = 'E2E SPL-132 Breakout Studio';
const terrace = 'E2E SPL-132 Garden Terrace';
const lakeside = 'E2E SPL-132 Lakeside Room';
const riverside = 'E2E SPL-132 Riverside Room';
const day = '2031-03-10';

async function caption(page: Page, text: string) {
  await page.evaluate(message => {
    let banner = document.getElementById('uat-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'uat-caption';
      banner.setAttribute('aria-hidden', 'true');
      Object.assign(banner.style, {
        position: 'fixed', left: '16px', right: '16px', bottom: '16px', zIndex: '2147483647', padding: '12px 16px',
        borderRadius: '8px', background: 'rgba(16, 32, 56, 0.92)', color: '#fff', font: '600 20px/1.35 system-ui',
        pointerEvents: 'none',
      });
      document.body.appendChild(banner);
    }
    banner.textContent = message;
  }, text);
  await page.waitForTimeout(2_600);
  await page.evaluate(() => document.getElementById('uat-caption')?.remove());
}

async function signIn(page: Page, email: string, role?: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace$/, { timeout: 15_000 });
  // A multi-role account chooses its workspace first (SPL-46).
  if (role) await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible({ timeout: 15_000 });
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

async function openNotifications(page: Page) {
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'Notifications' }).click();
  await expect(page.getByRole('heading', { name: 'Notifications', exact: true })).toBeVisible();
}

async function blockPm(page: Page, venue: string, reason: string) {
  // A fresh catalogue, so only the chosen venue's unavailability form is open.
  await page.goto('/workspace');
  await page.getByRole('link', { name: 'Venue catalogue' }).click();
  await page.getByRole('button', { name: new RegExp(venue) }).first().click();
  await page.getByLabel('Unavailable from').fill(day);
  await page.getByLabel('Unavailable through').fill(day);
  await page.getByLabel('PM · 1pm–6pm unavailable').check();
  await page.getByLabel('Reason for unavailability').fill(reason);
  await page.getByRole('button', { name: 'Record unavailability' }).click();
  await expect(page.getByText('Operational unavailability recorded. 1 active booking requires review.')).toBeVisible();
}

async function openRequest(page: Page, venue: string) {
  await page.getByRole('link', { name: 'Booking requests' }).click();
  const row = page.getByRole('row').filter({ hasText: eventName }).filter({ hasText: venue });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: `Review the booking request for ${eventName}` }).click();
  await expect(page).toHaveURL(/\/workspace\/venue-bookings\/\d+$/);
}

async function openEvent(page: Page) {
  await page.goto(`/workspace/assigned-events/${eventId}`);
  await expect(page.getByRole('heading', { name: eventName })).toBeVisible();
}

const card = (page: Page, venue: string) => page.getByRole('article', { name: venue, exact: true });
// The flag shows as "Marked for review." or as the recorded finding with the block's reason.
const flagged = /Marked for review|unavailable|Burst pipe|Storm damage|Fire alarm/;

// QA-SPL-132-200 | AC1-AC11 | BB
test('[QA-SPL-132-200] the coordinator replaces a venue that became unavailable', async ({ page }) => {
  test.setTimeout(900_000);

  await test.step('AC1: Venue Staff mark the Harbour Hall unavailable over its future booking', async () => {
    await signIn(page, venueStaff);
    await blockPm(page, hall, 'Burst pipe in the plant room');
    await caption(page, 'AC1: Venue Staff block the Harbour Hall for the afternoon of 10 Mar 2031; its one future booking is flagged');
    await signOut(page);
  });

  await test.step('AC10: the Confirmed event returns to Planning and the organiser is told', async () => {
    await signIn(page, organiser, 'Event Organiser');
    await openNotifications(page);
    const notice = page.getByRole('listitem').filter({ hasText: `${eventName} has returned to Planning because a booked venue became unavailable.` });
    await expect(notice).toHaveCount(1);
    await caption(page, 'AC10: the organiser is informed that the Confirmed event has returned to Planning');
    await signOut(page);
  });

  await test.step('AC2: the assigned coordinator gets one notice naming event, venue, time and reason', async () => {
    await signIn(page, coordinator);
    await openNotifications(page);
    const notice = page.getByRole('listitem').filter({ hasText: `Venue booking for ${eventName} at ${hall} on Mon 10 Mar 2031` });
    await expect(notice).toHaveCount(1);
    await expect(notice).toContainText('needs a replacement: Venue Staff marked the venue unavailable (Burst pipe in the plant room).');
    await caption(page, 'AC2: exactly one notice for the affected booking, with the event, venue, time and reason');
  });

  await test.step('AC3: the event and its other arrangements are unchanged', async () => {
    await openEvent(page);
    await expect(page.getByText('In planning').first()).toBeVisible();
    await expect(card(page, hall)).toContainText(flagged);
    await expect(card(page, hall)).toContainText('Status: Approved');
    await expect(card(page, studio)).toContainText('Status: Approved');
    await expect(card(page, terrace)).toContainText('Status: Approved');
    await caption(page, 'AC3: same date and times; nothing is cancelled. The hall is flagged; the studio and terrace are untouched');
  });

  await test.step('AC11: the event cannot be confirmed while the disruption is unresolved', async () => {
    const confirmation = page.getByRole('region', { name: 'Confirm this event' });
    await confirmation.scrollIntoViewIfNeeded();
    await expect(confirmation).toContainText(`Resolve the review flagged on the ${hall} booking.`);
    await expect(confirmation.getByRole('button', { name: 'Confirm event' })).toBeDisabled();
    await caption(page, 'AC11 refused: Confirm event is disabled until the flagged hall booking is resolved');
  });

  await test.step('AC4: the replacement search starts from the affected booking', async () => {
    await card(page, hall).getByRole('button', { name: 'Find a replacement venue' }).click();
    await expect(page.getByRole('note')).toContainText(`Finding a replacement for the ${hall} booking`);
    await expect(page.getByLabel('Singapore date')).toHaveValue(day);
    await expect(page.getByLabel('Expected attendance')).toHaveValue('80');
    await expect(page.getByLabel('PM · 1pm–6pm')).toBeChecked();
    await expect(page.getByLabel('Room layout')).toHaveValue('Theatre');
    await caption(page, 'AC4: the search is seeded with the hall booking\'s date, PM slot, 80 attendees, theatre and Projector');
  });

  await test.step('AC5: a linked replacement goes through the normal request', async () => {
    await page.getByRole('button', { name: 'Search venues' }).click();
    await page.getByRole('button', { name: new RegExp(lakeside) }).click();
    await page.getByRole('button', { name: 'Request replacement' }).click();
    await expect(page.getByText(/Booking requested/)).toBeVisible();
    await openEvent(page);
    await expect(card(page, hall)).toContainText(`Replacement requested: ${lakeside} (Requested).`);
    await expect(card(page, lakeside)).toContainText(`Replacement for the ${hall} booking.`);
    await expect(card(page, hall).getByRole('button', { name: 'Find a replacement venue' })).toHaveCount(0);
    await caption(page, 'AC5: the Lakeside request is linked to the hall booking and waits for Venue Staff; only one can be pending');
    await signOut(page);
  });

  await test.step('AC6: a rejected replacement leaves the original flagged; the coordinator asks again', async () => {
    await signIn(page, venueStaff);
    await openRequest(page, lakeside);
    await page.getByRole('button', { name: 'Reject booking' }).click();
    await page.getByLabel('Rejection reason').fill('Lakeside is closed for a private function.');
    await page.getByRole('button', { name: 'Confirm rejection' }).click();
    await expect(page.getByRole('status')).toContainText('Lakeside is closed for a private function.');
    await signOut(page);
    await signIn(page, coordinator);
    await openEvent(page);
    await expect(card(page, hall)).toContainText('Status: Approved');
    await expect(card(page, hall)).toContainText(`Replacement requested: ${lakeside} (Rejected).`);
    await caption(page, 'AC6: Lakeside was rejected; the hall booking is still Approved and flagged, so a new search is offered');
    await card(page, hall).getByRole('button', { name: 'Find a replacement venue' }).click();
    await page.getByRole('button', { name: 'Search venues' }).click();
    await page.getByRole('button', { name: new RegExp(riverside) }).click();
    await page.getByRole('button', { name: 'Request replacement' }).click();
    await expect(page.getByText(/Booking requested/)).toBeVisible();
    await caption(page, 'AC6: the coordinator requests the Riverside Room as the replacement instead');
    await signOut(page);
  });

  await test.step('AC7: approving the replacement releases the original once, keeping both histories', async () => {
    await signIn(page, venueStaff);
    await openRequest(page, riverside);
    await expect(page.getByRole('list', { name: 'Request details' })).toContainText(`${hall} booking`);
    await expect(page.getByRole('list', { name: 'Request details' })).toContainText('approving releases it');
    await caption(page, 'AC7: Venue Staff see which booking this replaces and that approving releases it');
    await page.getByRole('button', { name: 'Approve booking' }).click();
    await page.getByRole('button', { name: 'Confirm approval' }).click();
    await expect(page.getByRole('status')).toContainText('Approved by');
    await expect(page.getByRole('button', { name: 'Approve booking' })).toHaveCount(0);
    await caption(page, 'AC7: approved once; it can no longer be approved again');
    await signOut(page);
    await signIn(page, coordinator);
    await openEvent(page);
    await expect(card(page, hall)).toContainText('Status: Cancelled');
    await expect(card(page, hall)).toContainText(`Replaced by the ${riverside} booking`);
    await expect(card(page, riverside)).toContainText('Status: Approved');
    await expect(card(page, riverside)).toContainText(`Replacement for the ${hall} booking.`);
    await caption(page, 'AC7: the hall booking was released with a history entry; the link is kept on both bookings');
    await signOut(page);
  });

  await test.step('AC8: removing the unavailability clears the flag with no replacement', async () => {
    await signIn(page, venueStaff);
    await blockPm(page, studio, 'Fire alarm testing');
    await caption(page, 'AC8: Venue Staff block the Breakout Studio, which flags its booking');
    await page.getByRole('button', { name: 'Remove Fire alarm testing' }).click();
    await expect(page.getByRole('button', { name: 'Remove Fire alarm testing' })).toHaveCount(0);
    await caption(page, 'AC8: Venue Staff remove the block again');
    await blockPm(page, terrace, 'Storm damage to the roof');
    await signOut(page);
    await signIn(page, coordinator);
    await openEvent(page);
    await expect(card(page, studio)).toContainText('Status: Approved');
    await expect(card(page, studio)).not.toContainText('Fire alarm testing');
    await expect(card(page, studio).getByRole('button', { name: 'Find a replacement venue' })).toHaveCount(0);
    await caption(page, 'AC8: the studio booking is no longer flagged and needs no replacement');
  });

  await test.step('AC9: the coordinator withdraws a disrupted booking without replacing it', async () => {
    await expect(card(page, terrace)).toContainText(flagged);
    await caption(page, 'AC9: the terrace was blocked too; the event no longer needs that room');
    await card(page, terrace).getByRole('button', { name: 'Cancel booking' }).click();
    const form = page.getByRole('form', { name: `Cancel ${terrace} booking` });
    await form.getByLabel('Cancellation reason').fill('The breakout session moves into the Riverside Room.');
    await form.getByRole('button', { name: 'Confirm cancellation' }).click();
    await expect(card(page, terrace)).toContainText('Status: Cancelled');
    await caption(page, 'AC9: the terrace booking is cancelled with a reason, without a replacement');
  });

  await test.step('AC11: once resolved, the event is confirmed only when the coordinator confirms it', async () => {
    await openEvent(page);
    await expect(page.getByText('In planning').first()).toBeVisible();
    const confirmation = page.getByRole('region', { name: 'Confirm this event' });
    await confirmation.scrollIntoViewIfNeeded();
    await caption(page, 'AC11: still In planning: nothing reconfirmed it automatically');
    await confirmation.getByRole('button', { name: 'Confirm event' }).click();
    await page.getByRole('button', { name: 'Confirm', exact: true }).click();
    await expect(page.getByText('Event confirmed.').first()).toBeVisible();
    await caption(page, 'AC11: the coordinator confirms the event again with the Riverside Room and Breakout Studio');
  });
});
