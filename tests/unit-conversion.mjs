// Compile first: npx tsc src/units.ts --target ES2022 --module ESNext --skipLibCheck --outDir .deploy/unit-tests
import assert from 'node:assert/strict';
import { toBytes, fromBytes, partitionSectors, readWindow } from '../.test-build/units.js';
assert.equal(partitionSectors(toBytes('100', 'MiB')), 204800);
assert.equal(partitionSectors(toBytes('1', 'GiB')), 2097152);
assert.throws(() => partitionSectors(1048577));
assert.throws(() => partitionSectors(NaN));
let viewed = 0;
for (let offset = 0; offset < 4194304; offset += 65536) {
  const page = readWindow(0, 4194304, offset);
  viewed += page.length;
  assert.equal(page.next, offset + 65536 < 4194304 ? offset + 65536 : null);
}
assert.equal(viewed, 4194304);
assert.equal(readWindow(512, 65537, 66048).length, 1);
assert.throws(() => readWindow(0, 4194304, 4194304));
assert.equal(toBytes('4', 'MiB'), 4194304);
assert.equal(toBytes('64', 'KiB'), 65536);
assert.equal(toBytes('0x3FFE00', 'B'), 4193792);
assert.equal(toBytes('0.5', 'KiB'), 512);
assert.equal(toBytes('8192', '扇区'), 4194304);
for (const n of [0, 1, 512, 4194304, 7818182656, Number.MAX_SAFE_INTEGER])
  for (const u of ['B', 'KiB', 'MiB', 'GiB', '扇区']) assert.equal(toBytes(fromBytes(n, u), u), n);
for (const s of ['', '-1', '1e3', '9007199254740992']) assert.ok(Number.isNaN(toBytes(s, 'B')));
assert.ok(Number.isNaN(toBytes('0.1', 'B')));
console.log('PASS: exact byte/unit conversion, round trips, bounds and invalid inputs');
