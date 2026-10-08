import { expect, test, type Page } from '@playwright/test';
const eventId = process.env.SPL137_EVENT_ID;
const venueName = process.env.SPL137_VENUE_NAME;
test.skip(!eventId || !venueName, 'Requires isolated SPL-137 browser fixtures.');
test.use({ timezoneId: 'Asia/Tokyo', viewport: { width: 390, height: 844 } });
async function signIn(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill('LocalDemo123!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace$/);
}

test('[TC-SPL-137-12] coordinator requests and staff approves identical exact times, with recorded history', async ({ page }, testInfo) => {
  let bookingId: number;
  await test.step('Coordinator reviews advertised and occupied SGT times and requests a booking', async () => {
    await signIn(page, 'event.coordinator@example.test');
    await page.goto(`/workspace/assigned-events/${eventId}/venue-search`);
    await expect(page.getByLabel('Event start (SGT)')).toHaveValue('10:00');
    await page.getByRole('button', { name: 'Search venues', exact: true }).click();
    await page.getByRole('button', { name: new RegExp(venueName!) }).click();
    const form = page.getByRole('form', { name: `Request ${venueName}` });
    await expect(form.getByText(/09:30.*12:45/)).toBeVisible();
    await testInfo.attach('Coordinator reviewed exact times', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
    const submitted = page.waitForResponse(response => response.url().endsWith(`/api/event-requests/${eventId}/venue-bookings`) && response.request().method() === 'POST');
    await form.getByRole('button', { name: 'Request booking', exact: true }).click();
    const response = await submitted;
    expect(response.status()).toBe(201);
    bookingId = (await response.json()).booking.id;
    await expect(page.getByText(`Booking requested for ${venueName}.`, { exact: true })).toBeVisible();
  });
  await test.step('Venue Staff checks immutable evidence and approves without amending it', async () => {
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await signIn(page, 'venue.staff@example.test');
    await page.goto(`/workspace/venue-bookings/${bookingId}`);
    await expect(page.getByText(/09:30.*12:45/)).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Requirements at request' })).toBeVisible();
    await page.getByRole('button', { name: 'Approve booking', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm approval', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: /^Approved by .+ on / })).toBeVisible();
    await testInfo.attach('Staff approval with exact evidence', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  });
  await test.step('Coordinator sees Approved history and retained occupied times', async () => {
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await signIn(page, 'event.coordinator@example.test');
    await page.goto(`/workspace/assigned-events/${eventId}`);
    await expect(page.getByText(/09:30.*12:45/)).toBeVisible();
    await expect(page.getByRole('list', { name: 'History', exact: true }).getByText('Approved', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await testInfo.attach('Coordinator approval history', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  });
});
