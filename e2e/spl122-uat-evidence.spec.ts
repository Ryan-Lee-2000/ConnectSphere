import { expect, test, type Page } from '@playwright/test';

// SPL-122 recorded UAT, QA-SPL-122-200. Real local Auth and an isolated fixture event
// "SPL-122 QA Founders Day" (Planning, assigned to Casey Lim) holding a requested Projector, a
// requested Document Camera and a Portable Speaker line with 2 of 2 units reserved. Skipped unless
// SPL122_EVENT_ID names that event, so the ordinary browser suite never runs it.

const eventId = process.env.SPL122_EVENT_ID;
test.skip(!eventId, 'Requires the isolated SPL-122 real-Auth fixture.');

const password = 'LocalDemo123!';
const coordinator = 'event.coordinator@example.test';
const technicalSupport = 'technical.support@example.test';
// A re-recording uses a fresh fixture whose names carry SPL122_SUFFIX, so runs never share data.
const suffix = process.env.SPL122_SUFFIX ?? '';
const eventName = `SPL-122 QA Founders Day${suffix}`;
const lapel = `SPL-122 QA Lapel Microphone${suffix}`;
const projector = `SPL-122 QA Projector${suffix}`;
const camera = `SPL-122 QA Document Camera${suffix}`;

async function caption(page: Page, text: string) {
  await page.evaluate(message => {
    let banner = document.getElementById('uat-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'uat-caption';
      banner.setAttribute('aria-hidden', 'true');
      Object.assign(banner.style, {
        position: 'fixed', left: '8px', right: '8px', bottom: '8px', zIndex: '2147483647', padding: '10px 12px',
        borderRadius: '8px', background: 'rgba(16, 32, 56, 0.92)', color: '#fff', font: '600 16px/1.35 system-ui',
        pointerEvents: 'none',
      });
      document.body.appendChild(banner);
    }
    banner.textContent = message;
  }, text);
  await page.waitForTimeout(2_200);
}

async function signIn(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

const card = (page: Page, name: string) => page.locator('.equipment-requirements__card').filter({
  has: page.getByRole('heading', { name, exact: true }),
});

const eventNotices = (page: Page) => page.getByRole('listitem').filter({ hasText: eventName });

async function openNotifications(page: Page) {
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'Notifications' }).click();
  await expect(page.getByRole('heading', { name: 'Notifications', exact: true })).toBeVisible();
}

// QA-SPL-122-200 | AC1-AC5 | BB
test('[QA-SPL-122-200] Technical Support is notified of requirement changes and the cancellation', async ({ page }) => {
  test.setTimeout(240_000);
  const equipmentPath = `/workspace/assigned-events/${eventId}/equipment-requirements`;

  await test.step('Setup: the coordinator opens the event\'s equipment requirements', async () => {
    await signIn(page, coordinator);
    await page.goto(equipmentPath);
    await expect(page.getByRole('heading', { name: 'Equipment requirements' })).toBeVisible();
    await expect(card(page, projector)).toBeVisible();
  });

  await test.step('AC1: a line is recorded, changed and removed', async () => {
    await caption(page, `AC1: Casey Lim plans equipment for ${eventName}`);
    await page.getByRole('button', { name: 'Add requirement' }).click();
    await page.getByLabel('Catalogue equipment').selectOption({ label: `${lapel} — QA Store` });
    await page.getByLabel('Quantity').fill('4');
    await page.getByRole('button', { name: 'Add requirement' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Equipment requirement added.' })).toBeVisible();
    await card(page, lapel).scrollIntoViewIfNeeded();
    await caption(page, 'AC1 recorded: a Lapel Microphone × 4 line is added');

    await card(page, lapel).getByRole('button', { name: 'Edit requirement' }).click();
    await page.getByLabel('Quantity').fill('5');
    await page.getByRole('button', { name: 'Save requirement' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Equipment requirement saved.' })).toBeVisible();
    await expect(card(page, lapel)).toContainText('5');
    await caption(page, 'AC1 changed: the quantity goes from 4 to 5');

    page.once('dialog', dialog => dialog.accept());
    await card(page, projector).getByRole('button', { name: 'Remove' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Equipment requirement removed from active planning.' })).toBeVisible();
    await expect(card(page, projector)).toHaveCount(0);
    await caption(page, 'AC1 removed: the Projector line is removed');
  });

  await test.step('AC4: an identical retry and a refused save', async () => {
    await card(page, lapel).getByRole('button', { name: 'Edit requirement' }).click();
    await page.getByRole('button', { name: 'Save requirement' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Equipment requirement saved.' })).toBeVisible();
    await caption(page, 'AC4 retry: saving the same values again changes nothing, so it must add no notice');

    await card(page, camera).getByRole('button', { name: 'Edit requirement' }).click();
    const otherTab = await page.context().newPage();
    await otherTab.goto(equipmentPath);
    otherTab.once('dialog', dialog => dialog.accept());
    await card(otherTab, camera).getByRole('button', { name: 'Remove' }).click();
    await expect(otherTab.getByRole('status').filter({ hasText: 'Equipment requirement removed from active planning.' })).toBeVisible();
    await otherTab.close();
    await caption(page, 'AC4: meanwhile the Document Camera line was removed in another tab');
    await page.getByRole('button', { name: 'Save requirement' }).click();
    const refusal = page.getByRole('alert');
    await expect(refusal).toHaveText('This equipment requirement can no longer be changed or removed.');
    await refusal.scrollIntoViewIfNeeded();
    await caption(page, 'AC4 refused: the server refuses this stale save, so it must send no notice');
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  });

  await test.step('AC2: the event holding 2 reserved units is cancelled', async () => {
    await page.goto(`/workspace/assigned-events/${eventId}`);
    await expect(page.getByRole('heading', { name: eventName })).toBeVisible();
    const panel = page.getByRole('region', { name: 'Cancel this event' });
    await panel.scrollIntoViewIfNeeded();
    await caption(page, 'AC2: the event still holds 2 reserved Portable Speakers');
    await panel.getByRole('button', { name: 'Cancel event' }).click();
    const form = page.getByRole('form', { name: 'Cancel the event' });
    await form.getByLabel('Cancellation reason').fill('The founders moved the celebration online.');
    await form.getByRole('button', { name: 'Confirm cancellation' }).click();
    const cancelled = page.getByRole('status').filter({ hasText: 'Event cancelled.' });
    await expect(cancelled).toBeVisible();
    await cancelled.scrollIntoViewIfNeeded();
    await caption(page, 'AC2: the coordinator cancels the event; its venues and equipment are freed');
    await page.reload();
    const cancelledBy = page.getByRole('rowheader', { name: 'Cancelled by' }).locator('xpath=..');
    await expect(cancelledBy).toContainText('Casey Lim');
    await cancelledBy.scrollIntoViewIfNeeded();
    await caption(page, 'AC2: after reload the event is recorded as cancelled by Casey Lim');
  });

  await test.step('AC3: only Technical Support receives the notices, one per action', async () => {
    await openNotifications(page);
    await expect(eventNotices(page)).toHaveCount(0);
    await caption(page, 'AC3: the coordinator\'s own inbox has none of these notices');
    await signOut(page);

    await signIn(page, technicalSupport);
    await openNotifications(page);
    const items = eventNotices(page);
    await expect(items).toHaveCount(5);
    await expect(items.nth(0)).toContainText(`${eventName} was cancelled. 2 reserved equipment unit(s) were released.`);
    await expect(items.nth(1)).toContainText(`Equipment requirement removed from ${eventName}: ${camera} × 1.`);
    await expect(items.nth(2)).toContainText(`Equipment requirement removed from ${eventName}: ${projector} × 1.`);
    await expect(items.nth(3)).toContainText(`Equipment requirement changed on ${eventName}: ${lapel} × 5 (quantity).`);
    await expect(items.nth(4)).toContainText(`Equipment requirement added to ${eventName}: ${lapel} × 4.`);
    await caption(page, 'AC3: Tara Ng (the active Technical Support account here) has one notice per action');
    await items.nth(4).scrollIntoViewIfNeeded();
    await caption(page, 'AC4: 5 notices for 5 actions; none for the identical retry or the refused save');
  });

  await test.step('AC5: the notice opens the Equipment review queue', async () => {
    const latest = eventNotices(page).nth(0);
    await latest.scrollIntoViewIfNeeded();
    await caption(page, 'AC5: each notice links to the Equipment review queue');
    await latest.getByRole('link', { name: eventName }).click();
    await expect(page).toHaveURL(/\/workspace\/equipment-review-queue$/);
    await expect(page.getByRole('heading', { name: 'Equipment awaiting review' })).toBeVisible();
    await caption(page, 'AC5: Technical Support lands on Equipment awaiting review, a page it can open');
  });
});
