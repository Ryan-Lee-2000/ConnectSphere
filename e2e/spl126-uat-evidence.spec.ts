import { expect, test, type Page } from '@playwright/test';

// SPL-126 recorded UAT. Needs the app running with EMAIL_BACKEND=smtp, so every email lands in
// local Supabase's Mailpit (never delivered externally), and the seeded local demo accounts.
const password = 'LocalDemo123!';
const organiser = { email: 'developer@example.test', password };
const lead = { email: 'operations.manager@example.test', password };
const casey = { email: 'event.coordinator@example.test', password };
const riley = { email: 'qa.coordinator.b@example.test', password };
const attendee = { email: 'attendee@example.test', password };
const MAILPIT = process.env.MAILPIT_URL ?? 'http://127.0.0.1:54324';
const ASSIGNMENT = 'coordinator_assignment';

// Slow enough for a reviewer to read the caption in the recording; set to 0 for a fast local run.
const PAUSE_MS = Number(process.env.QA_PAUSE_MS ?? 1800);

type MailSummary = { ID: string; Subject: string };

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

// The signed-in account's own API call, made from its browser session (no identifier is sent).
async function callApi(page: Page, path: string, method = 'GET', body?: unknown) {
  return page.evaluate(async ({ path, method, body }) => {
    const key = Object.keys(localStorage).find(k => k.startsWith('sb-') && k.endsWith('-auth-token'))!;
    const token = JSON.parse(localStorage.getItem(key)!).access_token;
    const response = await fetch(path, {
      method,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return { status: response.status, body: await response.json().catch(() => null) };
  }, { path, method, body });
}

async function openSettings(page: Page) {
  await page.getByRole('link', { name: 'Notifications' }).click();
  await page.getByRole('link', { name: 'Email settings' }).click();
  await expect(page).toHaveURL(/\/workspace\/notification-settings$/);
  await expect(page.getByRole('heading', { name: 'Email settings' })).toBeVisible();
}

async function submitRequest(page: Page, name: string) {
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('SPL-126 email settings walkthrough');
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
  await page.waitForTimeout(2000); // nothing else arrives late
  const emails = await emailsFor(page, event);
  expect(emails).toHaveLength(count);
  return emails;
}

async function showInbox(page: Page, event: string) {
  await page.goto(`${MAILPIT}/search?q=${encodeURIComponent(`subject:"${event}"`)}`);
  await expect(page.getByText(event).first()).toBeVisible();
}

// QA-SPL-126-200 | AC1-AC6 | UAT: each step is captioned with the AC it shows.
test('QA-SPL-126-200: a type turned off stops only its emails; in-app notices still arrive', async ({ page, browser }) => {
  test.setTimeout(Number(process.env.QA_TEST_TIMEOUT ?? 300_000));
  const name = `QA126 Forum ${Date.now()}`;

  try {
    // Setup (not a numbered step): the organiser submits one request; Casey starts from the default.
    await signIn(page, organiser, 'Event Organiser');
    await submitRequest(page, name);
    await signOut(page);
    await signIn(page, casey);
    expect((await callApi(page, `/api/notification-settings/${ASSIGNMENT}`, 'PUT', { email: true })).status).toBe(200);

    // Step 1 - AC2: the settings screen lists each type Casey receives, each with an email switch.
    await openSettings(page);
    const switches = page.getByRole('switch');
    await expect(switches).toHaveCount(5);
    await expect(page.getByRole('group', { name: 'Event Coordinator' })).toBeVisible();
    await caption(page, 'AC2: Email settings lists each of Casey\'s 5 notification types with an email on/off switch');

    // Step 2 - AC3: every switch starts on.
    for (const item of await switches.all()) await expect(item).toBeChecked();
    await caption(page, 'AC3: every type defaults to on: all 5 switches are on');

    // Step 3 - AC4: Casey turns one type off; it saves at once.
    const assignment = page.getByRole('switch', { name: 'Assignment changes' });
    await assignment.click();
    await expect(assignment).not.toBeChecked();
    await expect(page.getByText('Email off')).toBeVisible();
    await page.reload();
    await expect(page.getByRole('switch', { name: 'Assignment changes' })).not.toBeChecked();
    await caption(page, 'AC4: Casey turns "Assignment changes" off; it is still off after reloading the page');
    await signOut(page);

    // Step 4 - AC6: the Lead assigns Casey. SPL-125 checks the settings before sending.
    await signIn(page, lead);
    await page.getByRole('link', { name: 'Coordinator assignment' }).click();
    await page.getByRole('button', { name: `Assign coordinator to ${name}` }).click();
    await page.locator('form.assignment-panel').getByLabel('Event Coordinator').selectOption({ label: 'Casey Lim' });
    await page.getByRole('button', { name: 'Confirm assignment' }).click();
    await expect(page.getByText(`Casey Lim is now responsible for ${name}.`)).toBeVisible();
    const first = await waitForEmails(page, name, 1);
    expect(first[0].Subject).toBe(`[ConnectSphere] For Devon Lee (Event Organiser): ${name}`);
    await showInbox(page, name);
    await caption(page, 'AC6: the assignment notified Casey and Devon, but only Devon\'s email was sent; Casey\'s setting was checked first');

    // Step 5 - AC1, AC4: Casey's in-app notice still arrives; it is an "Assignment changes" notice.
    await page.goto('/workspace');
    await signOut(page);
    await signIn(page, casey);
    await page.getByRole('link', { name: 'Notifications' }).click();
    await expect(page.getByText(`You have been assigned to ${name}.`)).toHaveCount(1);
    await caption(page, 'AC1/AC4: in-app notices cannot be turned off: Casey\'s assignment notice (type "Assignment changes") is in her inbox');
    await signOut(page);

    // Step 6 - AC4: only that type and only Casey: a reassignment emails Riley and Devon, not Casey.
    await signIn(page, lead);
    await page.getByRole('link', { name: 'Coordinator assignment' }).click();
    const supervision = page.locator('section[aria-labelledby="supervision-heading"]');
    await supervision.getByRole('button', { name: `Reassign coordinator for ${name}` }).click();
    await page.getByLabel('New Event Coordinator').selectOption({ label: 'Riley Chen' });
    await page.getByRole('button', { name: 'Confirm reassignment' }).click();
    await expect(page.getByText(`Riley Chen is now responsible for ${name}.`)).toBeVisible();
    const all = await waitForEmails(page, name, 3);
    const subjects = all.map(m => m.Subject);
    expect(subjects).toContain(`[ConnectSphere] For Riley Chen (Event Coordinator): ${name}`);
    expect(subjects.filter(s => s.includes('Casey Lim'))).toHaveLength(0);
    await showInbox(page, name);
    await caption(page, 'AC4: the reassignment emailed Riley and Devon (3 emails in all); Casey\'s removal notice sent no email');
    await signOut(page);

    // Step 7 - AC5: another coordinator cannot see or change Casey's choice; every role has its own.
    await signIn(page, riley);
    await openSettings(page);
    for (const item of await page.getByRole('switch').all()) await expect(item).toBeChecked();
    const refused = await callApi(page, `/api/notification-settings/${ASSIGNMENT}`, 'PUT', {
      email: false, account_id: '00000000-0000-0000-0000-000000000000',
    });
    expect(refused.status).toBe(400);
    const otherRole = await callApi(page, '/api/notification-settings/attendee_registration', 'PUT', { email: false });
    expect(otherRole.status).toBe(404);
    await caption(page, `AC5: Riley sees only her own settings (all on); naming another account is refused (HTTP ${refused.status}), and a type outside her role is not found (HTTP ${otherRole.status})`);
    await signOut(page);
    await signIn(page, attendee);
    await openSettings(page);
    await expect(page.getByRole('group', { name: 'Attendee' })).toBeVisible();
    await expect(page.getByRole('switch')).toHaveCount(2);
    await caption(page, 'AC5: an Attendee account has its own settings too: its 2 attendee types, both on');
  } finally {
    // Leave Casey on the default, so later specs see every email.
    const reset = await browser.newPage();
    await signIn(reset, casey);
    expect((await callApi(reset, `/api/notification-settings/${ASSIGNMENT}`, 'PUT', { email: true })).status).toBe(200);
    await reset.close();
  }
});
