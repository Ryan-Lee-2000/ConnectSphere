import { expect, test, type Page } from '@playwright/test';

// SPL-121 recorded UAT, QA-SPL-121-200. Real local Auth and an isolated fixture: a Planning event
// "SPL-121 QA Gala<suffix>" assigned to Casey Lim, with Requested bookings at the fixture's own
// hall and studio and Requested lines on its own microphone and speaker types. Skipped unless
// SPL121_EVENT_ID and SPL121_MIC_TYPE_ID name that fixture, so the ordinary suite never runs it.

const eventId = process.env.SPL121_EVENT_ID;
const micTypeId = process.env.SPL121_MIC_TYPE_ID;
test.skip(!eventId || !micTypeId, 'Requires the isolated SPL-121 real-Auth fixture.');

const password = 'LocalDemo123!';
const coordinator = 'event.coordinator@example.test';
const venueStaff = 'venue.staff@example.test';
const technicalSupport = 'technical.support@example.test';
const suffix = process.env.SPL121_SUFFIX ?? '';
const eventName = `SPL-121 QA Gala${suffix}`;
const hall = `SPL-121 QA Hall${suffix}`;
const studio = `SPL-121 QA Studio${suffix}`;
const microphone = `SPL-121 QA Microphone${suffix}`;
const speaker = `SPL-121 QA Speaker${suffix}`;
const reason = 'The studio floor is being resurfaced.';

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
  // Clear it, so a caption never lingers over the next screen while that screen loads.
  await page.evaluate(() => document.getElementById('uat-caption')?.remove());
}

async function signIn(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace$/, { timeout: 15_000 });
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

const eventNotices = (page: Page) => page.getByRole('listitem').filter({ hasText: eventName });

async function openBooking(page: Page, venue: string) {
  await page.getByRole('link', { name: 'Booking requests' }).click();
  const row = page.getByRole('row').filter({ hasText: eventName }).filter({ hasText: venue });
  await expect(row).toBeVisible();
  await row.getByRole('button', { name: `Review the booking request for ${eventName}` }).click();
  await expect(page).toHaveURL(/\/workspace\/venue-bookings\/\d+$/);
}

const equipmentCard = (page: Page, type: string) => page.locator('.equipment-availability__card').filter({
  has: page.getByRole('heading', { name: type, exact: true }),
  hasText: eventName,
});

// QA-SPL-121-200 | AC1-AC5 | BB
test('[QA-SPL-121-200] the coordinator is told of each decision on their event arrangements', async ({ page }) => {
  test.setTimeout(300_000);

  await test.step('AC1: Venue Staff approve one booking and reject another with a reason', async () => {
    await signIn(page, venueStaff);
    await openBooking(page, hall);
    await caption(page, `AC1: Valerie Tan (Venue Staff) reviews the ${hall} request for ${eventName}`);
    await page.getByRole('button', { name: 'Approve booking' }).click();
    await page.getByRole('button', { name: 'Confirm approval' }).click();
    await expect(page.getByRole('status')).toContainText('Approved by Valerie Tan');
    await caption(page, 'AC1 approved: the hall booking is approved');

    await openBooking(page, studio);
    await page.getByRole('button', { name: 'Reject booking' }).click();
    await page.getByLabel('Rejection reason').fill('   ');
    await expect(page.getByRole('button', { name: 'Confirm rejection' })).toBeDisabled();
    await caption(page, 'AC5 refused: a rejection cannot be sent without a reason, so it sends no notice');
    await page.getByLabel('Rejection reason').fill(reason);
    await page.getByRole('button', { name: 'Confirm rejection' }).click();
    await expect(page.getByRole('status')).toContainText(reason);
    await caption(page, 'AC1 rejected: the studio booking is rejected with a reason');
  });

  await test.step('AC3: a Venue Staff block over the approved booking flags it', async () => {
    await page.getByRole('link', { name: 'Venue catalogue' }).click();
    await page.getByRole('button', { name: new RegExp(hall) }).first().click();
    await page.getByLabel('Unavailable from').fill('2027-04-20');
    await page.getByLabel('Unavailable through').fill('2027-04-20');
    await page.getByLabel('AM · 7am–12pm unavailable').check();
    await page.getByLabel('Reason for unavailability').fill('Air-conditioning repair');
    await page.getByRole('button', { name: 'Record unavailability' }).click();
    await expect(page.getByText('Air-conditioning repair').first()).toBeVisible();
    await caption(page, 'AC3: Venue Staff block the morning the approved hall booking uses');
    await signOut(page);
  });

  await test.step('AC2: Technical Support reserves part of one line and marks another unavailable', async () => {
    await signIn(page, technicalSupport);
    await page.getByRole('link', { name: 'Equipment availability' }).click();
    const mic = equipmentCard(page, microphone);
    await mic.scrollIntoViewIfNeeded();
    await mic.getByLabel('Units to reserve').fill('2');
    await mic.getByRole('button', { name: 'Reserve units' }).click();
    await expect(mic.getByText('Partially reserved', { exact: true })).toBeVisible();
    await caption(page, 'AC2 partly reserved: Tara Ng reserves 2 of the 4 microphones');

    const spk = equipmentCard(page, speaker);
    await spk.scrollIntoViewIfNeeded();
    const unavailable = spk.getByRole('region', { name: `Mark ${speaker} unavailable` });
    await unavailable.getByLabel('Reason').fill('Supplier recall');
    await unavailable.getByRole('button', { name: 'Mark unavailable' }).click();
    await expect(spk.getByText('Unavailable', { exact: true }).first()).toBeVisible();
    await caption(page, 'AC2 unavailable: the speaker requirement is marked Unavailable');
  });

  await test.step('AC4: units taken out of service flag the reserved microphone line', async () => {
    await page.goto(`/workspace/equipment-types/${micTypeId}/unavailability`);
    await expect(page.getByRole('heading', { name: microphone })).toBeVisible();
    await page.getByLabel('Number of units').fill('5');
    await page.getByLabel('Reason').fill('Water damage in the store');
    await page.getByRole('button', { name: 'Mark unavailable' }).click();
    await expect(page.getByText(/Marked unavailable: 5/)).toBeVisible();
    await caption(page, 'AC4: 5 of 6 microphones go out of service, so the 2 held are short and the line needs review');
  });

  await test.step('AC5: only the assigned coordinator receives the notices, one per decision', async () => {
    await openNotifications(page);
    await expect(eventNotices(page)).toHaveCount(0);
    await caption(page, 'AC5: Technical Support\'s own inbox has none of these notices');
    await signOut(page);

    await signIn(page, coordinator);
    await openNotifications(page);
    const items = eventNotices(page);
    await expect(items).toHaveCount(6);
    await expect(items.nth(0)).toContainText(`Equipment for ${eventName} needs review: ${microphone} × 4; units became unavailable.`);
    await expect(items.nth(1)).toContainText(`Equipment marked unavailable for ${eventName}: ${speaker} × 2.`);
    await expect(items.nth(2)).toContainText(`Equipment partially reserved for ${eventName}: ${microphone} × 4 (2 of 4 units).`);
    // SPL-132 AC2: the disruption notice now names the booking's time and the block's reason.
    await expect(items.nth(3)).toContainText(`Venue booking for ${eventName} at ${hall} on `);
    await expect(items.nth(3)).toContainText('needs a replacement: Venue Staff marked the venue unavailable (');
    await expect(items.nth(4)).toContainText(`Venue booking for ${eventName} at ${studio} was rejected: ${reason}`);
    await expect(items.nth(5)).toContainText(`Venue booking for ${eventName} at ${hall} was approved.`);
    await caption(page, 'AC5: Casey Lim, the assigned coordinator, has exactly one notice per decision');
    await items.nth(5).scrollIntoViewIfNeeded();
    await caption(page, 'AC5: none for the refused rejection; block, unavailability and recall reasons stay internal');
    await items.nth(0).getByRole('link', { name: eventName }).click();
    await expect(page).toHaveURL(new RegExp(`/workspace/assigned-events/${eventId}$`));
    await expect(page.getByRole('heading', { name: eventName })).toBeVisible();
    await caption(page, 'AC5: each notice opens the coordinator\'s own event page');
  });
});
