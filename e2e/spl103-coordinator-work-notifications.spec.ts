import { expect, test, type Page } from '@playwright/test';

const password = 'LocalDemo123!';
const organiser = { email: 'developer@example.test', password };
const lead = { email: 'operations.manager@example.test', password };
const casey = { email: 'event.coordinator@example.test', password };
const riley = { email: 'qa.coordinator.b@example.test', password };
const attendee = { email: 'attendee@example.test', password };

// Slow enough for a reviewer to read the caption in the recording; set to 0 for a fast local run.
const PAUSE_MS = Number(process.env.QA_PAUSE_MS ?? 1800);

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
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

async function submitRequest(page: Page, name: string) {
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByLabel('Event name').fill(name);
  await page.getByLabel('Purpose').fill('SPL-103 coordinator work notification walkthrough');
  await page.getByLabel('Proposed date').fill(tomorrow);
  await page.getByRole('radio', { name: /AM · 7am–12pm/ }).check();
  await page.getByLabel('Expected attendance').fill('80');
  await page.getByRole('button', { name: 'Submit event request' }).click();
  await expect(page).toHaveURL(/\/workspace\/my-requests$/);
}

async function openNotifications(page: Page) {
  await page.getByRole('link', { name: 'Notifications' }).click();
  await expect(page.getByRole('heading', { name: 'Notifications' })).toBeVisible();
}

async function assignTo(page: Page, name: string, coordinator: string) {
  await page.getByRole('button', { name: `Assign coordinator to ${name}` }).click();
  await page.locator('form.assignment-panel').getByLabel('Event Coordinator').selectOption({ label: coordinator });
  await page.getByRole('button', { name: 'Confirm assignment' }).click();
  await expect(page.getByText(`${coordinator} is now responsible for ${name}.`)).toBeVisible();
}

async function openAssignedEvent(page: Page, name: string) {
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'My assigned events' }).click();
  await page.getByRole('row').filter({ hasText: name }).getByRole('link', { name }).click();
}

// QA-SPL-103-200: the recorded manual flow for SPL-103. Each numbered step matches the written
// test steps in QA-SPL-103 and is introduced on screen by a caption naming the acceptance criterion.
test('QA-SPL-103-200: a coordinator is told of assignment, reassignment, answered clarification and change request, and nobody else is', async ({
  page,
}) => {
  test.setTimeout(Number(process.env.QA_TEST_TIMEOUT ?? 480_000));
  const stamp = Date.now();
  const forum = `QA103 Forum ${stamp}`; // assigned to Casey, then reassigned to Riley
  const summit = `QA103 Summit ${stamp}`; // assigned to Casey, clarified, change-requested
  let token = '';
  page.on('request', request => {
    const header = request.headers()['authorization'];
    if (header && request.url().includes('/api/')) token = header;
  });

  const assignedForum = `You have been assigned to ${forum}.`;
  const assignedSummit = `You have been assigned to ${summit}.`;
  const removedForum = `You are no longer responsible for ${forum}. It has been reassigned to Riley Chen.`;
  const answeredSummit = `The organiser responded to your clarification request on ${summit}.`;
  const changeSummit = `A change request was submitted on ${summit}: Expected attendance.`;

  // Setup (not a numbered step): the organiser submits two requests.
  await signIn(page, organiser, 'Event Organiser');
  for (const name of [forum, summit]) await submitRequest(page, name);
  await signOut(page);

  // Step 1 - AC1: assignment notifies the coordinator, naming the event.
  await signIn(page, lead);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  for (const name of [forum, summit]) await assignTo(page, name, 'Casey Lim');
  await caption(page, 'AC1: the Lead assigned the Forum and the Summit to Casey Lim');
  await signOut(page);
  await signIn(page, casey);
  await openNotifications(page);
  await expect(page.getByText(assignedForum)).toHaveCount(1);
  await expect(page.getByText(assignedSummit)).toHaveCount(1);
  await caption(page, 'AC1: Casey Lim has one notice per assignment, each naming the event');
  await signOut(page);

  // Step 2 - AC2: reassignment tells the previous coordinator, and the new one.
  await signIn(page, lead);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  const supervision = page.locator('section[aria-labelledby="supervision-heading"]');
  await supervision.getByRole('button', { name: `Reassign coordinator for ${forum}` }).click();
  await page.getByLabel('New Event Coordinator').selectOption({ label: 'Riley Chen' });
  await page.getByRole('button', { name: 'Confirm reassignment' }).click();
  await expect(page.getByText(`Riley Chen is now responsible for ${forum}.`)).toBeVisible();
  await caption(page, 'AC2: the Lead reassigned the Forum from Casey Lim to Riley Chen');
  await signOut(page);
  await signIn(page, casey);
  await openNotifications(page);
  await expect(page.getByText(removedForum)).toHaveCount(1);
  await caption(page, 'AC2: Casey Lim, the previous coordinator, is told the Forum was reassigned');
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'My assigned events' }).click();
  await expect(page.getByRole('row').filter({ hasText: summit })).toBeVisible();
  await expect(page.getByText(forum)).toHaveCount(0);
  await caption(page, 'AC2 (access): after reassignment the Forum has left Casey Lim\'s assigned events');
  await signOut(page);
  await signIn(page, riley);
  await openNotifications(page);
  await expect(page.getByText(assignedForum)).toHaveCount(1);
  await expect(page.getByText(removedForum)).toHaveCount(0);
  await caption(page, 'AC2: Riley Chen is told of the assignment and gets no "no longer responsible" notice');
  await signOut(page);

  // Step 3 - AC3: the organiser's answer notifies the coordinator who asked.
  await signIn(page, casey);
  await openAssignedEvent(page, summit);
  await page.getByRole('button', { name: 'Begin review' }).click();
  await page.getByLabel('Clarification for the Event Organiser').fill('Please confirm that attendance remains 80 people.');
  await page.getByRole('button', { name: 'Request clarification' }).click();
  await expect(page.getByRole('cell', { name: 'Returned for clarification' })).toBeVisible();
  await caption(page, 'AC3: Casey Lim asks the organiser to clarify the Summit');
  await openNotifications(page);
  await expect(page.getByText(answeredSummit)).toHaveCount(0);
  await caption(page, 'AC3 (negative): asking the question sends Casey Lim no "answered" notice');
  await signOut(page);
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'My requests' }).click();
  await page.getByRole('row').filter({ hasText: summit }).getByRole('button', { name: 'Respond to clarification' }).click();
  await page.getByLabel('Your response').fill('Attendance remains 80 people.');
  await page.getByRole('button', { name: 'Send response' }).click();
  await expect(page.getByRole('row').filter({ hasText: summit })).toContainText('Under review');
  await caption(page, 'AC3: the organiser answers the clarification request');
  await signOut(page);
  await signIn(page, casey);
  await openNotifications(page);
  await expect(page.getByText(answeredSummit)).toHaveCount(1);
  await caption(page, 'AC3: Casey Lim is told the organiser responded, naming the Summit');
  await page.reload();
  await openNotifications(page);
  await expect(page.getByText(answeredSummit)).toHaveCount(1);
  await caption(page, 'AC3 (after reload): still exactly one notice');
  await signOut(page);
  await signIn(page, riley);
  await openNotifications(page);
  await expect(page.getByText(answeredSummit)).toHaveCount(0);
  await caption(page, 'AC3 (access): Riley Chen, not involved in the Summit, is not told');
  await signOut(page);

  // Step 4 - AC4: a change request notifies the assigned coordinator.
  await signIn(page, organiser, 'Event Organiser');
  await page.getByRole('link', { name: 'My requests' }).click();
  const row = () => page.getByRole('row').filter({ hasText: summit });
  await row().getByRole('button', { name: 'Change requests' }).click();
  await page.getByRole('button', { name: 'Request a change' }).click();
  await page.getByLabel('Field to change').selectOption('expected_attendance');
  await page.getByLabel(/New value/).fill('60');
  await page.getByLabel('Reason').fill('The client reduced the guest list.');
  await page.getByRole('button', { name: 'Submit change request' }).click();
  await expect(page.getByRole('group', { name: 'Pending change request' })).toContainText('Pending');
  await caption(page, 'AC4: the organiser submits a change request on the Summit');
  await expect(page.getByRole('button', { name: 'Request a change' })).toHaveCount(0);
  await caption(page, 'AC4 (negative): a second request is not offered while one is pending');
  await signOut(page);
  await signIn(page, casey);
  await openNotifications(page);
  await expect(page.getByText(changeSummit)).toHaveCount(1);
  await expect(page.getByText('The client reduced the guest list.')).toHaveCount(0);
  await caption(page, 'AC4: Casey Lim is told a change request was submitted, naming the Summit and the field - not the value or reason');
  await signOut(page);

  // Step 5 - AC5: no false notices.
  await signIn(page, organiser, 'Event Organiser');
  const refusal = await page.evaluate(async ({ header, title }) => {
    const headers = { Authorization: header, 'Content-Type': 'application/json' };
    const events = await (await fetch('/api/event-requests', { headers })).json();
    const event = events.event_requests.find((item: { name: string }) => item.name === title);
    const response = await fetch(`/api/event-requests/${event.id}/change-requests`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ items: [{ field: 'name', requested_value: 'Another', reason: 'Second try.' }] }),
    });
    return response.status;
  }, { header: token, title: summit });
  expect(refusal).toBe(409);
  await caption(page, `AC5: a direct second change request is refused by the server (HTTP ${refusal})`);
  await signOut(page);
  await signIn(page, casey);
  await openNotifications(page);
  await page.reload();
  await openNotifications(page);
  for (const message of [assignedForum, assignedSummit, removedForum, answeredSummit, changeSummit]) {
    await expect(page.getByText(message)).toHaveCount(1);
  }
  await caption(page, 'AC5: after the refused request and a reload, each of Casey Lim\'s five notices appears exactly once');
  await signOut(page);
  await signIn(page, riley);
  await openNotifications(page);
  for (const message of [assignedSummit, removedForum, answeredSummit, changeSummit]) {
    await expect(page.getByText(message)).toHaveCount(0);
  }
  await caption(page, 'AC5: Riley Chen has none of the Summit\'s coordinator notices');
  await signOut(page);
  await signIn(page, attendee);
  await openNotifications(page);
  await expect(page.getByText('No notifications yet.')).toBeVisible();
  await caption(page, 'AC5: an unrelated account (attendee) has an empty inbox');
});
