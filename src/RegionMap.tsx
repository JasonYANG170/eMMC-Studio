import { t, locale } from './i18n.js';
import { partitionColors } from './layout';
type Region = {
  path: string;
  name: string;
  region: string;
  size: number;
  start?: number;
  fstype?: string;
};
type Disk = { size: number; regions: Region[] };
const size = (n: number) =>
  n >= 1073741824 ? (n / 1073741824).toFixed(2) + ' GiB' : (n / 1048576).toFixed(2) + ' MiB';
export function RegionMap({
  disk,
  selected,
  onSelect,
}: {
  disk: Disk;
  selected?: string;
  onSelect?: (path: string) => void;
}) {
  const partitions = disk.regions.filter((r) => r.region === 'partition'),
    boots = disk.regions.filter((r) => r.region.startsWith('boot'));
  const item = (r: Region, style?: React.CSSProperties) =>
    onSelect ? (
      <button
        key={r.path}
        className={'region-segment ' + (selected === r.path ? 'selected' : '')}
        style={style}
        onClick={() => onSelect(r.path)}
        title={`${r.path} · ${size(r.size)}`}
      >
        <b>{r.region === 'boot0' ? 'BOOT0' : r.region === 'boot1' ? 'BOOT1' : r.name}</b>
        <small>
          {size(r.size)}
          {r.fstype ? ' · ' + r.fstype : ''}
        </small>
      </button>
    ) : (
      <div
        key={r.path}
        className="region-segment"
        style={style}
        title={`${r.path} · ${size(r.size)}`}
      >
        <b>{r.region === 'boot0' ? 'BOOT0' : r.region === 'boot1' ? 'BOOT1' : r.name}</b>
        <small>{size(r.size)}</small>
      </div>
    );
  return (
    <div className="graphical-regions">
      <div className="region-rail-label">
        {t('用户区 ·')}
        {size(disk.size)}
        {onSelect && (
          <button
            className={'text-button ' + (selected === disk.regions[0]?.path ? 'active' : '')}
            onClick={() => onSelect(disk.regions[0].path)}
          >
            {t('选择整个用户区')}
          </button>
        )}
      </div>
      <div className="user-region-rail">
        {partitions.length ? (
          partitions.map((r) =>
            item(r, {
              left: (((r.start || 0) * 512) / disk.size) * 100 + '%',
              width: (r.size / disk.size) * 100 + '%',
              background: partitionColors[partitions.indexOf(r) % partitionColors.length],
              color: '#fff',
              borderColor: 'transparent',
            }),
          )
        ) : (
          <div className="unallocated">
            {t('未分区 ·')}
            {size(disk.size)}
          </div>
        )}
      </div>
      <div className="region-key">
        {partitions.map((r) => (
          <span key={r.path}>
            <i
              className="partition-swatch"
              style={{
                background: partitionColors[partitions.indexOf(r) % partitionColors.length],
              }}
            />
            {r.name} · {r.fstype || t('未格式化')} · {size(r.size)}
          </span>
        ))}
      </div>
      {boots.length > 0 && (
        <>
          <div className="region-rail-label">{t('硬件启动区 · 各区域有独立地址空间')}</div>
          <div className="boot-region-rail">{boots.map((r) => item(r))}</div>
        </>
      )}
      {selected && (
        <div className="region-selection">
          {t('当前区域：')}
          <b>{selected}</b>
        </div>
      )}
    </div>
  );
}
