import { expect, test, type Page } from '@playwright/test';

test.skip(process.env.SPL107_FIXTURE !== '1', 'Requires the isolated SPL-107 real-Auth fixtures.');
test.use({ timezoneId: 'Asia/Tokyo', viewport: { width: 390, height: 844 } });
async function signIn(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill('LocalDemo123!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/workspace/);
}
async function openOverview(page: Page) {
  await page.goto('/workspace/venue-calendar');
  await page.getByRole('button', { name: 'All venues', exact: true }).click();
  await page.getByLabel('Date (Singapore time)').fill('2026-10-14');
  await expect(page.getByRole('button', { name: 'Inspect SPL107 Harbour Hall', exact: true })).toBeVisible();
}

// Compare rendered positions with the independently stated clock times, at both widths.
async function expectAccurateTimeline(page: Page) {
  const offsets = await page.locator('.venue-overview__grid').evaluate(grid => {
    const errors: { label: string; pixels: number }[] = [];
    const tracks = Array.from(grid.querySelectorAll('.venue-overview__track'));
    for (const track of tracks) {
      const bounds = track.getBoundingClientRect();
      for (const segment of Array.from(track.children)) {
        const label = segment.getAttribute('aria-label') || '';
        const times = label.match(/(\d{2}):(\d{2})\u2013(\d{2}):(\d{2})/);
        if (!times) throw new Error(`Missing timing label: ${label}`);
        const rect = segment.getBoundingClientRect();
        const start = Number(times[1]) * 60 + Number(times[2]);
        const end = Number(times[3]) * 60 + Number(times[4]);
        errors.push({ label: `${label} start`, pixels: Math.abs(rect.left - bounds.left - bounds.width * start / 1440) });
        errors.push({ label: `${label} end`, pixels: Math.abs(rect.right - bounds.left - bounds.width * end / 1440) });
      }
    }
    const bounds = tracks[0].getBoundingClientRect();
    const ticks = Array.from(grid.querySelectorAll('.venue-overview__axis div span'));
    ticks.forEach((tick, index) => {
      const rect = tick.getBoundingClientRect();
      const anchor = index === 0 ? rect.left : index === ticks.length - 1 ? rect.right : (rect.left + rect.right) / 2;
      errors.push({ label: `Hour axis ${tick.textContent}`, pixels: Math.abs(anchor - bounds.left - bounds.width * index / 4) });
    });
    return errors;
  });
  for (const offset of offsets) expect(offset.pixels, offset.label).toBeLessThanOrEqual(1);
}

test('[TC-SPL-107-12] staff compares venues, inspects exact reviewed occupancy and opens permitted detail on a phone', async ({ page }, testInfo) => {
  await signIn(page, 'venue.staff@example.test');
  await openOverview(page);
  await test.step('Compare all venues and exact period labels in Singapore time', async () => {
    await expect(page.getByRole('button', { name: 'Inspect SPL107 Quiet Room', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Inspect SPL107 Timing pending', exact: true })).toBeVisible();
    const venue = page.getByRole('button', { name: 'Inspect SPL107 Harbour Hall', exact: true });
    await venue.focus(); await page.keyboard.press('Enter');
    await expect(page.getByRole('button', { name: 'Inspect 09:30–10:00 Setup', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Inspect 12:45–13:00 Closure', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Inspect 13:00–18:00 Available', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await expectAccurateTimeline(page);
    await page.screenshot({ path: 'artifacts/SPL-107/overview-mobile.png', fullPage: true });
    await testInfo.attach('Mobile all-venues timeline', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  });
  await test.step('An overlap retains booking preparation, closure detail and review', async () => {
    await page.getByRole('button', { name: 'Inspect 12:30–12:45 Closure', exact: true }).click();
    const detail = page.getByRole('region', { name: 'Selected period' });
    await expect(detail.getByText('Turnaround', { exact: true })).toBeVisible();
    await expect(detail.getByText('Operational closure', { exact: true })).toBeVisible();
    await expect(detail.getByText('SPL107 maintenance', { exact: true })).toBeVisible();
    await expect(detail.getByText('Review required', { exact: true })).toBeVisible();
    await testInfo.attach('All overlapping causes and authorized details', { body: await detail.screenshot(), contentType: 'image/png' });
    await detail.getByRole('link', { name: 'Open booking', exact: true }).click();
    await expect(page).toHaveURL(/workspace\/venue-bookings\/\d+/);
    await expect(page.getByText('Marked for review.', { exact: true })).toBeVisible();
  });
  await test.step('Desktop comparison remains readable', async () => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await openOverview(page);
    await expectAccurateTimeline(page);
    await page.screenshot({ path: 'artifacts/SPL-107/overview-desktop.png', fullPage: true });
    await testInfo.attach('Desktop all-venues timeline', { body: await page.screenshot({ fullPage: true }), contentType: 'image/png' });
  });
});

test('[TC-SPL-107-12] Lead sees anonymous occupied periods with no staff booking access', async ({ page }) => {
  await signIn(page, 'operations.manager@example.test');
  await openOverview(page);
  await page.getByRole('button', { name: 'Inspect SPL107 Harbour Hall', exact: true }).click();
  await page.getByRole('button', { name: 'Inspect 12:30–12:45 Closure', exact: true }).click();
  const detail = page.getByRole('region', { name: 'Selected period' });
  await expect(detail.getByText('Operational closure', { exact: true })).toBeVisible();
  await expect(detail.getByText('SPL107 maintenance', { exact: true })).toHaveCount(0);
  await expect(detail.getByText('SPL107 client forum', { exact: true })).toHaveCount(0);
  await expect(detail.getByRole('link')).toHaveCount(0);
});

test('[TC-SPL-107-12] assigned coordinator opens their event from its occupied period', async ({ page }) => {
  await signIn(page, 'event.coordinator@example.test');
  await openOverview(page);
  await page.getByRole('button', { name: 'Inspect SPL107 Harbour Hall', exact: true }).click();
  await page.getByRole('button', { name: 'Inspect 10:00–12:00 Approved', exact: true }).click();
  const detail = page.getByRole('region', { name: 'Selected period' });
  await expect(detail.getByText('SPL107 client forum', { exact: true })).toBeVisible();
  await detail.getByRole('link', { name: 'Open assigned event', exact: true }).click();
  await expect(page).toHaveURL(/workspace\/assigned-events\/\d+/);
  await expect(page.getByRole('heading', { name: 'SPL107 client forum', exact: true })).toBeVisible();
});

test('[TC-SPL-107-12] organiser is refused the internal calendar route', async ({ page }) => {
  await signIn(page, 'developer@example.test');
  await page.goto('/workspace/venue-calendar');
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'All venues', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Venue calendar', exact: true })).toHaveCount(0);
});
