import { expect, test, type Page } from '@playwright/test';

// SPL-86 (CS-E07-S5) recorded UAT, TC-SPL-86-44. Real local Auth and the seeded fixture
// "E2E SPL-86 Riverside Gala": a Planning event holding an Approved hall, a Requested studio and a
// lighting line with 2 of 4 units reserved. The journey shows the work that is pending before, the
// Lead refused, the coordinator cancelling in two steps with a reason, every commitment freed, and
// the cancellation shown to the coordinator, organiser and Lead, all at a 390px phone width.

const password = 'LocalDemo123!';
const coordinator = 'event.coordinator@example.test';
const venueStaff = 'venue.staff@example.test';
const technicalSupport = 'technical.support@example.test';
const organiser = 'developer@example.test';
const lead = 'operations.manager@example.test';
const eventName = 'E2E SPL-86 Riverside Gala';
const hall = 'E2E SPL-86 Riverside Hall';
const studio = 'E2E SPL-86 Riverside Studio';
const lighting = 'E2E SPL-86 Stage Lighting Kit';
const reason = 'The headline sponsor withdrew and the client called the gala off.';

test.use({ video: 'on', viewport: { width: 390, height: 844 } });

// Keep each visible state on screen long enough to read in the captured video.
const evidencePause = (page: Page) => page.waitForTimeout(1_800);

async function caption(page: Page, text: string) {
  await page.evaluate(message => {
    let banner = document.getElementById('uat-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'uat-caption';
      banner.setAttribute('aria-hidden', 'true');
      Object.assign(banner.style, {
        position: 'fixed', left: '8px', right: '8px', bottom: '8px', zIndex: '2147483647', padding: '10px 12px',
        borderRadius: '8px', background: 'rgba(16, 32, 56, 0.92)', color: '#fff', font: '600 14px/1.35 system-ui',
        pointerEvents: 'none',
      });
      document.body.appendChild(banner);
    }
    banner.textContent = message;
  }, text);
  await evidencePause(page);
}

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

const lightingCard = (page: Page) => page.locator('.equipment-availability__card').filter({
  has: page.getByRole('heading', { name: lighting }),
  hasText: eventName,
});

const arrangement = (page: Page, venue: string) =>
  page.getByRole('list', { name: 'Venue bookings' }).getByRole('article', { name: venue });

async function expectNoHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test('TC-SPL-86-44 cancels an event, frees its venues and equipment and keeps its records', async ({ page }) => {
  test.setTimeout(300_000);
  let eventPath = '';

  await test.step('Before: the studio request waits for Venue Staff (AC7 baseline)', async () => {
    await signIn(page, venueStaff);
    await page.getByRole('link', { name: 'Booking requests' }).click();
    const row = page.getByRole('row').filter({ hasText: eventName });
    await expect(row).toHaveCount(1);
    await expect(row).toContainText(studio);
    await row.scrollIntoViewIfNeeded();
    await caption(page, 'Before: the gala\'s studio request is waiting in the Venue Staff queue');
    await signOut(page);
  });

  await test.step('Before: 2 of 4 lighting units are held for the gala (AC3/AC7 baseline)', async () => {
    await signIn(page, technicalSupport);
    await page.getByRole('link', { name: 'Equipment availability' }).click();
    const card = lightingCard(page);
    await card.scrollIntoViewIfNeeded();
    await expect(card.getByText('2 of 4 units held')).toBeVisible();
    await caption(page, 'Before: Technical Support has 2 of 4 lighting units held for the gala');
    await signOut(page);
  });

  await test.step('AC2: the Event Coordinator Lead cannot cancel the event (Q132)', async () => {
    await signIn(page, lead);
    await expect(page.getByRole('link', { name: 'My assigned events' })).toHaveCount(0);
    await page.getByRole('link', { name: 'Coordinator assignment' }).click();
    const row = page.getByRole('row').filter({ hasText: eventName });
    await row.scrollIntoViewIfNeeded();
    await expect(row).toContainText('In planning');
    await expect(page.getByRole('button', { name: 'Cancel event' })).toHaveCount(0);
    await caption(page, 'AC2 (refused): the Lead supervises the gala but has no Cancel event action');
    await signOut(page);
  });

  await test.step('AC1/AC2: the assigned coordinator cancels in two steps with a reason', async () => {
    await signIn(page, coordinator);
    await page.getByRole('link', { name: 'My assigned events' }).click();
    await page.getByRole('link', { name: eventName }).click();
    await expect(page.getByRole('heading', { name: eventName })).toBeVisible();
    eventPath = new URL(page.url()).pathname;
    await expect(arrangement(page, hall).getByText('Status: Approved')).toBeVisible();
    await expect(arrangement(page, studio).getByText('Status: Requested')).toBeVisible();
    const panel = page.getByRole('region', { name: 'Cancel this event' });
    await panel.scrollIntoViewIfNeeded();
    await caption(page, 'AC1: the gala is in Planning with an approved hall and a requested studio');
    await panel.getByRole('button', { name: 'Cancel event' }).click();
    const form = page.getByRole('form', { name: 'Cancel the event' });
    await form.getByRole('button', { name: 'Keep event' }).click();
    await expect(form).toHaveCount(0);
    await caption(page, 'AC1: "Keep event" backs out and nothing changes');
    await panel.getByRole('button', { name: 'Cancel event' }).click();
    await form.getByLabel('Cancellation reason').fill('   ');
    await form.getByRole('button', { name: 'Confirm cancellation' }).click();
    const refusal = form.getByRole('alert');
    await expect(refusal).toHaveText('Give a reason for cancelling this event.');
    await expect(refusal).toBeInViewport();
    await caption(page, 'AC2 (refused): a blank reason is not accepted');
    await form.getByLabel('Cancellation reason').fill(reason);
    await caption(page, 'AC1: give the reason, then confirm the cancellation');
    await form.getByRole('button', { name: 'Confirm cancellation' }).click();
    await expect(page.getByRole('status').filter({ hasText: 'Event cancelled. Its venues and equipment are free for other events.' })).toBeVisible();
    await evidencePause(page);
  });

  await test.step('AC3/AC6: both bookings are cancelled with the reason; who, when and why are kept', async () => {
    await page.goto(eventPath);
    await expect(page.getByRole('region', { name: 'Cancel this event' })).toHaveCount(0);
    const cancelledBy = page.getByRole('rowheader', { name: 'Cancelled by' }).locator('xpath=..');
    await expect(cancelledBy).toContainText('Casey Lim');
    await expect(page.getByRole('rowheader', { name: 'Cancellation reason' }).locator('xpath=..')).toContainText(reason);
    await cancelledBy.scrollIntoViewIfNeeded();
    await caption(page, 'AC6: the event shows Cancelled, who cancelled it, when and why');
    await expect(arrangement(page, hall).getByText('Status: Cancelled')).toBeVisible();
    await expect(arrangement(page, studio).getByText('Status: Cancelled')).toBeVisible();
    await expect(page.getByRole('list', { name: `History of ${hall} booking` })).toContainText(`Event cancelled: ${reason}`);
    await arrangement(page, hall).scrollIntoViewIfNeeded();
    await caption(page, 'AC3: the approved hall and the requested studio are both Cancelled, with the reason in their history');
    await expectNoHorizontalOverflow(page);
    await signOut(page);
  });

  await test.step('AC7: the studio request has left the Venue Staff queue', async () => {
    await signIn(page, venueStaff);
    await page.getByRole('link', { name: 'Booking requests' }).click();
    await expect(page.getByRole('heading', { name: 'Booking requests' }).first()).toBeVisible();
    await expect(page.getByRole('row').filter({ hasText: eventName })).toHaveCount(0);
    await caption(page, 'AC7: the cancelled gala no longer appears in the Venue Staff queue');
    await signOut(page);
  });

  await test.step('AC3/AC7: the lighting units are released and the line is no longer actionable', async () => {
    await signIn(page, technicalSupport);
    await page.getByRole('link', { name: 'Equipment availability' }).click();
    await expect(page.getByRole('heading', { name: 'Equipment availability' }).first()).toBeVisible();
    await expect(lightingCard(page)).toHaveCount(0);
    await caption(page, 'AC3/AC7: the 2 held units are released and the gala\'s line has left the list');
    await signOut(page);
  });

  await test.step('AC6: the organiser sees Cancelled with who, when and the reason', async () => {
    await signIn(page, organiser, 'Event Organiser');
    await page.getByRole('link', { name: 'My requests' }).click();
    const row = page.getByRole('row').filter({ hasText: eventName });
    await row.scrollIntoViewIfNeeded();
    await expect(row.getByText('Cancelled', { exact: true })).toBeVisible();
    await expect(row.getByText(/^Cancelled by Casey Lim on /)).toBeVisible();
    await expect(row.getByText(`Reason: ${reason}`)).toBeVisible();
    await caption(page, 'AC6: the organiser\'s request shows Cancelled, by whom, when and why');
    await signOut(page);
  });

  await test.step('AC6: the Lead\'s supervision view shows the cancellation', async () => {
    await signIn(page, lead);
    await page.getByRole('link', { name: 'Coordinator assignment' }).click();
    const row = page.getByRole('row').filter({ hasText: eventName });
    await row.scrollIntoViewIfNeeded();
    await expect(row).toContainText(`Cancelled by Casey Lim: ${reason}`);
    await caption(page, 'AC6: the Lead sees who cancelled the gala and why; access is unchanged');
    await expectNoHorizontalOverflow(page);
  });
});
