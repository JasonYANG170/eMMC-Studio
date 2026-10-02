export const byteUnits = { B: 1, KiB: 1024, MiB: 1048576, GiB: 1073741824, 扇区: 512 } as const;
export type ByteUnit = keyof typeof byteUnits;

export function partitionSectors(bytes: number): number {
  if (!Number.isSafeInteger(bytes) || bytes < 1048576 || bytes % 1048576 !== 0)
    throw new Error('分区起点和大小需按 1 MiB 对齐');
  return bytes / 512;
}

export function readWindow(start: number, length: number, offset = start) {
  if (
    ![start, length, offset].every(Number.isSafeInteger) ||
    start < 0 ||
    length < 1 ||
    !Number.isSafeInteger(start + length) ||
    offset < start ||
    offset >= start + length
  )
    throw new Error('读取范围无效');
  return {
    offset,
    length: Math.min(65536, start + length - offset),
    previous: offset > start ? Math.max(start, offset - 65536) : null,
    next: offset + 65536 < start + length ? offset + 65536 : null,
  };
}

// Decimal conversion is exact: reject fractional bytes and unsafe integers.
export function toBytes(raw: string, unit: ByteUnit): number {
  const text = raw.trim();
  if (unit === 'B' && /^0x[\da-f]+$/i.test(text)) {
    const n = BigInt(text);
    return n <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(n) : NaN;
  }
  const match = /^(\d+)(?:\.(\d{0,30}))?$/.exec(text);
  if (!match) return NaN;
  const fraction = match[2] || '';
  const divisor = 10n ** BigInt(fraction.length);
  const numerator = BigInt(match[1] + fraction) * BigInt(byteUnits[unit]);
  if (numerator % divisor !== 0n) return NaN;
  const bytes = numerator / divisor;
  return bytes <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(bytes) : NaN;
}

export function fromBytes(bytes: number, unit: ByteUnit): string {
  if (!Number.isSafeInteger(bytes) || bytes < 0) return '';
  const factor = BigInt(byteUnits[unit]);
  const integer = BigInt(bytes) / factor;
  let remainder = BigInt(bytes) % factor;
  let fraction = '';
  while (remainder) {
    remainder *= 10n;
    fraction += String(remainder / factor);
    remainder %= factor;
  }
  return String(integer) + (fraction ? '.' + fraction : '');
}
