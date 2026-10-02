import { t, locale, serverText } from './i18n.js';
import { useEffect, useState } from 'react';
import { Download, RefreshCw, ShieldCheck, Upload } from 'lucide-react';

type Props = {
  api: (path: string, options?: RequestInit) => Promise<any>;
  post: (path: string, data: any) => Promise<any>;
};
export function UpgradePage({ api, post }: Props) {
  const [status, setStatus] = useState<any>(null);
  const [release, setRelease] = useState<any>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [reinstall, setReinstall] = useState(false);
  const [upload, setUpload] = useState<number | null>(null);
  const [connected, setConnected] = useState(true);
  const refresh = async () => {
    try {
      setStatus(await api('/upgrade'));
      setConnected(true);
      setError((previous) => (previous.includes('Failed to fetch') ? '' : previous));
    } catch {
      setConnected(false);
      // Web/worker restart during installation. Polling resumes automatically.
    }
  };
  useEffect(() => {
    api('/upgrade')
      .then(setStatus)
      .catch((e) => setError(String(e)));
    const timer = window.setInterval(refresh, 2000);
    return () => window.clearInterval(timer);
  }, []);
  const action = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError('');
    try {
      await fn();
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''));
    } finally {
      setBusy(false);
      setUpload(null);
    }
  };
  const install = async (source: 'online' | 'local') => {
    if (
      !window.confirm(t('升级将短暂重启网页和磁盘服务。管理员、备份和任务数据将保留。是否开始？'))
    )
      return;
    await action(async () => {
      let token: string | undefined;
      if (source === 'local') {
        if (!file || !file.size || file.size > 128 * 1024 * 1024)
          throw new Error(t('请选择不超过 128 MiB 的官方签名升级包'));
        const created = await post('/uploads', { name: file.name, size: file.size });
        token = created.id;
        const chunk = 2 * 1024 * 1024;
        for (let offset = 0; offset < file.size; offset += chunk) {
          await api(`/uploads/${token}?offset=${offset}`, {
            method: 'PUT',
            body: file.slice(offset, offset + chunk),
          });
          setUpload(Math.min(100, Math.round(((offset + chunk) * 100) / file.size)));
        }
      }
      setStatus(await post('/upgrade/install', { source, upload: token, reinstall }));
    });
  };
  const task = status?.task;
  const disabled = busy || task?.state === 'running';
  return (
    <>
      {error && <div className="alert error">{error}</div>}
      {!connected && (
        <p className="muted">{t('网页服务暂时断开，正在自动重新连接。升级任务在后台继续运行。')}</p>
      )}
      <section className="panel">
        <div className="panel-head">
          <h2>
            <ShieldCheck size={21} />
            {t('应用升级')}
          </h2>
          <span className="badge">{t('官方签名验证')}</span>
        </div>
        <p>
          {t('当前版本')}
          <strong>{status?.current || t('读取中…')}</strong>
          {t('· 更新源 JasonYANG170/eMMC-Studio')}
        </p>
        <p className="muted">
          {t('升级只更新应用程序。有进行中的磁盘任务时会拒绝安装；关闭浏览器不会取消升级。')}
        </p>
        <label className="upgrade-choice">
          <input
            type="checkbox"
            checked={reinstall}
            onChange={(e) => setReinstall(e.target.checked)}
            disabled={disabled}
          />{' '}
          {t('允许重新安装同版本')}
        </label>
      </section>
      <div className="two-columns">
        <section className="panel">
          <div className="panel-head">
            <h2>
              <Download size={21} />
              {t('在线升级')}
            </h2>
          </div>
          <p>{t('从 GitHub Release 检测最新稳定版本并下载升级包。')}</p>
          <button
            className="button secondary"
            disabled={disabled}
            onClick={() => action(async () => setRelease(await post('/upgrade/check', {})))}
          >
            <RefreshCw size={16} />
            {t('检查更新')}
          </button>
          {release && (
            <>
              <p>
                {t('最新版本')}
                <strong>{release.version}</strong> · {(release.size / 1048576).toFixed(2)} MiB ·{' '}
                {release.available ? t('有新版本') : t('已是最新版本')}
              </p>
              <p>
                <a href={release.release_url} target="_blank" rel="noreferrer">
                  {t('查看发布说明')}
                </a>
              </p>
              <button
                className="button"
                disabled={disabled || (!release.available && !reinstall)}
                onClick={() => install('online')}
              >
                {t('下载并升级')}
              </button>
            </>
          )}
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>
              <Upload size={21} />
              {t('本地导入')}
            </h2>
          </div>
          <p>
            {t('选择 Release 中的')}
            <strong>eMMC-Studio-update.tar.gz</strong>
            {t('。可在设备离线时安装，签名验证在设备本地完成。')}
          </p>
          <label className="field">
            {t('官方升级包')}
            <input
              type="file"
              accept=".gz,.tar.gz"
              disabled={disabled}
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </label>
          {upload !== null && (
            <p>
              {t('上传中')}
              {upload}%
            </p>
          )}
          <button className="button" disabled={disabled || !file} onClick={() => install('local')}>
            <Upload size={16} />
            {t('导入并升级')}
          </button>
        </section>
      </div>
      {task && task.state !== 'idle' && (
        <section className="panel">
          <div className="panel-head">
            <h2>{t('升级状态')}</h2>
            <span className="badge">
              {{
                running: t('运行中'),
                completed: t('已完成'),
                failed: t('失败'),
                interrupted: t('中断'),
              }[task.state as string] || task.state}
            </span>
          </div>
          <p>
            {task.from} {task.to ? `→ ${task.to}` : ''} · {serverText(task.phase)}
          </p>
          <progress
            value={task.progress || 0}
            max={100}
            style={{ width: '100%', accentColor: 'var(--primary)' }}
          />
          <p className="muted">
            {t('任务')}
            {task.id} · {task.progress || 0}%
          </p>
          {task.error && <div className="alert error">{serverText(task.error)}</div>}
          {task.state === 'completed' && (
            <button className="button secondary" onClick={() => window.location.reload()}>
              {t('刷新页面加载新版')}
            </button>
          )}
        </section>
      )}
    </>
  );
}
