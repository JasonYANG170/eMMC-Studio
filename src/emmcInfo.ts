export function lifetime(raw?: string) {
  const n = raw && /^0x[\da-f]+$/i.test(raw) ? Number(raw) : NaN;
  if (n >= 1 && n <= 10) return `预计已消耗 ${(n - 1) * 10}–${n * 10}%`;
  if (n === 11) return '已超出预计寿命';
  if (n === 0) return '设备未提供寿命估计';
  return raw ? '保留值 / 无法解码' : '设备未提供';
}
export function preEol(raw?: string) {
  return (
    (
      {
        1: '正常 · 备用块已消耗 0–<80%',
        2: '预警 · 备用块已消耗 80–<90%',
        3: '紧急 · 备用块已消耗 ≥90%',
        0: '设备未提供预警状态',
      } as Record<number, string>
    )[Number(raw)] || (raw ? '保留值 / 无法解码' : '设备未提供')
  );
}
export function manufacturer(raw?: string) {
  if (!raw) return '设备未提供';
  const names: Record<number, string> = {
    0x11: 'Toshiba / KIOXIA（东芝 / 铠侠）',
    0x13: 'Micron（美光）',
    0x15: 'Samsung（三星）',
    0x45: 'SanDisk（闪迪）',
    0x70: 'Kingston（金士顿）',
    0x90: 'SK hynix（海力士）',
  };
  return names[Number(raw)] || '未知厂商（保留原始 ID）';
}
export function supportedModes(cardType: string, strobe: string) {
  const n = Number(cardType),
    es = Number(strobe) & 1;
  return [
    { name: 'HS26', mask: 1, clock: 26, rate: 26, voltage: '额定 I/O 电压', transfer: 'SDR' },
    { name: 'HS52', mask: 2, clock: 52, rate: 52, voltage: '额定 I/O 电压', transfer: 'SDR' },
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
  if (!raw) return '尚未读取';
  const n = Number(raw),
    boot = (n >> 3) & 7,
    access = n & 7;
  return `${({ 0: '未启用 eMMC 硬件启动', 1: '从 BOOT0 启动', 2: '从 BOOT1 启动', 7: '从用户区启动' } as Record<number, string>)[boot] || '保留启动配置'}；启动应答${n & 64 ? '开启' : '关闭'}；当前访问${['用户区', 'BOOT0', 'BOOT1', 'RPMB', 'GP1', 'GP2', 'GP3', 'GP4'][access]}`;
}
// Register layouts: Linux include/linux/mmc/mmc.h and barebox commands/mmc_extcsd.c.
// Opaque IDs/firmware are retained; reserved bits are never interpreted as normal states.
function byteValue(raw?: string) {
  if (!raw || !/^(?:0x[\da-f]+|\d+)$/i.test(raw)) return null;
  const n = Number(raw);
  return Number.isInteger(n) && n >= 0 && n <= 255 ? n : null;
}
export function hexNumber(raw?: string) {
  if (!raw) return '设备未提供';
  if (!/^0x[\da-f]+$/i.test(raw)) return raw;
  return `${BigInt(raw).toLocaleString()}（原值 ${raw}）`;
}
export function productRevision(raw?: string) {
  const n = byteValue(raw);
  return n === null ? raw || '设备未提供' : `${n >> 4}.${n & 15}（原值 ${raw}）`;
}
export function binaryFlag(raw?: string, on = '开启', off = '关闭') {
  const n = byteValue(raw);
  return n === null
    ? '设备未提供'
    : `${n === 1 ? on : n === 0 ? off : '保留值 / 无法解码'}（原值 ${raw}）`;
}
export function decodeRegister(key: string, raw: string) {
  const n = byteValue(raw);
  if (n === null) return raw ? `无法解码（原值 ${raw}）` : '尚未读取';
  let text = '',
    mask = 255;
  const flag = (bit: number) => (n & bit ? '开启' : '关闭');
  switch (key) {
    case 'BOOT_BUS_CONDITIONS':
      mask = 0x1f;
      text = `启动总线 ${['1 位 SDR / 4 位 DDR', '4 位', '8 位', '保留宽度'][n & 3]}；${['SDR 兼容时序', 'SDR 高速时序', 'DDR', '保留时序'][(n >> 3) & 3]}；启动后${n & 4 ? '保留配置' : '重置为 1 位 SDR 兼容时序'}`;
      break;
    case 'BOOT_CONFIG_PROT':
      mask = 0x11;
      text = `本次上电启动配置保护${flag(1)}；永久启动配置保护${flag(16)}`;
      break;
    case 'BOOT_WP_STATUS':
      mask = 0x0f;
      text = [0, 1]
        .map(
          (i) =>
            `BOOT${i}：${['无硬件写保护', '本次上电写保护', '永久写保护', '保留状态'][(n >> (i * 2)) & 3]}`,
        )
        .join('；');
      break;
    case 'BOOT_WP':
      mask = 0xdf;
      text = `上电写保护启用${flag(1)}（${n & 128 ? (n & 2 ? 'BOOT1' : 'BOOT0') : '两个 BOOT 区'}）；永久写保护启用${flag(4)}（${n & 128 ? (n & 8 ? 'BOOT1' : 'BOOT0') : '两个 BOOT 区'}）；上电保护设置${n & 64 ? '已禁用' : '允许'}；永久保护设置${n & 16 ? '已禁用' : '允许'}`;
      break;
    case 'USER_WP':
      mask = 0xdd;
      text = `CMD28 上电保护${flag(1)}；CMD28 永久保护${flag(4)}；上电保护设置${n & 8 ? '已禁用' : '允许'}；永久保护设置${n & 16 ? '已禁用' : '允许'}；CSD 永久保护设置${n & 64 ? '已禁用' : '允许'}；密码保护功能${n & 128 ? '已禁用' : '允许'}（配置不代表各保护组的实际锁定状态）`;
      break;
    case 'WR_REL_SET':
      mask = 0x1f;
      text = ['用户区', 'GP1', 'GP2', 'GP3', 'GP4']
        .map((name, i) => `${name}：${n & (1 << i) ? '可靠写入保护开启' : '性能优先'}`)
        .join('；');
      break;
    case 'RST_N_FUNCTION':
      mask = 3;
      text = ['复位引脚暂未启用', '复位引脚已永久启用', '复位引脚已永久禁用', '保留复位配置'][
        n & 3
      ];
      break;
    case 'BKOPS_STATUS':
      mask = 3;
      text = [
        '无需后台整理',
        '需要后台整理（非紧急）',
        '需要后台整理（已影响性能）',
        '急需后台整理',
      ][n & 3];
      break;
    case 'BKOPS_EN':
      mask = 3;
      text = `手动后台整理${flag(1)}；自动后台整理${flag(2)}`;
      break;
    case 'CACHE_CTRL':
      mask = 1;
      text = `缓存${flag(1)}`;
      break;
    case 'HS_TIMING':
      mask = 0xff;
      text = `${['向后兼容时序', '高速时序', 'HS200', 'HS400'][n & 15] || '保留时序'}；驱动类型 ${['B', 'A', 'C', 'D'][n >> 4] || '保留类型'}`;
      break;
    case 'STROBE_SUPPORT':
      mask = 1;
      text = n & 1 ? '支持 HS400 增强选通' : '不支持 HS400 增强选通';
      break;
    default:
      return hexNumber(raw);
  }
  return `${text}${n & ~mask ? '；含未解析的保留位' : ''}（原值 ${raw}）`;
}
export function mmcCsd(raw?: string): [string, string][] {
  if (!raw || !/^(?:0x)?[\da-f]{32}$/i.test(raw)) return [];
  const value = BigInt(raw.startsWith('0x') ? raw : '0x' + raw),
    bits = (start: number, width: number) =>
      Number((value >> BigInt(start)) & ((1n << BigInt(width)) - 1n));
  const structure = bits(126, 2);
  if (!structure) return [['CSD 结构', '不支持的结构（保留原值）']];
  return [
    ['CSD 结构', String(structure)],
    ['CSD MMC 规格版本字段', String(bits(122, 4)) + '（当前 eMMC 版本以 EXT_CSD 为准）'],
    ['CSD 最大读取块', 2 ** bits(80, 4) + ' B'],
    ['CSD 最大写入块', 2 ** bits(22, 4) + ' B'],
    ['支持部分块读取', bits(79, 1) ? '是' : '否'],
    ['支持部分块写入', bits(21, 1) ? '是' : '否'],
    ['实现 DSR 驱动阶段寄存器', bits(76, 1) ? '是' : '否'],
    ['CSD 命令类位图', '0x' + bits(84, 12).toString(16)],
  ];
}
export function ocrInfo(raw?: string) {
  if (!raw || !/^(?:0x)?[\da-f]{1,8}$/i.test(raw)) return raw || '设备未提供';
  const n = Number.parseInt(raw.replace(/^0x/i, ''), 16),
    volts: string[] = [];
  if (n & 128) volts.push('1.65–1.95 V');
  for (let i = 8; i <= 23; i++)
    if (n & (1 << i))
      volts.push(`${(2 + (i - 8) / 10).toFixed(1)}–${(2.1 + (i - 8) / 10).toFixed(1)} V`);
  return `供电范围：${volts.join('、') || '未报告支持的电压'}（原值 ${raw}；sysfs 电压掩码，不代表初始化状态或信号电压）`;
}
export function partitionType(raw?: string) {
  if (!raw) return '—';
  const names: Record<number, string> = {
    1: 'FAT12',
    4: 'FAT16 <32M',
    5: '扩展分区',
    6: 'FAT16',
    7: 'HPFS / NTFS / exFAT',
    11: 'FAT32',
    12: 'FAT32（LBA）',
    14: 'FAT16（LBA）',
    15: '扩展分区（LBA）',
    0x82: 'Linux swap / Solaris',
    0x83: 'Linux',
    0x8e: 'Linux LVM',
    0xee: 'GPT 保护分区',
    0xef: 'EFI 系统分区',
  };
  if (/^0x[\da-f]{1,2}$/i.test(raw))
    return `${names[Number(raw)] || '未知 MBR 类型'}（原值 ${raw}）`;
  return raw;
}
