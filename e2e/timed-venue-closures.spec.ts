import { expect, test } from '@playwright/test';
const venueName = process.env.SPL138_VENUE_NAME;
const bookingId = process.env.SPL138_BOOKING_ID;
test.skip(!venueName || !bookingId, 'Requires isolated SPL-138 real-Auth fixtures.');
test.use({ timezoneId: 'Asia/Tokyo', viewport: { width: 390, height: 844 } });
test('[TC-SPL-138-10] staff records a timed closure, sees affected occupancy and removes it with history intact', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Email address').fill('venue.staff@example.test');
  await page.getByLabel('Password').fill('LocalDemo123!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/workspace/);
  await test.step('Create 12:30-13:00 SGT closure overlapping approved turnaround', async () => {
    await page.goto('/workspace/venues');
    await page.getByRole('button', { name: new RegExp(venueName!) }).click();
    await page.getByLabel('Unavailable from').fill('2026-10-12');
    await page.getByLabel('Start time (SGT)').fill('12:30');
    await page.getByLabel('End time (SGT)').selectOption('13:00');
    await page.getByLabel('Reason for unavailability').fill('SPL138 walkthrough maintenance');
    await page.getByRole('button', { name: 'Record unavailability', exact: true }).click();
    await expect(page.getByText('Operational unavailability recorded. 1 active booking requires review.')).toBeVisible();
    await testInfo.attach('Timed closure recorded', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  });
  await test.step('Calendar shows precise overlap and adjacent free time in Singapore time', async () => {
    await page.goto('/workspace/venue-calendar');
    await page.getByLabel('From', { exact: true }).fill('2026-10-12');
    const day = page.getByRole('region', { name: '12 Oct 2026', exact: true });
    await expect(day.getByText(/12:30.*12:45.*Blocked/)).toBeVisible();
    await expect(day.getByText(/12:45.*13:00.*Blocked/)).toBeVisible();
    await expect(day.getByText(/13:00.*Available/)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await testInfo.attach('Precise calendar overlap', { body: await day.screenshot(), contentType: 'image/png' });
  });
  await test.step('Booking remains approved and visibly requires review', async () => {
    await page.goto(`/workspace/venue-bookings/${bookingId}`);
    await expect(page.getByText('Marked for review.', { exact: true })).toBeVisible();
    await expect(page.getByText(/09:30.*12:45/).first()).toBeVisible();
  });
  await test.step('Remove closure; retain booking occupancy and unresolved review', async () => {
    await page.goto('/workspace/venues');
    await page.getByRole('button', { name: new RegExp(venueName!) }).click();
    await page.getByRole('button', { name: 'Remove SPL138 walkthrough maintenance', exact: true }).click();
    await expect(page.getByText('Operational unavailability removed.')).toBeVisible();
    await page.goto('/workspace/venue-calendar');
    await page.getByLabel('From', { exact: true }).fill('2026-10-12');
    const day = page.getByRole('region', { name: '12 Oct 2026', exact: true });
    await expect(day.getByText(/12:45.*Available/)).toBeVisible();
    await expect(day.getByText(/Blocked/)).toHaveCount(0);
    await page.goto(`/workspace/venue-bookings/${bookingId}`);
    await expect(page.getByText('Marked for review.', { exact: true })).toBeVisible();
    await expect(page.getByText(/09:30.*12:45/).first()).toBeVisible();
    await testInfo.attach('Review preserved after closure removal', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  });
});
