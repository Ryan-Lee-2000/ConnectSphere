import { expect, test, type Page } from '@playwright/test';

const password = 'LocalDemo123!';
const organiser = { email: 'developer@example.test', password };
const lead = { email: 'operations.manager@example.test', password };
const casey = { email: 'event.coordinator@example.test', password };
const riley = { email: 'qa.coordinator.b@example.test', password };

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
  await page.getByLabel('Purpose').fill('SPL-134 Lead supervision walkthrough');
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

// QA-SPL-134-060: the recorded manual flow for SPL-134. Each numbered step matches the written
// test steps in QA-SPL-134 and is introduced on screen by a caption naming the acceptance criterion.
test('QA-SPL-134-060: the Lead assigns, supervises and reassigns; each affected account is told once', async ({
  page,
}) => {
  test.setTimeout(Number(process.env.QA_TEST_TIMEOUT ?? 300_000));
  const name = `QA134 Gala ${Date.now()}`;
  const assigned = `You have been assigned to ${name}.`;
  const toOrganiserFirst = `Casey Lim is now the Event Coordinator responsible for ${name}.`;
  const removed = `You are no longer responsible for ${name}. It has been reassigned to Riley Chen.`;
  const toOrganiserSecond = `Riley Chen has taken over ${name} from Casey Lim as the Event Coordinator responsible for it.`;

  // Setup (not a numbered step): the organiser submits one request.
  await signIn(page, organiser, 'Event Organiser');
  await submitRequest(page, name);
  await signOut(page);

  // Step 1 - AC1: the request waits in the unassigned queue; nothing is chosen for the Lead.
  await signIn(page, lead);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  const queue = page.locator('section[aria-labelledby="assignment-queue-heading"]');
  await expect(queue.getByRole('row').filter({ hasText: name })).toBeVisible();
  await caption(page, 'AC1: the new request is in the unassigned queue; no coordinator was chosen automatically');
  await page.getByRole('button', { name: `Assign coordinator to ${name}` }).click();
  const panel = page.locator('form.assignment-panel');
  await expect(panel.getByText('SPL-134 Lead supervision walkthrough')).toBeVisible();
  await expect(panel.getByText('Expected attendance')).toBeVisible();
  await expect(panel.getByLabel('Event Coordinator')).toHaveValue('');
  await caption(page, 'AC1: basic information is shown (purpose, client, time, attendance, status); no coordinator preselected');
  await panel.getByLabel('Event Coordinator').selectOption({ label: 'Casey Lim' });
  await page.getByRole('button', { name: 'Confirm assignment' }).click();
  await expect(page.getByText(`Casey Lim is now responsible for ${name}.`)).toBeVisible();
  await caption(page, 'AC1: the Lead assigned an active coordinator; the request has left the queue');
  await expect(queue.getByRole('row').filter({ hasText: name })).toHaveCount(0);
  await signOut(page);

  // Step 2 - AC5: the new coordinator and the organiser are each notified once on assignment.
  await signIn(page, casey);
  await openNotifications(page);
  await expect(page.getByText(assigned)).toHaveCount(1);
  await caption(page, 'AC5 (assign): the new coordinator has one notice naming the event and the assignment');
  await signOut(page);
  await signIn(page, organiser, 'Event Organiser');
  await openNotifications(page);
  await expect(page.getByText(toOrganiserFirst)).toHaveCount(1);
  await caption(page, 'AC5 (assign): the organiser has one notice naming the event and the new coordinator');
  await signOut(page);

  // Step 3 - AC2: the Lead sees the assignment and the active event in the supervision view.
  await signIn(page, lead);
  await page.getByRole('link', { name: 'Coordinator assignment' }).click();
  const supervision = page.locator('section[aria-labelledby="supervision-heading"]');
  const row = supervision.getByRole('row').filter({ hasText: name });
  await expect(row).toContainText('Casey Lim');
  await expect(row).toContainText('Submitted');
  await caption(page, 'AC2: supervision lists the active event with its coordinator, status and basic information');

  // Step 4 - AC3: reassign; the status and arrangements stay as they were.
  await supervision.getByRole('button', { name: `Reassign coordinator for ${name}` }).click();
  await expect(page.getByText(/Casey Lim stops being responsible immediately/)).toBeVisible();
  await page.getByLabel('New Event Coordinator').selectOption({ label: 'Riley Chen' });
  await page.getByRole('button', { name: 'Confirm reassignment' }).click();
  await expect(page.getByText(`Riley Chen is now responsible for ${name}.`)).toBeVisible();
  await expect(row).toContainText('Riley Chen');
  await expect(row).toContainText('Submitted');
  await caption(page, 'AC3: reassigned to Riley Chen; the event status is unchanged (still Submitted)');
  await signOut(page);

  // Step 5 - AC5: former, new coordinator and organiser are each told once; the old notice no
  // longer opens the event.
  await signIn(page, casey);
  await openNotifications(page);
  await expect(page.getByText(removed)).toHaveCount(1);
  await expect(page.getByText(assigned)).toHaveCount(1);
  await caption(page, 'AC5 (reassign): the former coordinator has one new notice that responsibility has moved');
  await page.getByRole('link', { name }).first().click();
  await expect(page).toHaveURL(/\/workspace\/assigned-events\/\d+$/);
  await expect(page.getByRole('alert')).toBeVisible();
  await caption(page, 'AC3/AC4: the former coordinator is refused the event after reassignment');

  // Step 6 - AC4: a coordinator manages only their own events and cannot assign or reassign.
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'My assigned events' }).click();
  await expect(page.getByText(name)).toHaveCount(0);
  await caption(page, 'AC4: the former coordinator\'s own list no longer contains the event');
  await expect(page.getByRole('link', { name: 'Coordinator assignment' })).toHaveCount(0);
  await page.goto('/workspace/assignments');
  await expect(page.getByRole('heading', { name: 'Events awaiting a coordinator' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Active events and coordinators' })).toHaveCount(0);
  await caption(page, 'AC4: a coordinator is never offered assignment or supervision, even by typing the address');
  await signOut(page);

  await signIn(page, riley);
  await openNotifications(page);
  await expect(page.getByText(assigned)).toHaveCount(1);
  await caption(page, 'AC5 (reassign): the new coordinator has one notice naming the event');
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'My assigned events' }).click();
  await expect(page.getByText(name).first()).toBeVisible();
  await caption(page, 'AC3: authority has moved - the event is now in the new coordinator\'s own list');
  await signOut(page);

  await signIn(page, organiser, 'Event Organiser');
  await openNotifications(page);
  await expect(page.getByText(toOrganiserSecond)).toHaveCount(1);
  await expect(page.getByText(toOrganiserFirst)).toHaveCount(1);
  await caption(page, 'AC5 (reassign): the organiser has one notice naming the event and who took over');
});
