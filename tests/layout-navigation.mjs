import assert from 'node:assert/strict';
import { hexPageOffset, resizeLimit } from '../.test-build/layout.js';
assert.equal(hexPageOffset(0, 4194304, 16384), 4194048);
assert.equal(hexPageOffset(37, 65537, 257), 65573);
assert.equal(hexPageOffset(0, 7818182656, Math.ceil(7818182656 / 256)), 7818182400);
assert.throws(() => hexPageOffset(0, 4194304, 16385));
assert.throws(() => hexPageOffset(0, 4194304, 0));
assert.throws(() => hexPageOffset(0, 4194304, 1.5));
const disk = {
  size: 1024 * 1048576,
  table: { label: 'gpt' },
  regions: [
    { path: 'p1', region: 'partition', start: 2048 },
    { path: 'p2', region: 'partition', start: 206848 },
  ],
};
assert.equal(resizeLimit(disk, disk.regions[0]), 100 * 1048576);
assert.equal(resizeLimit(disk, disk.regions[1]), 922 * 1048576);
console.log(
  'PASS: full-region pagination, final partial page, bounds, adjacent partition and GPT end limits',
);
