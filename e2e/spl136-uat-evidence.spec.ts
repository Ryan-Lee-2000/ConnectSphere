import { expect, test, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

// QA-SPL-136-200: deliberately paced visual UAT. The local fixture is disposable and this
// recording demonstrates the human-facing safety-return/reconfirmation path without credentials.
const password = process.env.VITE_LOCAL_DEMO_PASSWORD ?? 'LocalDemo123!';
const coordinator = process.env.VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL ?? 'event.coordinator@example.test';
const safetyOfficer = process.env.VITE_LOCAL_DEMO_SAFETY_OFFICER_EMAIL ?? 'safety.officer@example.test';
const runId = randomUUID();
const fixtureEnv = { ...process.env, SPL136_E2E_RUN_ID: runId };
const eventName = `E2E SPL-136 ${runId} Community Access Briefing`;
const pause = (page: Page) => page.waitForTimeout(2_000);

test.use({ video: { mode: 'on', size: { width: 1920, height: 1080 } }, viewport: { width: 1920, height: 1080 } });
// Use this worktree's interpreter on both supported development platforms.
const python = process.platform === 'win32'
  ? path.resolve(process.cwd(), '.venv', 'Scripts', 'python.exe')
  : path.resolve(process.cwd(), '.venv', 'bin', 'python');
let fixturesCreated = false;
test.beforeAll(() => {
  execFileSync(python, ['scripts/prepare_e2e_spl136.py'], { stdio: 'inherit', env: fixtureEnv });
  fixturesCreated = true;
});
test.afterAll(() => {
  if (fixturesCreated) execFileSync(python, ['scripts/cleanup_e2e_spl136.py'], { stdio: 'inherit', env: fixtureEnv });
});

async function caption(page: Page, text: string) {
  await page.evaluate(message => {
    let element = document.getElementById('uat-caption');
    if (!element) {
      element = document.createElement('div'); element.id = 'uat-caption'; element.setAttribute('aria-hidden', 'true');
      Object.assign(element.style, { position: 'fixed', left: '24px', right: '24px', bottom: '24px', zIndex: '2147483647', padding: '16px 20px', borderRadius: '10px', background: 'rgba(16,32,56,.94)', color: '#fff', font: '600 20px/1.4 system-ui', pointerEvents: 'none' });
      document.body.appendChild(element);
    }
    element.textContent = message;
  }, text);
  await pause(page);
}
async function signIn(page: Page, email: string) {
  await page.goto('/'); await page.getByLabel('Email address').fill(email); await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click(); await expect(page).toHaveURL(/\/workspace$/); await pause(page);
}
async function signOut(page: Page) { await page.getByRole('button', { name: 'Sign out' }).click(); await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible(); }
async function openEvent(page: Page) { await page.getByRole('link', { name: 'My assigned events', exact: true }).click(); await page.getByRole('link', { name: eventName }).click(); await expect(page.getByRole('heading', { name: eventName, exact: true })).toBeVisible(); }
async function submitPlan(page: Page) {
  await page.getByLabel('Emergency access').fill('Keep the marked fire exit clear and brief the event ushers.'); await pause(page);
  await page.getByLabel('Equipment placement').fill('Route presentation cables behind the marked stage line.'); await pause(page);
  await page.getByLabel('Crowd movement').fill('Use separate entry and exit queues with two volunteer ushers.'); await pause(page);
  await page.getByLabel('Venue restrictions').fill('No open flame and no blocked exits.'); await pause(page);
  await page.getByRole('button', { name: 'Submit safety review' }).click(); await expect(page.getByRole('status')).toContainText('Safety review submitted.');
}

// QA-SPL-136-200 | AC1-AC4 | BB recorded UAT
test('QA-SPL-136-200 records a paced safety-return and renewed-review journey', async ({ page }) => {
  test.setTimeout(240_000);
  await signIn(page, coordinator); await openEvent(page);
  await page.getByRole('heading', { name: 'Safety review' }).scrollIntoViewIfNeeded();
  await caption(page, 'AC1: a confirmed event presents its current venue and technical arrangements for Safety review');
  await submitPlan(page); await caption(page, 'AC1 unhappy path setup: the submitted plan awaits an independent Safety decision');
  await signOut(page);
  await signIn(page, safetyOfficer); await page.getByRole('link', { name: 'Safety reviews' }).click();
  const row = page.getByRole('listitem').filter({ hasText: eventName }); await row.getByRole('button', { name: 'Review' }).click();
  await caption(page, 'AC1: Safety Officer can request changes only with an accountable reason');
  await page.getByRole('button', { name: 'Request changes' }).click(); await expect(page.getByRole('alert')).toContainText('A reason is required'); await pause(page);
  await page.getByLabel('Decision reason').fill('Clarify the crowd-control steward positions before preparation.'); await page.getByRole('button', { name: 'Request changes' }).click(); await pause(page); await signOut(page);
  await signIn(page, coordinator); await openEvent(page);
  await caption(page, 'AC1 / AC3: the decision returns this event to Planning, shows its reason, and blocks preparation');
  await expect(page.getByRole('status', { name: 'Safety rework required' })).toBeVisible();
  await page.getByRole('status', { name: 'Safety rework required' }).scrollIntoViewIfNeeded(); await pause(page);
  await caption(page, 'AC4: reconfirm the corrected venue and technical arrangements before submitting a renewed Safety review');
  await page.getByRole('button', { name: 'Confirm corrected arrangements' }).click();
  await page.getByRole('group', { name: 'Confirm corrected arrangements' }).getByRole('button', { name: 'Confirm corrected arrangements' }).click();
  await caption(page, 'AC4: reconfirming corrected arrangements returns the event to Confirmed and immediately opens renewed Safety review');
  await expect(page.getByRole('heading', { name: 'Safety review' })).toBeVisible();
  await caption(page, 'UAT complete: the coordinator can now submit a renewed safety review for the corrected event.');
});
