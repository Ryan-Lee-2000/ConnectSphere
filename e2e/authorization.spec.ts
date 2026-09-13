import { expect, test, type Page } from '@playwright/test';

const validAccount = {
  email: 'developer@example.test',
  password: 'LocalDemo123!',
};

async function signIn(page: Page) {
  await page.getByLabel('Email address').fill(validAccount.email);
  await page.getByLabel('Password').fill(validAccount.password);
  await page.getByRole('button', { name: 'Sign in' }).click();
}

test('TC-CS-E01-S2-01 current-account roles come from trusted application data', async ({
  page,
}) => {
  await page.goto('/');
  const verificationRequest = page.waitForRequest(
    request =>
      request.url().endsWith('/api/session') &&
      request.headers().authorization?.startsWith('Bearer ') === true,
  );

  await signIn(page);
  const authorization = (await verificationRequest).headers().authorization;
  expect(authorization).toBeTruthy();

  const response = await page.request.get(
    '/api/account/roles?account_id=00000000-0000-0000-0000-000000000000&role=venue_staff',
    {
      headers: {
        Authorization: authorization!,
        'X-Account-Role': 'venue_staff',
      },
    },
  );

  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ roles: ['attendee', 'event_organiser'] });
});
