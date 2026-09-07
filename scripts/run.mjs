// npm provides its own CLI path, avoiding Windows .cmd shell wrappers.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const command = process.argv[2] ?? 'help';
if (Number(process.versions.node.split('.')[0]) !== 24) {
  console.error(`Node 24 is required; found ${process.version}. Install Node 24 from https://nodejs.org/en/download and reopen your terminal.`);
  process.exit(1);
}
if (!process.env.npm_execpath) {
  console.error('Run through npm: npm run setup, npm start, or npm run doctor.');
  process.exit(1);
}
const child = spawn('uv', ['run', '--no-project', '--python', '3.13', 'scripts/dev.py', command], {
  cwd: fileURLToPath(new URL('../', import.meta.url)),
  stdio: 'inherit',
  env: { ...process.env, CONNECTSPHERE_NODE: process.execPath, CONNECTSPHERE_NPM: process.env.npm_execpath },
});
child.on('error', (error) => {
  console.error(error.code === 'ENOENT'
    ? 'uv is missing. Install it from https://docs.astral.sh/uv/getting-started/installation/ and reopen your terminal.'
    : `Unable to start uv: ${error.message}`);
  process.exitCode = 1;
});
// The console delivers Ctrl+C to Python too; allow it to clean up its servers.
process.on('SIGINT', () => {});
child.on('exit', (code) => { process.exitCode = code ?? 1; });
