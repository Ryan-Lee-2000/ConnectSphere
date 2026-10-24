import { expect, test, type Page } from '@playwright/test';

const organiser = { email: 'developer@example.test', password: 'LocalDemo123!' };
const outsider = { email: 'qa.spl119.other-organiser@example.test', password: 'LocalDemo123!' };
const eventName = 'SPL-119 UAT Registration List';
const disabledName = 'SPL-119 UAT Registration Disabled';

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

async function signIn(page: Page, account: { email: string; password: string }) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(account.email);
  await page.getByLabel('Password').fill(account.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
  const role = page.getByRole('button', { name: /^Event Organiser/ });
  if (await role.count()) await role.click();
  await expect(page.getByRole('navigation', { name: 'Workspace' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Sign out' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome back' })).toBeVisible();
}

// QA-SPL-119-200 | AC1-AC5 | BB recorded UAT
test('QA-SPL-119-200: organiser registration-list walkthrough and cross-organisation refusal', async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, organiser);
  await page.getByRole('link', { name: 'Organisation events' }).click();
  await page.getByRole('link', { name: eventName }).click();
  await expect(page.getByRole('heading', { name: eventName })).toBeVisible();
  const eventUrl = page.url();

  await expect(page.getByLabel('2 of 5 places registered')).toBeVisible();
  await caption(page, 'AC1: the signed-in organiser opens a submitted event in their own organisation');

  const current = page.getByRole('table', { name: 'Currently registered attendees' });
  await expect(current).toContainText('Blake Ong');
  await expect(current).toContainText('blake@example.test');
  await expect(current).toContainText('+65 9000 1196');
  await expect(current).toContainText('Vegetarian meal');
  await expect(current).toContainText('Cheryl Tan');
  await expect(current).toContainText('None recorded');
  await current.scrollIntoViewIfNeeded();
  await caption(page, 'AC2: 2/5 and every attendee name, email, contact number and special requirement are visible');

  const withdrawn = page.getByRole('table', { name: 'Withdrawn attendee registrations' });
  await expect(withdrawn).toContainText('Blake Ong (earlier registration)');
  await expect(current).not.toContainText('earlier registration');
  await withdrawn.scrollIntoViewIfNeeded();
  await caption(page, 'AC3: withdrawn registrations appear in a separate labelled table and do not increase 2/5');

  await expect(page.getByRole('button', { name: /export|download/i })).toHaveCount(0);
  await expect(page.getByRole('link', { name: /export|download/i })).toHaveCount(0);
  await caption(page, 'AC5: no export or download control is offered; export remains outside this story');

  await page.getByRole('link', { name: 'Back to organisation events' }).click();
  await page.getByRole('link', { name: disabledName }).click();
  await expect(page.getByText('Registration is not enabled for this event.')).toBeVisible();
  await expect(page.getByRole('table', { name: /attendees/i })).toHaveCount(0);
  await caption(page, 'AC4: a registration-disabled event explains the state instead of showing an empty attendee list');

  await signOut(page);
  await signIn(page, outsider);
  await page.goto(eventUrl);
  await expect(page.getByRole('alert')).toContainText("We couldn't find that event in your client organisation.");
  await expect(page.getByText('Blake Ong')).toHaveCount(0);
  await caption(page, 'AC1 access refusal: an organiser from another organisation receives a generic refusal and no attendee data');
});
