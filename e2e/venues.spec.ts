import { expect, test, type Page } from '@playwright/test';
import { existsSync } from 'node:fs';
import { loadEnvFile } from 'node:process';

if (existsSync('frontend/.env.local')) loadEnvFile('frontend/.env.local');

const password = process.env.VITE_LOCAL_DEMO_PASSWORD ?? 'LocalDemo123!';
const venueStaffEmail = process.env.VITE_LOCAL_DEMO_VENUE_STAFF_EMAIL ?? 'venue.staff@example.test';
const coordinatorEmail =
  process.env.VITE_LOCAL_DEMO_EVENT_COORDINATOR_EMAIL ?? 'event.coordinator@example.test';

async function signIn(page: Page, email: string) {
  await page.goto('/');
  await page.getByLabel('Email address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).toHaveURL(/\/workspace$/);
}

test.describe('venue catalogue journeys', () => {
  test('Venue Staff creates a venue and retrieves it after refresh', async ({ page }) => {
    const venueName = `E2E Venue ${Date.now()}`;
    await signIn(page, venueStaffEmail);
    await expect(page.getByRole('button', { name: 'Add venue' })).toBeVisible();

    await page.getByRole('button', { name: 'Add venue' }).click();
    await page.getByLabel('Venue name').fill(venueName);
    await page.getByLabel('Location').fill('E2E Test Location');
    await page.getByLabel('Description').fill('A fully populated browser-test venue profile.');
    await page.getByLabel(/^Facilities/).fill('Projector, PA system');
    await page.getByLabel(/^Accessibility features/).fill('Step-free access, Accessible restroom');
    await page.getByLabel('AM · 7am–12pm').check();
    await page.getByLabel('Setup slots before event').fill('1');
    await page.getByLabel('Turnaround slots after event').fill('1');
    await page.getByRole('button', { name: 'Save venue' }).click();
    await expect(page.locator('.notice')).toContainText('Venue and its room layouts created.');
    await expect(page.getByRole('button', { name: new RegExp(venueName) })).toBeVisible();

    await page.reload();
    await expect(page.getByRole('button', { name: new RegExp(venueName) })).toBeVisible();
    await page.getByRole('button', { name: new RegExp(venueName) }).click();
    await expect(page.getByRole('heading', { name: venueName })).toBeVisible();
    await expect(page.getByRole('article').getByText('E2E Test Location')).toBeVisible();
    await expect(page.getByRole('article').getByText('Projector')).toBeVisible();
    await expect(page.getByRole('article').getByText('Step-free access')).toBeVisible();
  });

  test('Venue Staff edits a venue profile and layout', async ({ page }) => {
    const initialName = `E2E Editable ${Date.now()}`;
    const updatedName = `${initialName} Updated`;
    await signIn(page, venueStaffEmail);
    await page.getByRole('button', { name: 'Add venue' }).click();
    await page.getByLabel('Venue name').fill(initialName);
    await page.getByLabel('PM · 1pm–6pm').check();
    await page.getByRole('button', { name: 'Save venue' }).click();
    await page.getByRole('button', { name: new RegExp(initialName) }).click();
    await expect(page.getByRole('heading', { name: initialName })).toBeVisible();
    await page.getByRole('button', { name: 'Edit venue' }).click();
    await expect(page.locator('form[aria-label="Edit venue"]')).toBeVisible();

    await page.getByLabel('Venue name').fill(updatedName);
    await page.getByRole('button', { name: 'Add layout' }).click();
    await page.getByLabel('Stated capacity 1').fill('42');
    await page.getByRole('button', { name: 'Save venue' }).click();
    await expect(page.locator('.notice')).toContainText('Venue profile and room layouts updated.');
    await expect(page.getByRole('heading', { name: updatedName })).toBeVisible();
    await expect(page.getByRole('article').getByRole('cell', { name: '42' })).toBeVisible();
  });

  test('Event Coordinator can browse venue details but cannot manage the catalogue', async ({ page }) => {
    await signIn(page, coordinatorEmail);
    const firstVenue = page.locator('.venue-card').first();
    await expect(firstVenue).toBeVisible();
    await firstVenue.click();
    await expect(page.getByRole('article')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Add venue' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Edit venue' })).toHaveCount(0);
  });
});
