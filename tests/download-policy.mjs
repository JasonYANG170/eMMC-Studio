import assert from 'node:assert/strict';
import { wantsDownload, readyDownloads } from '../.test-build/downloads.js';
assert.equal(wantsDownload({ op: 'range_export' }), true);
assert.equal(wantsDownload({ op: 'backup', storage: 'browser' }), true);
assert.equal(wantsDownload({ op: 'backup', storage: 'local' }), false);
assert.equal(wantsDownload({ op: 'hex_write' }), false);
const jobs = [
  { id: 'old', state: 'completed', result: { download: 'a'.repeat(32) } },
  { id: 'new', state: 'completed', result: { download: 'b'.repeat(32) } },
  { id: 'wait', state: 'running', result: { download: 'c'.repeat(32) } },
  { id: 'invalid', state: 'completed', result: { download: '../../bad' } },
];
const pending = new Set(['new', 'wait', 'invalid']);
assert.deepEqual(
  readyDownloads(jobs, pending).map((j) => j.id),
  ['new'],
);
pending.delete('new');
assert.equal(readyDownloads(jobs, pending).length, 0);
console.log(
  'PASS: automatic downloads only for requested, completed jobs; no replay or invalid token',
);
