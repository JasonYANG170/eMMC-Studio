import assert from 'node:assert/strict';
import {
  decodeRegister as d,
  hexNumber,
  productRevision,
  binaryFlag,
} from '../.test-build/emmcInfo.js';
assert.equal(hexNumber('0x12345678'), '305,419,896（原值 0x12345678）');
assert.match(hexNumber('0xffffffffffffffff'), /18,446,744,073,709,551,615/);
assert.equal(productRevision('0xa1'), '10.1（原值 0xa1）');
assert.match(d('BOOT_BUS_CONDITIONS', '0x00'), /1 位 SDR.*重置/);
assert.match(d('BOOT_BUS_CONDITIONS', '0x16'), /8 位.*DDR.*保留配置/);
assert.match(d('BOOT_CONFIG_PROT', '0x11'), /本次上电.*开启.*永久.*开启/);
assert.match(d('BOOT_WP_STATUS', '0x09'), /BOOT0：本次上电写保护；BOOT1：永久写保护/);
assert.match(d('BOOT_WP_STATUS', '0x03'), /保留状态/);
assert.match(d('BOOT_WP', '0x10'), /永久保护设置已禁用/);
assert.match(d('BOOT_WP', '0x89'), /上电写保护启用开启（BOOT0）/);
assert.match(d('BOOT_WP', '0x89'), /永久写保护启用关闭（BOOT1）/);
assert.match(d('USER_WP', '0x00'), /配置不代表各保护组的实际锁定状态/);
assert.match(d('WR_REL_SET', '0x1f'), /用户区：可靠写入保护开启.*GP4：可靠写入保护开启/);
assert.match(d('WR_REL_SET', '0x00'), /用户区：性能优先/);
assert.match(d('RST_N_FUNCTION', '0x01'), /已永久启用/);
assert.match(d('BKOPS_STATUS', '0x02'), /已影响性能/);
assert.match(d('CACHE_CTRL', '0x80'), /含未解析的保留位/);
assert.match(d('HS_TIMING', '0x03'), /HS400.*类型 B/);
assert.match(d('HS_TIMING', '0xf7'), /保留时序.*保留类型/);
assert.equal(d('BOOT_WP', ''), '尚未读取');
assert.match(d('BOOT_WP', '0x100'), /无法解码/);
assert.match(binaryFlag('2'), /保留值/);
console.log(
  'PASS: 22 register decoding assertions including reserved values, region bit masks and exact 64-bit numbers',
);
import { mmcCsd, ocrInfo, partitionType } from '../.test-build/emmcInfo.js';
const csd = (3n << 126n) | (4n << 122n) | (9n << 80n) | (9n << 22n) | (1n << 76n);
const fields = Object.fromEntries(mmcCsd(csd.toString(16).padStart(32, '0')));
assert.equal(fields['CSD 最大读取块'], '512 B');
assert.equal(fields['CSD 最大写入块'], '512 B');
assert.equal(fields['实现 DSR 驱动阶段寄存器'], '是');
assert.deepEqual(mmcCsd('invalid'), []);
assert.equal(mmcCsd('00000000000000000000000000000000').length, 1);
assert.match(ocrInfo('0x80000080'), /1.65–1.95 V.*不代表初始化状态/);
assert.match(ocrInfo('0x00040000'), /3.0–3.1 V.*不代表初始化状态/);
assert.match(partitionType('0x83'), /Linux/);
assert.match(partitionType('0xff'), /未知/);
assert.equal(partitionType('custom-guid'), 'custom-guid');
console.log('PASS: CSD bit extraction, OCR voltage windows and MBR labels (10 assertions)');
