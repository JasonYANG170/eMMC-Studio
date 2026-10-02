import assert from 'node:assert/strict';
import { lifetime, preEol, extValue, bootConfig } from '../.test-build/emmcInfo.js';
assert.equal(lifetime('0x01'), '预计已消耗 0–10%');
assert.equal(lifetime('0x0a'), '预计已消耗 90–100%');
assert.equal(lifetime('0x0b'), '已超出预计寿命');
assert.equal(lifetime('0x00'), '设备未提供寿命估计');
assert.equal(lifetime('0xff'), '保留值 / 无法解码');
assert.equal(lifetime(), '设备未提供');
assert.match(preEol('0x01'), /^正常/);
assert.match(preEol('0x02'), /^预警/);
assert.match(preEol('0x03'), /^紧急/);
assert.match(preEol('0xff'), /^保留值/);
assert.equal(
  extValue('Boot configuration bytes [PARTITION_CONFIG: 0x00]', 'PARTITION_CONFIG'),
  '0x00',
);
assert.equal(
  extValue('Boot write protection status registers [BOOT_WP_STATUS]: 0x00', 'BOOT_WP_STATUS'),
  '0x00',
);
assert.match(bootConfig('0x00'), /未启用/);
assert.match(bootConfig('0x48'), /BOOT0/);
assert.match(bootConfig('0x10'), /BOOT1/);
console.log(
  'PASS: eMMC lifetime ranges, missing/reserved states, pre-EOL, register formats and boot config',
);
