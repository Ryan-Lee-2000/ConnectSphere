import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

test.skip(!process.env.SPL113_UAT_IDS, 'Requires isolated SPL-113 outcome fixtures.');

async function login(page: Page, email: string, chooseRole = false) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill('LocalDemo123!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/workspace/, { timeout: 30000 });
  if (chooseRole) await page.getByRole('button', { name: /^Event Organiser/ }).click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible({ timeout: 30000 });
}

async function caption(page: Page, text: string, frame: string) {
  await page.evaluate(message => {
    let banner = document.getElementById('qa-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'qa-caption';
      banner.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:99999;background:#163c42;color:white;padding:14px;font:18px system-ui;text-align:center;pointer-events:none';
      document.body.appendChild(banner);
    }
    banner.textContent = message;
  }, text);
  await page.waitForTimeout(1800);
  await page.screenshot({ path: `artifacts/spl-113-qa/${frame}.png` });
}

async function openHistory(page: Page) {
  await page.goto('/workspace/my-requests');
  const row = page.getByRole('row').filter({ hasText: 'SPL-113 Revised outcome' });
  await row.getByRole('button', { name: 'Change requests', exact: true }).click({ timeout: 30000 });
  await expect(page.getByRole('group', { name: 'Pending change request', exact: true })).toBeVisible({ timeout: 30000 });
}

// QA-SPL-113-200 | AC1-4 | BB
test('[QA-SPL-113-200] organiser sees outcomes, Closed history, current values and client isolation', async ({ page }) => {
  test.setTimeout(180000);
  const ids = JSON.parse(readFileSync(process.env.SPL113_UAT_IDS!, 'utf8'));
  await login(page, 'developer@example.test', true);
  await openHistory(page);
  await test.step('AC1 each item has its own saved outcome', async () => {
    const pending = page.getByRole('group', { name: 'Pending change request', exact: true });
    const description = pending.getByRole('listitem').filter({ has: page.getByText('Description', { exact: true }) });
    await expect(description).toContainText('Outcome: Declined');
    await expect(description).toContainText('Decline reason: Keep the original description.');
    await expect(pending.getByRole('listitem').filter({ has: page.getByText('Expected attendance', { exact: true }) })).toContainText('Outcome: Pending');
    await expect(pending.getByRole('listitem').filter({ has: page.getByText('Equipment requirement', { exact: true }) })).toContainText('Outcome: Accepted');
    await description.scrollIntoViewIfNeeded();
    await caption(page, 'AC1: every item has its own outcome; Declined includes the reason', 'ac1');
  });
  await test.step('AC2 Closed history remains available after reopening', async () => {
    await page.reload();
    await page.getByRole('row').filter({ hasText: 'SPL-113 Revised outcome' }).getByRole('button', { name: 'Change requests', exact: true }).click({ timeout: 30000 });
    const closed = page.getByRole('group', { name: `Closed change request ${ids.closed}`, exact: true });
    await expect(closed).toContainText('North entrance', { timeout: 30000 });
    await expect(closed).toContainText('Outcome: Accepted');
    await closed.scrollIntoViewIfNeeded();
    await caption(page, 'AC2: Closed history survives reload alongside the newer pending request', 'ac2');
  });
  await test.step('AC3 current event values show the accepted changes', async () => {
    await page.getByRole('link', { name: 'View current event details', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'SPL-113 Revised outcome', exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByText('Theatre', { exact: true })).toBeVisible();
    await expect(page.getByText('Stage, Projector', { exact: true })).toBeVisible();
    await expect(page.getByText('Step-free access', { exact: true })).toBeVisible();
    await page.getByText('Theatre', { exact: true }).scrollIntoViewIfNeeded();
    await caption(page, 'AC3: current event shows accepted layout, facilities and accessibility', 'ac3-fields');
    const equipment = page.getByRole('row').filter({ hasText: 'SPL-113 display' });
    await expect(equipment).toContainText('Technical notes: HDMI and power');
    await expect(equipment).toContainText('0/4');
    await equipment.scrollIntoViewIfNeeded();
    await caption(page, 'AC3: the responsible organiser sees accepted equipment quantity and technical notes', 'ac3-equipment');
  });
  await test.step('AC4 another organisation has no access', async () => {
    await page.getByRole('button', { name: 'Sign out', exact: true }).click();
    await login(page, ids.foreign_email);
    await page.goto('/workspace/my-requests');
    await expect(page.getByText('You have not submitted any event requests yet.', { exact: true })).toBeVisible({ timeout: 30000 });
    await expect(page.getByRole('row').filter({ hasText: 'SPL-113 Revised outcome' })).toHaveCount(0);
    await page.goto(`/workspace/organisation-events/${ids.event}`);
    await expect(page.getByRole('alert')).toBeVisible({ timeout: 30000 });
    await expect(page.getByRole('button', { name: 'Change requests', exact: true })).toHaveCount(0);
    await caption(page, 'AC4: an organiser from another client cannot open this event or its requests', 'ac4');
  });
});
