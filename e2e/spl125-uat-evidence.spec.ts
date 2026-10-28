import { expect, test, type Page } from '@playwright/test';

// SPL-125 recorded UAT. Needs the app running with EMAIL_BACKEND=smtp, so every email lands in
// local Supabase's Mailpit (never delivered externally), and the seeded local demo accounts.
const password = 'LocalDemo123!';
const organiser = { email: 'developer@example.test', password };
const lead = { email: 'operations.manager@example.test', password };
const casey = { email: 'event.coordinator@example.test', password };
const MAILPIT = process.env.MAILPIT_URL ?? 'http://127.0.0.1:54324';
const SHARED = 'connectsphere.notices@gmail.com';

// Slow enough for a reviewer to read the caption in the recording; set to 0 for a fast local run.
const PAUSE_MS = Number(process.env.QA_PAUSE_MS ?? 1800);

type MailSummary = { ID: string; Subject: string; Created: string; Tags: string[]; To: { Address: string }[] };

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
  await expect(page).toHaveURL(/\/workspace$/);
  if (role) await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.goto('/workspace');
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

async function submitRequest(page: Page, name: string) {
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('SPL-125 email walkthrough');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByRole('radio', { name: /AM · 7am–12pm/ }).check();
  await page.getByLabel('Expected attendance').fill('80');
  await page.getByRole('button', { name: 'Submit event request' }).click();
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
}

async function emailsFor(page: Page, event: string): Promise<MailSummary[]> {
  const response = await page.request.get(`${MAILPIT}/api/v1/search`, {
    params: { query: `subject:"${event}"`, limit: '50' },
  });
  expect(response.ok()).toBeTruthy();
  return (await response.json()).messages as MailSummary[];
}

async function waitForEmails(page: Page, event: string, count: number) {
  await expect.poll(async () => (await emailsFor(page, event)).length, { timeout: 15_000 }).toBe(count);
  return emailsFor(page, event);
}

async function showInbox(page: Page, event: string) {
  await page.goto(`${MAILPIT}/search?q=${encodeURIComponent(`subject:"${event}"`)}`);
  await expect(page.getByText(event).first()).toBeVisible();
}

async function showEmail(page: Page, id: string) {
  await page.goto(`${MAILPIT}/view/${id}`);
  await expect(page.locator('body')).toContainText('[ConnectSphere]');
}

async function plainText(page: Page, id: string) {
  const response = await page.request.get(`${MAILPIT}/view/${id}.txt`);
  expect(response.ok()).toBeTruthy();
  return response.text();
}

// QA-SPL-125-200 | AC1-AC5, AC7 | UAT: each step is captioned with the AC it shows.
test('QA-SPL-125-200: every notice also arrives once by email, named for its recipient and role', async ({
  page,
}) => {
  test.setTimeout(Number(process.env.QA_TEST_TIMEOUT ?? 300_000));
  const name = `QA125 Gala ${Date.now()}`;
  const assigned = `You have been assigned to ${name}.`;

  // Setup (not a numbered step): the organiser submits one request.
  await signIn(page, organiser, 'Event Organiser');
  await submitRequest(page, name);
  await signOut(page);
  expect(await emailsFor(page, name)).toHaveLength(0);

  // Step 1 - AC1, AC2: the Lead assigns Casey; each in-app notice produces one email at once.
  await signIn(page, lead);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  await page.getByRole('button', { name: `Assign coordinator to ${name}` }).click();
  await page.locator('form.assignment-panel').getByLabel('Event Coordinator').selectOption({ label: 'Casey Lim' });
  const savedAt = Date.now();
  await page.getByRole('button', { name: 'Confirm assignment' }).click();
  await expect(page.getByText(`Casey Lim is now responsible for ${name}.`)).toBeVisible();
  await caption(page, 'AC1/AC2: the assignment is saved; it notifies Casey (coordinator) and Devon (organiser)');
  const first = await waitForEmails(page, name, 2);
  const seconds = Math.max(...first.map(m => (Date.parse(m.Created) - savedAt) / 1000));
  expect(seconds).toBeLessThan(10);
  await showInbox(page, name);
  await caption(page, `AC1/AC2/AC7: exactly 2 emails, one per notice, in local Mailpit within ${seconds.toFixed(1)} s of the save`);

  // Step 2 - AC3: one shared address; subject and first line name the recipient and role.
  const toCasey = first.find(m => m.Subject.includes('Casey Lim'))!;
  const toDevon = first.find(m => m.Subject.includes('Devon Lee'))!;
  expect(toCasey.Subject).toBe(`[ConnectSphere] For Casey Lim (Event Coordinator): ${name}`);
  expect(toDevon.Subject).toBe(`[ConnectSphere] For Devon Lee (Event Organiser): ${name}`);
  expect(first.every(m => m.To.length === 1 && m.To[0].Address === SHARED)).toBeTruthy();
  await showEmail(page, toCasey.ID);
  await caption(page, `AC3: sent to the one shared address; the subject names Casey Lim and the role Event Coordinator`);
  const body = await plainText(page, toCasey.ID);
  expect(body.split('\n')[0].trim()).toBe('For Casey Lim (Event Coordinator)');
  await caption(page, 'AC3: the first line of the email is "For Casey Lim (Event Coordinator)"');

  // Step 3 - AC4: event, the in-app wording, Singapore time, and a link to the notice's page.
  expect(body).toContain(`Event: ${name}`);
  expect(body).toContain(`What changed: ${assigned}`);
  expect(body).toMatch(/When: \w{3} \d{1,2} \w{3} \d{4}, \d{2}:\d{2} SGT/);
  const link = body.match(/Open: (\S+)/)![1];
  await caption(page, 'AC4: event name, what changed, when (SGT) and an Open link are in the email');
  await signOut(page);
  await signIn(page, casey);
  await page.getByRole('link', { name: 'Notifications' }).click();
  await expect(page.getByText(assigned)).toHaveCount(1);
  await caption(page, 'AC4: Casey\'s in-app notice uses the same wording as the email');
  await page.getByRole('link', { name }).first().click();
  const noticePage = new URL(page.url()).pathname;
  await page.goto(link);
  expect(new URL(page.url()).pathname).toBe(noticePage);
  await expect(page.getByRole('heading', { name })).toBeVisible();
  await caption(page, `AC4: the email's link opens the same page as the in-app notice (${noticePage})`);

  // Step 4 - AC5: a refused action sends no email.
  const status = await page.evaluate(async path => {
    const key = Object.keys(localStorage).find(k => k.startsWith('sb-') && k.endsWith('-auth-token'))!;
    const token = JSON.parse(localStorage.getItem(key)!).access_token;
    const response = await fetch(path, {
      method: 'PUT',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ coordinator_account_id: '00000000-0000-0000-0000-000000000000' }),
    });
    return response.status;
  }, `/api/event-requests/${noticePage.split('/').pop()}/coordinator`);
  expect(status).toBe(403);
  await caption(page, `AC5: Casey tries to reassign the event herself; the server refuses it (HTTP ${status})`);
  await page.waitForTimeout(2000);
  expect(await emailsFor(page, name)).toHaveLength(2);
  await showInbox(page, name);
  await caption(page, 'AC5: still exactly 2 emails; the refused action sent none');
  await signOut(page);

  // Step 5 - AC1, AC3: a reassignment notifies three accounts, each by their own email and role.
  await signIn(page, lead);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  const supervision = page.locator('section[aria-labelledby="supervision-heading"]');
  await supervision.getByRole('button', { name: `Reassign coordinator for ${name}` }).click();
  await page.getByLabel('New Event Coordinator').selectOption({ label: 'Riley Chen' });
  await page.getByRole('button', { name: 'Confirm reassignment' }).click();
  await expect(page.getByText(`Riley Chen is now responsible for ${name}.`)).toBeVisible();
  const all = await waitForEmails(page, name, 5);
  const subjects = all.map(m => m.Subject);
  expect(subjects).toContain(`[ConnectSphere] For Riley Chen (Event Coordinator): ${name}`);
  expect(subjects.filter(s => s.includes('For Casey Lim (Event Coordinator)'))).toHaveLength(2);
  expect(subjects.filter(s => s.includes('For Devon Lee (Event Organiser)'))).toHaveLength(2);
  expect(all.every(m => m.Tags.length > 0 && !m.Tags.includes('retried'))).toBeTruthy();
  await showInbox(page, name);
  await caption(page, 'AC1/AC3: reassignment added 3 emails (Riley, Casey, Devon), each naming its recipient and role');
});
