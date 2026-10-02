export const partitionColors = [
  '#3478db',
  '#14a38b',
  '#a568d1',
  '#e09628',
  '#d05d80',
  '#598ba3',
  '#8f9b35',
  '#bd7141',
];
export function resizeLimit(
  disk: { size: number; table: any; regions: { path: string; region: string; start?: number }[] },
  region: { path: string; start?: number },
) {
  const start = (region.start || 0) * 512;
  const next = disk.regions
    .filter(
      (r) => r.region === 'partition' && r.path !== region.path && (r.start || 0) * 512 > start,
    )
    .map((r) => (r.start || 0) * 512);
  const end = Math.min(disk.size - (disk.table?.label === 'gpt' ? 34 * 512 : 0), ...next);
  return Math.max(0, Math.floor((end - start) / 1048576) * 1048576);
}
export function hexPageOffset(start: number, length: number, page: number) {
  if (!Number.isSafeInteger(page) || page < 1 || page > Math.ceil(length / 256))
    throw new Error('页码超出选定范围');
  return start + (page - 1) * 256;
}
