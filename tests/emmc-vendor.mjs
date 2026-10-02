import assert from 'node:assert/strict';
import { manufacturer, supportedModes, currentBusRate, preEol } from '../.test-build/emmcInfo.js';
assert.match(manufacturer('0x000090'), /SK hynix/);
assert.match(manufacturer('0xff'), /未知/);
assert.match(preEol('0x01'), /0–<80%/);
assert.match(preEol('0x02'), /80–<90%/);
assert.match(preEol('0x03'), /≥90%/);
const modes = supportedModes('0x57', '0x01');
assert.equal(modes.length, 5);
assert.equal(modes.at(-1).name, 'HS400 / HS400 ES');
assert.equal(modes.at(-1).rate, 400);
assert.ok(modes.every((m) => m.voltage !== '1.2 V'));
assert.equal(
  currentBusRate({
    'actual clock': '200000000 Hz',
    'bus width': '3 (8 bits)',
    'timing spec': '10 (mmc HS400 enhanced strobe)',
  }),
  400,
);
assert.equal(
  currentBusRate({
    clock: '52000000 Hz',
    'bus width': '2 (4 bits)',
    'timing spec': '1 (mmc high-speed)',
  }),
  26,
);
assert.equal(currentBusRate({}), null);
assert.equal(supportedModes('', '').length, 0);
console.log('PASS: vendor ID, pre-EOL intervals, CARD_TYPE flags, ES and negotiated bandwidth');
