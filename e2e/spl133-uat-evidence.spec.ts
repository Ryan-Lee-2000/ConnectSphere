import { expect, test, type Locator, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';

// SPL-133 recorded UAT, QA-SPL-133-200. Real local Auth and disposable fixtures
// (scripts/prepare_e2e_hold_expiry.py): "E2E SPL-133 Harbour Launch" has no booking yet, and
// "E2E SPL-133 Riverside Forum" holds a booking whose deadline passed a minute ago. Recorded
// landscape at 1920x1080 so the whole workspace is on screen.

const password = process.env.VITE_LOCAL_DEMO_PASSWORD ?? 'LocalDemo123!';
const coordinator = process.env.VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL ?? 'event.coordinator@example.test';
const venueStaff = process.env.VITE_LOCAL_DEMO_VENUE_STAFF_EMAIL ?? 'venue.staff@example.test';
const launch = 'E2E SPL-133 Harbour Launch';
const forum = 'E2E SPL-133 Riverside Forum';
const harbourRoom = 'E2E SPL-133 Harbour Room';
const riverRoom = 'E2E SPL-133 River Room';

test.use({
  viewport: { width: 1920, height: 1080 },
  video: { mode: 'on', size: { width: 1920, height: 1080 } },
});

// uv picks the project interpreter on Windows and macOS alike, as scripts/run-e2e.mjs does.
const runPython = (script: string) => execFileSync('uv', ['run', '--frozen', 'python', script], { stdio: 'inherit' });

test.beforeAll(() => runPython('scripts/prepare_e2e_hold_expiry.py'));
test.afterAll(() => runPython('scripts/cleanup_e2e_hold_expiry.py'));

const evidencePause = (page: Page) => page.waitForTimeout(3_500);
const clearCaption = (page: Page) => page.evaluate(() => document.getElementById('uat-caption')?.remove());
const centre = (locator: Locator) => locator.evaluate(element => element.scrollIntoView({ block: 'center' }));

async function caption(page: Page, text: string) {
  await page.evaluate(message => {
    let banner = document.getElementById('uat-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'uat-caption';
      banner.setAttribute('aria-hidden', 'true');
      Object.assign(banner.style, {
        position: 'fixed', left: '24px', right: '24px', bottom: '24px', zIndex: '2147483647', padding: '16px 20px',
        borderRadius: '10px', background: 'rgba(16, 32, 56, 0.94)', color: '#fff', font: '600 20px/1.4 system-ui',
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
  // Role loading waits on the API; allow for a busy local machine without sleeping.
  await expect(page).toHaveURL(/\/workspace$/, { timeout: 30_000 });
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible({ timeout: 30_000 });
}

async function signOut(page: Page) {
  // The caption belongs to the step just shown; do not carry it onto the sign-in screen.
  await clearCaption(page);
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible({ timeout: 30_000 });
}

async function openEvent(page: Page, name: string) {
  await clearCaption(page);
  await page.getByRole('link', { name: 'My assigned events', exact: true }).click();
  await page.getByRole('link', { name }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible({ timeout: 30_000 });
}

async function openNotifications(page: Page) {
  await clearCaption(page);
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'Notifications' }).click();
  await expect(page.getByRole('heading', { name: 'Notifications', exact: true })).toBeVisible({ timeout: 30_000 });
}

const card = (page: Page, venue: string) =>
  page.getByRole('list', { name: 'Venue bookings' }).getByRole('article', { name: venue });

// The default deadline the server sets: 7 days after now, shown in Singapore time.
function inSevenDays(): string {
  return new Intl.DateTimeFormat('en-SG', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Singapore' })
    .format(new Date(Date.now() + 7 * 24 * 60 * 60 * 1000));
}

// A datetime-local value (SGT) for 17:00 three days from now, and one 20 days away.
function sgtInput(daysAhead: number, hour: number): string {
  const day = new Date(Date.now() + daysAhead * 24 * 60 * 60 * 1000 + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
  return `${day}T${String(hour).padStart(2, '0')}:00`;
}

// QA-SPL-133-200 | AC1-AC10 | BB recorded UAT
test('QA-SPL-133-200 a tentative hold shows its deadline, can be moved, and expires to free the venue', async ({ page }) => {
  test.setTimeout(360_000);
  let launchPath = '';

  await test.step('AC1/AC8: the coordinator requests a venue and the hold gets a 7-day deadline', async () => {
    await signIn(page, coordinator);
    await openEvent(page, launch);
    launchPath = new URL(page.url()).pathname;
    await page.getByRole('button', { name: 'Find venues' }).click();
    await page.getByLabel('Expected attendance').fill('80');
    await page.getByRole('button', { name: 'Search venues' }).click();
    await expect(page.getByLabel('Available venue results')).toBeVisible({ timeout: 30_000 });
    await page.getByRole('button', { name: new RegExp(harbourRoom) }).click();
    await page.getByRole('button', { name: 'Request booking' }).click();
    await expect(page.getByText(`Booking requested for ${harbourRoom}.`)).toBeVisible({ timeout: 30_000 });
    await page.goto(launchPath);
    const deadline = card(page, harbourRoom).getByText(/^Hold expires /);
    await expect(deadline).toContainText(inSevenDays());
    await centre(deadline);
    await caption(page, 'AC1: the system gives the new hold a deadline 7 days ahead; the coordinator did not choose it');
    await openNotifications(page);
    const notice = page.getByText(new RegExp(`${harbourRoom} is held for ${launch} until`));
    await expect(notice).toBeVisible({ timeout: 30_000 });
    await caption(page, 'AC8: the coordinator is told the hold was created, naming the event, venue and exact deadline');
    await signOut(page);
  });

  await test.step('AC2/AC3: Venue Staff see the deadline; an out-of-range change is refused, a valid one saved', async () => {
    await signIn(page, venueStaff);
    await page.getByRole('link', { name: 'Booking requests' }).click();
    const row = page.getByRole('row').filter({ hasText: launch });
    await expect(row).toContainText('Hold expires');
    await centre(row);
    await caption(page, 'AC2: Venue Staff see when each hold expires in the pending list');
    await row.getByRole('button', { name: `Review the booking request for ${launch}` }).click();
    const region = page.getByRole('region', { name: 'Hold deadline' });
    await clearCaption(page);
    await centre(region);
    await region.getByRole('button', { name: 'Change deadline' }).click();
    const form = page.getByRole('form', { name: 'Change hold deadline' });
    await form.getByLabel('New deadline (SGT)').fill(sgtInput(20, 17));
    await form.getByRole('button', { name: 'Save deadline' }).click();
    await expect(form.getByRole('alert')).toHaveText('A hold can be kept for at most 14 days from now.');
    await caption(page, 'AC3 (refused): a deadline 20 days away is beyond the 14-day maximum');
    await form.getByLabel('New deadline (SGT)').fill(sgtInput(3, 17));
    await form.getByRole('button', { name: 'Save deadline' }).click();
    await expect(form).toHaveCount(0);
    await expect(region).toContainText('5:00 pm');
    await caption(page, 'AC3: Venue Staff move the deadline to 17:00 in three days; it is recorded and shown');
    await signOut(page);
  });

  await test.step('AC3/AC8: the coordinator sees the new deadline, its history entry and a notice', async () => {
    await signIn(page, coordinator);
    await page.goto(launchPath);
    const hall = card(page, harbourRoom);
    await expect(hall.getByText(/^Hold expires /)).toContainText('5:00 pm', { timeout: 30_000 });
    const history = page.getByRole('list', { name: `History of ${harbourRoom} booking` });
    await expect(history).toContainText('Hold deadline changed');
    await expect(history).toContainText('Hold deadline moved from');
    await centre(hall);
    await caption(page, 'AC3: the history records who moved the deadline, when, and the old and new times');
    await openNotifications(page);
    await expect(page.getByText(new RegExp(`The hold on ${harbourRoom} for ${launch} now expires at`))).toBeVisible({ timeout: 30_000 });
    await caption(page, 'AC8: the coordinator is told the new deadline');
  });

  await test.step('AC5/AC6/AC9: a hold past its deadline shows Expired, notifies once and frees the venue', async () => {
    await openEvent(page, forum);
    const river = card(page, riverRoom);
    await expect(river).toContainText('Expired');
    await expect(river).toContainText('Its time is released; request the venue again if it is still needed.');
    await expect(page.getByRole('list', { name: `History of ${riverRoom} booking` })).toContainText('ConnectSphere');
    await centre(river);
    await caption(page, 'AC5/AC6: the Riverside hold passed its deadline: it shows Expired, recorded by ConnectSphere');
    await clearCaption(page);
    await page.getByRole('button', { name: 'Find venues' }).click();
    await page.getByLabel('Expected attendance').fill('80');
    await page.getByRole('button', { name: 'Search venues' }).click();
    await expect(page.getByRole('button', { name: new RegExp(riverRoom) })).toBeVisible({ timeout: 30_000 });
    await centre(page.getByRole('button', { name: new RegExp(riverRoom) }));
    await caption(page, 'AC5/AC6: the River Room is free again, so the coordinator can request it afresh');
    await openNotifications(page);
    const expiry = page.getByText(new RegExp(`The hold on ${riverRoom} for ${forum} expired at`));
    await expect(expiry).toHaveCount(1, { timeout: 30_000 });
    await caption(page, 'AC9: exactly one notice tells the coordinator the hold expired');
    await signOut(page);
  });

  await test.step('AC4/AC7/AC10: Venue Staff approve the Harbour hold before its deadline', async () => {
    await signIn(page, venueStaff);
    await page.getByRole('link', { name: 'Booking requests' }).click();
    // Wait for the loaded list (the Harbour hold is in it) before checking the Riverside hold is not.
    const harbourRow = page.getByRole('row').filter({ hasText: launch });
    await expect(harbourRow).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('row').filter({ hasText: forum })).toHaveCount(0);
    await centre(harbourRow);
    await caption(page, 'AC5: the expired Riverside hold has left the Venue Staff queue');
    await clearCaption(page);
    await harbourRow.getByRole('button', { name: `Review the booking request for ${launch}` }).click();
    await page.getByRole('button', { name: 'Approve booking' }).click();
    await page.getByRole('button', { name: 'Confirm approval' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Approved by' })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole('region', { name: 'Hold deadline' })).toHaveCount(0);
    await caption(page, 'AC4/AC7: approved strictly before its deadline, the booking is Approved and no longer expires');
    await signOut(page);
  });
});
