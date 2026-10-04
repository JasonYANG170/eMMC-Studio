import { useEffect, useState } from 'react';
import { Usb, AlertTriangle } from 'lucide-react';
import { t } from './i18n';

export function UsbModePanel({
  api,
  post,
}: {
  api: (path: string) => Promise<any>;
  post: (path: string, data: any) => Promise<any>;
}) {
  const [status, setStatus] = useState<any>(null);
  const [error, setError] = useState('');
  const [pending, setPending] = useState<'host' | 'device' | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  useEffect(() => {
    let alive = true;
    const refresh = () =>
      api('/usb-mode')
        .then((data) => {
          if (alive) {
            setStatus(data);
            setError('');
          }
        })
        .catch((e) => {
          if (alive) setError(String(e));
        });
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);
  const usbConnection = window.location.hostname === '172.30.77.1';
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>
          <Usb size={20} /> {t('USB 模式切换')}
        </h2>
        <span className="badge">
          {status?.mode === 'host' ? 'Host' : status?.mode === 'device' ? 'Device' : '—'}
        </span>
      </div>
      <p className="panel-description">
        {t('Host 用于 U 盘克隆与 USB 外置设备；Device 用于 Windows 上位机 USB 直连。')}
      </p>
      <div className="info-strip">
        <AlertTriangle size={16} />{' '}
        {t(
          '切换会断开当前 OTG 连接。请先结束传输、安全卸载 USB 存储，并使用以太网或独立串口操作。',
        )}
      </div>
      {usbConnection && (
        <div className="info-strip">
          {t('当前正通过 USB 连接，请先改用下方以太网地址或独立串口。')}
        </div>
      )}
      <div className="info-strip">
        {t('其他连接地址：')}
        {status?.alternate_urls?.map((url: string) => (
          <a key={url} href={url}>
            {url}{' '}
          </a>
        ))}
        {t('独立串口可执行 CLI。Device 会启用 USB 网卡开机启动；Host 会停用。')}
      </div>
      {!status?.available && status && (
        <p className="panel-description">{t('USB 网卡服务尚未安装，无法切换')}</p>
      )}
      <div className="heading-actions">
        {(['host', 'device'] as const).map((mode) => (
          <button
            key={mode}
            className="button secondary"
            disabled={
              !status?.available ||
              status?.switching ||
              busy ||
              status?.mode === mode ||
              (usbConnection && mode === 'host')
            }
            onClick={() => {
              setPending(mode);
              setAcknowledged(false);
              setSubmitted(false);
            }}
          >
            {mode === 'host' ? t('切换 Host · U 盘 / 外设') : t('切换 Device · USB 上位机')}
          </button>
        ))}
      </div>
      {pending && (
        <div className="info-strip" style={{ display: 'block' }}>
          <p>
            {t('即将切换到 {0} 模式。请确认当前没有传输或 USB 克隆任务，并已使用其他连接方式。', [
              pending,
            ])}
          </p>
          <label>
            <input
              type="checkbox"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />{' '}
            {t('我已使用以太网或独立串口连接，并已安全卸载 USB 存储')}
          </label>
          <div className="heading-actions">
            <button
              className="button"
              disabled={!acknowledged || busy}
              onClick={async () => {
                setBusy(true);
                setError('');
                try {
                  await post('/usb-mode', { mode: pending, acknowledged: true });
                  setSubmitted(true);
                  setPending(null);
                } catch (e) {
                  setError(String(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {t('确认切换')}
            </button>
            <button className="button secondary" disabled={busy} onClick={() => setPending(null)}>
              {t('取消')}
            </button>
          </div>
        </div>
      )}
      {submitted && (
        <div className="info-strip">
          {t('切换任务已提交，3 秒后开始；可在任务记录中查看结果。')}
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </section>
  );
}
