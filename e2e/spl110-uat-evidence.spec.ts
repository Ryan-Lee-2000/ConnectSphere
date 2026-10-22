import { expect, test, type Page } from '@playwright/test';

const organiser = { email: 'developer@example.test', password: 'LocalDemo123!' };
const attendee = { email: 'attendee@example.test', password: 'LocalDemo123!' };
const eventName = 'SPL-110 Confirmed Arrangements Manual Test';

async function caption(page: Page, text: string, pause = 2600) {
  await page.evaluate(message => {
    let banner = document.getElementById('qa-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'qa-caption';
      banner.setAttribute('role', 'presentation');
      banner.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;pointer-events:none;padding:14px 18px;'
        + 'background:#1e2a3a;color:#fff;font:600 18px/1.4 system-ui,sans-serif;text-align:center;';
      document.body.appendChild(banner);
    }
    banner.textContent = message;
  }, text);
  await page.waitForTimeout(pause);
}

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

// QA-SPL-110-012 | AC1-AC4 | BB: recorded organiser summary and access-control walkthrough.
test('QA-SPL-110-012: organiser views current confirmed arrangements read-only and unrelated access is refused', async ({
  page,
}) => {
  test.setTimeout(120_000);
  const mutations: string[] = [];
  page.on('request', request => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method()) && request.url().includes('/api/')) {
      mutations.push(`${request.method()} ${request.url()}`);
    }
  });

  await signIn(page, organiser, 'Event Organiser');
  mutations.length = 0;
  await page.getByRole('link', { name: 'Organisation events' }).click();
  await page.getByRole('link', { name: eventName }).click();
  await expect(page.getByRole('heading', { name: eventName })).toBeVisible();

  const eventUrl = page.url();
  await expect(page.getByText('Confirmed', { exact: true })).toBeVisible();
  await expect(page.getByText('Casey Lim', { exact: true })).toBeVisible();
  await caption(page, 'AC1: a trusted organiser sees the submitted event, Confirmed status and assigned coordinator Casey Lim');

  const arrangements = page.locator('.organisation-arrangements');
  await arrangements.scrollIntoViewIfNeeded();
  const approvedVenue = arrangements.getByRole('row').filter({ hasText: 'SPL-110 Harbour Hall' });
  await expect(approvedVenue).toContainText('8 Marina Way');
  await expect(approvedVenue).toContainText('20 Nov 2030');
  await expect(approvedVenue).toContainText('14:00 to 17:00');
  await expect(arrangements.getByText('SPL-110 Wireless Microphone', { exact: true })).toBeVisible();
  await expect(arrangements.getByText('6/6', { exact: true })).toBeVisible();
  await expect(arrangements.getByText('Enabled', { exact: true })).toBeVisible();
  await expect(arrangements.getByText('75', { exact: true })).toBeVisible();
  await caption(page, 'AC2: approved venue, booked date/time, equipment quantity/status and registration settings are shown');

  await expect(arrangements.getByText('Review required', { exact: true })).toBeVisible();
  await expect(arrangements.getByText('Awaiting approval', { exact: true })).toBeVisible();
  await expect(arrangements.getByText('Unavailable', { exact: true })).toBeVisible();
  const pageText = await page.locator('body').innerText();
  for (const privateNote of [
    'Internal coordinator handover. This must not appear to organisers.',
    'Venue Staff internal approval note. Must stay hidden.',
    'Review details are internal.',
    'Internal equipment planning note. Must stay hidden.',
  ]) {
    expect(pageText).not.toContain(privateNote);
  }
  await caption(page, 'AC3: review-required, awaiting-approval and unavailable states are explicit; internal notes are excluded');

  await expect(arrangements.locator('button, input, select, textarea')).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('heading', { name: eventName })).toBeVisible();
  await expect(page.getByText('Casey Lim', { exact: true })).toBeVisible();
  await expect(page.getByText('SPL-110 Harbour Hall', { exact: true })).toBeVisible();
  await expect(page.getByText('75', { exact: true })).toBeVisible();
  await expect(page.locator('.organisation-arrangements').locator('button, input, select, textarea')).toHaveCount(0);
  expect(mutations).toEqual([]);
  await page.locator('.organisation-arrangements').scrollIntoViewIfNeeded();
  await caption(page, 'AC4: after reload the latest saved values remain, with no edit controls and no mutation requests');

  await signOut(page);
  await signIn(page, attendee);
  await expect(page.getByRole('link', { name: 'Organisation events' })).toHaveCount(0);
  await page.goto(eventUrl);
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByText(eventName)).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Workspace access confirmed' })).toBeVisible();
  await caption(page, 'AC1 access refusal: an unrelated attendee cannot open the organisation event, even with its direct URL');
});
