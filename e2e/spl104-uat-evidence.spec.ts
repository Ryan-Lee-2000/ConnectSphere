import { expect, test, type Page } from '@playwright/test';

// SPL-104 recorded UAT, QA-SPL-104-200. Real local Auth and an isolated fixture event
// "SPL-104 QA Coastal Forum" (Planning, assigned to Casey Lim, 13:00-18:00 on a far-future date).
// Skipped unless SPL104_EVENT_ID names that event, so the ordinary browser suite never runs it.

const eventId = process.env.SPL104_EVENT_ID;
test.skip(!eventId, 'Requires the isolated SPL-104 real-Auth fixture.');

const password = 'LocalDemo123!';
const coordinator = 'event.coordinator@example.test';
const venueStaff = 'venue.staff@example.test';
const eventName = `SPL-104 QA Coastal Forum${process.env.SPL104_SUFFIX ?? ''}`;

async function caption(page: Page, text: string) {
  await page.evaluate(message => {
    let banner = document.getElementById('uat-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'uat-caption';
      banner.setAttribute('aria-hidden', 'true');
      Object.assign(banner.style, {
        position: 'fixed', left: '8px', right: '8px', bottom: '8px', zIndex: '2147483647', padding: '10px 12px',
        borderRadius: '8px', background: 'rgba(16, 32, 56, 0.92)', color: '#fff', font: '600 16px/1.35 system-ui',
        pointerEvents: 'none',
      });
      document.body.appendChild(banner);
    }
    banner.textContent = message;
  }, text);
  await page.waitForTimeout(2_200);
}

async function signIn(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

async function openNotifications(page: Page) {
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'Notifications' }).click();
  await expect(page.getByRole('heading', { name: 'Notifications', exact: true })).toBeVisible();
}

const eventNotices = (page: Page) => page.getByRole('listitem').filter({ hasText: eventName });
// Seeded catalogue venues with one setup and one turnaround slot, so AC5's occupancy is visible.
const first = 'Harbour Hall';
const second = 'Grand Ballroom';
const venueCard = (page: Page, venue: string) => page.locator('.venue-availability__card').filter({
  has: page.getByText(venue, { exact: true }),
});
const bookingCard = (page: Page, venue: string) => page.locator('.venue-arrangements__item').filter({
  has: page.getByText(venue, { exact: true }),
});

async function requestVenue(page: Page, venue: string) {
  await page.getByRole('button', { name: 'Search venues', exact: true }).click();
  await expect(venueCard(page, venue)).toContainText('Suitable for this event');
  await venueCard(page, venue).click();
  await page.getByRole('button', { name: 'Request booking' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Booking requested' })).toBeVisible();
}

// QA-SPL-104-200 | AC1-AC5 AC7 | BB
test('[QA-SPL-104-200] Venue Staff are notified of each booking request and withdrawal', async ({ page }) => {
  test.setTimeout(240_000);
  const searchPath = `/workspace/assigned-events/${eventId}/venue-search`;

  await test.step('Setup: the coordinator opens venue search for the Planning event', async () => {
    await signIn(page, coordinator);
    await page.goto(searchPath);
    await expect(page.getByRole('button', { name: 'Search venues', exact: true })).toBeVisible();
  });

  await test.step('AC1: the coordinator requests a venue booking', async () => {
    await caption(page, `AC1: Casey Lim requests a venue for ${eventName}`);
    await requestVenue(page, first);
    await caption(page, `AC1: ${first} is requested (13:00–18:00)`);
  });

  await test.step('AC4: a second venue booking on the same event', async () => {
    await requestVenue(page, second);
    await expect(bookingCard(page, first)).toContainText('Status: Requested');
    await expect(bookingCard(page, second)).toContainText('Status: Requested');
    await bookingCard(page, second).scrollIntoViewIfNeeded();
    await caption(page, `AC4: a second booking, ${second}, on the same event; each gets its own notice`);
  });

  await test.step('AC2 and AC7: one booking is withdrawn; a repeated withdrawal is refused', async () => {
    await bookingCard(page, first).getByRole('button', { name: 'Withdraw request' }).click();
    const otherTab = await page.context().newPage();
    await otherTab.goto(searchPath);
    await bookingCard(otherTab, first).getByRole('button', { name: 'Withdraw request' }).click();
    await otherTab.getByRole('group', { name: `Confirm withdrawal of ${first}` })
      .getByRole('button', { name: 'Confirm withdrawal' }).click();
    await expect(otherTab.getByRole('status').filter({ hasText: 'Request withdrawn' })).toBeVisible();
    await otherTab.close();
    await caption(page, `AC2: ${first} was withdrawn in another tab`);
    await page.getByRole('group', { name: `Confirm withdrawal of ${first}` })
      .getByRole('button', { name: 'Confirm withdrawal' }).click();
    const refusal = bookingCard(page, first).getByRole('alert');
    await expect(refusal).toContainText('Only a Requested venue-booking request can be withdrawn.');
    await refusal.scrollIntoViewIfNeeded();
    await caption(page, 'AC7: withdrawing it again is refused, so no second notice is sent');
  });

  await test.step('AC3: only Venue Staff are notified', async () => {
    await openNotifications(page);
    await expect(eventNotices(page)).toHaveCount(0);
    await caption(page, 'AC3: Casey Lim (coordinator, not Venue Staff) receives none of these notices');
    await signOut(page);
    await signIn(page, venueStaff);
    await openNotifications(page);
    await expect(eventNotices(page)).toHaveCount(3);
    await caption(page, 'AC3: the Venue Staff account has one notice per action: 3 in all');
  });

  await test.step('AC5: each notice carries the booking details', async () => {
    const [withdrawn, secondRequested, firstRequested] = await eventNotices(page).all();
    await expect(withdrawn).toContainText(`Venue booking request withdrawn for ${eventName}: ${first} on `);
    await expect(secondRequested).toContainText(`Venue booking requested for ${eventName}: ${second} on `);
    await expect(firstRequested).toContainText(`Venue booking requested for ${eventName}: ${first} on `);
    for (const notice of [withdrawn, secondRequested, firstRequested]) {
      await expect(notice).toContainText(
        'on Wed 12 Mar 2031, 13:00–18:00 SGT; venue occupied PM (setup AM, turnaround Night).',
      );
    }
    await caption(page, 'AC5: event, venue, date, 13:00–18:00 SGT, occupied PM with setup AM and turnaround Night');
  });

  await test.step('Link: a notice opens the booking queue', async () => {
    await eventNotices(page).first().getByRole('link', { name: eventName }).click();
    await expect(page).toHaveURL(/\/workspace\/booking-requests$/);
    await expect(page.getByRole('heading', { name: 'Booking requests awaiting review' })).toBeVisible();
    const rows = page.getByRole('row').filter({ hasText: eventName });
    await expect(rows).toHaveCount(1);
    await expect(rows).toContainText(second);
    await rows.evaluate(row => row.scrollIntoView({ block: 'center' }));
    await caption(page, `The notice opens Booking requests: only ${second} is awaiting review; ${first} was withdrawn`);
  });
});
