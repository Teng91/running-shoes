#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const root = path.resolve(__dirname, '..');
const candidates = process.platform === 'win32'
  ? [path.join(root, 'venv', 'Scripts', 'python.exe'), 'python']
  : [path.join(root, 'venv', 'bin', 'python'), 'python3', 'python'];
const python = candidates.find(candidate => !candidate.includes(path.sep) || fs.existsSync(candidate));

if (!python) {
  process.stderr.write('Claude Stop hook could not find Python. Run the repository setup task first.\n');
  process.exit(2);
}

const result = spawnSync(python, [path.join(root, 'scripts', 'claude_stop_hook.py')], {
  cwd: root,
  input: fs.readFileSync(0),
  encoding: 'utf8',
});

if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
if (result.error) {
  process.stderr.write(`Claude Stop hook failed to start: ${result.error.message}\n`);
  process.exit(2);
}
process.exit(result.status ?? 2);
