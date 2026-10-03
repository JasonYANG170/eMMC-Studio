import { t, locale, serverText } from './i18n.js';
import { LanguageSelector } from './LanguageSelector';
import React, { useEffect, useState, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  Archive,
  ArrowLeftRight,
  ArrowUpRight,
  Binary,
  Check,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Download,
  FileText,
  Folder,
  FolderOpen,
  HardDrive,
  Layers,
  LayoutDashboard,
  Loader2,
  Lock,
  LogOut,
  Monitor,
  Moon,
  Pencil,
  Plus,
  RefreshCw,
  Settings,
  ShieldCheck,
  Sun,
  Trash2,
  Upload,
  Wifi,
  X,
  AlertTriangle,
  ArrowLeft,
  Search,
  Square,
} from 'lucide-react';
import './style.css';
import './theme.css';
import { useTheme, type ThemeMode } from './useTheme';
import { ByteInput } from './ByteInput';
import { DevicePage } from './DevicePage';
import { RegionMap } from './RegionMap';
import { HexGrid } from './HexGrid';
import { ResizeView } from './ResizeView';
import { DiskDetails } from './DiskDetails';
import { CacheCleaner } from './CacheCleaner';
import { UpgradePage } from './UpgradePage';
import { resizeLimit } from './layout';
import { VolumeLabel } from './VolumeLabel';
import { wantsDownload, readyDownloads } from './downloads';
import { partitionSectors, readWindow } from './units';

type Region = {
  name: string;
  kname: string;
  path: string;
  size: number;
  region: string;
  fstype?: string;
  label?: string;
  uuid?: string;
  partlabel?: string;
  parttype?: string;
  start?: number;
  mountpoints?: string[];
  ro: boolean;
  identity: string;
};
type Disk = Region & {
  kind: string;
  cid: string;
  identity: string;
  model: string;
  protected: boolean;
  writable: boolean;
  regions: Region[];
  table: any;
  topology: string;
  sector_size: number;
  health: { life_time: string; pre_eol: string; manufacturer: string; revision: string };
  rpmb: { path: string; size: number; available: boolean; note: string };
};
type Job = {
  id: string;
  title: string;
  op: string;
  state: string;
  created: number;
  finished?: number;
  progress: number;
  bytes: number;
  total: number;
  speed: number;
  phase: string;
  error?: string;
  target?: string;
  cancellable: boolean;
  logs?: { time: number; message: string }[];
  result?: any;
};
type Entry = { name: string; directory: boolean; symlink: boolean; size: number; modified: number };
type Field = {
  key: string;
  label: string;
  type?: string;
  value: any;
  options?: { value: string; label: string }[];
  help?: string;
  max?: number;
};
type Dialog = { title: string; args: any; fields: Field[]; danger: boolean; note?: string };
let csrf = '';
async function api(path: string, options: RequestInit = {}) {
  const res = await fetch('/api/v1' + path, {
    ...options,
    headers: {
      ...(options.body instanceof Blob ? {} : { 'Content-Type': 'application/json' }),
      'X-CSRF-Token': csrf,
      ...options.headers,
    },
  });
  const data = await res.json();
  if (!res.ok) throw new Error(serverText(data.error || t('请求失败')));
  return data;
}
const post = (path: string, data: any) => api(path, { method: 'POST', body: JSON.stringify(data) });
const query = (params: any) =>
  new URLSearchParams(
    Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])),
  ).toString();
const fmt = (n: number) => {
  if (!Number.isFinite(n)) return '—';
  if (n < 1024) return n + ' B';
  const u = ['KiB', 'MiB', 'GiB', 'TiB'];
  let i = -1;
  do {
    n /= 1024;
    i++;
  } while (n >= 1024 && i < 3);
  return n.toFixed(n >= 100 ? 0 : 2) + ' ' + u[i];
};
const date = (n: number) => new Date(n * 1000).toLocaleString(locale, { hour12: false });
const names: Record<string, string> = {
  user: t('用户区'),
  boot0: 'BOOT0',
  boot1: 'BOOT1',
  partition: t('文件系统分区'),
  sd: t('系统 SD 卡'),
  emmc: 'eMMC',
  usb: t('USB 存储'),
  disk: t('磁盘'),
  loop: t('测试磁盘'),
};
const states: Record<string, string> = {
  queued: t('等待中'),
  running: t('执行中'),
  completed: t('已完成'),
  failed: t('失败'),
  cancelled: t('已取消'),
  interrupted: t('已中断'),
};
const nav = [
  { id: 'device', title: t('设备信息'), icon: Cpu },
  { id: 'overview', title: t('磁盘概览'), icon: LayoutDashboard },
  { id: 'diskdetails', title: t('磁盘详情'), icon: HardDrive },
  { id: 'partitions', title: t('分区管理'), icon: Layers },
  { id: 'files', title: t('文件管理'), icon: FolderOpen },
  { id: 'hex', title: t('扇区编辑'), icon: Binary },
  { id: 'transfer', title: t('克隆与恢复'), icon: ArrowLeftRight },
  { id: 'backups', title: t('备份库'), icon: Archive },
  { id: 'jobs', title: t('任务记录'), icon: Activity },
  { id: 'cache', title: t('缓存清理'), icon: Trash2 },
  { id: 'upgrade', title: t('应用升级'), icon: Download },
  { id: 'settings', title: t('设置'), icon: Settings },
];
const navGroups = [
  { title: t('设备与磁盘'), ids: ['device', 'overview', 'diskdetails'] },
  { title: t('数据操作'), ids: ['partitions', 'files', 'hex', 'transfer', 'backups'] },
  { title: t('维护与设置'), ids: ['jobs', 'cache', 'upgrade', 'settings'] },
].map((group) => ({ ...group, items: nav.filter((item) => group.ids.includes(item.id)) }));

function App() {
  const { mode: themeMode, theme, setMode: setThemeMode } = useTheme();
  const [auth, setAuth] = useState<any>(null),
    [page, setPage] = useState(sessionStorage.getItem('workspace-page') || 'overview'),
    [disks, setDisks] = useState<Disk[]>([]),
    [selected, setSelected] = useState(''),
    [jobs, setJobs] = useState<Job[]>([]),
    [backups, setBackups] = useState<any[]>([]),
    [snapshots, setSnapshots] = useState<any[]>([]),
    [free, setFree] = useState(0),
    [busy, setBusy] = useState<string[]>([]),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [loading, setLoading] = useState(false),
    [dialog, setDialog] = useState<Dialog | null>(null),
    [ext, setExt] = useState(''),
    [regionPath, setRegionPath] = useState(''),
    [path, setPath] = useState(''),
    [entries, setEntries] = useState<Entry[]>([]),
    [textEdit, setTextEdit] = useState<{ path: string; text: string; sha256: string } | null>(null),
    [hex, setHex] = useState<any>(null),
    [hexValue, setHexValue] = useState(''),
    [offset, setOffset] = useState('0'),
    [hexLength, setHexLength] = useState('512'),
    [uploadProgress, setUploadProgress] = useState<number | null>(null),
    [uploadInfo, setUploadInfo] = useState<any>(null),
    [settings, setSettings] = useState<any>(null),
    [oldPassword, setOldPassword] = useState(''),
    [newPassword, setNewPassword] = useState('');
  const [fileEditing, setFileEditing] = useState(false);
  const [extLoading, setExtLoading] = useState(false),
    [extError, setExtError] = useState('');
  const pendingDownloads = useRef<Set<string>>(
    (() => {
      try {
        return new Set<string>(JSON.parse(sessionStorage.getItem('pending-downloads') || '[]'));
      } catch {
        return new Set<string>();
      }
    })(),
  );
  const [downloadReady, setDownloadReady] = useState<{
    token: string;
    title: string;
    stream?: boolean;
  } | null>(null);
  const savePendingDownloads = () =>
    sessionStorage.setItem('pending-downloads', JSON.stringify([...pendingDownloads.current]));
  useEffect(() => {
    if (!auth?.authenticated || auth.must_change) return;
    for (const job of readyDownloads(jobs, pendingDownloads.current)) {
      pendingDownloads.current.delete(job.id);
      savePendingDownloads();
      const token = job.result!.download!;
      setDownloadReady({ token, title: job.title });
      const link = document.createElement('a');
      link.href = '/api/v1/downloads/' + token;
      link.download = '';
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      link.remove();
    }
    for (const job of jobs) {
      if (
        ['failed', 'cancelled', 'interrupted'].includes(job.state) &&
        pendingDownloads.current.delete(job.id)
      )
        savePendingDownloads();
    }
  }, [jobs, auth?.authenticated, auth?.must_change]);
  const [hexRange, setHexRange] = useState<{ start: number; length: number } | null>(null);
  const disk = disks.find((d) => d.path === selected),
    region = disk?.regions.find((r) => r.path === regionPath) || disk?.regions[0];
  const targetArgs = (r: Region = region!, d: Disk = disk!) => ({
    target: r.path,
    identity: d.identity,
  });
  useEffect(() => {
    sessionStorage.setItem('workspace-page', page);
  }, [page]);
  const activeJobs = jobs.filter((j) => ['queued', 'running'].includes(j.state));
  const [source, setSource] = useState(''),
    [restoreType, setRestoreType] = useState('upload'),
    [usbPartition, setUsbPartition] = useState(''),
    [imagePath, setImagePath] = useState(''),
    [imageGzip, setImageGzip] = useState(false),
    [imageSize, setImageSize] = useState(''),
    [backupCompressed, setBackupCompressed] = useState(true),
    [backupFull, setBackupFull] = useState(true),
    [backupStorage, setBackupStorage] = useState('browser'),
    [backupUsb, setBackupUsb] = useState('');
  const allRegions = disks.flatMap((d) => d.regions.map((r) => ({ ...r, disk: d }))),
    usbRegions = allRegions.filter((r) => r.disk.kind === 'usb' && r.region === 'partition');
  const refresh = async () => {
    try {
      const data = await api('/devices');
      setDisks(data.disks);
      setBusy(data.busy);
      setFree(data.local_free);
      setError((previous) => (previous.includes('Failed to fetch') ? '' : previous));
      setSelected((prev) =>
        data.disks.some((d: Disk) => d.path === prev)
          ? prev
          : data.disks.find((d: Disk) => d.kind === 'emmc')?.path || data.disks[0]?.path || '',
      );
    } catch (e) {
      setError(String(e));
    }
  };
  const refreshBackups = async () => {
    try {
      const b = await api('/backups');
      setBackups(b.backups);
      setSnapshots(b.snapshots);
    } catch (e) {
      setError(String(e));
    }
  };
  const refreshSettings = async () => {
    try {
      setSettings(await api('/settings'));
    } catch (e) {
      setError(String(e));
    }
  };
  const loadFiles = async (p = path) => {
    if (!disk || !region) return;
    setLoading(true);
    try {
      const data = await api('/files?' + query({ ...targetArgs(), path: p }));
      setEntries(data.entries);
      setPath(p);
    } catch (e) {
      setError(String(e));
      setEntries([]);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    api('/auth/status')
      .then((a) => {
        csrf = a.csrf || '';
        setAuth(a);
      })
      .catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    if (!auth?.authenticated || auth.must_change) return;
    refresh();
    refreshBackups();
    refreshSettings();
    api('/jobs').then((d) => setJobs(d.jobs));
    const timer = setInterval(refresh, 10000);
    const stream = new EventSource('/api/v1/events');
    stream.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.jobs) setJobs(d.jobs);
    };
    return () => {
      clearInterval(timer);
      stream.close();
    };
  }, [auth?.authenticated, auth?.must_change]);
  useEffect(() => {
    setRegionPath(disk?.regions[0]?.path || '');
    setPath('');
    setEntries([]);
    setExt('');
    setHex(null);
    setHexRange(null);
    setOffset('0');
    setHexLength('512');
  }, [selected]);
  useEffect(() => {
    setFileEditing(false);
    setTextEdit(null);
    if (page === 'files' && region?.region === 'partition') loadFiles('');
    setHex(null);
    setHexRange(null);
    setOffset('0');
    setHexLength(String(Math.min(512, region?.size || 512)));
    setPath('');
    setEntries([]);
  }, [regionPath, page]);
  useEffect(() => {
    if (page === 'backups') refreshBackups();
    if (page === 'settings') refreshSettings();
  }, [page, jobs.filter((j) => j.state === 'completed').length]);
  useEffect(() => {
    setExt('');
    setExtError('');
    setExtLoading(false);
    if (page !== 'diskdetails' || disk?.kind !== 'emmc') return;
    let active = true;
    setExtLoading(true);
    api('/extcsd?' + query({ target: disk.path }))
      .then((d) => {
        if (active) setExt(d.text);
      })
      .catch((e) => {
        if (active) setExtError(String(e));
      })
      .finally(() => {
        if (active) setExtLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, selected, disk?.kind]);
  useEffect(() => {
    if (notice) {
      const t = setTimeout(() => setNotice(''), 7000);
      return () => clearTimeout(t);
    }
  }, [notice]);
  const open = (title: string, args: any, fields: Field[] = [], danger = true, note?: string) => {
    setDialog({ title, args, fields, danger, note });
  };
  const submit = async () => {
    if (!dialog) return;
    setLoading(true);
    try {
      let args = { ...dialog.args };
      for (const field of dialog.fields)
        args[field.key] =
          field.type === 'sectorbytes'
            ? partitionSectors(Number(field.value))
            : ['number', 'bytes'].includes(field.type || '')
              ? Number(field.value)
              : field.value;
      args.title = dialog.title;
      const job = await post('/jobs', args);
      if (job.result?.stream) {
        const token = job.result.stream;
        setDownloadReady({ token, title: args.title, stream: true });
        const link = document.createElement('a');
        link.href = '/api/v1/streams/' + token;
        link.download = '';
        document.body.appendChild(link);
        link.click();
        link.remove();
      } else if (wantsDownload(args)) {
        pendingDownloads.current.add(job.id);
        savePendingDownloads();
      }
      setJobs((prev) => [job, ...prev]);
      setNotice(
        wantsDownload(args)
          ? t('已请求流式下载，浏览器接收时开始传输')
          : t('任务已提交，可在任务记录中查看进度'),
      );
      setDialog(null);
      setPage('jobs');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };
  const launch = (title: string, args: any, danger = true, note?: string) =>
    open(title, args, [], danger, note);
  const upload = async (file: File) => {
    setUploadProgress(0);
    try {
      const resumeKey = 'upload:' + file.name + ':' + file.size + ':' + file.lastModified;
      let info: any;
      const saved = sessionStorage.getItem(resumeKey);
      if (saved) {
        try {
          info = { id: saved, ...(await api('/uploads/' + saved)) };
        } catch {}
      }
      if (!info) info = await post('/uploads', { name: file.name, size: file.size });
      sessionStorage.setItem(resumeKey, info.id);
      let off = info.received;
      while (off < file.size) {
        const blob = file.slice(off, Math.min(off + 4 * 1024 * 1024, file.size));
        const m = await api('/uploads/' + info.id + '?offset=' + off, {
          method: 'PUT',
          body: blob,
          headers: { 'Content-Type': 'application/octet-stream' },
        });
        off = m.received;
        setUploadProgress((off / file.size) * 100);
        info = { id: info.id, ...m };
      }
      setUploadInfo(info);
      setNotice(t('上传完成，文件已暂存'));
      return info;
    } catch (e) {
      setError(String(e));
      throw e;
    } finally {
      setUploadProgress(null);
    }
  };
  const hexLoad = async (jump?: number) => {
    if (!region) return;
    setLoading(true);
    try {
      const off = jump ?? (offset.startsWith('0x') ? parseInt(offset, 16) : Number(offset));
      if (jump !== undefined) setOffset(String(jump));
      const range =
        jump !== undefined && hexRange ? hexRange : { start: off, length: Number(hexLength) };
      if (range.start + range.length > region.size) throw new Error(t('读取范围超出当前区域'));
      const window = readWindow(range.start, range.length, off);
      const data = await api(
        '/hex?' + query({ ...targetArgs(), offset: window.offset, length: window.length }),
      );
      setHexRange(range);
      setHex(data);
      setHexValue(data.hex);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };
  const fileAction = (title: string, args: any, fields: Field[] = []) =>
    open(
      title,
      { ...targetArgs(), op: 'file_write', edit_mode: fileEditing, ...args },
      fields,
      true,
      t('修改完成后分区会自动卸载，默认浏览模式仍为只读。'),
    );

  if (!auth)
    return (
      <div className="startup">
        <Cpu size={40} />
        <span>{t('连接存储工作台…')}</span>
        {error && <p>{error}</p>}
      </div>
    );
  if (auth.authenticated && auth.must_change)
    return (
      <ForcePassword
        username={auth.username}
        onChanged={() => setAuth({ ...auth, must_change: false })}
      />
    );
  if (!auth.authenticated)
    return (
      <Login
        configured={auth.configured}
        username={auth.username || 'emmc-admin'}
        onLogin={(a) => {
          csrf = a.csrf;
          setAuth({ ...auth, ...a, configured: true, authenticated: true });
        }}
      />
    );
  const regionSelector = disk ? (
    <div className="region-select graphical-select">
      <RegionMap disk={disk} selected={region?.path} onSelect={setRegionPath} />
      {disk.protected && (
        <span className="badge amber">
          <Lock size={12} />
          {t('系统磁盘 · 已保护')}
        </span>
      )}
    </div>
  ) : null;
  return (
    <div className="app-shell">
      <aside>
        <a className="brand" onClick={() => setPage('overview')}>
          <span className="brand-icon">
            <Cpu size={26} />
          </span>
          <span>
            eMMC <b>Studio</b>
            <small>{t('存储工作台')}</small>
          </span>
        </a>
        <div className="nav-label">{t('工作空间')}</div>
        <nav className="workspace-nav" aria-label={t('工作空间')}>
          {navGroups.map((group) => (
            <section className="nav-group" key={group.title} aria-label={group.title}>
              <h2 className="nav-group-title">{group.title}</h2>
              <div className="nav-group-buttons">
                {group.items.map((n) => (
                  <button
                    aria-label={n.title}
                    aria-current={page === n.id ? 'page' : undefined}
                    title={n.title}
                    className={page === n.id ? 'active' : ''}
                    key={n.id}
                    onClick={() => setPage(n.id)}
                  >
                    <n.icon size={19} />
                    <span>{n.title}</span>
                    {n.id === 'jobs' && activeJobs.length > 0 && <i>{activeJobs.length}</i>}
                  </button>
                ))}
              </div>
            </section>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="connected">
            <span className="pulse" />
            {t('设备在线')}
            <span>R28S</span>
          </div>
          <small>
            {t('本地部署 · v')}
            {settings?.version || '…'}
          </small>
          <button
            onClick={async () => {
              await post('/auth/logout', {});
              setAuth({ ...auth, authenticated: false });
            }}
          >
            <LogOut size={17} />
            {t('退出登录')}
          </button>
        </div>
      </aside>
      <main>
        <header>
          <div className="breadcrumb">
            {t('存储工作台')}
            <ChevronRight size={15} />
            <strong>{nav.find((n) => n.id === page)?.title}</strong>
          </div>
          <div className="header-actions">
            <LanguageSelector
              dirty={
                !!dialog || !!textEdit || uploadProgress !== null || (!!hex && hexValue !== hex.hex)
              }
            />
            <span className="network">
              <Wifi size={14} />
              {t('局域网连接')}
            </span>
            <div className="theme-control">
              {themeMode === 'system' ? (
                <Monitor size={16} />
              ) : theme === 'dark' ? (
                <Moon size={16} />
              ) : (
                <Sun size={16} />
              )}
              <select
                aria-label={t('主题模式')}
                title={t('主题模式')}
                value={themeMode}
                onChange={(e) => setThemeMode(e.target.value as ThemeMode)}
              >
                <option value="system">{t('跟随系统')}</option>
                <option value="light">{t('浅色')}</option>
                <option value="dark">{t('深色')}</option>
              </select>
            </div>
            <div className="avatar">A</div>
          </div>
        </header>
        <div className="workspace">
          <div className="page-heading">
            <div>
              <div className="eyebrow">STORAGE WORKSPACE</div>
              <h1>{nav.find((n) => n.id === page)?.title}</h1>
              <p>
                {
                  (
                    {
                      device: t('实时查看设备运行状态、资源使用和网络连接。'),
                      overview: t('掌握每个存储区域，管理每一份数据。'),
                      diskdetails: t('查看设备标识、容量布局、健康状态及寄存器解析。'),
                      partitions: t('查看布局，创建和调整磁盘分区。'),
                      files: t('浏览分区中的目录与文件，按需开启编辑。'),
                      hex: t('查看原始字节，精确编辑指定范围。'),
                      transfer: t('在 USB 存储、镜像与 eMMC 之间传输数据。'),
                      backups: t('保存完整副本，让每次恢复都有据可查。'),
                      jobs: t('每一次读写，都有清晰的进度与结果。'),
                      cache: t('按类型选择记录与暂存文件，查看空间并安全清理。'),
                      upgrade: t('检测官方版本或导入签名升级包，独立升级应用程序。'),
                      settings: t('管理访问密码和工作台设置。'),
                    } as any
                  )[page]
                }
              </p>
            </div>
            <div className="heading-actions">
              <select
                aria-label={t('选择磁盘')}
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                {disks.map((d) => (
                  <option value={d.path} key={d.path}>
                    {d.model} · {d.name}
                  </option>
                ))}
              </select>
              <button className="button secondary" onClick={refresh}>
                <RefreshCw size={15} />
                {t('刷新')}
              </button>
            </div>
          </div>
          {error && (
            <div className="alert error">
              <AlertTriangle size={18} />
              <span>{error.replace(/^Error: /, '')}</span>
              <button onClick={() => setError('')}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success">
              <CheckCircle2 size={18} />
              {notice}
            </div>
          )}
          {downloadReady && (
            <div className="alert success">
              <Download size={18} />
              <span>
                {serverText(downloadReady.title)}
                {t('：')}
                {downloadReady.stream
                  ? t('已请求直接流式下载，不占用 SD 卡镜像暂存。')
                  : t('文件已生成，已请求浏览器下载。')}
                {t('如未弹出下载，请点击右侧按钮；内置浏览器若取消下载，请改用 Chrome/Edge。')}
              </span>
              <a
                className="button secondary small"
                href={
                  '/api/v1/' +
                  (downloadReady.stream ? 'streams/' : 'downloads/') +
                  downloadReady.token
                }
                download
              >
                {t('立即下载')}
              </a>
              <button aria-label={t('关闭下载提示')} onClick={() => setDownloadReady(null)}>
                <X size={16} />
              </button>
            </div>
          )}
          {!disk && !['jobs', 'settings', 'backups', 'cache', 'upgrade'].includes(page) ? (
            <Empty
              icon={HardDrive}
              title={t('未发现可管理的磁盘')}
              text={t('连接 eMMC 或 USB 存储后刷新列表。')}
            />
          ) : (
            <>
              {page === 'device' && <DevicePage fetchInfo={() => api('/system')} disks={disks} />}
              {page === 'overview' && disk && (
                <>
                  <section className="device-hero">
                    <div className="hero-copy">
                      <div className="hero-tags">
                        <span>{names[disk.kind] || disk.kind}</span>
                        <span>
                          <span className="pulse" />
                          {busy.includes(disk.identity) ? t('任务执行中') : t('已连接')}
                        </span>
                      </div>
                      <h2>{disk.model}</h2>
                      <div className="device-path">
                        {disk.path}
                        <span>
                          {disk.table?.label?.toUpperCase() || t('未分区')} ·{' '}
                          {disk.protected ? t('系统磁盘已保护') : t('可管理设备')}
                        </span>
                      </div>
                      <div className="hero-metrics">
                        <div>
                          <small>{t('用户区容量')}</small>
                          <strong>{fmt(disk.size)}</strong>
                        </div>
                        <div>
                          <small>{t('硬件启动区')}</small>
                          <strong>
                            {disk.regions.filter((r) => r.region.startsWith('boot')).length}{' '}
                            <em>{t('个')}</em>
                          </strong>
                        </div>
                        <div>
                          <small>{t('文件系统分区')}</small>
                          <strong>
                            {disk.regions.filter((r) => r.region === 'partition').length}{' '}
                            <em>{t('个')}</em>
                          </strong>
                        </div>
                      </div>
                    </div>
                    <div className="chip-art">
                      <div className="chip-core">
                        <Cpu size={54} />
                        <span>eMMC</span>
                        <small>STORAGE MODULE</small>
                      </div>
                      <i className="orbit one" />
                      <i className="orbit two" />
                    </div>
                  </section>
                  <div className="stat-grid">
                    <Stat
                      icon={Layers}
                      label={t('分区表')}
                      value={disk.table?.label?.toUpperCase() || t('无分区表')}
                      detail={t('实时读取磁盘布局')}
                    />
                    <Stat
                      icon={ShieldCheck}
                      label={t('BOOT 区保护')}
                      value={
                        disk.regions.some((r) => r.region.startsWith('boot'))
                          ? t('默认只读')
                          : t('不适用')
                      }
                      detail={t('仅在确认写入时临时解锁')}
                    />
                    <Stat
                      icon={Archive}
                      label={t('本地备份空间')}
                      value={fmt(free)}
                      detail={t('存储在系统 SD 卡上')}
                    />
                    <Stat
                      icon={Activity}
                      label={t('进行中的任务')}
                      value={String(activeJobs.length)}
                      detail={t('浏览器关闭后任务仍继续')}
                    />
                  </div>
                  <div className="overview-columns">
                    <section className="panel">
                      <PanelHead
                        icon={Layers}
                        title={t('存储区域')}
                        action={
                          <button className="text-button" onClick={() => setPage('partitions')}>
                            {t('管理分区')}
                            <ArrowUpRight size={15} />
                          </button>
                        }
                      />
                      <PartitionMap disk={disk} />
                      <div className="region-cards">
                        {disk.regions
                          .filter((r) => r.region !== 'partition')
                          .map((r) => (
                            <button
                              key={r.path}
                              className="region-card"
                              onClick={() => {
                                setRegionPath(r.path);
                                setPage('hex');
                              }}
                            >
                              <div className={'region-icon ' + r.region}>
                                <HardDrive size={21} />
                              </div>
                              <div>
                                <strong>{names[r.region]}</strong>
                                <small>{r.name}</small>
                              </div>
                              <div>
                                <b>{fmt(r.size)}</b>
                                <small>
                                  {r.ro ? t('只读保护') : t('用户数据')}
                                  <ChevronRight size={13} />
                                </small>
                              </div>
                            </button>
                          ))}
                        {disk.rpmb.available && (
                          <div className="region-card muted">
                            <div className="region-icon">
                              <Lock size={20} />
                            </div>
                            <div>
                              <strong>RPMB</strong>
                              <small>{disk.rpmb.path}</small>
                            </div>
                            <div>
                              <b>{fmt(disk.rpmb.size)}</b>
                              <small>{t('认证访问')}</small>
                            </div>
                          </div>
                        )}
                      </div>
                    </section>
                    <section className="panel">
                      <PanelHead
                        icon={Activity}
                        title={t('最近任务')}
                        action={
                          <button className="text-button" onClick={() => setPage('jobs')}>
                            {t('查看全部')}
                            <ArrowUpRight size={15} />
                          </button>
                        }
                      />
                      {jobs.length ? (
                        jobs.slice(0, 3).map((j) => <JobRow key={j.id} job={j} compact />)
                      ) : (
                        <Empty
                          icon={Activity}
                          title={t('一切就绪')}
                          text={t('开始备份或克隆后，进度会显示在这里。')}
                        />
                      )}
                      <div className="quick-actions">
                        <button
                          onClick={() => {
                            setPage('backups');
                          }}
                        >
                          <Archive size={18} />
                          {t('创建备份')}
                          <ChevronRight size={16} />
                        </button>
                        <button onClick={() => setPage('transfer')}>
                          <ArrowLeftRight size={18} />
                          {t('克隆与恢复')}
                          <ChevronRight size={16} />
                        </button>
                      </div>
                    </section>
                  </div>
                  <button className="button secondary" onClick={() => setPage('diskdetails')}>
                    <HardDrive size={16} />
                    {t('查看磁盘详情')}
                    <ArrowUpRight size={15} />
                  </button>
                </>
              )}
              {page === 'diskdetails' && disk && (
                <>
                  <section className="panel">
                    <PanelHead
                      icon={HardDrive}
                      title={t('磁盘详情')}
                      action={
                        disk.kind === 'emmc' ? (
                          <button
                            className="button secondary small"
                            disabled={extLoading}
                            onClick={async () => {
                              setExtLoading(true);
                              setExtError('');
                              try {
                                setExt((await api('/extcsd?' + query({ target: disk.path }))).text);
                              } catch (e) {
                                setExtError(String(e));
                              } finally {
                                setExtLoading(false);
                              }
                            }}
                          >
                            {extLoading ? t('正在读取 EXT_CSD…') : t('刷新 EXT_CSD')}
                          </button>
                        ) : null
                      }
                    />
                    <DiskDetails disk={disk} ext={ext} loading={extLoading} error={extError} />
                  </section>
                </>
              )}
              {page === 'partitions' && disk && (
                <>
                  <section className="panel">
                    <PanelHead
                      icon={Layers}
                      title={t('分区布局')}
                      action={
                        <div className="button-group">
                          <button
                            disabled={!disk.writable}
                            className="button secondary"
                            onClick={() =>
                              open(
                                t('建立分区表'),
                                {
                                  ...targetArgs(disk.regions[0]),
                                  op: 'partition',
                                  action: 'new_table',
                                },
                                [
                                  {
                                    key: 'table',
                                    label: t('分区表类型'),
                                    type: 'select',
                                    value: 'gpt',
                                    options: [
                                      { value: 'gpt', label: 'GPT' },
                                      { value: 'dos', label: 'MBR' },
                                    ],
                                  },
                                ],
                                true,
                                t('此操作将替换原分区表，原文件系统可能无法访问。'),
                              )
                            }
                          >
                            {t('建立分区表')}
                          </button>
                          <button
                            disabled={!disk.writable || !disk.table}
                            className="button"
                            onClick={() =>
                              open(
                                t('创建分区'),
                                {
                                  ...targetArgs(disk.regions[0]),
                                  op: 'partition',
                                  action: 'create',
                                },
                                [
                                  {
                                    key: 'start',
                                    label: t('分区起点'),
                                    type: 'sectorbytes',
                                    value: nextStart(disk) * 512,
                                    max: disk.size - 1048576,
                                  },
                                  {
                                    key: 'size',
                                    label: t('分区容量'),
                                    type: 'sectorbytes',
                                    value: 100 * 1048576,
                                    max: disk.size - nextStart(disk) * 512,
                                    help: t('支持容量与扇区换算；起点和容量均需 1 MiB 对齐。'),
                                  },
                                ],
                              )
                            }
                          >
                            <Plus size={16} />
                            {t('创建分区')}
                          </button>
                        </div>
                      }
                    />
                    <PartitionMap disk={disk} />
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>{t('分区')}</th>
                            <th>{t('文件系统 / 卷标')}</th>
                            <th>{t('起点 / 大小')}</th>
                            <th>{t('UUID / 类型')}</th>
                            <th>{t('操作')}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {disk.regions
                            .filter((r) => r.region === 'partition')
                            .map((r) => (
                              <tr key={r.path}>
                                <td>
                                  <strong>{r.name}</strong>
                                  <small>{r.path}</small>
                                </td>
                                <td>
                                  <span className="badge">{r.fstype || t('未格式化')}</span>
                                  <small>{r.label || r.partlabel || '—'}</small>
                                </td>
                                <td>
                                  {fmt(r.size)}
                                  <small>
                                    {t('起始扇区')}
                                    {r.start}
                                    {t('· 末扇区')} {Number(r.start) + Math.floor(r.size / 512) - 1}
                                  </small>
                                  <small>
                                    {r.ro ? t('只读') : t('可读写')} ·{' '}
                                    {(r.mountpoints || []).filter(Boolean).join(', ') ||
                                      t('未挂载')}
                                  </small>
                                </td>
                                <td className="mono small-text">
                                  {r.uuid || '—'}
                                  <small>{r.parttype || '—'}</small>
                                </td>
                                <td>
                                  <div className="row-actions">
                                    <button
                                      title={t('修改属性')}
                                      disabled={!disk.writable}
                                      onClick={() =>
                                        open(
                                          t('修改分区属性'),
                                          {
                                            ...targetArgs(disk.regions[0]),
                                            op: 'partition',
                                            action: 'modify',
                                            index: partIndex(r),
                                          },
                                          [
                                            {
                                              key: 'label',
                                              label: t('GPT 分区名称'),
                                              value: r.partlabel || '',
                                              help:
                                                disk.table?.label === 'dos'
                                                  ? t('MBR 不支持名称，此字段会忽略。')
                                                  : '',
                                            },
                                            {
                                              key: 'type',
                                              label: t('类型代码或 GUID'),
                                              value: r.parttype || '',
                                            },
                                            {
                                              key: 'bootable',
                                              label: t('MBR 启动标志'),
                                              type: 'checkbox',
                                              value: Boolean(
                                                disk.table?.partitions?.find(
                                                  (p: any) => p.node === r.path,
                                                )?.bootable,
                                              ),
                                            },
                                          ],
                                        )
                                      }
                                    >
                                      <Pencil size={15} />
                                    </button>
                                    <button
                                      title={t('格式化')}
                                      disabled={!disk.writable}
                                      onClick={() =>
                                        open(
                                          t('格式化分区'),
                                          { ...targetArgs(r), op: 'format' },
                                          [
                                            {
                                              key: 'filesystem',
                                              label: t('文件系统'),
                                              type: 'select',
                                              value: 'ext4',
                                              options: ['ext4', 'vfat', 'exfat', 'ntfs'].map(
                                                (x) => ({
                                                  value: x,
                                                  label: x === 'vfat' ? 'FAT32' : x.toUpperCase(),
                                                }),
                                              ),
                                            },
                                            {
                                              key: 'label',
                                              label: t('卷标（最多 11 字符）'),
                                              type: 'label',
                                              value: '',
                                            },
                                          ],
                                          true,
                                          t('格式化会清除该分区的现有文件。'),
                                        )
                                      }
                                    >
                                      {t('格式化')}
                                    </button>
                                    <button
                                      title={t('调整大小')}
                                      disabled={!disk.writable || r.fstype !== 'ext4'}
                                      onClick={() =>
                                        open(
                                          t('调整 ext4 分区大小'),
                                          { ...targetArgs(r), op: 'resize' },
                                          [
                                            {
                                              key: 'size',
                                              label: t('新容量'),
                                              type: 'sectorbytes',
                                              value: r.size,
                                              max: resizeLimit(disk, r),
                                            },
                                          ],
                                          true,
                                          t('离线检查文件系统后调整大小，不移动分区起点。'),
                                        )
                                      }
                                    >
                                      {t('调整')}
                                    </button>
                                    <button
                                      title={t('删除分区')}
                                      disabled={!disk.writable}
                                      className="danger-icon"
                                      onClick={() =>
                                        launch(
                                          t('删除分区'),
                                          {
                                            ...targetArgs(disk.regions[0]),
                                            op: 'partition',
                                            action: 'delete',
                                            index: partIndex(r),
                                          },
                                          true,
                                          t('删除分区表中的这一项，原数据将无法通过该分区访问。'),
                                        )
                                      }
                                    >
                                      <Trash2 size={15} />
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </div>
                    {!disk.regions.some((r) => r.region === 'partition') && (
                      <Empty
                        icon={Layers}
                        title={t('还没有分区')}
                        text={t('建立分区表后即可创建分区。')}
                      />
                    )}
                    <div className="info-strip">
                      {t('分区表修改前会自动保存快照。ext4 支持离线调整；不移动已有分区。')}
                    </div>
                  </section>
                </>
              )}
              {page === 'files' && disk && (
                <section className="panel">
                  {regionSelector}
                  <PanelHead
                    icon={FolderOpen}
                    title={t('文件浏览器')}
                    action={
                      <button
                        className="button secondary small"
                        disabled={!disk.writable || region?.region !== 'partition'}
                        onClick={() => setFileEditing(!fileEditing)}
                      >
                        {fileEditing ? <Pencil size={12} /> : <Lock size={12} />}{' '}
                        {fileEditing ? t('编辑模式 · 点击退出') : t('只读浏览 · 开启编辑模式')}
                      </button>
                    }
                  />
                  {region?.region !== 'partition' ? (
                    <Empty
                      icon={FolderOpen}
                      title={t('选择文件系统分区')}
                      text={t('BOOT 区和整盘请使用扇区编辑或镜像备份。')}
                    />
                  ) : (
                    <>
                      <div className="file-toolbar">
                        <button
                          className="icon-button"
                          aria-label={t('上级目录')}
                          onClick={() => loadFiles(path.split('/').slice(0, -1).join('/'))}
                        >
                          <ArrowLeft size={17} />
                        </button>
                        <span className="file-path">/{path}</span>
                        <button className="button secondary small" onClick={() => loadFiles()}>
                          <RefreshCw size={14} />
                        </button>
                        <button
                          disabled={!disk.writable || !fileEditing}
                          className="button secondary small"
                          onClick={() =>
                            fileAction(t('新建目录'), { action: 'mkdir' }, [
                              {
                                key: 'path',
                                label: t('目录路径'),
                                value: path ? path + t('/新目录') : t('新目录'),
                              },
                            ])
                          }
                        >
                          <Plus size={14} />
                          {t('新建目录')}
                        </button>
                        <label
                          className={
                            'button small ' + (!disk.writable || !fileEditing ? 'disabled' : '')
                          }
                        >
                          <Upload size={14} />
                          {t('上传文件')}
                          <input
                            type="file"
                            hidden
                            disabled={!disk.writable || !fileEditing}
                            onChange={async (e) => {
                              const f = e.target.files?.[0];
                              if (!f) return;
                              try {
                                const u = await upload(f);
                                fileAction(
                                  t('上传文件'),
                                  {
                                    action: 'upload',
                                    upload: u.id,
                                    path: path ? path + '/' + f.name : f.name,
                                  },
                                  [
                                    {
                                      key: 'overwrite',
                                      label: t('允许覆盖同名文件'),
                                      type: 'checkbox',
                                      value: false,
                                    },
                                  ],
                                );
                              } catch {}
                              e.target.value = '';
                            }}
                          />
                        </label>
                      </div>
                      {loading ? (
                        <div className="inline-loading">
                          <Loader2 className="spin" />
                          {t('读取目录…')}
                        </div>
                      ) : (
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>{t('名称')}</th>
                                <th>{t('大小')}</th>
                                <th>{t('修改时间')}</th>
                                <th>{t('操作')}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {entries.map((e) => {
                                const ep = path ? path + '/' + e.name : e.name;
                                return (
                                  <tr key={e.name}>
                                    <td>
                                      <button
                                        className="file-name"
                                        disabled={e.symlink}
                                        onClick={async () => {
                                          if (e.directory) loadFiles(ep);
                                          else {
                                            try {
                                              const t = await api(
                                                '/text?' + query({ ...targetArgs(), path: ep }),
                                              );
                                              setTextEdit({ path: ep, ...t });
                                            } catch (err) {
                                              setError(String(err));
                                            }
                                          }
                                        }}
                                      >
                                        {e.directory ? (
                                          <Folder size={18} />
                                        ) : (
                                          <FileText size={18} />
                                        )}
                                        <strong>{e.name}</strong>
                                        {e.symlink && (
                                          <span className="badge amber">{t('符号链接')}</span>
                                        )}
                                      </button>
                                    </td>
                                    <td>{e.directory ? t('目录') : fmt(e.size)}</td>
                                    <td>{date(e.modified)}</td>
                                    <td>
                                      <div className="row-actions">
                                        {!e.directory && (
                                          <button
                                            title={t('下载')}
                                            disabled={e.symlink}
                                            onClick={() =>
                                              launch(
                                                t('导出文件'),
                                                { ...targetArgs(), op: 'file_export', path: ep },
                                                false,
                                              )
                                            }
                                          >
                                            <Download size={15} />
                                          </button>
                                        )}
                                        <button
                                          title={t('重命名')}
                                          disabled={!disk.writable || !fileEditing || e.symlink}
                                          onClick={() =>
                                            fileAction(
                                              t('重命名文件'),
                                              { action: 'rename', path: ep },
                                              [
                                                {
                                                  key: 'destination',
                                                  label: t('新路径'),
                                                  value: ep,
                                                },
                                              ],
                                            )
                                          }
                                        >
                                          <Pencil size={15} />
                                        </button>
                                        <button
                                          title={t('删除')}
                                          className="danger-icon"
                                          disabled={!disk.writable || !fileEditing || e.symlink}
                                          onClick={() =>
                                            fileAction(t('删除文件或目录'), {
                                              action: 'delete',
                                              path: ep,
                                            })
                                          }
                                        >
                                          <Trash2 size={15} />
                                        </button>
                                      </div>
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                          {!entries.length && (
                            <Empty
                              icon={Folder}
                              title={t('目录为空')}
                              text={t('文件上传后会出现在这里。')}
                            />
                          )}
                        </div>
                      )}
                    </>
                  )}
                </section>
              )}
              {page === 'hex' && disk && (
                <section className="panel">
                  {regionSelector}
                  <PanelHead
                    icon={Binary}
                    title={t('原始字节编辑器')}
                    action={<span className="badge">{t('每页 256 B · 按需加载 64 KiB')}</span>}
                  />
                  <div className="info-strip">
                    {t('区域总容量：')}
                    {fmt(region!.size)} = {region!.size.toLocaleString(locale)}
                    {t('字节。1 KiB = 1024 B；1 MiB = 1024 KiB；1 GiB = 1024 MiB。')}
                  </div>
                  <div className="info-strip">
                    {region?.region === 'partition'
                      ? t(
                          '分区起点：{0} B；区域内偏移：{1} B；用户区绝对偏移：{2} B。分区内的 0 对应分区起点。',
                          [
                            ((region.start || 0) * 512).toLocaleString(locale),
                            Number(offset).toLocaleString(locale),
                            ((region.start || 0) * 512 + Number(offset)).toLocaleString(locale),
                          ],
                        )
                      : region?.region.startsWith('boot')
                        ? t('BOOT 区使用独立地址空间，偏移 0 就是该 BOOT 区起点。')
                        : t('当前偏移以用户区起点为基准。')}
                  </div>
                  <div className="hex-toolbar">
                    <ByteInput
                      label={t('区域内读取偏移')}
                      value={Number(offset)}
                      onChange={(n) => setOffset(String(n))}
                      max={region!.size - 1}
                    />
                    <ByteInput
                      label={t('读取长度')}
                      value={Number(hexLength)}
                      onChange={(n) => setHexLength(String(n))}
                      initialUnit="KiB"
                      min={1}
                      max={Math.max(1, region!.size - Number(offset))}
                    />
                    <button
                      className="button secondary"
                      onClick={() => {
                        setOffset('0');
                        setHexLength(String(region!.size));
                      }}
                    >
                      {t('整个区域（')}
                      {fmt(region!.size)}
                      {t('）')}
                    </button>
                    <button
                      className="button"
                      disabled={
                        loading ||
                        !Number.isSafeInteger(Number(offset)) ||
                        Number(offset) < 0 ||
                        !Number.isSafeInteger(Number(hexLength)) ||
                        Number(hexLength) < 1 ||
                        Number(offset) + Number(hexLength) > region!.size
                      }
                      onClick={() => hexLoad()}
                    >
                      <Search size={16} />
                      {t('读取')}
                    </button>
                    {hex && (
                      <>
                        <button
                          className="button secondary"
                          onClick={() =>
                            open(
                              t('导出原始范围'),
                              {
                                ...targetArgs(),
                                op: 'range_export',
                                offset: hexRange?.start ?? hex.offset,
                              },
                              [
                                {
                                  key: 'length',
                                  label: t('导出长度'),
                                  type: 'bytes',
                                  value: hexRange?.length ?? hex.length,
                                  max: region!.size - (hexRange?.start ?? hex.offset),
                                },
                              ],
                              false,
                            )
                          }
                        >
                          <Download size={15} />
                          {t('导出范围')}
                        </button>
                      </>
                    )}
                  </div>
                  {!hex ? (
                    <Empty
                      icon={Binary}
                      title={t('从一个偏移开始')}
                      text={t('读取后可查看十六进制字节、ASCII 和编辑前校验值。')}
                    />
                  ) : (
                    <>
                      <div className="info-strip">
                        {t('选定读取范围：')}
                        {hexRange?.start.toLocaleString()}
                        {t('字节起，共')} {fmt(hexRange?.length || hex.length)}
                        {t('；当前已读取')}
                        {fmt(hex.length)}
                        {t('，加载块')}{' '}
                        {hexRange ? Math.floor((hex.offset - hexRange.start) / 65536) + 1 : 1} /{' '}
                        {Math.ceil((hexRange?.length || hex.length) / 65536)}
                        {t('。大范围按需读取，单次修改仍最多 64 KiB。')}
                      </div>
                      <HexGrid
                        rangeStart={hexRange?.start ?? hex.offset}
                        rangeLength={hexRange?.length ?? hex.length}
                        loading={loading}
                        onRead={(n) => hexLoad(n)}
                        original={hex.hex}
                        value={hexValue}
                        offset={hex.offset}
                        onChange={setHexValue}
                        writable={disk.writable}
                      />
                      <div className="editor-footer">
                        <span className="mono small-text">
                          {t('原始 SHA-256：')}
                          {hex.sha256}
                        </span>
                        <button
                          className="button"
                          disabled={!disk.writable || hexValue.replace(/\s/g, '') === hex.hex}
                          onClick={() =>
                            launch(
                              t('保存原始字节'),
                              {
                                ...targetArgs(),
                                op: 'hex_write',
                                offset: hex.offset,
                                hex: hexValue.replace(/\s/g, ''),
                                expected_sha256: hex.sha256,
                              },
                              true,
                              t('修改前会保存原始字节快照，完成后自动读回校验。'),
                            )
                          }
                        >
                          <Check size={16} />
                          {t('核对并保存')}
                        </button>
                      </div>
                    </>
                  )}
                </section>
              )}
              {page === 'transfer' && disk && (
                <>
                  {regionSelector}
                  <div className="two-columns">
                    <section className="panel">
                      <PanelHead icon={ArrowLeftRight} title={t('设备克隆')} />
                      <p className="panel-description">
                        {t('逐字节复制另一块磁盘或分区，并读回验证。')}
                      </p>
                      <label className="field">
                        {t('源设备')}
                        <select value={source} onChange={(e) => setSource(e.target.value)}>
                          <option value="">{t('选择源设备')}</option>
                          {allRegions
                            .filter(
                              (r) => r.disk.path !== disk.path && !r.region.startsWith('boot'),
                            )
                            .map((r) => (
                              <option key={r.path} value={r.path}>
                                {r.name} · {names[r.disk.kind]} · {fmt(r.size)}
                              </option>
                            ))}
                        </select>
                      </label>
                      <div className="transfer-flow">
                        <div>
                          <HardDrive size={26} />
                          <strong>{source || t('未选择来源')}</strong>
                          <small>{t('源设备')}</small>
                        </div>
                        <ArrowLeftRight size={23} />
                        <div>
                          <Cpu size={28} />
                          <strong>{region?.name}</strong>
                          <small>
                            {t('目标 ·')}
                            {fmt(region?.size || 0)}
                          </small>
                        </div>
                      </div>
                      <button
                        className="button full"
                        disabled={!disk.writable || !source || region?.region.startsWith('boot')}
                        onClick={() => {
                          const s = allRegions.find((r) => r.path === source)!;
                          launch(
                            t('克隆设备'),
                            {
                              ...targetArgs(),
                              op: 'clone',
                              source: s.path,
                              source_identity: s.disk.identity,
                            },
                            true,
                            t(
                              '目标现有数据将被覆盖。源容量不得超过目标；整盘对应整盘，分区对应分区。',
                            ),
                          );
                        }}
                      >
                        {t('核对克隆目标')}
                        <ArrowUpRight size={16} />
                      </button>
                      <div className="info-strip">{t('BOOT 区请使用单独镜像或完整备份恢复。')}</div>
                    </section>
                    <section className="panel">
                      <PanelHead icon={Download} title={t('镜像恢复')} />
                      <div className="segmented">
                        <button
                          className={restoreType === 'upload' ? 'active' : ''}
                          onClick={() => setRestoreType('upload')}
                        >
                          {t('电脑上传')}
                        </button>
                        <button
                          className={restoreType === 'usb' ? 'active' : ''}
                          onClick={() => setRestoreType('usb')}
                        >
                          {t('U 盘镜像')}
                        </button>
                        <button
                          className={restoreType === 'backup' ? 'active' : ''}
                          onClick={() => setRestoreType('backup')}
                        >
                          {t('已有备份')}
                        </button>
                      </div>
                      {restoreType === 'upload' ? (
                        <>
                          <label className="upload-drop">
                            <Upload size={26} />
                            <strong>{uploadInfo?.name || t('选择镜像文件')}</strong>
                            <small>
                              {uploadInfo
                                ? fmt(uploadInfo.size) + t(' · 上传完成')
                                : t('原始 IMG / BIN 或 gzip 镜像')}
                            </small>
                            <input
                              type="file"
                              hidden
                              onChange={async (e) => {
                                if (e.target.files?.[0])
                                  try {
                                    await upload(e.target.files[0]);
                                  } catch {}
                                e.target.value = '';
                              }}
                            />
                          </label>
                          {uploadInfo && (
                            <small className="mono helper">SHA-256：{uploadInfo.sha256}</small>
                          )}
                        </>
                      ) : restoreType === 'usb' ? (
                        <>
                          <label className="field">
                            {t('U 盘分区')}
                            <select
                              value={usbPartition}
                              onChange={(e) => setUsbPartition(e.target.value)}
                            >
                              <option value="">{t('选择 USB 分区')}</option>
                              {usbRegions.map((r) => (
                                <option key={r.path} value={r.path}>
                                  {r.name} · {fmt(r.size)}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="field">
                            {t('镜像相对路径')}
                            <input
                              value={imagePath}
                              onChange={(e) => setImagePath(e.target.value)}
                              placeholder="images/system.img"
                            />
                          </label>
                          {!usbRegions.length && (
                            <div className="info-strip">
                              {t('当前没有 USB 存储，插入后会自动发现。')}
                            </div>
                          )}
                        </>
                      ) : (
                        <>
                          <p className="panel-description">
                            {t('在备份库中选择区域镜像或完整备份进行恢复。')}
                          </p>
                          <button
                            className="button secondary full"
                            onClick={() => setPage('backups')}
                          >
                            {t('打开备份库')}
                            <ChevronRight size={16} />
                          </button>
                        </>
                      )}
                      {restoreType !== 'backup' && (
                        <>
                          <label className="checkbox">
                            <input
                              type="checkbox"
                              checked={imageGzip}
                              onChange={(e) => setImageGzip(e.target.checked)}
                            />
                            {t('镜像使用 gzip 压缩')}
                          </label>
                          {imageGzip && (
                            <label className="field">
                              {t('解压后大小（字节）')}
                              <input
                                type="number"
                                value={imageSize}
                                onChange={(e) => setImageSize(e.target.value)}
                              />
                              <small>{t('写入前会验证完整解压长度。')}</small>
                            </label>
                          )}
                          <button
                            className="button full"
                            disabled={
                              !disk.writable ||
                              (restoreType === 'upload' ? !uploadInfo : !usbPartition || !imagePath)
                            }
                            onClick={() => {
                              const s = usbRegions.find((r) => r.path === usbPartition);
                              launch(
                                t('恢复镜像'),
                                {
                                  ...targetArgs(),
                                  op: 'restore',
                                  ...(restoreType === 'usb'
                                    ? {
                                        image_source: 'usb',
                                        image_partition: s!.path,
                                        image_identity: s!.disk.identity,
                                        image_path: imagePath,
                                      }
                                    : { upload: uploadInfo.id }),
                                  gzip: imageGzip,
                                  image_size: Number(imageSize),
                                },
                                true,
                                t('镜像数据将覆盖所选区域，完成后进行读回校验。'),
                              );
                            }}
                          >
                            {t('核对恢复目标')}
                            <ArrowUpRight size={16} />
                          </button>
                        </>
                      )}
                    </section>
                  </div>
                </>
              )}
              {page === 'backups' && (
                <>
                  <div className="two-columns">
                    <section className="panel">
                      <PanelHead icon={Archive} title={t('创建备份')} />
                      {disk ? (
                        <>
                          {' '}
                          {regionSelector}
                          <label className="checkbox">
                            <input
                              type="checkbox"
                              checked={
                                backupFull && disk.kind === 'emmc' && region?.region === 'user'
                              }
                              onChange={(e) => setBackupFull(e.target.checked)}
                              disabled={disk.kind !== 'emmc' || region?.region !== 'user'}
                            />
                            {t('完整备份：用户区 + BOOT0 + BOOT1')}
                          </label>
                          <label className="checkbox">
                            <input
                              type="checkbox"
                              checked={backupCompressed}
                              onChange={(e) => setBackupCompressed(e.target.checked)}
                            />
                            {t('gzip 压缩，节省存储空间')}
                          </label>
                          <label className="field">
                            {t('保存位置')}
                            <select
                              value={backupStorage}
                              onChange={(e) => setBackupStorage(e.target.value)}
                            >
                              <option value="local">
                                {t('设备 SD 卡 · 剩余')}
                                {fmt(free)}
                              </option>
                              <option value="usb">{t('USB 存储分区')}</option>
                              <option value="browser">
                                {t('下载到电脑（直接流式，不占 SD 卡）')}
                              </option>
                            </select>
                          </label>
                          {backupStorage === 'usb' && (
                            <label className="field">
                              {t('USB 分区')}
                              <select
                                value={backupUsb}
                                onChange={(e) => setBackupUsb(e.target.value)}
                              >
                                <option value="">{t('选择 USB 分区')}</option>
                                {usbRegions.map((r) => (
                                  <option value={r.path} key={r.path}>
                                    {r.name} · {fmt(r.size)}
                                  </option>
                                ))}
                              </select>
                            </label>
                          )}
                          <button
                            className="button full"
                            disabled={
                              !disk || disk.protected || (backupStorage === 'usb' && !backupUsb)
                            }
                            onClick={() => {
                              const s = usbRegions.find((r) => r.path === backupUsb);
                              launch(
                                t('创建磁盘备份'),
                                {
                                  ...targetArgs(),
                                  op: 'backup',
                                  full:
                                    backupFull && disk.kind === 'emmc' && region?.region === 'user',
                                  gzip: backupCompressed,
                                  storage: backupStorage,
                                  ...(s
                                    ? { storage_target: s.path, storage_identity: s.disk.identity }
                                    : {}),
                                },
                                false,
                              );
                            }}
                          >
                            <Archive size={16} />
                            {t('开始备份')}
                          </button>
                        </>
                      ) : (
                        <Empty
                          icon={HardDrive}
                          title={t('未选择磁盘')}
                          text={t('连接设备后创建备份。')}
                        />
                      )}
                    </section>
                    <section className="backup-intro">
                      <div className="backup-graphic">
                        <Archive size={48} />
                        <ShieldCheck size={26} />
                      </div>
                      <h2>{t('为每个区域保存一份副本')}</h2>
                      <p>
                        {t(
                          '完整备份包含原始镜像、分区表、设备信息与 SHA-256 校验清单。下载到电脑后，可随时重新导入恢复。',
                        )}
                      </p>
                      <div>
                        <CheckCircle2 size={16} />
                        {t('流式读取，低内存占用')}
                      </div>
                      <div>
                        <CheckCircle2 size={16} />
                        {t('恢复前核对，恢复后读回校验')}
                      </div>
                      <label className="button secondary">
                        <Upload size={16} />
                        {t('导入完整备份包')}
                        <input
                          type="file"
                          accept=".tar,.tar.gz,.tgz"
                          hidden
                          onChange={async (e) => {
                            const f = e.target.files?.[0];
                            if (f)
                              try {
                                const u = await upload(f);
                                launch(
                                  t('导入备份包'),
                                  { op: 'import_backup', upload: u.id },
                                  false,
                                );
                              } catch {}
                            e.target.value = '';
                          }}
                        />
                      </label>
                    </section>
                  </div>
                  <section className="panel">
                    <PanelHead
                      icon={Archive}
                      title={t('备份库')}
                      action={
                        <span className="badge">
                          {backups.length}
                          {t('份备份')}
                        </span>
                      }
                    />
                    {!backups.length ? (
                      <Empty
                        icon={Archive}
                        title={t('还没有备份')}
                        text={t('创建第一份备份后，镜像和校验信息会保存在这里。')}
                      />
                    ) : (
                      <div className="backup-list">
                        {backups.map((b) => (
                          <div className="backup-item" key={b.id}>
                            <div className="backup-item-top">
                              <div className="region-icon">
                                <Archive size={22} />
                              </div>
                              <div>
                                <strong>
                                  {b.full ? t('完整 eMMC 备份') : t('区域备份')} · {b.model}
                                </strong>
                                <small>
                                  {date(b.created)} ·{' '}
                                  {b.storage === 'usb'
                                    ? t('USB 存储')
                                    : b.storage === 'browser'
                                      ? t('旧版浏览器备份 · SD 暂存')
                                      : t('本地 SD 卡')}
                                </small>
                              </div>
                              <span className="badge teal">
                                {b.regions.length}
                                {t('个区域')}
                              </span>
                              <button
                                title={t('下载备份包')}
                                className="icon-button"
                                onClick={() =>
                                  launch(
                                    t('导出备份包'),
                                    { op: 'backup_export', backup: b.id },
                                    false,
                                  )
                                }
                              >
                                <Download size={17} />
                              </button>
                              <button
                                className="icon-button danger-icon"
                                title={t('删除备份')}
                                onClick={async () => {
                                  const answer = window.prompt(
                                    t('输入备份标识确认删除：\n') + b.id,
                                  );
                                  if (answer !== b.id) return;
                                  try {
                                    await post('/backups/' + b.id + '/delete', { confirm: answer });
                                    refreshBackups();
                                  } catch (e) {
                                    setError(String(e));
                                  }
                                }}
                              >
                                <Trash2 size={17} />
                              </button>
                            </div>
                            <div className="backup-regions">
                              {b.regions.map((r: any) => (
                                <div key={r.region}>
                                  <span>
                                    <b>{names[r.region] || r.name}</b>
                                    <small>
                                      {fmt(r.size)} · {r.compressed ? 'gzip' : t('原始镜像')}
                                    </small>
                                  </span>
                                  <button
                                    className="button secondary small"
                                    disabled={!disk?.writable || region?.region !== r.region}
                                    onClick={() =>
                                      launch(
                                        t('恢复区域备份'),
                                        {
                                          ...targetArgs(),
                                          op: 'restore',
                                          backup: b.id,
                                          backup_region: r.region,
                                        },
                                        true,
                                        t('将备份区域恢复到当前选定区域：') + region?.path,
                                      )
                                    }
                                  >
                                    {t('恢复到选定区域')}
                                  </button>
                                </div>
                              ))}
                            </div>
                            {b.full && (
                              <button
                                disabled={!disk?.writable || disk.kind !== 'emmc'}
                                className="button secondary small"
                                onClick={() =>
                                  launch(
                                    t('恢复完整 eMMC 备份'),
                                    {
                                      ...targetArgs(disk!.regions[0]),
                                      op: 'restore_full',
                                      backup: b.id,
                                    },
                                    true,
                                    t(
                                      '恢复用户区及两个 BOOT 区，覆盖目标的现有内容；不自动修改 EXT_CSD 启动配置。',
                                    ),
                                  )
                                }
                              >
                                {t('恢复整套备份')}
                                <ArrowUpRight size={14} />
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </section>
                  <section className="panel">
                    <PanelHead icon={ShieldCheck} title={t('操作前快照')} />
                    {snapshots.length ? (
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>{t('类型 / 时间')}</th>
                              <th>{t('目标 / 范围')}</th>
                              <th>{t('操作')}</th>
                            </tr>
                          </thead>
                          <tbody>
                            {snapshots.map((s) => (
                              <tr key={s.id}>
                                <td>
                                  {s.kind === 'hex' ? t('字节修改') : t('分区表')}
                                  <small>{date(s.created)}</small>
                                </td>
                                <td className="mono">
                                  {s.target || s.disk}
                                  <small>
                                    {s.kind === 'hex'
                                      ? t('偏移 {0} · {1}', [s.offset, fmt(s.size)])
                                      : fmt(s.size)}
                                  </small>
                                </td>
                                <td>
                                  <button
                                    className="button secondary small"
                                    disabled={!disk?.writable || disk.identity !== s.disk}
                                    onClick={() =>
                                      launch(
                                        t('恢复操作前快照'),
                                        {
                                          ...targetArgs(
                                            s.kind === 'hex'
                                              ? disk!.regions.find((r) => r.path === s.target)!
                                              : disk!.regions[0],
                                          ),
                                          op: s.kind === 'hex' ? 'undo_hex' : 'restore_table',
                                          snapshot: s.id,
                                        },
                                        true,
                                        t(
                                          '恢复保存的原始字节或分区表。字节回退会核对当前内容，分区表回退不会回退文件系统大小。',
                                        ),
                                      )
                                    }
                                  >
                                    {t('恢复快照')}
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="empty-note">
                        {t('修改分区表或原始字节前，系统会自动保存快照。')}
                      </p>
                    )}
                  </section>
                </>
              )}
              {page === 'jobs' && (
                <section className="panel">
                  <PanelHead
                    icon={Activity}
                    title={t('任务历史')}
                    action={
                      <div className="button-group">
                        <span className="badge">
                          {activeJobs.length}
                          {t('个任务进行中')}
                        </span>
                        <CacheCleaner
                          mode="jobs"
                          api={api}
                          post={post}
                          onChanged={() => api('/jobs').then((d) => setJobs(d.jobs))}
                        />
                      </div>
                    }
                  />
                  {jobs.length ? (
                    jobs.map((j) => (
                      <div key={j.id} className="job-detail">
                        <JobRow job={j} />
                        <div className="job-footer">
                          <span>
                            {j.target || t('备份文件')} · {date(j.created)}
                          </span>
                          <div>
                            {j.result?.download && j.state === 'completed' && (
                              <a
                                className="button secondary small"
                                href={'/api/v1/downloads/' + j.result.download}
                                download
                              >
                                <Download size={14} />
                                {t('下载结果')}
                              </a>
                            )}
                            {j.result?.stream &&
                              j.state !== 'cancelled' &&
                              j.state !== 'interrupted' && (
                                <a
                                  className="button secondary small"
                                  href={'/api/v1/streams/' + j.result.stream}
                                  download
                                >
                                  <Download size={14} />
                                  {t('流式下载')}
                                </a>
                              )}
                            {['queued', 'running'].includes(j.state) && j.cancellable && (
                              <button
                                className="button secondary small"
                                onClick={async () => {
                                  try {
                                    await post('/jobs/' + j.id + '/cancel', {});
                                  } catch (e) {
                                    setError(String(e));
                                  }
                                }}
                              >
                                <Square size={12} />
                                {t('取消任务')}
                              </button>
                            )}
                          </div>
                        </div>
                        {!!j.logs?.length && (
                          <details>
                            <summary>{t('任务日志')}</summary>
                            <pre>
                              {j.logs
                                .map((l) => date(l.time) + '  ' + serverText(l.message))
                                .join('\n')}
                            </pre>
                          </details>
                        )}
                        {j.result && (
                          <details>
                            <summary>{t('结果详情')}</summary>
                            <pre>{JSON.stringify(j.result, null, 2)}</pre>
                          </details>
                        )}
                      </div>
                    ))
                  ) : (
                    <Empty
                      icon={Activity}
                      title={t('还没有任务')}
                      text={t('备份、编辑、克隆和恢复操作会记录在这里。')}
                    />
                  )}
                </section>
              )}
              {page === 'cache' && (
                <CacheCleaner
                  api={api}
                  post={post}
                  onChanged={() => {
                    api('/jobs').then((d) => setJobs(d.jobs));
                    refreshBackups();
                    refresh();
                  }}
                />
              )}
              {page === 'upgrade' && <UpgradePage api={api} post={post} />}
              {page === 'settings' && (
                <>
                  <div className="two-columns">
                    <section className="panel">
                      <PanelHead icon={Lock} title={t('管理员密码')} />
                      <label className="field">
                        {t('用户名')}
                        <input value={auth.username} readOnly />
                      </label>
                      <label className="field">
                        {t('当前密码')}
                        <input
                          type="password"
                          autoComplete="current-password"
                          value={oldPassword}
                          onChange={(e) => setOldPassword(e.target.value)}
                        />
                      </label>
                      <label className="field">
                        {t('新密码')}
                        <input
                          type="password"
                          autoComplete="new-password"
                          minLength={8}
                          maxLength={128}
                          value={newPassword}
                          onChange={(e) => setNewPassword(e.target.value)}
                          placeholder={t('8–128 个字符')}
                        />
                      </label>
                      <div className="info-strip">
                        {t('密码长度 8–128 个字符，使用随机盐 + scrypt 单向哈希保存，不保存明文。')}
                      </div>
                      <button
                        className="button"
                        disabled={
                          !oldPassword ||
                          Array.from(newPassword).length < 8 ||
                          Array.from(newPassword).length > 128
                        }
                        onClick={async () => {
                          try {
                            await post('/auth/password', {
                              old: oldPassword,
                              password: newPassword,
                            });
                            setOldPassword('');
                            setNewPassword('');
                            setNotice(t('密码已更新，其他登录会话已失效'));
                          } catch (e) {
                            setError(String(e));
                          }
                        }}
                      >
                        {t('更新密码')}
                      </button>
                    </section>
                    <section className="panel">
                      <PanelHead icon={Settings} title={t('工作台信息')} />
                      <dl className="details-grid single">
                        <Detail label={t('版本')} value={settings?.version || t('读取中…')} />
                        <Detail label={t('访问端口')} value="HTTP · 80" />
                        <Detail label={t('运行位置')} value={t('NanoPi R28S · 本地设备')} />
                        <Detail label={t('可用暂存空间')} value={fmt(settings?.free || free)} />
                        <Detail label={t('登录会话')} value={t('最长 8 小时')} />
                        <Detail label={t('任务管理')} value={t('后台执行 · 重启后不自动续写')} />
                      </dl>
                      <div className="info-strip">
                        {t('BOOT 写保护仅按操作临时解除；RPMB 与永久保护配置不开放写入。')}
                      </div>
                    </section>
                  </div>
                  <section className="panel">
                    <PanelHead icon={Archive} title={t('缓存与历史管理')} />
                    <p className="empty-note">
                      {t('在独立清理页面选择任务记录、操作快照、导出文件和上传暂存。')}
                    </p>
                    <button className="button secondary" onClick={() => setPage('cache')}>
                      <Trash2 size={15} />
                      {t('打开缓存清理')}
                    </button>
                  </section>
                </>
              )}
            </>
          )}
          <footer>
            <span>
              <ShieldCheck size={13} />
              {t('系统 SD 卡已保护')}
            </span>
            <span>{t('eMMC Studio · 所有数据留在设备上')}</span>
          </footer>
        </div>
      </main>
      {uploadProgress !== null && (
        <div className="upload-progress">
          <Loader2 size={17} className="spin" />
          {t('文件上传')}
          <strong>{uploadProgress.toFixed(1)}%</strong>
          <div className="progress">
            <i style={{ width: uploadProgress + '%' }} />
          </div>
        </div>
      )}
      {dialog && (
        <div className="modal-backdrop" role="presentation">
          <section className="modal" role="dialog" aria-modal="true" aria-label={dialog.title}>
            <div className="modal-title">
              <span className={'region-icon ' + (dialog.danger ? 'warning' : '')}>
                {dialog.danger ? <AlertTriangle size={22} /> : <Archive size={22} />}
              </span>
              <h2>{dialog.title}</h2>
              <button className="icon-button" onClick={() => setDialog(null)}>
                <X size={20} />
              </button>
            </div>
            {dialog.args.target && (
              <div className="target-summary">
                <small>{t('操作目标')}</small>
                <strong>{dialog.args.target}</strong>
                <span>
                  {disk?.model} ·{' '}
                  {fmt(allRegions.find((r) => r.path === dialog.args.target)?.size || 0)}
                </span>
              </div>
            )}
            {dialog.note && <p className="modal-note">{dialog.note}</p>}
            {dialog.args.op === 'range_export' && (
              <div className="range-presets">
                <span>{t('选择导出范围')}</span>
                <button
                  className="button secondary small"
                  onClick={() =>
                    setDialog({
                      ...dialog,
                      args: { ...dialog.args, offset: 0 },
                      fields: dialog.fields.map((f) =>
                        f.key === 'length' ? { ...f, value: region!.size, max: region!.size } : f,
                      ),
                    })
                  }
                >
                  {t('整个区域（')}
                  {fmt(region!.size)}
                  {t('）')}
                </button>
                <button
                  className="button secondary small"
                  onClick={() =>
                    setDialog({
                      ...dialog,
                      args: { ...dialog.args, offset: hex.offset },
                      fields: dialog.fields.map((f) =>
                        f.key === 'length'
                          ? {
                              ...f,
                              value: region!.size - hex.offset,
                              max: region!.size - hex.offset,
                            }
                          : f,
                      ),
                    })
                  }
                >
                  {t('从当前偏移到末尾')}
                </button>
                <small>
                  {t('起点')}
                  {dialog.args.offset.toLocaleString(locale)}
                  {t('字节 · 直接流式传输，可导出整个区域；关闭下载会中断传输。')}
                </small>
              </div>
            )}
            {dialog.args.op === 'resize' && disk && (
              <ResizeView
                disk={disk}
                region={allRegions.find((r) => r.path === dialog.args.target)!}
                value={Number(dialog.fields[0].value)}
                onChange={(n) =>
                  setDialog({
                    ...dialog,
                    fields: dialog.fields.map((f) => (f.key === 'size' ? { ...f, value: n } : f)),
                  })
                }
              />
            )}{' '}
            {dialog.fields.map((f, i) =>
              ['bytes', 'sectorbytes'].includes(f.type || '') ? (
                <ByteInput
                  key={f.key}
                  label={f.label}
                  value={Number(f.value)}
                  initialUnit="MiB"
                  min={f.type === 'sectorbytes' ? 1048576 : 1}
                  alignment={f.type === 'sectorbytes' ? 1048576 : 1}
                  max={f.max}
                  onChange={(n) =>
                    setDialog({
                      ...dialog,
                      fields: dialog.fields.map((x, j) => (j === i ? { ...x, value: n } : x)),
                    })
                  }
                />
              ) : f.type === 'label' ? (
                <VolumeLabel
                  key={f.key}
                  label={f.label}
                  value={f.value}
                  onChange={(v) =>
                    setDialog({
                      ...dialog,
                      fields: dialog.fields.map((x, j) => (j === i ? { ...x, value: v } : x)),
                    })
                  }
                />
              ) : (
                <label className={f.type === 'checkbox' ? 'checkbox' : 'field'} key={f.key}>
                  {f.type === 'checkbox' ? (
                    <>
                      <input
                        type="checkbox"
                        checked={f.value}
                        onChange={(e) =>
                          setDialog({
                            ...dialog,
                            fields: dialog.fields.map((x, j) =>
                              j === i ? { ...x, value: e.target.checked } : x,
                            ),
                          })
                        }
                      />
                      {f.label}
                    </>
                  ) : (
                    <>
                      {f.label}
                      {f.type === 'select' ? (
                        <select
                          value={f.value}
                          onChange={(e) =>
                            setDialog({
                              ...dialog,
                              fields: dialog.fields.map((x, j) =>
                                j === i ? { ...x, value: e.target.value } : x,
                              ),
                            })
                          }
                        >
                          {f.options?.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={f.type || 'text'}
                          value={f.value}
                          onChange={(e) =>
                            setDialog({
                              ...dialog,
                              fields: dialog.fields.map((x, j) =>
                                j === i ? { ...x, value: e.target.value } : x,
                              ),
                            })
                          }
                        />
                      )}
                    </>
                  )}
                  {f.help && <small>{f.help}</small>}
                </label>
              ),
            )}
            {dialog.args.op === 'hex_write' && (
              <div className="hex-diff">
                <div>
                  <small>{t('修改前')}</small>
                  <code>{hex?.hex?.slice(0, 256)}</code>
                </div>
                <div>
                  <small>{t('修改后')}</small>
                  <code>{dialog.args.hex.slice(0, 256)}</code>
                </div>
                <small>
                  {t('预览前 128 字节，写入总长度')}
                  {dialog.args.hex.length / 2}
                  {t('字节。')}
                </small>
              </div>
            )}
            <div className="modal-buttons">
              <button className="button secondary" onClick={() => setDialog(null)}>
                {t('取消')}
              </button>
              <button
                className={'button ' + (dialog.danger ? 'danger' : '')}
                disabled={
                  loading ||
                  dialog.fields.some(
                    (f) =>
                      ['bytes', 'sectorbytes'].includes(f.type || '') &&
                      (!Number.isSafeInteger(Number(f.value)) ||
                        Number(f.value) < (f.type === 'sectorbytes' ? 1048576 : 1) ||
                        Number(f.value) > (f.max || Number.MAX_SAFE_INTEGER) ||
                        (f.type === 'sectorbytes' && Number(f.value) % 1048576 !== 0)),
                  )
                }
                onClick={submit}
              >
                {loading ? <Loader2 size={16} className="spin" /> : <Check size={16} />}
                {t('确认并提交')}
              </button>
            </div>
          </section>
        </div>
      )}
      {textEdit && (
        <div className="modal-backdrop">
          <section className="modal text-modal">
            <div className="modal-title">
              <FileText size={21} />
              <h2>{textEdit.path}</h2>
              <button className="icon-button" onClick={() => setTextEdit(null)}>
                <X size={20} />
              </button>
            </div>
            <textarea
              className="text-editor"
              readOnly={!fileEditing}
              value={textEdit.text}
              onChange={(e) => setTextEdit({ ...textEdit, text: e.target.value })}
              spellCheck={false}
            />
            <div className="modal-buttons">
              <span className="helper">{t('UTF-8 · 最多 2 MiB')}</span>
              <button
                className="button"
                disabled={!disk?.writable || !fileEditing}
                onClick={() => {
                  fileAction(t('保存文本文件'), {
                    action: 'text',
                    path: textEdit.path,
                    text: textEdit.text,
                    overwrite: true,
                    expected_sha256: textEdit.sha256,
                  });
                  setTextEdit(null);
                }}
              >
                {t('核对并保存')}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function Login({
  configured,
  username,
  onLogin,
}: {
  configured: boolean;
  username: string;
  onLogin: (a: any) => void;
}) {
  const [password, setPassword] = useState(''),
    [code, setCode] = useState(''),
    [repeat, setRepeat] = useState(''),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      if (!configured && password !== repeat) throw new Error(t('两次输入的密码不一致'));
      const a = await post(
        configured ? '/auth/login' : '/auth/setup',
        configured ? { username, password } : { code, password },
      );
      onLogin(a);
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''));
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="login-screen">
      <div className="login-art">
        <div className="brand">
          <span className="brand-icon">
            <Cpu size={28} />
          </span>
          <span>
            eMMC <b>Studio</b>
          </span>
        </div>
        <div className="login-message">
          <span className="eyebrow">YOUR STORAGE. YOUR CONTROL.</span>
          <h1>
            {t('每一个字节，')}
            <br />
            {t('都在掌握之中。')}
          </h1>
          <p>
            {t('从分区管理到完整备份，')}
            <br />
            {t('为你的 eMMC 提供一个清晰的工作空间。')}
          </p>
          <div className="login-chip">
            <Cpu size={110} />
            <span>eMMC</span>
          </div>
        </div>
        <div className="login-foot">
          <ShieldCheck size={16} />
          {t('本地运行，数据留在设备上。')}
        </div>
      </div>
      <div className="login-form">
        <LanguageSelector dirty={!!password || !!code} />
        <span className="badge teal">
          <Lock size={13} />
          {t('设备管理')}
        </span>
        <h2>{configured ? t('欢迎回来') : t('初始化工作台')}</h2>
        <p>
          {configured
            ? t('登录以查看和管理存储设备。')
            : t('使用串口提供的一次性设置码创建管理员密码。')}
        </p>
        <form onSubmit={submit}>
          {!configured && (
            <label className="field">
              {t('一次性设置码')}
              <input
                autoFocus
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="off"
                required
              />
            </label>
          )}
          <label className="field">
            {t('管理员账号')}
            <input value={username} readOnly autoComplete="username" />
          </label>
          <label className="field">
            {configured ? t('密码') : t('设置密码')}
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={configured ? 'current-password' : 'new-password'}
              minLength={configured ? 1 : 8}
              maxLength={128}
              required
              placeholder={configured ? t('输入管理员密码') : t('8–128 个字符')}
            />
          </label>
          {!configured && (
            <label className="field">
              {t('再次输入密码')}
              <input
                type="password"
                value={repeat}
                onChange={(e) => setRepeat(e.target.value)}
                required
                autoComplete="new-password"
              />
            </label>
          )}
          {error && <div className="alert error">{error}</div>}
          <button className="button full" disabled={loading}>
            {loading ? <Loader2 className="spin" size={18} /> : null}
            {configured ? t('登录工作台') : t('创建管理员并进入')}
            <ArrowUpRight size={17} />
          </button>
        </form>
        <small>{t('eMMC Studio · 局域网存储工作台')}</small>
      </div>
    </div>
  );
}
function ForcePassword({ username, onChanged }: { username: string; onChanged: () => void }) {
  const [old, setOld] = useState(''),
    [password, setPassword] = useState(''),
    [repeat, setRepeat] = useState(''),
    [error, setError] = useState(''),
    [loading, setLoading] = useState(false);
  return (
    <div className="force-password">
      <LanguageSelector dirty={!!password || !!old} />
      <div className="brand">
        <span className="brand-icon">
          <Cpu size={26} />
        </span>
        <span>
          eMMC <b>Studio</b>
        </span>
      </div>
      <section className="panel">
        <span className="badge amber">
          <Lock size={13} />
          {t('首次登录')}
        </span>
        <h2>{t('设置你的专属密码')}</h2>
        <p className="panel-description">
          {t('账号')}
          {username}
          {t('使用初始密码。修改完成后即可进入存储工作台。')}
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setLoading(true);
            try {
              if (password !== repeat) throw new Error(t('两次输入的密码不一致'));
              await post('/auth/password', { old, password });
              onChanged();
            } catch (e) {
              setError(String(e).replace(/^Error: /, ''));
            } finally {
              setLoading(false);
            }
          }}
        >
          <label className="field">
            {t('当前密码')}
            <input
              type="password"
              value={old}
              onChange={(e) => setOld(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <label className="field">
            {t('新密码')}
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              maxLength={128}
              autoComplete="new-password"
              placeholder={t('8–128 个字符')}
              required
            />
          </label>
          <label className="field">
            {t('再次输入新密码')}
            <input
              type="password"
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
              minLength={8}
              autoComplete="new-password"
              required
            />
          </label>
          {error && <div className="alert error">{error}</div>}
          <button className="button full" disabled={loading}>
            {loading ? <Loader2 className="spin" size={16} /> : <Check size={16} />}
            {t('修改密码并进入')}
          </button>
        </form>
        <button
          className="text-button"
          onClick={async () => {
            await post('/auth/logout', {});
            location.reload();
          }}
        >
          {t('退出登录')}
        </button>
      </section>
    </div>
  );
}
function Empty({ icon: Icon, title, text }: { icon: any; title: string; text: string }) {
  return (
    <div className="empty">
      <span>
        <Icon size={30} />
      </span>
      <strong>{title}</strong>
      <p>{text}</p>
    </div>
  );
}
function Stat({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: any;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="stat">
      <div>
        <span>{label}</span>
        <Icon size={19} />
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
function PanelHead({
  icon: Icon,
  title,
  action,
}: {
  icon: any;
  title: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="panel-head">
      <h3>
        <Icon size={19} />
        {title}
      </h3>
      {action}
    </div>
  );
}
function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
function PartitionMap({ disk }: { disk: Disk }) {
  return <RegionMap disk={disk} />;
}
function JobRow({ job: j, compact = false }: { job: Job; compact?: boolean }) {
  return (
    <div className={'job-row ' + (compact ? 'compact' : '')}>
      <div className={'job-icon ' + j.state}>
        {j.state === 'running' ? (
          <Loader2 className="spin" size={20} />
        ) : j.state === 'completed' ? (
          <CheckCircle2 size={20} />
        ) : j.state === 'failed' || j.state === 'interrupted' ? (
          <AlertTriangle size={20} />
        ) : (
          <Activity size={20} />
        )}
      </div>
      <div className="job-main">
        <div className="job-name">
          <strong>{serverText(j.title)}</strong>
          <span
            className={
              'badge ' + (j.state === 'completed' ? 'teal' : j.state === 'failed' ? 'red' : '')
            }
          >
            {states[j.state] || j.state}
          </span>
        </div>
        <small>
          {serverText(j.phase)}
          {j.total > 0 ? ' · ' + fmt(j.bytes) + ' / ' + fmt(j.total) : ''}
          {j.state === 'running' && j.speed > 0 ? ' · ' + fmt(j.speed) + '/s' : ''}
        </small>
        {j.state === 'running' && (
          <div className="progress">
            <i style={{ width: j.progress + '%' }} />
          </div>
        )}
        {j.error && <p className="job-error">{serverText(j.error)}</p>}
      </div>
      <b className="job-percent">
        {j.state === 'running'
          ? j.progress.toFixed(1) + '%'
          : j.state === 'completed'
            ? '100%'
            : ''}
      </b>
    </div>
  );
}
function partIndex(r: Region) {
  return Number(r.name.match(/(\d+)$/)?.[1]);
}
function nextStart(d: Disk) {
  return (
    Math.ceil(
      Math.max(2048, ...(d.table?.partitions || []).map((p: any) => p.start + p.size)) / 2048,
    ) * 2048
  );
}
createRoot(document.getElementById('root')!).render(<App />);
