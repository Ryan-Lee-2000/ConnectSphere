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

const testResult = await run(process.execPath, [playwrightCli, 'test', ...process.argv.slice(2)]);
const cleanupResult = await run('uv', ['run', '--frozen', 'python', 'scripts/cleanup_e2e_venues.py']);
process.exitCode = testResult || cleanupResult;
