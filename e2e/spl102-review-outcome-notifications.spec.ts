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
  await page.getByLabel('Purpose').fill('SPL-102 review outcome notification walkthrough');
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

// QA-SPL-102-060: the recorded manual flow for SPL-102. Each numbered step matches the written
// test steps in QA-SPL-102 and is introduced on screen by a caption naming the acceptance criterion.
test('QA-SPL-102-060: the organiser is told of assignment, clarification, decision and withdrawal, and nobody else is', async ({
  page,
}) => {
  test.setTimeout(Number(process.env.QA_TEST_TIMEOUT ?? 420_000));
  const stamp = Date.now();
  const a = `QA102 Forum ${stamp}`; // assigned, questioned, approved
  const b = `QA102 Summit ${stamp}`; // assigned, rejected
  const c = `QA102 Expo ${stamp}`; // assigned, reassigned, withdrawn
  const question = 'Please confirm that attendance remains 80 people.';
  const reason = 'The proposed date clashes with the examination period.';

  const assignedA = `Casey Lim is now the Event Coordinator responsible for ${a}.`;
  const assignedB = `Casey Lim is now the Event Coordinator responsible for ${b}.`;
  const assignedC = `Casey Lim is now the Event Coordinator responsible for ${c}.`;
  const reassignedC = `Riley Chen has taken over ${c} from Casey Lim as the Event Coordinator responsible for it.`;
  const clarificationA = `Clarification was requested on ${a}: ${question}`;
  const approvedA = `${a} has been approved.`;
  const rejectedB = `${b} has been rejected. Reason: ${reason}`;
  const withdrawnC = `The withdrawal of ${c} has been recorded.`;
  const organiserMessages = [
    assignedA, assignedB, assignedC, reassignedC, clarificationA, approvedA, rejectedB, withdrawnC,
  ];

  // Setup (not a numbered step): the organiser submits three requests.
  await signIn(page, organiser, 'Event Organiser');
  for (const name of [a, b, c]) await submitRequest(page, name);
  await signOut(page);

  // Step 1 - AC1: assignment and reassignment each notify the organiser, naming the event.
  await signIn(page, lead);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  for (const name of [a, b, c]) await assignTo(page, name, 'Casey Lim');
  const supervision = page.locator('section[aria-labelledby="supervision-heading"]');
  await supervision.getByRole('button', { name: `Reassign coordinator for ${c}` }).click();
  await page.getByLabel('New Event Coordinator').selectOption({ label: 'Riley Chen' });
  await page.getByRole('button', { name: 'Confirm reassignment' }).click();
  await expect(page.getByText(`Riley Chen is now responsible for ${c}.`)).toBeVisible();
  await caption(page, 'AC1: the Lead assigned three requests to Casey Lim and reassigned one to Riley Chen');
  await signOut(page);
  await signIn(page, organiser, 'Event Organiser');
  await openNotifications(page);
  for (const message of [assignedA, assignedB, assignedC, reassignedC]) {
    await expect(page.getByText(message)).toHaveCount(1);
  }
  await caption(page, 'AC1: the organiser has one notice per assignment and one for the reassignment, each naming the event');
  await signOut(page);

  // Step 2 - AC2: a clarification request notifies the organiser with the coordinator's message.
  await signIn(page, casey);
  await openAssignedEvent(page, a);
  await page.getByRole('button', { name: 'Begin review' }).click();
  await page.getByLabel('Clarification for the Event Organiser').fill(question);
  await page.getByRole('button', { name: 'Request clarification' }).click();
  await expect(page.getByRole('cell', { name: 'Returned for clarification' })).toBeVisible();
  await caption(page, 'AC2: Casey Lim requests clarification on the Forum with a message');
  await expect(page.getByRole('button', { name: 'Request clarification' })).toHaveCount(0);
  await caption(page, 'AC2 (negative): the request cannot be repeated - the action is no longer offered');
  await signOut(page);
  await signIn(page, organiser, 'Event Organiser');
  await openNotifications(page);
  await expect(page.getByText(clarificationA)).toHaveCount(1);
  await caption(page, 'AC2: the organiser has one notice naming the event and containing the coordinator\'s message');
  await page.reload();
  await openNotifications(page);
  await expect(page.getByText(clarificationA)).toHaveCount(1);
  await caption(page, 'AC2 (after reload): still exactly one notice');
  await page.getByRole('link', { name: 'My requests' }).click();
  await page.getByRole('row').filter({ hasText: a }).getByRole('button', { name: 'Respond to clarification' }).click();
  await page.getByLabel('Your response').fill('Attendance remains 80 people.');
  await page.getByRole('button', { name: 'Send response' }).click();
  await expect(page.getByRole('row').filter({ hasText: a })).toContainText('Under review');
  await signOut(page);

  // Step 3 - AC3: approval and rejection (with the reason) notify the organiser.
  await signIn(page, casey);
  await openAssignedEvent(page, a);
  await page.getByRole('button', { name: 'Approve request' }).click();
  await expect(page.getByRole('button', { name: 'Approve request' })).toHaveCount(0);
  await caption(page, 'AC3: Casey Lim approves the Forum');
  await expect(page.getByRole('button', { name: 'Reject request' })).toHaveCount(0);
  await caption(page, 'AC3 (negative): a decided request offers no second decision, so no conflicting notice can be sent');
  await openAssignedEvent(page, b);
  await page.getByRole('button', { name: 'Begin review' }).click();
  await page.getByRole('button', { name: 'Reject request' }).click();
  await page.getByLabel('Reason for rejecting this request').fill(reason);
  await page.getByRole('button', { name: 'Continue' }).click();
  await page.getByRole('button', { name: 'Confirm rejection' }).click();
  await expect(page.getByRole('button', { name: 'Confirm rejection' })).toHaveCount(0);
  await caption(page, 'AC3: Casey Lim rejects the Summit and gives a reason');
  await signOut(page);
  await signIn(page, organiser, 'Event Organiser');
  await openNotifications(page);
  await expect(page.getByText(approvedA)).toHaveCount(1);
  await expect(page.getByText(rejectedB)).toHaveCount(1);
  await caption(page, 'AC3: the organiser has an approval notice naming the event and a rejection notice with the reason');
  await page.getByRole('link', { name: b }).first().click();
  await expect(page).toHaveURL(/\/workspace\/organisation-events\/\d+$/);
  await caption(page, 'AC3: the notice opens the organiser\'s own event page');
  await signOut(page);

  // Step 4 - AC4: a recorded withdrawal notifies the organiser, naming the event.
  await signIn(page, casey);
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'My assigned events' }).click();
  await expect(page.getByRole('row').filter({ hasText: b })).toBeVisible();
  await expect(page.getByText(c)).toHaveCount(0);
  await caption(page, 'AC4 (access): after reassignment the Expo has left Casey Lim\'s list, so Casey Lim cannot withdraw it');
  await signOut(page);
  await signIn(page, riley);
  await openAssignedEvent(page, c);
  await page.getByRole('button', { name: 'Record withdrawal' }).click();
  await page.getByLabel('Withdrawal note (optional)').fill('Organiser withdrew by email.');
  await page.getByRole('button', { name: 'Confirm withdrawal' }).click();
  await expect(page.getByRole('cell', { name: 'Withdrawn' })).toBeVisible();
  await caption(page, 'AC4: the new coordinator, Riley Chen, records the withdrawal of the Expo');
  await expect(page.getByRole('button', { name: 'Record withdrawal' })).toHaveCount(0);
  await caption(page, 'AC4 (negative): a withdrawn request cannot be withdrawn again');
  await signOut(page);
  await signIn(page, organiser, 'Event Organiser');
  await openNotifications(page);
  await expect(page.getByText(withdrawnC)).toHaveCount(1);
  await expect(page.getByText('Organiser withdrew by email.')).toHaveCount(0);
  await caption(page, 'AC4: the organiser has one notice naming the event; the coordinator\'s note is not copied into it');

  // Step 5 - AC5: no false notices, and only the organiser of that event is notified.
  await page.reload();
  await openNotifications(page);
  for (const message of organiserMessages) await expect(page.getByText(message)).toHaveCount(1);
  await caption(page, 'AC5: after reload every one of the eight notices still appears exactly once - none repeated');
  await signOut(page);
  for (const [who, label] of [[casey, 'the former coordinator'], [riley, 'the new coordinator']] as const) {
    await signIn(page, who);
    await openNotifications(page);
    for (const message of [clarificationA, approvedA, rejectedB, withdrawnC]) {
      await expect(page.getByText(message)).toHaveCount(0);
    }
    await caption(page, `AC5: ${label} has none of the organiser's review-outcome notices`);
    await signOut(page);
  }
  await signIn(page, attendee);
  await openNotifications(page);
  await expect(page.getByText('No notifications yet.')).toBeVisible();
  await caption(page, 'AC5: an unrelated account (attendee) has an empty inbox');
});
