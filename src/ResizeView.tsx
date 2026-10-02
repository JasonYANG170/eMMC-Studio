import { t, locale } from './i18n.js';
import { partitionColors, resizeLimit } from './layout';
export function ResizeView({
  disk,
  region,
  value,
  onChange,
}: {
  disk: {
    size: number;
    table: any;
    regions: { path: string; name: string; region: string; start?: number; size: number }[];
  };
  region: { path: string; name: string; start?: number; size: number };
  value: number;
  onChange: (n: number) => void;
}) {
  const max = resizeLimit(disk, region),
    start = (region.start || 0) * 512,
    parts = disk.regions.filter((r) => r.region === 'partition');
  return (
    <div className="resize-view">
      <strong>{t('拖动右侧边界调整容量')}</strong>
      <p>
        {t('起点固定 · 当前')}
        {(region.size / 1048576).toFixed(0)}
        {t('MiB · 最大')}
        {(max / 1048576).toFixed(0)} MiB
      </p>
      <div className="resize-disk" aria-label={t('调整后的磁盘布局')}>
        {parts.map((r, i) => (
          <div
            key={r.path}
            title={r.name}
            style={{
              left: (((r.start || 0) * 512) / disk.size) * 100 + '%',
              width: ((r.path === region.path ? value : r.size) / disk.size) * 100 + '%',
              background: partitionColors[i % partitionColors.length],
            }}
          >
            {r.name}
          </div>
        ))}
      </div>
      <div className="resize-track">
        <div className="resize-fill" style={{ width: Math.min(100, (value / max) * 100) + '%' }} />
        <input
          aria-label={t('拖动分区容量')}
          type="range"
          min={1048576}
          max={max}
          step={1048576}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </div>
      <div className="resize-caption">
        <span>1 MiB</span>
        <b>{(value / 1048576).toLocaleString()} MiB</b>
        <span>{(max / 1048576).toLocaleString()} MiB</span>
      </div>
      <small>
        {t('可调整区间：')}
        {start.toLocaleString()}–{(start + max).toLocaleString()}{' '}
        {t('字节；右侧相邻分区是扩容边界。拖动只改变预览，确认提交后才执行。')}
      </small>
    </div>
  );
}
