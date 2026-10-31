import { expect, test, type Page } from '@playwright/test';

// QA-SPL-111-200: the recorded manual (UAT) flow for SPL-111, "Submit a change request".
// One scripted step per acceptance criterion, in the same order as the written steps on the
// QA-SPL-111 page. Every step shows an on-screen caption naming the AC it proves, then pauses so
// the recording can be read without narration.

const organiser = { email: 'developer@example.test', password: 'LocalDemo123!' };
const manager = { email: 'operations.manager@example.test', password: 'LocalDemo123!' };
const coordinator = { email: 'event.coordinator@example.test', password: 'LocalDemo123!' };
const attendee = { email: 'attendee@example.test', password: 'LocalDemo123!' };
const coordinatorName = 'Casey Lim';

async function caption(page: Page, text: string, pause = 2200) {
  await page.evaluate(message => {
    let banner = document.getElementById('qa-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'qa-caption';
      banner.setAttribute('role', 'presentation');
      banner.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;pointer-events:none;padding:12px 16px;'
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

test('QA-SPL-111-200: an organiser submits a change request, the coordinator sees it, a second is refused', async ({
  page,
}) => {
  test.setTimeout(180_000);
  const name = `E2E Change ${Date.now()}`;
  let token = '';
  page.on('request', request => {
    const header = request.headers()['authorization'];
    if (header && request.url().includes('/api/')) token = header;
  });

  // Setup (not an AC): the organiser submits an event, the manager assigns a coordinator.
  await signIn(page, organiser, 'Event Organiser');
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('SPL-111 change request end-to-end check');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByRole('radio', { name: /AM · 7am–12pm/ }).check();
  await page.getByLabel('Expected attendance').fill('120');
  await page.getByRole('button', { name: 'Submit event request' }).click();
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);

  // AC1 (negative): a Submitted event cannot have a change request started.
  const row = () => page.getByRole('row').filter({ hasText: name });
  await expect(row()).toContainText('Submitted');
  await row().getByRole('button', { name: 'Change requests' }).click();
  await expect(page.getByText('No pending change request.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Request a change', exact: true })).toHaveCount(0);
  await caption(page, 'AC1: history opens while Submitted, but a new change request is not offered');
  await signOut(page);

  await signIn(page, manager);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  await page.getByRole('button', { name: `Assign coordinator to ${name}` }).click();
  await page.locator('form.assignment-panel').getByLabel('Event Coordinator').selectOption({ label: coordinatorName });
  await page.getByRole('button', { name: 'Confirm assignment' }).click();
  await expect(page.getByText(`${coordinatorName} is now responsible for ${name}.`)).toBeVisible();
  await signOut(page);

  await signIn(page, coordinator);
  await page.getByRole('link', { name: 'My assigned events' }).click();
  await page.getByRole('link', { name }).click();
  await page.getByRole('button', { name: 'Begin review' }).click();
  await expect(page.getByText('Under review').first()).toBeVisible();
  await signOut(page);

  // AC1 (positive): once Under review, the organiser is offered Change requests.
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'My requests' }).click();
  await expect(row()).toContainText('Under review');
  await caption(page, 'AC1: now Under review, so Change requests is offered');
  await row().getByRole('button', { name: 'Change requests' }).click();
  await expect(page.getByText('No pending change request.')).toBeVisible();

  // AC2 (negative then positive): an item must be complete; several items can be added.
  await page.getByRole('button', { name: 'Request a change' }).click();
  await page.getByRole('button', { name: 'Submit change request' }).click();
  await expect(page.getByRole('alert')).toContainText('Complete every item');
  await caption(page, 'AC2: cannot submit without a complete item (field, new value, reason)');
  await page.getByLabel('Field to change').selectOption('expected_attendance');
  await expect(page.getByRole('alert')).toHaveCount(0); // the refusal clears once the fix starts
  await page.getByLabel(/New value/).fill('80');
  await page.getByLabel('Reason').fill('The client reduced the guest list.');
  await page.getByRole('button', { name: 'Add another item' }).click();
  await page.getByLabel('Field to change').nth(1).selectOption('description');
  await page.getByLabel(/New value/).nth(1).fill('A smaller, seated evening.');
  await page.getByLabel('Reason').nth(1).fill('Matches the smaller guest list.');
  await caption(page, 'AC2: two complete items, each with field, new value and reason');
  await page.getByRole('button', { name: 'Submit change request' }).click();

  // AC3: the request is Pending.
  const pending = page.getByRole('group', { name: 'Pending change request' });
  await expect(pending).toContainText('Pending');
  await caption(page, 'AC3: status is Pending');
  await signOut(page);

  // AC3: the assigned coordinator can see it, on demand, read-only.
  await signIn(page, coordinator);
  await page.getByRole('link', { name: 'My assigned events' }).click();
  await page.getByRole('link', { name }).click();
  await page.getByRole('button', { name: 'View change requests' }).click();
  const seen = page.getByRole('group', { name: 'Pending change request' });
  await expect(seen).toContainText('Expected attendance');
  await expect(seen).toContainText('Requested: 80');
  await expect(page.getByRole('button', { name: 'Request a change' })).toHaveCount(0);
  await caption(page, 'AC3: the assigned coordinator sees the pending request and its items');
  await signOut(page);

  // Access: an attendee-only account has no route to the organiser's requests.
  await signIn(page, attendee);
  await expect(page.getByRole('link', { name: 'My requests' })).toHaveCount(0);
  await page.goto('/workspace/my-requests');
  await expect(page.getByText(name)).toHaveCount(0);
  await caption(page, 'Access: an attendee cannot reach the organiser\'s request or its change request');
  await signOut(page);

  // AC4: a second request is not offered, and the server refuses a direct attempt.
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'My requests' }).click();
  await row().getByRole('button', { name: 'Change requests' }).click();
  await expect(page.getByRole('group', { name: 'Pending change request' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Request a change' })).toHaveCount(0);
  await expect(page.getByText(/once this one is Closed/)).toBeVisible();
  await caption(page, 'AC4: no second request is offered while one is Pending');
  const refusal = await page.evaluate(async ({ header, title }) => {
    const headers = { Authorization: header, 'Content-Type': 'application/json' };
    const events = await (await fetch('/api/event-requests', { headers })).json();
    const event = events.event_requests.find((item: { name: string }) => item.name === title);
    const response = await fetch(`/api/event-requests/${event.id}/change-requests`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ items: [{ field: 'name', requested_value: 'Another', reason: 'Second try.' }] }),
    });
    return { status: response.status, body: await response.json() };
  }, { header: token, title: name });
  expect(refusal.status).toBe(409);
  await caption(page, `AC4: a direct second submission is refused by the server (HTTP ${refusal.status})`, 3000);

  // AC5: the pending request, with every item, is still there after a reload.
  await page.reload();
  await page.getByRole('link', { name: 'My requests' }).click();
  await row().getByRole('button', { name: 'Change requests' }).click();
  const after = page.getByRole('group', { name: 'Pending change request' });
  await expect(after).toContainText('Expected attendance');
  await expect(after).toContainText('At submission: 120');
  await expect(after).toContainText('Requested: 80');
  await expect(after).toContainText('The client reduced the guest list.');
  await expect(after).toContainText('Description');
  await expect(after).toContainText('A smaller, seated evening.');
  await caption(page, 'AC5: after a reload, the pending request shows all of its items', 3500);
});
