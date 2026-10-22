import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir:'./e2e', workers:1, retries:0,
  // SPL-110's recorded walkthrough uses an isolated local fixture that ordinary E2E setup does not create.
  testIgnore: ['**/spl110-uat-evidence.spec.ts'],
  use:{baseURL:'http://127.0.0.1:5173',trace:'retain-on-failure', reducedMotion:'reduce'},
  reporter:[['list'],['html',{open:'never'}]],
});
