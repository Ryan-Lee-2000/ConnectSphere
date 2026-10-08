import { expect, test, type Page } from '@playwright/test';

const password = 'LocalDemo123!';
const technicalSupport = 'technical.support@example.test';
const organiser = 'developer@example.test';

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

const evidencePause = (page: Page) => page.waitForTimeout(1_500);

// SPL-94 recorded UAT: happy, negative, boundary and authorisation paths.
test('TC-SPL-94-UAT-01 records complete equipment catalogue acceptance evidence', async ({ page }) => {
  const itemName = `E2E UAT Presentation Adapter ${Date.now()}`;

  await signIn(page, technicalSupport);
  await page.getByRole('link', { name: 'Equipment catalogue' }).click();
  await expect(page.getByRole('heading', { name: 'Equipment catalogue' })).toBeVisible();
  await evidencePause(page);

  // AC1 happy path: create then edit a valid, unique pooled equipment type.
  await page.getByLabel('Equipment type name').fill(itemName);
  await page.getByLabel('Total units in stock').fill('2');
  await page.getByLabel('Description').fill('Portable adapter for hybrid presentation demonstrations.');
  await page.getByLabel('Storage location').fill('Technical Store');
  await page.getByRole('button', { name: 'Add equipment type' }).click();
  await expect(page.getByText('Equipment type added to the catalogue.')).toBeVisible();
  await evidencePause(page);
  await page.getByRole('button', { name: `Edit ${itemName}` }).click();
  await page.getByLabel('Total units in stock').fill('3');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByText('Equipment type updated.')).toBeVisible();
  await evidencePause(page);

  // AC1 unhappy path: names remain unique regardless of letter case.
  await page.getByLabel('Equipment type name').fill(itemName.toUpperCase());
  await page.getByLabel('Total units in stock').fill('1');
  await page.getByRole('button', { name: 'Add equipment type' }).click();
  await expect(page.getByRole('alert')).toContainText('already exists');
  await evidencePause(page);

  // AC1 boundary path: negative stock is stopped in the interface and never saved.
  await page.getByLabel('Equipment type name').fill(`E2E UAT Boundary ${Date.now()}`);
  await page.getByLabel('Total units in stock').fill('-1');
  await page.getByRole('button', { name: 'Add equipment type' }).click();
  await expect(page.getByRole('alert')).toContainText('whole number of zero or more');
  await evidencePause(page);
  await signOut(page);

  // AC3 unhappy path: an organiser cannot reach Technical Support management controls.
  await signIn(page, organiser, 'Event Organiser');
  await expect(page.getByRole('link', { name: 'Equipment catalogue' })).toHaveCount(0);
  await page.goto('/workspace/equipment-catalogue');
  await expect(page.getByRole('heading', { name: 'Equipment catalogue' })).toHaveCount(0);
  await evidencePause(page);

  // AC2 happy path: an organiser can choose a saved catalogue entry.
  await page.getByRole('link', { name: 'Event requests' }).click();
  await page.getByRole('button', { name: 'Add equipment' }).click();
  await page.getByLabel('Equipment type 1').selectOption({ label: `${itemName} — Technical Store` });
  await page.getByLabel('Equipment quantity 1').fill('2');
  await page.getByLabel('Equipment notes 1').fill('Use for the keynote presentation.');
  await expect(page.getByLabel('Equipment type 1')).toHaveValue(itemName);
  await evidencePause(page);

  // AC2 alternate path: a non-catalogue item remains explicitly labelled for review.
  await page.getByRole('button', { name: 'Can’t find the equipment you need?' }).click();
  await page.getByLabel('Requested equipment 1').fill('Portable document camera');
  await expect(page.getByText('This will be reviewed by Technical Support before it can be arranged.')).toBeVisible();
  await evidencePause(page);
});
