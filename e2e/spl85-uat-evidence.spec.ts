import { expect, test, type Page } from '@playwright/test';

// SPL-85 (CS-E07-S3) recorded UAT, TC-SPL-85-26. Real local Auth and the seeded fixture
// "E2E SPL-85 Confirmation Showcase": an Approved booking and an Essential microphone line reserved
// 3 of 4. The journey shows the blocker, Technical Support clears it, the coordinator confirms in
// two steps, and the organiser sees the confirmed arrangements, all at a 390px phone width.

const password = 'LocalDemo123!';
const coordinator = 'event.coordinator@example.test';
const technicalSupport = 'technical.support@example.test';
const organiser = 'developer@example.test';
const eventName = 'E2E SPL-85 Confirmation Showcase';
const microphone = 'E2E SPL-85 Stage Microphone';
const venue = 'E2E SPL-85 Harbour Hall';

// Keep each visible state on screen long enough to read in the captured video.
const evidencePause = (page: Page) => page.waitForTimeout(1_500);

test.use({ video: 'on', viewport: { width: 390, height: 844 } });

async function signIn(page: Page, email: string, role?: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  if (role) await page.getByRole('button', { name: new RegExp(`^${role}`) }).click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

async function openAssignedEvent(page: Page) {
  await page.getByRole('link', { name: 'My assigned events' }).click();
  await page.getByRole('link', { name: eventName }).click();
  await expect(page.getByRole('heading', { name: eventName })).toBeVisible();
  return page.getByRole('region', { name: 'Confirm this event' });
}

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test('TC-SPL-85-26 confirms an event once its essential arrangements are complete', async ({ page }) => {
  test.setTimeout(180_000);

  await test.step('AC3: the coordinator sees the essential shortfall and cannot confirm', async () => {
    await signIn(page, coordinator);
    const panel = await openAssignedEvent(page);
    await panel.scrollIntoViewIfNeeded();
    await expect(panel.getByText('Not ready to confirm')).toBeVisible();
    await expect(panel.getByText(`Reserve 1 more unit(s) of ${microphone}.`)).toBeVisible();
    await expect(panel.getByRole('button', { name: 'Confirm event' })).toBeDisabled();
    await expectNoHorizontalOverflow(page);
    await evidencePause(page);
    await signOut(page);
  });

  await test.step('Technical Support reserves the last essential unit', async () => {
    await signIn(page, technicalSupport);
    await page.getByRole('link', { name: 'Equipment availability' }).click();
    const card = page.locator('.equipment-availability__card').filter({
      has: page.getByRole('heading', { name: microphone }),
      hasText: eventName,
    });
    await card.scrollIntoViewIfNeeded();
    await expect(card.getByText('3 of 4 units held')).toBeVisible();
    await card.getByLabel('Units to reserve').fill('1');
    await evidencePause(page);
    await card.getByRole('button', { name: 'Reserve units' }).click();
    await expect(card.getByText('4 of 4 units held')).toBeVisible();
    await evidencePause(page);
    await signOut(page);
  });

  await test.step('AC1/AC5: the assigned coordinator confirms in two steps', async () => {
    await signIn(page, coordinator);
    const panel = await openAssignedEvent(page);
    await panel.scrollIntoViewIfNeeded();
    await expect(panel.getByText('Ready to confirm')).toBeVisible();
    await evidencePause(page);
    await panel.getByRole('button', { name: 'Confirm event' }).click();
    await page.getByRole('button', { name: 'Keep planning' }).click();
    await expect(panel.getByRole('button', { name: 'Confirm event' })).toBeEnabled();
    await panel.getByRole('button', { name: 'Confirm event' }).click();
    const step = page.getByRole('group', { name: 'Confirm the event' });
    await expect(step).toContainText('Confirm this event?');
    await evidencePause(page);
    await step.getByRole('button', { name: 'Confirm', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Event confirmed.' })).toBeVisible();
    const confirmedRow = page.getByRole('rowheader', { name: 'Confirmed by' }).locator('xpath=..');
    await confirmedRow.scrollIntoViewIfNeeded();
    await expect(confirmedRow).toContainText('Casey Lim');
    await expect(page.getByRole('region', { name: 'Confirm this event' })).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
    await evidencePause(page);
    await signOut(page);
  });

  await test.step('AC5/Q98: the organiser sees Confirmed, who confirmed it and the arrangements', async () => {
    await signIn(page, organiser, 'Event Organiser');
    await page.getByRole('link', { name: 'My requests' }).click();
    const row = page.getByRole('row').filter({ hasText: eventName });
    await row.scrollIntoViewIfNeeded();
    await expect(row.getByText('Confirmed', { exact: true })).toBeVisible();
    await expect(row.getByText(/^Confirmed by Casey Lim on /)).toBeVisible();
    await expect(row.getByRole('list', { name: 'Confirmed venues' })).toContainText(venue);
    await expect(row.getByRole('list', { name: 'Confirmed equipment' })).toContainText(`${microphone}: 4 of 4 reserved (essential)`);
    await evidencePause(page);
  });
});
