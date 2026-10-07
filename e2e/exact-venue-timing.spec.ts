import { expect, test, type Page } from '@playwright/test';

// Run only against an isolated database with the SPL-129 feature and fixtures enabled.
const eventId = process.env.SPL129_EVENT_ID;
const venueName = process.env.SPL129_VENUE_NAME;
test.skip(!eventId || !venueName, 'Requires isolated SPL-129 browser fixtures.');
test.use({ timezoneId: 'Asia/Tokyo', viewport: { width: 390, height: 844 } });
async function signIn(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill('LocalDemo123!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace$/);
}

test('[TC-SPL-129-12] real Auth staff save to coordinator search; Tokyo browser retains SGT', async ({ page }, testInfo) => {
  await test.step('Venue Staff saves 30-minute setup, 45-minute turnaround and daily hours (AC1)', async () => {
    await signIn(page, 'venue.staff@example.test');
    await page.getByRole('link', { name: 'Venue catalogue' }).click();
    await page.getByRole('button', { name: new RegExp(venueName!) }).click();
    await page.getByLabel('Setup minutes').fill('30');
    await page.getByLabel('Turnaround minutes').fill('45');
    if (await page.getByLabel('Opening time 1').count() === 0) {
      await page.getByRole('button', { name: 'Add opening interval' }).click();
    }
    await page.getByLabel('Opening time 1').fill('09:00');
    await page.getByLabel('Closing time 1').fill('18:00');
    await page.getByRole('button', { name: 'Save timing' }).click();
    await expect(page.getByText('Timing saved.', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await testInfo.attach('Staff timing settings', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  });
  await test.step('Assigned coordinator opens exact-time search in Singapore time (AC1)', async () => {
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await signIn(page, 'event.coordinator@example.test');
    await page.goto(`/workspace/assigned-events/${eventId}/venue-search`);
    await expect(page.getByLabel('Event start (SGT)')).toHaveValue('10:00');
    await expect(page.getByLabel('Event end (SGT)')).toHaveValue('12:00');
  });
  await test.step('Keyboard search shows 09:30 to 12:45 occupancy and no booking action (AC2, AC4)', async () => {
    await page.getByRole('button', { name: 'Search venues', exact: true }).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('button', { name: new RegExp(venueName!) })).toBeVisible();
    await expect(page.getByText(/Occupied:.*09:30.*12:45/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Request booking', exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await testInfo.attach('Coordinator search results', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  });
});
