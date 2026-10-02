import { useEffect, useState } from 'react';
import { Archive, Check, RefreshCw, Trash2, X } from 'lucide-react';
type Item = {
  kind: string;
  id: string;
  name: string;
  created: number;
  target: string;
  size: number;
  state: string;
  locked: boolean;
  reason: string;
  stamp: string;
};
const kinds: Record<string, string> = {
  jobs: '任务记录',
  snapshots: '操作前快照',
  downloads: '导出文件',
  uploads: '上传暂存',
};
const bytes = (n: number) =>
  n >= 1073741824
    ? (n / 1073741824).toFixed(2) + ' GiB'
    : n < 1024
      ? n + ' B'
      : n < 1048576
        ? (n / 1024).toFixed(1) + ' KiB'
        : (n / 1048576).toFixed(2) + ' MiB';
const key = (i: Item) => i.kind + ':' + i.id;
const states: Record<string, string> = {
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
  running: '执行中',
  queued: '等待中',
};
export function CacheCleaner({
  api,
  post,
  onChanged,
  mode = 'all',
}: {
  api: (path: string) => Promise<any>;
  post: (path: string, data: any) => Promise<any>;
  onChanged: () => void;
  mode?: 'all' | 'jobs';
}) {
  const [items, setItems] = useState<Item[]>([]),
    [selected, setSelected] = useState<Set<string>>(new Set()),
    [filter, setFilter] = useState('all'),
    [dialog, setDialog] = useState(false),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [free, setFree] = useState(0);
  const refresh = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await api('/cache');
      const next = data.items.filter((i: Item) => mode === 'all' || i.kind === 'jobs');
      setItems(next);
      setFree(data.free);
      setSelected(
        (prev) => new Set(next.filter((i: Item) => !i.locked && prev.has(key(i))).map(key)),
      );
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''));
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    if (mode === 'all') refresh();
  }, []);
  const visible = items.filter((i) => filter === 'all' || i.kind === filter),
    chosen = items.filter((i) => selected.has(key(i)) && !i.locked),
    size = chosen.reduce((n, i) => n + i.size, 0);
  const toggle = (list: Item[], enabled: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      list
        .filter((i) => !i.locked)
        .forEach((i) => (enabled ? next.add(key(i)) : next.delete(key(i))));
      return next;
    });
  const execute = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await post('/cache/clear', {
        items: chosen.map(({ kind, id, stamp }) => ({ kind, id, stamp })),
      });
      setNotice(
        `已清理 ${result.removed.length} 项，文件释放 ${bytes(result.freed)}。` +
          (result.skipped.length
            ? ` ${result.skipped.length} 项因状态变化保留：${[...new Set(result.skipped.map((s: any) => s.reason))].join('；')}`
            : ''),
      );
      setDialog(false);
      setSelected(new Set());
      await refresh();
      onChanged();
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''));
    } finally {
      setLoading(false);
    }
  };
  const list = (
    <>
      <div className="cleanup-filters">
        <button
          className={'button secondary small ' + (filter === 'all' ? 'active' : '')}
          onClick={() => setFilter('all')}
        >
          全部
        </button>
        {Object.entries(kinds)
          .filter(([k]) => mode === 'all' || k === 'jobs')
          .map(([k, label]) => (
            <button
              className={'button secondary small ' + (filter === k ? 'active' : '')}
              key={k}
              onClick={() => setFilter(k)}
            >
              {label} · {items.filter((i) => i.kind === k).length}
            </button>
          ))}
      </div>
      <div className="cleanup-selection">
        <label className="checkbox">
          <input
            aria-label="全选当前列表"
            type="checkbox"
            checked={
              visible.some((i) => !i.locked) &&
              visible.filter((i) => !i.locked).every((i) => selected.has(key(i)))
            }
            onChange={(e) => toggle(visible, e.target.checked)}
          />
          全选当前列表
        </label>
        <span>
          已选择 {chosen.length} 项 · 文件 {bytes(size)}
        </span>
      </div>
      <div className="table-scroll cleanup-table">
        <table>
          <thead>
            <tr>
              <th>选择 / 类型</th>
              <th>名称 / 时间</th>
              <th>目标 / 标识</th>
              <th>占用 / 状态</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((i) => (
              <tr key={key(i)}>
                <td>
                  <label className="checkbox">
                    <input
                      aria-label={'选择 ' + i.name + ' ' + i.id}
                      disabled={i.locked || loading}
                      type="checkbox"
                      checked={selected.has(key(i))}
                      onChange={(e) => toggle([i], e.target.checked)}
                    />
                    {kinds[i.kind]}
                  </label>
                </td>
                <td>
                  <b>{i.name}</b>
                  <small>
                    {new Date(i.created * 1000).toLocaleString('zh-CN', { hour12: false })}
                  </small>
                </td>
                <td>
                  {i.target || '—'}
                  <small className="mono">{i.id}</small>
                </td>
                <td>
                  {i.kind === 'jobs' ? '历史记录' : bytes(i.size)}
                  <small>{i.locked ? i.reason : states[i.state] || '可清理'}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!visible.length && <p className="empty-note">没有可显示的项目。</p>}
      </div>
    </>
  );
  return (
    <>
      {mode === 'jobs' ? (
        <button
          className="button secondary small"
          onClick={async () => {
            await refresh();
            setDialog(true);
          }}
        >
          {' '}
          <Trash2 size={14} />
          清除任务记录
        </button>
      ) : (
        <>
          <div className="cleanup-summary">
            {Object.entries(kinds).map(([kind, label]) => {
              const rows = items.filter((i) => i.kind === kind);
              return (
                <button key={kind} className="panel cleanup-card" onClick={() => setFilter(kind)}>
                  <Archive size={21} />
                  <span>{label}</span>
                  <b>{rows.length} 项</b>
                  <small>
                    {kind === 'jobs'
                      ? '保留正在运行和等待的任务'
                      : bytes(rows.reduce((n, i) => n + i.size, 0))}
                  </small>
                </button>
              );
            })}
          </div>
          <section className="panel">
            <div className="panel-head">
              <h3>选择清理项目</h3>
              <button className="button secondary small" disabled={loading} onClick={refresh}>
                <RefreshCw size={14} />
                刷新
              </button>
            </div>
            <div className="info-strip">
              清除任务记录仅移除历史及日志；快照删除后无法回退对应操作。正式备份在备份库管理。可用空间{' '}
              {bytes(free)}。
            </div>
            {list}
            <div className="editor-footer">
              <span>上传中的文件和存储任务使用的缓存会被保护。</span>
              <button
                className="button danger"
                disabled={loading || !chosen.length}
                onClick={() => setDialog(true)}
              >
                <Trash2 size={15} />
                清理所选（{chosen.length}）
              </button>
            </div>
          </section>
        </>
      )}
      {notice && <div className="alert success">{notice}</div>}
      {error && <div className="alert error">{error}</div>}
      {dialog && (
        <div className="modal-backdrop">
          <section
            className={'modal ' + (mode === 'jobs' ? 'cleanup-modal' : '')}
            role="dialog"
            aria-modal="true"
            aria-label={mode === 'jobs' ? '清除任务记录' : '确认缓存清理'}
          >
            <div className="modal-title">
              <Trash2 size={22} />
              <h2>{mode === 'jobs' ? '清除任务记录' : '确认缓存清理'}</h2>
              <button
                className="icon-button"
                aria-label="关闭清理窗口"
                disabled={loading}
                onClick={() => setDialog(false)}
              >
                <X size={20} />
              </button>
            </div>
            {mode === 'jobs' ? (
              list
            ) : (
              <div className="cleanup-confirm-list">
                {Object.entries(kinds).map(([kind, label]) => {
                  const n = chosen.filter((i) => i.kind === kind).length;
                  return n ? (
                    <p key={kind}>
                      {label}
                      <b>{n} 项</b>
                    </p>
                  ) : null;
                })}
                <p>
                  文件预计释放<b>{bytes(size)}</b>
                </p>
              </div>
            )}
            <p className="modal-note">
              清理后无法恢复。清除快照会失去相应操作的回退数据；正在运行或等待的任务保留。执行前会再次核对项目状态。
            </p>
            {error && <div className="alert error">{error}</div>}
            <div className="modal-buttons">
              <button
                className="button secondary"
                disabled={loading}
                onClick={() => setDialog(false)}
              >
                取消
              </button>
              <button
                className="button danger"
                disabled={loading || !chosen.length}
                onClick={execute}
              >
                <Check size={16} />
                {loading ? '正在清理…' : `确认清理 ${chosen.length} 项`}
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
