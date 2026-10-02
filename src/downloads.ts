export type DownloadJob = {
  id: string;
  state: string;
  result?: { download?: string };
  op?: string;
};
export function wantsDownload(args: { op: string; storage?: string }) {
  return (
    ['range_export', 'file_export', 'backup_export'].includes(args.op) ||
    (args.op === 'backup' && args.storage === 'browser')
  );
}
// Only jobs explicitly requested by this browser may initiate a download.
export function readyDownloads<T extends DownloadJob>(jobs: T[], pending: Set<string>) {
  return jobs.filter(
    (j) =>
      pending.has(j.id) &&
      j.state === 'completed' &&
      /^[a-f0-9]{32}$/.test(j.result?.download || ''),
  );
}
