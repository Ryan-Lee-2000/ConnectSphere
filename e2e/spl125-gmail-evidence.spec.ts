import { expect, test, type Page } from '@playwright/test';

// SPL-125 live Gmail API evidence. Opt-in: needs the app running with EMAIL_BACKEND=gmail_api and
// real Gmail credentials in the local .env, and sends two real emails to the shared inbox.
//   SPL125_GMAIL=1 npm run e2e:record -- e2e/spl125-gmail-evidence.spec.ts
// The Gmail inbox itself is shown by a screenshot added to QA-SPL-125 by the account owner.
const password = 'LocalDemo123!';
const organiser = { email: 'developer@example.test', password };
const lead = { email: 'operations.manager@example.test', password };
const MAILPIT = process.env.MAILPIT_URL ?? 'http://127.0.0.1:54324';
const PAUSE_MS = Number(process.env.QA_PAUSE_MS ?? 1800);

test.skip(process.env.SPL125_GMAIL !== '1', 'Live Gmail send; set SPL125_GMAIL=1 to run it.');

async function caption(page: Page, text: string) {
  await page.evaluate(message => {
    document.getElementById('qa-caption')?.remove();
    const bar = document.createElement('div');
    bar.id = 'qa-caption';
    bar.setAttribute('role', 'note');
    bar.textContent = message;
    Object.assign(bar.style, {
      position: 'fixed', bottom: '0', left: '0', right: '0', zIndex: '2147483647',
      padding: '12px 20px', background: '#12263a', color: '#ffffff',
      font: '600 18px/1.3 system-ui, sans-serif', borderTop: '4px solid #f2b705', pointerEvents: 'none',
    });
    document.body.appendChild(bar);
  }, text);
  await page.waitForTimeout(PAUSE_MS);
}

async function signIn(page: Page, account: { email: string; password: string }, role?: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(account.email);
  await page.getByLabel('Password').fill(account.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/, { timeout: 15_000 });
  if (role) await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.goto('/workspace');
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

// QA-SPL-125-201 | AC3, AC7 | UAT live: one assignment sends real email through the Gmail API.
test('QA-SPL-125-201: with the Gmail API backend an assignment is emailed to the shared inbox', async ({ page }) => {
  test.setTimeout(Number(process.env.QA_TEST_TIMEOUT ?? 180_000));
  const name = `QA125 Gmail ${Date.now()}`;
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);

  // Setup (not a numbered step): the organiser submits one request.
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('SPL-125 Gmail API live send');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByRole('radio', { name: /AM · 7am–12pm/ }).check();
  await page.getByLabel('Expected attendance').fill('40');
  await page.getByRole('button', { name: 'Submit event request' }).click();
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
  await signOut(page);

  // Step 1 - AC1/AC3: the Lead assigns Casey; two notices, so two real emails.
  await signIn(page, lead);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  await page.getByRole('button', { name: `Assign coordinator to ${name}` }).click();
  await page.locator('form.assignment-panel').getByLabel('Event Coordinator').selectOption({ label: 'Casey Lim' });
  await page.getByRole('button', { name: 'Confirm assignment' }).click();
  await expect(page.getByText(`Casey Lim is now responsible for ${name}.`)).toBeVisible();
  await caption(page, `AC1/AC3: assignment saved for "${name}"; Casey and Devon are each sent one email`);

  // Step 2 - AC7: the Gmail backend sends through the Gmail API, so nothing reaches local Mailpit.
  await page.waitForTimeout(5000);
  const response = await page.request.get(`${MAILPIT}/api/v1/search`, {
    params: { query: `subject:"${name}"` },
  });
  expect((await response.json()).messages_count).toBe(0);
  await page.goto(`${MAILPIT}/search?q=${encodeURIComponent(`subject:"${name}"`)}`);
  await caption(page, 'AC7: Mailpit has no copy; the emails went to the shared Gmail inbox (see the Gmail screenshot)');
  await caption(page, `Subjects sent: "[ConnectSphere] For Casey Lim (Event Coordinator): ${name}" and "… For Devon Lee (Event Organiser) …"`);
});
