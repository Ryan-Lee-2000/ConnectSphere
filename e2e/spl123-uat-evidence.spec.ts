import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

test.skip(!process.env.SPL123_UAT_IDS, 'Requires isolated SPL-123 real-Auth fixtures.');

async function caption(page: Page, message: string, frame: string) {
  await page.evaluate(text => {
    let banner = document.getElementById('spl123-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'spl123-caption';
      banner.setAttribute('aria-hidden', 'true');
      banner.style.cssText = 'position:fixed;bottom:8px;left:8px;right:8px;z-index:99999;background:#163c42;color:white;padding:14px;font:18px system-ui;pointer-events:none';
      document.body.appendChild(banner);
    }
    banner.textContent = text;
  }, message);
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `artifacts/spl-123-qa/uat-run${process.env.SPL123_UAT_RUN ?? '1'}-frames/${frame}.png` });
}

async function login(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill('LocalDemo123!');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  const organiser = page.getByRole('button', { name: /^Event Organiser/ });
  if (email === 'developer@example.test') {
    await expect(organiser.or(page.getByRole('navigation', { name: 'Workspace' }))).toBeVisible();
    if (await organiser.isVisible()) await organiser.click();
  }
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

async function logout(page: Page) {
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByLabel('Email address')).toBeVisible();
}

async function inbox(page: Page) {
  await page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'Notifications', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Notifications', exact: true })).toBeVisible();
}

async function decisions(page: Page, id: number) {
  await page.goto(`/workspace/assigned-events/${id}`);
  await page.getByRole('button', { name: 'View change requests', exact: true }).click();
  await expect(page.getByRole('region', { name: /Decisions for change request/ })).toBeVisible();
}

const notices = (page: Page, name: string) => page.getByRole('listitem').filter({ hasText: name });

// QA-SPL-123-200 | AC1 AC2 AC3 AC4 AC5 | BB
test('[QA-SPL-123-200] organiser sees lifecycle and item notices; refused retries and access stay protected', async ({ page }) => {
  test.setTimeout(240_000);
  const ids = JSON.parse(readFileSync(process.env.SPL123_UAT_IDS!, 'utf8'));
  const lifecycle = ids.Lifecycle;
  const items = ids['Item Decisions'];
  const retry = ids.Retry;
  const assigned = ids.Reassigned;

  await test.step('AC1: confirm and reload the organiser notification', async () => {
    await login(page, 'event.coordinator@example.test');
    await page.goto(`/workspace/assigned-events/${lifecycle.id}`);
    const panel = page.getByRole('region', { name: 'Confirm this event' });
    await panel.scrollIntoViewIfNeeded();
    await expect(panel).toContainText('Ready to confirm');
    await panel.getByRole('button', { name: 'Confirm event', exact: true }).click();
    await page.getByRole('group', { name: 'Confirm the event', exact: true }).getByRole('button', { name: 'Confirm', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Event confirmed.' })).toBeVisible();
    await logout(page);
    await login(page, 'developer@example.test');
    await inbox(page);
    await expect(notices(page, lifecycle.name)).toHaveCount(1);
    await expect(notices(page, lifecycle.name)).toContainText(`${lifecycle.name} has been confirmed.`);
    await page.reload();
    await expect(notices(page, lifecycle.name)).toHaveCount(1);
    await caption(page, 'AC1: the organiser receives one confirmation notice, still present after reload', 'ac1');
    await notices(page, lifecycle.name).getByRole('link').click();
    await expect(page).toHaveURL(new RegExp(`/workspace/organisation-events/${lifecycle.id}$`));
    await expect(page.getByRole('heading', { name: lifecycle.name, exact: true })).toBeVisible();
    await logout(page);
  });

  await test.step('AC2: a significant change returns Confirmed to Planning and notifies the organiser', async () => {
    await login(page, 'event.coordinator@example.test');
    await page.goto(`/workspace/assigned-events/${lifecycle.id}`);
    await page.getByRole('button', { name: 'Edit event requirements', exact: true }).click();
    await page.getByLabel('Expected attendance', { exact: true }).fill('90');
    await page.getByRole('button', { name: 'Review changes', exact: true }).click();
    await expect(page.getByRole('region', { name: 'Review significant changes' })).toContainText(/Planning/);
    await page.getByRole('button', { name: 'Confirm and save changes', exact: true }).click();
    await expect(page.getByText('Event requirements saved. Affected arrangements are marked for review.')).toBeVisible();
    await logout(page);
    await login(page, 'developer@example.test');
    await inbox(page);
    await expect(notices(page, lifecycle.name)).toHaveCount(2);
    await expect(notices(page, lifecycle.name).filter({ hasText: 'has returned to Planning after a significant change and must be confirmed again.' })).toHaveCount(1);
    await caption(page, 'AC2: the organiser receives one return-to-Planning notice after the significant change', 'ac2');
    await logout(page);
  });

  await test.step('AC3: cancellation notice includes the recorded reason', async () => {
    await login(page, 'event.coordinator@example.test');
    await page.goto(`/workspace/assigned-events/${lifecycle.id}`);
    await page.getByRole('region', { name: 'Cancel this event' }).getByRole('button', { name: 'Cancel event', exact: true }).click();
    await page.getByLabel('Cancellation reason').fill('The organiser moved the celebration online.');
    await page.getByRole('button', { name: 'Confirm cancellation', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Event cancelled.' })).toBeVisible();
    await logout(page);
    await login(page, 'developer@example.test');
    await inbox(page);
    await expect(notices(page, lifecycle.name)).toHaveCount(3);
    await expect(notices(page, lifecycle.name).filter({ hasText: 'has been cancelled. Reason: The organiser moved the celebration online.' })).toHaveCount(1);
    await caption(page, 'AC3: the organiser receives the cancellation notice with its reason', 'ac3');
    await logout(page);
  });

  await test.step('AC4: each accepted or declined item sends its own outcome notice', async () => {
    await login(page, 'event.coordinator@example.test');
    await decisions(page, items.id);
    await page.getByRole('combobox', { name: 'Outcome for Description', exact: true }).selectOption('accepted');
    await page.getByRole('combobox', { name: 'Outcome for Expected attendance', exact: true }).selectOption('declined');
    await page.getByLabel('Decline reason for Expected attendance').fill('Keep attendance within the agreed capacity.');
    await page.getByRole('button', { name: 'Review decisions', exact: true }).click();
    await page.getByRole('button', { name: 'Confirm decisions', exact: true }).click();
    await expect(page.getByRole('group', { name: 'Closed change request', exact: true })).toBeVisible();
    await logout(page);
    await login(page, 'developer@example.test');
    await inbox(page);
    await expect(notices(page, items.name)).toHaveCount(2);
    await expect(notices(page, items.name).filter({ hasText: 'Description was accepted.' })).toHaveCount(1);
    await expect(notices(page, items.name).filter({ hasText: 'Expected attendance was declined. Reason: Keep attendance within the agreed capacity.' })).toHaveCount(1);
    await caption(page, 'AC4: two decided items produce two notices; the declined item includes its reason', 'ac4');
    await logout(page);
  });

  await test.step('AC5: a stale retry is refused visibly and adds no duplicate', async () => {
    await login(page, 'event.coordinator@example.test');
    await decisions(page, retry.id);
    await page.getByRole('combobox', { name: 'Outcome for Description', exact: true }).selectOption('accepted');
    await page.getByRole('button', { name: 'Review decisions', exact: true }).click();
    const otherTab = await page.context().newPage();
    await decisions(otherTab, retry.id);
    await otherTab.getByRole('combobox', { name: 'Outcome for Description', exact: true }).selectOption('accepted');
    await otherTab.getByRole('button', { name: 'Review decisions', exact: true }).click();
    await otherTab.getByRole('button', { name: 'Confirm decisions', exact: true }).click();
    await expect(otherTab.getByRole('group', { name: 'Closed change request', exact: true })).toBeVisible();
    await otherTab.close();
    await page.getByRole('button', { name: 'Confirm decisions', exact: true }).click();
    await expect(page.getByRole('alert')).toBeVisible();
    await page.getByRole('alert').scrollIntoViewIfNeeded();
    await caption(page, 'AC5: this stale retry is refused because another tab already decided the item', 'ac5-refused');
    await logout(page);
    await login(page, 'developer@example.test');
    await inbox(page);
    await expect(notices(page, retry.name)).toHaveCount(1);
    await page.reload();
    await expect(notices(page, retry.name)).toHaveCount(1);
    await caption(page, 'AC5: one successful action and its refused retry leave exactly one notice after reload', 'ac5-inbox');
    await logout(page);
  });

  await test.step('Access: reassigned event and another account inbox stay protected', async () => {
    await login(page, 'event.coordinator@example.test');
    await page.goto(`/workspace/assigned-events/${assigned.id}`);
    await expect(page.getByRole('alert')).toBeVisible();
    await expect(page.getByRole('button', { name: 'View change requests', exact: true })).toHaveCount(0);
    await caption(page, 'Access: the former coordinator cannot open this reassigned event', 'access-reassigned');
    await logout(page);
    await login(page, 'qa.spl123.other@example.test');
    await inbox(page);
    await expect(page.getByText('No notifications yet.', { exact: true })).toBeVisible();
    await expect(page.getByRole('listitem')).toHaveCount(0);
    await caption(page, 'Access: another organisation account has an empty inbox and cannot see these notices', 'access-inbox');
  });
});
