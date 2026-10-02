import { t, locale } from './i18n.js';
import { useEffect, useState } from 'react';
const size = (n: number) =>
  n >= 1073741824 ? (n / 1073741824).toFixed(2) + ' GiB' : (n / 1048576).toFixed(1) + ' MiB';
function Gauge({
  label,
  percent,
  detail,
}: {
  label: string;
  percent: number | null;
  detail: string;
}) {
  const n = percent ?? 0;
  return (
    <div className="panel gauge-card">
      <div
        className="gauge-ring"
        style={{ background: `conic-gradient(var(--teal) ${n * 3.6}deg,var(--line) 0deg)` }}
      >
        <div>
          <b>{percent === null ? t('采样中') : n.toFixed(1) + '%'}</b>
          <small>{label}</small>
        </div>
      </div>
      <p>{detail}</p>
    </div>
  );
}
export function DevicePage({ fetchInfo, disks }: { fetchInfo: () => Promise<any>; disks: any[] }) {
  const [info, setInfo] = useState<any>(null),
    [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    const refresh = () =>
      fetchInfo()
        .then((i) => {
          if (alive) {
            setInfo(i);
            setError('');
          }
        })
        .catch((e) => {
          if (alive) setError(String(e));
        });
    refresh();
    const timer = setInterval(refresh, 3000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);
  if (!info) return <div className="panel">{error || t('正在读取设备信息…')}</div>;
  const root = info.filesystems.find((f: any) => f.mount === '/');
  return (
    <>
      <div className="panel system-summary">
        <h2>{info.model || info.hostname}</h2>
        <p>
          {info.hostname} · {info.os} · {info.architecture}
        </p>
        <small>
          {t('内核')}
          {info.kernel}
          {t('· 运行')}
          {Math.floor(info.uptime / 86400)}
          {t('天')} {Math.floor(info.uptime / 3600) % 24}
          {t('小时')}
          {Math.floor(info.uptime / 60) % 60}
          {t('分钟 · 每 3 秒刷新')}
        </small>
      </div>
      {error && <div className="alert error">{error}</div>}
      <div className="telemetry-gauges">
        <Gauge
          label={t('CPU 使用率')}
          percent={info.cpu.usage}
          detail={t('{0} 核 · {1}', [info.cpu.cores, info.cpu.model])}
        />
        <Gauge
          label={t('内存使用率')}
          percent={(info.memory.used / info.memory.total) * 100}
          detail={`${size(info.memory.used)} / ${size(info.memory.total)}`}
        />
        <Gauge
          label={t('系统磁盘使用率')}
          percent={root ? (root.used / root.total) * 100 : null}
          detail={root ? `${size(root.used)} / ${size(root.total)}` : t('暂无数据')}
        />
      </div>
      <div className="two-columns">
        <section className="panel">
          <h3>{t('处理器与内存')}</h3>
          <dl className="details-grid single">
            <div>
              <dt>{t('CPU 温度')}</dt>
              <dd>
                {info.cpu.temperatures
                  .map((t: any) => `${t.name}: ${t.celsius.toFixed(1)} °C`)
                  .join(' / ') || t('未提供传感器')}
              </dd>
            </div>
            <div>
              <dt>{t('负载（1 / 5 / 15 分钟）')}</dt>
              <dd>{info.cpu.load.map((n: number) => n.toFixed(2)).join(' / ')}</dd>
            </div>
            <div>
              <dt>{t('可用内存')}</dt>
              <dd>{size(info.memory.available)}</dd>
            </div>
            <div>
              <dt>{t('交换空间使用')}</dt>
              <dd>
                {size(info.memory.swap_used)} / {size(info.memory.swap_total)}
              </dd>
            </div>
          </dl>
        </section>
        <section className="panel">
          <h3>{t('磁盘与挂载空间')}</h3>
          {disks.map((d) => (
            <div className="system-disk" key={d.path}>
              <strong>
                {d.model} · {d.path}
              </strong>
              <span>
                {size(d.size)} · {d.kind} ·{' '}
                {d.regions.filter((r: any) => r.region === 'partition').length}
                {t('个分区')}
                {d.protected ? t(' · 系统保护') : ''}
              </span>
            </div>
          ))}
          {info.filesystems.map((f: any) => (
            <div key={f.mount} className="system-disk">
              <strong>
                {f.mount}
                {t('· 可用')}
                {size(f.free)}
              </strong>
              <div className="progress">
                <i style={{ width: (f.used / f.total) * 100 + '%' }} />
              </div>
            </div>
          ))}
        </section>
      </div>
      <section className="panel">
        <h3>{t('网络接口')}</h3>
        <div className="network-cards">
          {info.network.map((n: any) => (
            <div className="network-card" key={n.name}>
              <strong>
                {n.name}
                <span className="badge">{n.state}</span>
              </strong>
              <p>{n.addresses.join(' · ') || t('没有 IP 地址')}</p>
              <small>
                MAC {n.mac || '—'} · MTU {n.mtu} ·{' '}
                {Number(n.speed_mbps) > 0 ? n.speed_mbps + ' Mbps' : t('速率未提供')}
              </small>
              <div className="network-rates">
                <span>
                  {t('接收')}
                  {n.rx_rate === null ? t('采样中') : (n.rx_rate / 1024).toFixed(1) + ' KiB/s'}
                  <small>
                    {t('累计')}
                    {size(n.rx_bytes)}
                  </small>
                </span>
                <span>
                  {t('发送')}
                  {n.tx_rate === null ? t('采样中') : (n.tx_rate / 1024).toFixed(1) + ' KiB/s'}
                  <small>
                    {t('累计')}
                    {size(n.tx_bytes)}
                  </small>
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
