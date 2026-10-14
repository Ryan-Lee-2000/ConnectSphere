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

// Rebuild the named local equipment fixtures before browser journeys, including the assigned
// Planning event and stock scenarios required by SPL-90/95/97. No manual data preparation is needed.
const preparationResult = await run('uv', ['run', '--frozen', 'python', 'scripts/prepare_e2e_equipment.py']);
const testResult = preparationResult === 0
  ? await run(process.execPath, [playwrightCli, 'test', ...process.argv.slice(2)])
  : preparationResult;
const cleanupResult = await run('uv', ['run', '--frozen', 'python', 'scripts/cleanup_e2e_venues.py']);
process.exitCode = testResult || cleanupResult;
