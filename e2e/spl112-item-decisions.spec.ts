import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';
test.skip(!process.env.SPL112_UAT_IDS, 'Requires isolated SPL-112 real-Auth UAT fixtures.');
async function caption(page: Page, text: string, name: string) {
  await page.evaluate(message => {
    let el = document.getElementById('qa-caption');
    if (!el) { el = document.createElement('div'); el.id = 'qa-caption'; el.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:99999;background:#163c42;color:white;padding:14px;font:18px system-ui;text-align:center;pointer-events:none'; document.body.appendChild(el); }
    el.textContent = message;
  }, text);
  await page.waitForTimeout(1800);
  await page.screenshot({ path: `artifacts/spl-112-qa/${name}.png` });
}
async function login(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill('LocalDemo123!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/workspace/, { timeout: 30000 });
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible({ timeout: 30000 });
}
async function open(page: Page, id: number) {
  await page.goto(`/workspace/assigned-events/${id}`);
  await page.getByRole('button', { name: 'View change requests', exact: true }).click({ timeout: 30000 });
  await expect(page.getByRole('region', { name: /Decisions for change request/ })).toBeVisible({ timeout: 30000 });
}
// QA-SPL-112-200 | AC1-5 | BB
test('[QA-SPL-112-200] partial decisions, impacts, audit and finality', async ({ page }) => {
  test.setTimeout(240000);
  const ids = JSON.parse(readFileSync(process.env.SPL112_UAT_IDS!, 'utf8'));
  await login(page, 'event.coordinator@example.test');
  await open(page, ids.confirmed.event);
  await test.step('AC1 require a decline reason and select acceptance independently', async () => {
    await page.getByRole('combobox', { name: 'Outcome for Description', exact: true }).selectOption('declined');
    await page.getByRole('button', { name: 'Review decisions', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('Give a reason for every declined item.');
    await caption(page, 'AC1: Decline without a reason is refused; items are decided independently', 'ac1');
    await page.getByLabel('Decline reason for Description').fill('Keep the original description.');
    await page.getByRole('combobox', { name: 'Outcome for Expected attendance', exact: true }).selectOption('accepted');
    await page.getByRole('combobox', { name: 'Outcome for Equipment requirement', exact: true }).selectOption('accepted');
  });
  await test.step('AC2 review impacts before applying accepted values', async () => {
    await page.getByRole('button', { name: 'Review decisions', exact: true }).click();
    const impacts = page.getByRole('region', { name: 'Review decision impacts' });
    await expect(impacts).toContainText('This event will return to Planning.');
    await expect(impacts).toContainText(/release|review/i);
    await impacts.scrollIntoViewIfNeeded();
    await caption(page, 'AC2: accepted attendance and equipment changes preview review impacts and return to Planning', 'ac2');
    await page.getByRole('button', { name: 'Confirm decisions', exact: true }).click();
    await expect(page.getByRole('group', { name: 'Pending change request', exact: true })).toContainText('Accepted', { timeout: 30000 });
    await expect(page.getByRole('combobox')).toHaveCount(1);
    await page.goto(`/workspace/assigned-events/${ids.confirmed.event}/equipment-requirements`);
    const line = page.getByRole('article').filter({ hasText: ids.equipment });
    await expect(line).toContainText(/review required/i, { timeout: 30000 });
    await expect(line.locator('dd').first()).toHaveText('4');
    await open(page, ids.confirmed.event);
  });
  await test.step('AC3 partial request stays Pending and last decision closes it', async () => {
    await expect(page.getByRole('group', { name: 'Pending change request', exact: true })).toBeVisible();
    await page.getByRole('combobox', { name: 'Outcome for Event name', exact: true }).selectOption('accepted');
    await page.getByRole('button', { name: 'Review decisions', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm decisions', exact: true }).click();
    const closed = page.getByRole('group', { name: 'Closed change request', exact: true });
    await expect(closed).toBeVisible({ timeout: 30000 });
    await expect(closed).toContainText('Declined');
    await closed.scrollIntoViewIfNeeded();
    await caption(page, 'AC3: mixed Accepted and Declined results; the last pending item closes the request', 'ac3');
  });
  await test.step('AC4 decision actor and time survive reload', async () => {
    await open(page, ids.confirmed.event);
    const closed = page.getByRole('group', { name: 'Closed change request', exact: true });
    await expect(closed).toContainText('by Casey Lim');
    await expect(closed).toContainText('Decline reason: Keep the original description.');
    await closed.scrollIntoViewIfNeeded();
    await caption(page, 'AC4: each decision retains Casey Lim, decision date/time and the decline reason after reload', 'ac4');
  });
  await test.step('AC5 Closed and terminal events have no decision action; other coordinator denied', async () => {
    await expect(page.getByRole('button', { name: 'Review decisions', exact: true })).toHaveCount(0);
    for (const status of ['cancelled', 'completed']) {
      await open(page, ids[status].event);
      await expect(page.getByText('Pending · decisions are unavailable in this event status.', { exact: true })).toHaveCount(3);
      await expect(page.getByRole('combobox')).toHaveCount(0);
      await caption(page, `AC5: ${status} event refuses decisions; pending proposals are read-only`, `ac5-${status}`);
    }
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await login(page, 'qa.coordinator.b@example.test');
    await page.goto(`/workspace/assigned-events/${ids.confirmed.event}`);
    await expect(page.getByRole('alert')).toBeVisible({ timeout: 30000 });
    await expect(page.getByRole('button', { name: 'Review decisions', exact: true })).toHaveCount(0);
    await caption(page, 'Access: another coordinator cannot view or decide this assigned event', 'access');
  });
});
