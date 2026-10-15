import { expect, test, type Page } from '@playwright/test';

const venueName = process.env.SPL130_VENUE_NAME;
const requestedBookingId = process.env.SPL130_REQUESTED_BOOKING_ID;
const approvedBookingId = process.env.SPL130_APPROVED_BOOKING_ID;
const requestedEventId = process.env.SPL130_REQUESTED_EVENT_ID;
test.skip(
  !venueName || !requestedBookingId || !approvedBookingId || !requestedEventId,
  'Requires isolated SPL-130 real-Auth fixtures.',
);
test.use({ timezoneId: 'Asia/Tokyo', viewport: { width: 1280, height: 900 } });

async function signIn(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill('LocalDemo123!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace$/);
}

async function setPreparation(page: Page, setup: string, turnaround: string) {
  await page.goto('/workspace/venues');
  await page.getByRole('button', { name: new RegExp(venueName!) }).click();
  await page.getByLabel('Setup minutes').fill(setup);
  await page.getByLabel('Turnaround minutes').fill(turnaround);
  await page.getByRole('button', { name: 'Save timing', exact: true }).click();
}

test('[TC-SPL-130-010] real Auth timing change, shared findings and explicit review', async ({ page }, testInfo) => {
  await test.step('Venue Staff changes preparation rules and sees every affected commitment', async () => {
    await signIn(page, 'venue.staff@example.test');
    await setPreparation(page, '30', '30');
    await expect(page.getByText('Timing saved. 2 active bookings need review.')).toBeVisible();
    await page.getByRole('link', { name: 'Timing reviews', exact: true }).click();
    const requestedRow = page.getByRole('row', { name: /SPL-130 Browser Requested Needs review/ });
    const approvedRow = page.getByRole('row', { name: /SPL-130 Browser Approved Needs review/ });
    await expect(requestedRow).toBeVisible();
    await expect(approvedRow).toBeVisible();
    await expect(requestedRow.getByText('Requested', { exact: true })).toBeVisible();
    await expect(approvedRow.getByText('Approved', { exact: true })).toBeVisible();
    await expect(page.getByText('Casey Lim', { exact: true })).toHaveCount(2);
    await expect(page.getByText(/^Original:/)).toHaveCount(2);
    await expect(page.getByText(/^Current:/)).toHaveCount(2);
    await testInfo.attach('Venue Staff affected-booking queue', {
      body: await page.screenshot({ fullPage: true }), contentType: 'image/png',
    });

    await page.goto(`/workspace/venue-bookings/${requestedBookingId}`);
    await expect(page.getByRole('heading', { name: 'Timing review findings' })).toBeVisible();
    await page.getByRole('button', { name: 'Confirm timing reviewed' }).click();
    await expect(page.getByRole('alert')).toContainText('Current timing checks still fail');
  });

  await test.step('Assigned coordinator sees the same persisted reason and occupancy evidence', async () => {
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await signIn(page, 'event.coordinator@example.test');
    await page.goto(`/workspace/assigned-events/${requestedEventId}`);
    await expect(page.getByRole('heading', { name: 'Timing review findings' })).toBeVisible();
    await expect(page.getByText(/overlaps SPL-130 Browser Approved/)).toBeVisible();
    await expect(page.getByText('Original occupancy', { exact: true })).toBeVisible();
    await expect(page.getByText('Under current rules', { exact: true })).toBeVisible();
    await testInfo.attach('Assigned coordinator timing finding', {
      body: await page.screenshot({ fullPage: true }), contentType: 'image/png',
    });
  });

  await test.step('Safe rules do not silently clear findings; Venue Staff clears each explicitly', async () => {
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await signIn(page, 'venue.staff@example.test');
    await setPreparation(page, '0', '0');
    await expect(page.getByText('Timing saved. No active bookings need review.')).toBeVisible();
    await page.goto('/workspace/timing-reviews');
    await expect(page.getByRole('row', { name: /SPL-130 Browser Requested Needs review/ })).toBeVisible();

    for (const bookingId of [requestedBookingId, approvedBookingId]) {
      await page.goto(`/workspace/venue-bookings/${bookingId}`);
      await page.getByRole('button', { name: 'Confirm timing reviewed' }).click();
      await expect(page.getByRole('heading', { name: 'Timing review findings' })).toHaveCount(0);
    }
    await page.goto('/workspace/timing-reviews');
    await expect(page.getByRole('heading', { name: 'No timing reviews' })).toBeVisible();
    await testInfo.attach('Explicit review completed', {
      body: await page.screenshot({ fullPage: true }), contentType: 'image/png',
    });
  });
});
