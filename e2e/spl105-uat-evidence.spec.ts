import { expect, test, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';

// SPL-105 recorded UAT, QA-SPL-105-200. Real local Auth and two disposable Preparing events
// assigned to the local coordinator (scripts/prepare_e2e_completion.py): one ended two days ago,
// one ends in 2031. Recorded landscape at 1920x1080 so the whole workspace is on screen.

const password = process.env.VITE_LOCAL_DEMO_PASSWORD ?? 'LocalDemo123!';
const coordinator = process.env.VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL ?? 'event.coordinator@example.test';
const otherCoordinator = 'qa.coordinator.b@example.test';
const lead = process.env.VITE_LOCAL_DEMO_OPERATIONS_MANAGER_EMAIL ?? 'operations.manager@example.test';
const organiser = process.env.VITE_LOCAL_DEMO_EMAIL ?? 'developer@example.test';
const ended = 'E2E SPL-105 Harbour Awards Night';
const upcoming = 'E2E SPL-105 Riverside Gala';
const note = '142 guests attended. The stage microphone failed for ten minutes; the spare was used.';

test.use({
  viewport: { width: 1920, height: 1080 },
  video: { mode: 'on', size: { width: 1920, height: 1080 } },
});

// uv picks the project interpreter on Windows and macOS alike, as scripts/run-e2e.mjs does.
const runPython = (script: string) => execFileSync('uv', ['run', '--frozen', 'python', script], { stdio: 'inherit' });

test.beforeAll(() => {
  // The walkthrough owns its disposable events so it can run in the complete browser suite.
  runPython('scripts/prepare_e2e_completion.py');
});

test.afterAll(() => {
  runPython('scripts/cleanup_e2e_completion.py');
});

// Keep each visible state on screen long enough to read in the captured video.
const evidencePause = (page: Page) => page.waitForTimeout(2_000);

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

async function signIn(page: Page, email: string, role?: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  // Role loading waits on the API; allow for a busy local machine without sleeping.
  await expect(page).toHaveURL(/\/workspace$/, { timeout: 30_000 });
  if (role) await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible({ timeout: 30_000 });
}

async function signOut(page: Page) {
  // The caption belongs to the step just shown; do not carry it onto the sign-in screen.
  await page.evaluate(() => document.getElementById('uat-caption')?.remove());
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible({ timeout: 30_000 });
}

async function openAssigned(page: Page, name: string) {
  await page.getByRole('link', { name: 'My assigned events', exact: true }).click();
  await page.getByRole('link', { name }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
}

const detailRow = (page: Page, label: string) => page.getByRole('rowheader', { name: label, exact: true }).locator('xpath=..');

// QA-SPL-105-200 | AC1-AC6 | BB recorded UAT
test('QA-SPL-105-200 the assigned coordinator completes an ended event, which then stays read-only and viewable', async ({ page }) => {
  test.setTimeout(300_000);
  let eventPath = '';

  await test.step('AC2 (refused): an event that has not ended cannot be completed yet', async () => {
    await signIn(page, coordinator);
    await openAssigned(page, upcoming);
    const panel = page.getByRole('region', { name: 'Mark this event completed' });
    await panel.scrollIntoViewIfNeeded();
    await expect(panel.getByText(/^You can mark this event completed from 22 Jan 2031, 12:00/)).toBeVisible();
    await expect(panel.getByRole('button', { name: 'Mark as completed' })).toBeDisabled();
    await caption(page, 'AC2 (refused): the Riverside Gala ends on 22 Jan 2031, so Mark as completed is disabled until then');
    await signOut(page);
  });

  await test.step('AC3 (refused): another coordinator and the Lead cannot complete it', async () => {
    await signIn(page, otherCoordinator);
    await page.getByRole('link', { name: 'My assigned events', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'My assigned events' }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: ended })).toHaveCount(0);
    await caption(page, 'AC3 (refused): a different coordinator does not see the Harbour Awards Night at all');
    await signOut(page);
    await signIn(page, lead);
    await page.getByRole('link', { name: 'Coordinator assignment' }).click();
    const row = page.getByRole('row').filter({ hasText: ended });
    await row.scrollIntoViewIfNeeded();
    await expect(row).toContainText('Preparing');
    await expect(page.getByRole('button', { name: 'Mark as completed' })).toHaveCount(0);
    await caption(page, 'AC3 (refused): the Event Coordinator Lead supervises the event but has no completion action');
    await signOut(page);
  });

  await test.step('AC1/AC4: the assigned coordinator completes the ended event with a closing note', async () => {
    await signIn(page, coordinator);
    await openAssigned(page, ended);
    eventPath = new URL(page.url()).pathname;
    const panel = page.getByRole('region', { name: 'Mark this event completed' });
    await panel.scrollIntoViewIfNeeded();
    await expect(panel.getByRole('button', { name: 'Mark as completed' })).toBeEnabled();
    await caption(page, 'AC1: the Harbour Awards Night is Preparing and ended two days ago, so it can be completed');
    await panel.getByRole('button', { name: 'Mark as completed' }).click();
    const form = page.getByRole('form', { name: 'Complete the event' });
    await form.getByRole('button', { name: 'Keep open' }).click();
    await expect(form).toHaveCount(0);
    await caption(page, 'AC1: "Keep open" backs out and nothing changes');
    await panel.getByRole('button', { name: 'Mark as completed' }).click();
    await form.getByLabel('Closing note (optional)').fill(note);
    await caption(page, 'AC4: add an optional closing note (attendance and issues), then confirm');
    await form.getByRole('button', { name: 'Confirm completion' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Event completed. It is now closed as a historical record.' })).toBeVisible();
    await evidencePause(page);
  });

  await test.step('AC4: Completed, who completed it, when, and the closing note are recorded', async () => {
    await page.goto(eventPath);
    await expect(detailRow(page, 'Status')).toContainText('Completed');
    await expect(detailRow(page, 'Completed by')).toContainText(/, \d{1,2} \w{3} \d{4}, /);
    await expect(detailRow(page, 'Closing note')).toContainText(note);
    await detailRow(page, 'Completed by').evaluate(row => row.scrollIntoView({ block: 'center' }));
    await caption(page, 'AC4: the event shows Completed, who completed it and when, and the closing note');
  });

  await test.step('AC5: the completed event offers no edit, cancel or completion actions', async () => {
    await expect(page.getByRole('button', { name: 'Edit event information' })).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'Cancel this event' })).toHaveCount(0);
    await expect(page.getByRole('region', { name: 'Mark this event completed' })).toHaveCount(0);
    await page.getByRole('heading', { name: ended, exact: true }).scrollIntoViewIfNeeded();
    await caption(page, 'AC5: no Edit event information, Cancel event or completion action remains');
    await signOut(page);
  });

  await test.step('AC5/AC6: the Lead still sees it, with no Reassign action', async () => {
    await signIn(page, lead);
    await page.getByRole('link', { name: 'Coordinator assignment' }).click();
    const row = page.getByRole('row').filter({ hasText: ended });
    await row.scrollIntoViewIfNeeded();
    await expect(row).toContainText('Completed');
    await expect(row.getByRole('button', { name: `Reassign coordinator for ${ended}` })).toHaveCount(0);
    await expect(page.getByText(note)).toHaveCount(0);
    await caption(page, 'AC6/AC5: the Lead still sees the event as Completed; it can no longer be reassigned and the note stays private');
    await signOut(page);
  });

  await test.step('AC6: the responsible organiser still sees it as Completed', async () => {
    await signIn(page, organiser, 'Event Organiser');
    await page.getByRole('link', { name: 'My requests' }).click();
    const row = page.getByRole('row').filter({ hasText: ended });
    await row.scrollIntoViewIfNeeded();
    await expect(row.getByText('Completed', { exact: true })).toBeVisible();
    await expect(page.getByText(note)).toHaveCount(0);
    await caption(page, 'AC6: the organiser still sees the request, now Completed; the coordinator\'s note is not shown');
    await signOut(page);
  });
});
