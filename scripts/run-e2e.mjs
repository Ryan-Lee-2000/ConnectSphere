import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const playwrightCli = require.resolve('@playwright/test/cli');

function run(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: 'inherit' });
    child.on('error', reject);
    child.on('exit', code => resolve(code ?? 1));
  });
}

// Rebuild only the named local SPL-97 evidence fixtures before browser journeys. This keeps the
// review-required walkthrough repeatable without relying on a developer's prior manual database edits.
const preparationResult = await run('uv', ['run', '--frozen', 'python', 'scripts/prepare_e2e_equipment.py']);
const testResult = preparationResult === 0
  ? await run(process.execPath, [playwrightCli, 'test', ...process.argv.slice(2)])
  : preparationResult;
const cleanupResult = await run('uv', ['run', '--frozen', 'python', 'scripts/cleanup_e2e_venues.py']);
process.exitCode = testResult || cleanupResult;
