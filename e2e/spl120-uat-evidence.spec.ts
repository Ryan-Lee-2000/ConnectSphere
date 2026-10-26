import { expect, test, type Page } from '@playwright/test';

const coordinator = { email: 'event.coordinator@example.test', password: 'LocalDemo123!' };
const eventName = 'SPL-120 UAT Registration List';
const disabledName = 'SPL-120 UAT Registration Disabled';
const protectedName = 'SPL-120 UAT Other Coordinator Event';

async function caption(page: Page, text: string, pause = 2600) {
  await page.evaluate(message => {
    let banner = document.getElementById('qa-caption');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'qa-caption';
      banner.setAttribute('role', 'presentation');
      banner.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;pointer-events:none;padding:14px 18px;'
        + 'background:#1e2a3a;color:#fff;font:600 18px/1.4 system-ui,sans-serif;text-align:center;';
      document.body.appendChild(banner);
    }
    banner.textContent = message;
  }, text);
  await page.waitForTimeout(pause);
}

async function signIn(page: Page) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(coordinator.email);
  await page.getByLabel('Password').fill(coordinator.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

// QA-SPL-120-200 | AC1-AC3 | BB recorded coordinator walkthrough and assignment refusal
test('QA-SPL-120-200: coordinator opens assigned-event registrations and another assignment is refused', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page);
  await page.getByRole('link', { name: 'My assigned events' }).click();
  await expect(page.getByRole('link', { name: eventName })).toBeVisible();
  await expect(page.getByText(protectedName)).toHaveCount(0);
  await caption(page, 'AC1: My assigned events includes the current coordinator\'s event and excludes another coordinator\'s event');

  await page.getByRole('link', { name: eventName }).click();
  await expect(page.getByRole('heading', { name: eventName })).toBeVisible();
  const registrationHeading = page.getByRole('heading', { name: 'Registered attendees' });
  await expect(registrationHeading).toBeVisible();
  await registrationHeading.scrollIntoViewIfNeeded();
  await caption(page, 'AC3: the read-only registration list is accessible directly from the assigned event page');

  await expect(page.getByLabel('2 of 5 places registered')).toBeVisible();
  const current = page.getByRole('table', { name: 'Currently registered attendees' });
  await expect(current).toContainText('Blake Ong');
  await expect(current).toContainText('blake@example.test');
  await expect(current).toContainText('+65 9000 1206');
  await expect(current).toContainText('Vegetarian meal');
  await expect(current).toContainText('Cheryl Tan');
  await expect(current).toContainText('None recorded');
  const withdrawn = page.getByRole('table', { name: 'Withdrawn attendee registrations' });
  await expect(withdrawn).toContainText('Blake Ong (earlier registration)');
  await withdrawn.scrollIntoViewIfNeeded();
  await caption(page, 'AC2: the coordinator sees the same 2/5 count, attendee fields and separate withdrawn list as CS-E19-S6');

  await page.getByRole('link', { name: 'Back to my assigned events' }).click();
  await page.getByRole('link', { name: disabledName }).click();
  const disabledExplanation = page.getByText('Registration is not enabled for this event.');
  await expect(disabledExplanation).toBeVisible();
  await disabledExplanation.scrollIntoViewIfNeeded();
  await caption(page, 'AC2 boundary: a registration-disabled event shows the shared explanatory state rather than an empty list');

  await page.goto('/workspace/assigned-events/12000003');
  await expect(page.getByRole('alert')).toContainText('This assigned event is unavailable.');
  await expect(page.getByRole('heading', { name: 'Registered attendees' })).toHaveCount(0);
  await caption(page, 'AC1 negative: a non-assigned event reference receives a generic refusal and exposes no attendee data');
});
