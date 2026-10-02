import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';

const compiler = spawnSync(
  process.execPath,
  [
    'node_modules/typescript/bin/tsc',
    'src/i18n.ts',
    'src/units.ts',
    'src/layout.ts',
    'src/downloads.ts',
    'src/emmcInfo.ts',
    '--target',
    'ES2022',
    '--module',
    'ESNext',
    '--skipLibCheck',
    '--outDir',
    '.test-build',
  ],
  { stdio: 'inherit' },
);
if (compiler.status !== 0) process.exit(compiler.status || 1);
for (const file of readdirSync('tests')
  .filter((name) => name.endsWith('.mjs'))
  .sort()) {
  const result = spawnSync(process.execPath, ['tests/' + file], { stdio: 'inherit' });
  if (result.status !== 0) process.exit(result.status || 1);
}
