import { t, locale } from './i18n.js';
export function lifetime(raw?: string) {
  const n = raw && /^0x[\da-f]+$/i.test(raw) ? Number(raw) : NaN;
  if (n >= 1 && n <= 10) return t('预计已消耗 {0}–{1}%', [(n - 1) * 10, n * 10]);
  if (n === 11) return t('已超出预计寿命');
  if (n === 0) return t('设备未提供寿命估计');
  return raw ? t('保留值 / 无法解码') : t('设备未提供');
}
export function preEol(raw?: string) {
  return (
    (
      {
        1: t('正常 · 备用块已消耗 0–<80%'),
        2: t('预警 · 备用块已消耗 80–<90%'),
        3: t('紧急 · 备用块已消耗 ≥90%'),
        0: t('设备未提供预警状态'),
      } as Record<number, string>
    )[Number(raw)] || (raw ? t('保留值 / 无法解码') : t('设备未提供'))
  );
}
export function manufacturer(raw?: string) {
  if (!raw) return t('设备未提供');
  const names: Record<number, string> = {
    0x11: t('Toshiba / KIOXIA（东芝 / 铠侠）'),
    0x13: t('Micron（美光）'),
    0x15: t('Samsung（三星）'),
    0x45: t('SanDisk（闪迪）'),
    0x70: t('Kingston（金士顿）'),
    0x90: t('SK hynix（海力士）'),
  };
  return names[Number(raw)] || t('未知厂商（保留原始 ID）');
}
export function supportedModes(cardType: string, strobe: string) {
  const n = Number(cardType),
    es = Number(strobe) & 1;
  return [
    { name: 'HS26', mask: 1, clock: 26, rate: 26, voltage: t('额定 I/O 电压'), transfer: 'SDR' },
    { name: 'HS52', mask: 2, clock: 52, rate: 52, voltage: t('额定 I/O 电压'), transfer: 'SDR' },
    { name: 'DDR52', mask: 4, clock: 52, rate: 104, voltage: '1.8 V / 3 V', transfer: 'DDR' },
    { name: 'DDR52', mask: 8, clock: 52, rate: 104, voltage: '1.2 V', transfer: 'DDR' },
    { name: 'HS200', mask: 16, clock: 200, rate: 200, voltage: '1.8 V', transfer: 'SDR' },
    { name: 'HS200', mask: 32, clock: 200, rate: 200, voltage: '1.2 V', transfer: 'SDR' },
    { name: 'HS400', mask: 64, clock: 200, rate: 400, voltage: '1.8 V', transfer: 'DDR' },
    { name: 'HS400', mask: 128, clock: 200, rate: 400, voltage: '1.2 V', transfer: 'DDR' },
  ]
    .filter((m) => n & m.mask)
    .map((m) => ({ ...m, name: m.name === 'HS400' && es ? 'HS400 / HS400 ES' : m.name }));
}
export function currentBusRate(ios: Record<string, string>) {
  const hz = parseInt(ios['actual clock'] || ios.clock || ''),
    bits = Number(/\((\d+) bits?\)/.exec(ios['bus width'] || '')?.[1]),
    timing = ios['timing spec'] || '';
  if (!hz || !bits || !timing) return null;
  return (((hz * bits) / 8) * (/HS400|DDR/i.test(timing) ? 2 : 1)) / 1e6;
}
export function extValue(text: string, key: string) {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = new RegExp(
    `\\[${escaped}(?::\\s*(0x[\\da-f]+))?\\](?::\\s*(0x[\\da-f]+))?`,
    'i',
  ).exec(text);
  return match?.[1] || match?.[2] || '';
}
export function bootConfig(raw: string) {
  if (!raw) return t('尚未读取');
  const n = Number(raw),
    boot = (n >> 3) & 7,
    access = n & 7;
  return t('{0}；启动应答{1}；当前访问{2}', [
    (
      {
        0: t('未启用 eMMC 硬件启动'),
        1: t('从 BOOT0 启动'),
        2: t('从 BOOT1 启动'),
        7: t('从用户区启动'),
      } as Record<number, string>
    )[boot] || t('保留启动配置'),
    n & 64 ? t('开启') : t('关闭'),
    [t('用户区'), 'BOOT0', 'BOOT1', 'RPMB', 'GP1', 'GP2', 'GP3', 'GP4'][access],
  ]);
}
// Register layouts: Linux include/linux/mmc/mmc.h and barebox commands/mmc_extcsd.c.
// Opaque IDs/firmware are retained; reserved bits are never interpreted as normal states.
function byteValue(raw?: string) {
  if (!raw || !/^(?:0x[\da-f]+|\d+)$/i.test(raw)) return null;
  const n = Number(raw);
  return Number.isInteger(n) && n >= 0 && n <= 255 ? n : null;
}
export function hexNumber(raw?: string) {
  if (!raw) return t('设备未提供');
  if (!/^0x[\da-f]+$/i.test(raw)) return raw;
  return t('{0}（原值 {1}）', [BigInt(raw).toLocaleString(), raw]);
}
export function productRevision(raw?: string) {
  const n = byteValue(raw);
  return n === null ? raw || t('设备未提供') : t('{0}.{1}（原值 {2}）', [n >> 4, n & 15, raw]);
}
export function binaryFlag(raw?: string, on = t('开启'), off = t('关闭')) {
  const n = byteValue(raw);
  return n === null
    ? t('设备未提供')
    : t('{0}（原值 {1}）', [n === 1 ? on : n === 0 ? off : t('保留值 / 无法解码'), raw]);
}
export function decodeRegister(key: string, raw: string) {
  const n = byteValue(raw);
  if (n === null) return raw ? t('无法解码（原值 {0}）', [raw]) : t('尚未读取');
  let text = '',
    mask = 255;
  const flag = (bit: number) => (n & bit ? t('开启') : t('关闭'));
  switch (key) {
    case 'BOOT_BUS_CONDITIONS':
      mask = 0x1f;
      text = t('启动总线 {0}；{1}；启动后{2}', [
        [t('1 位 SDR / 4 位 DDR'), t('4 位'), t('8 位'), t('保留宽度')][n & 3],
        [t('SDR 兼容时序'), t('SDR 高速时序'), 'DDR', t('保留时序')][(n >> 3) & 3],
        n & 4 ? t('保留配置') : t('重置为 1 位 SDR 兼容时序'),
      ]);
      break;
    case 'BOOT_CONFIG_PROT':
      mask = 0x11;
      text = t('本次上电启动配置保护{0}；永久启动配置保护{1}', [flag(1), flag(16)]);
      break;
    case 'BOOT_WP_STATUS':
      mask = 0x0f;
      text = [0, 1]
        .map(
          (i) =>
            `BOOT${i}：${[t('无硬件写保护'), t('本次上电写保护'), t('永久写保护'), t('保留状态')][(n >> (i * 2)) & 3]}`,
        )
        .join('；');
      break;
    case 'BOOT_WP':
      mask = 0xdf;
      text = t(
        '上电写保护启用{0}（{1}）；永久写保护启用{2}（{3}）；上电保护设置{4}；永久保护设置{5}',
        [
          flag(1),
          n & 128 ? (n & 2 ? 'BOOT1' : 'BOOT0') : t('两个 BOOT 区'),
          flag(4),
          n & 128 ? (n & 8 ? 'BOOT1' : 'BOOT0') : t('两个 BOOT 区'),
          n & 64 ? t('已禁用') : t('允许'),
          n & 16 ? t('已禁用') : t('允许'),
        ],
      );
      break;
    case 'USER_WP':
      mask = 0xdd;
      text = t(
        'CMD28 上电保护{0}；CMD28 永久保护{1}；上电保护设置{2}；永久保护设置{3}；CSD 永久保护设置{4}；密码保护功能{5}（配置不代表各保护组的实际锁定状态）',
        [
          flag(1),
          flag(4),
          n & 8 ? t('已禁用') : t('允许'),
          n & 16 ? t('已禁用') : t('允许'),
          n & 64 ? t('已禁用') : t('允许'),
          n & 128 ? t('已禁用') : t('允许'),
        ],
      );
      break;
    case 'WR_REL_SET':
      mask = 0x1f;
      text = [t('用户区'), 'GP1', 'GP2', 'GP3', 'GP4']
        .map((name, i) => `${name}：${n & (1 << i) ? t('可靠写入保护开启') : t('性能优先')}`)
        .join('；');
      break;
    case 'RST_N_FUNCTION':
      mask = 3;
      text = [
        t('复位引脚暂未启用'),
        t('复位引脚已永久启用'),
        t('复位引脚已永久禁用'),
        t('保留复位配置'),
      ][n & 3];
      break;
    case 'BKOPS_STATUS':
      mask = 3;
      text = [
        t('无需后台整理'),
        t('需要后台整理（非紧急）'),
        t('需要后台整理（已影响性能）'),
        t('急需后台整理'),
      ][n & 3];
      break;
    case 'BKOPS_EN':
      mask = 3;
      text = t('手动后台整理{0}；自动后台整理{1}', [flag(1), flag(2)]);
      break;
    case 'CACHE_CTRL':
      mask = 1;
      text = t('缓存{0}', [flag(1)]);
      break;
    case 'HS_TIMING':
      mask = 0xff;
      text = t('{0}；驱动类型 {1}', [
        [t('向后兼容时序'), t('高速时序'), 'HS200', 'HS400'][n & 15] || t('保留时序'),
        ['B', 'A', 'C', 'D'][n >> 4] || t('保留类型'),
      ]);
      break;
    case 'STROBE_SUPPORT':
      mask = 1;
      text = n & 1 ? t('支持 HS400 增强选通') : t('不支持 HS400 增强选通');
      break;
    default:
      return hexNumber(raw);
  }
  return t('{0}{1}（原值 {2}）', [text, n & ~mask ? t('；含未解析的保留位') : '', raw]);
}
export function mmcCsd(raw?: string): [string, string][] {
  if (!raw || !/^(?:0x)?[\da-f]{32}$/i.test(raw)) return [];
  const value = BigInt(raw.startsWith('0x') ? raw : '0x' + raw),
    bits = (start: number, width: number) =>
      Number((value >> BigInt(start)) & ((1n << BigInt(width)) - 1n));
  const structure = bits(126, 2);
  if (!structure) return [[t('CSD 结构'), t('不支持的结构（保留原值）')]];
  return [
    [t('CSD 结构'), String(structure)],
    [t('CSD MMC 规格版本字段'), String(bits(122, 4)) + t('（当前 eMMC 版本以 EXT_CSD 为准）')],
    [t('CSD 最大读取块'), 2 ** bits(80, 4) + ' B'],
    [t('CSD 最大写入块'), 2 ** bits(22, 4) + ' B'],
    [t('支持部分块读取'), bits(79, 1) ? t('是') : t('否')],
    [t('支持部分块写入'), bits(21, 1) ? t('是') : t('否')],
    [t('实现 DSR 驱动阶段寄存器'), bits(76, 1) ? t('是') : t('否')],
    [t('CSD 命令类位图'), '0x' + bits(84, 12).toString(16)],
  ];
}
export function ocrInfo(raw?: string) {
  if (!raw || !/^(?:0x)?[\da-f]{1,8}$/i.test(raw)) return raw || t('设备未提供');
  const n = Number.parseInt(raw.replace(/^0x/i, ''), 16),
    volts: string[] = [];
  if (n & 128) volts.push('1.65–1.95 V');
  for (let i = 8; i <= 23; i++)
    if (n & (1 << i))
      volts.push(`${(2 + (i - 8) / 10).toFixed(1)}–${(2.1 + (i - 8) / 10).toFixed(1)} V`);
  return t('供电范围：{0}（原值 {1}；sysfs 电压掩码，不代表初始化状态或信号电压）', [
    volts.join('、') || t('未报告支持的电压'),
    raw,
  ]);
}
export function partitionType(raw?: string) {
  if (!raw) return '—';
  const names: Record<number, string> = {
    1: 'FAT12',
    4: 'FAT16 <32M',
    5: t('扩展分区'),
    6: 'FAT16',
    7: 'HPFS / NTFS / exFAT',
    11: 'FAT32',
    12: 'FAT32（LBA）',
    14: 'FAT16（LBA）',
    15: t('扩展分区（LBA）'),
    0x82: 'Linux swap / Solaris',
    0x83: 'Linux',
    0x8e: 'Linux LVM',
    0xee: t('GPT 保护分区'),
    0xef: t('EFI 系统分区'),
  };
  if (/^0x[\da-f]{1,2}$/i.test(raw))
    return t('{0}（原值 {1}）', [names[Number(raw)] || t('未知 MBR 类型'), raw]);
  return raw;
}
