import { expect, test, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const password = process.env.VITE_LOCAL_DEMO_PASSWORD ?? 'LocalDemo123!';
const coordinator = process.env.VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL ?? 'event.coordinator@example.test';
const safetyOfficer = process.env.VITE_LOCAL_DEMO_SAFETY_OFFICER_EMAIL ?? 'safety.officer@example.test';
const approvalEvent = 'E2E SPL-135 Safety approval';
const changesEvent = 'E2E SPL-135 Safety changes';

const evidencePause = (page: Page) => page.waitForTimeout(1_800);

test.beforeAll(() => {
  // The walkthrough owns its disposable events so it can run in the complete browser suite.
  // SPL-142: uv picks the project interpreter on Windows and macOS alike.
  execFileSync('uv', ['run', '--frozen', 'python', 'scripts/prepare_e2e_safety.py'], {
    stdio: 'inherit',
  });
});

// SPL-142: the events use a shared equipment type, so they must not outlive the walkthrough.
test.afterAll(() => {
  execFileSync('uv', ['run', '--frozen', 'python', 'scripts/cleanup_e2e_safety.py'], {
    stdio: 'inherit',
  });
});

async function caption(page: Page, text: string) {
  await page.evaluate(message => {
    let banner = document.getElementById('uat-caption');
    if (!banner) {
      banner = document.createElement('div'); banner.id = 'uat-caption'; banner.setAttribute('aria-hidden', 'true');
      Object.assign(banner.style, { position: 'fixed', left: '12px', right: '12px', bottom: '12px', zIndex: '2147483647', padding: '12px 14px', borderRadius: '8px', background: 'rgba(16,32,56,.94)', color: '#fff', font: '600 14px/1.4 system-ui', pointerEvents: 'none' });
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
  await expect(page).toHaveURL(/\/workspace$/);
  await evidencePause(page);
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
  await evidencePause(page);
}

async function openEvent(page: Page, name: string) {
  await page.getByRole('link', { name: 'My assigned events', exact: true }).click();
  await page.getByRole('link', { name }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  await page.getByRole('heading', { name: 'Safety review' }).scrollIntoViewIfNeeded();
}

async function completePlan(page: Page) {
  await page.getByLabel('Emergency access').fill('Keep the marked fire exit clear and brief the ushers.');
  await evidencePause(page);
  await page.getByLabel('Equipment placement').fill('Route equipment and cables behind the marked stage line.');
  await evidencePause(page);
  await page.getByLabel('Crowd movement').fill('Use separate entry and exit queues with two ushers.');
  await evidencePause(page);
  await page.getByLabel('Venue restrictions').fill('No open flame and no blocked exits.');
  await evidencePause(page);
  await page.getByRole('button', { name: 'Submit safety review' }).click();
  await expect(page.getByRole('status')).toContainText('Safety review submitted.');
  await evidencePause(page);
}

async function review(page: Page, name: string) {
  await page.getByRole('link', { name: 'Safety reviews' }).click();
  const row = page.getByRole('listitem').filter({ hasText: name });
  await row.scrollIntoViewIfNeeded();
  await row.getByRole('button', { name: 'Review' }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
}

// QA-SPL-135-UAT-021 | AC1-AC4 | BB manual evidence
test('QA-SPL-135-UAT-021 records a paced Safety Officer approval and change-request walkthrough', async ({ page }) => {
  test.setTimeout(180_000);
  await signIn(page, coordinator);
  await openEvent(page, approvalEvent);
  await caption(page, 'AC1 / AC2: confirmed venue, attendance, accessibility and equipment evidence are visible before submission');
  await expect(page.getByText('Approved venue arrangements')).toBeVisible();
  await expect(page.getByText('Technical arrangements')).toBeVisible();

  await caption(page, 'AC2 unhappy path: missing safety-plan information is refused');
  await page.getByRole('button', { name: 'Submit safety review' }).click();
  await expect(page.getByRole('alert')).toContainText('Explain each safety-plan item');
  await evidencePause(page);
  await caption(page, 'AC2 happy path: the coordinator records emergency, equipment, crowd and venue safety arrangements');
  await completePlan(page);
  await signOut(page);

  await signIn(page, safetyOfficer);
  await review(page, approvalEvent);
  await caption(page, 'AC3: Safety Officer reads the submitted plan and confirmed arrangement before deciding');
  await page.getByText('Emergency access').scrollIntoViewIfNeeded();
  await evidencePause(page);
  await page.getByRole('button', { name: 'Approve' }).click();
  await caption(page, 'AC3 / AC4: approval is recorded; only a current approval can unlock Preparation');
  await expect(page.getByText('Nothing is awaiting safety review.')).toBeVisible();
  await signOut(page);

  await signIn(page, coordinator);
  await openEvent(page, approvalEvent);
  await page.getByRole('button', { name: 'Begin preparation' }).scrollIntoViewIfNeeded();
  await page.getByRole('button', { name: 'Begin preparation' }).click();
  await expect(page.getByRole('region', { name: 'Requirements to consider' }).getByText('Preparing', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Begin preparation' })).toHaveCount(0);
  await caption(page, 'AC4 happy path: the assigned coordinator explicitly begins Preparation after current Safety approval');

  await page.getByRole('link', { name: 'My assigned events', exact: true }).click();
  await page.getByRole('link', { name: changesEvent }).click();
  await page.getByRole('heading', { name: 'Safety review' }).scrollIntoViewIfNeeded();
  await completePlan(page);
  await signOut(page);

  await signIn(page, safetyOfficer);
  await review(page, changesEvent);
  await caption(page, 'AC3 unhappy path: Request changes requires an accountable reason');
  await page.getByRole('button', { name: 'Request changes' }).click();
  await expect(page.getByRole('alert')).toContainText('A reason is required');
  await evidencePause(page);
  await page.getByLabel('Decision reason').fill('Clarify the crowd-control steward positions before preparation.');
  await page.getByRole('button', { name: 'Request changes' }).click();
  await expect(page.getByText('Nothing is awaiting safety review.')).toBeVisible();
  await caption(page, 'AC3 / AC4: changes return the event to Planning; it is not cancelled and cannot enter Preparation');
});
