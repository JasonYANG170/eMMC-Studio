import { t, locale } from './i18n.js';
import { useEffect, useState } from 'react';
import { hexPageOffset } from './layout';
function HexByte({
  value,
  onChange,
  label,
  changed,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  label: string;
  changed: boolean;
  disabled: boolean;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (/^[0-9a-f]{2}$/i.test(draft)) onChange(draft.toLowerCase());
    else setDraft(value);
  };
  return (
    <input
      aria-label={label}
      className={'hex-byte ' + (changed ? 'changed' : '')}
      value={draft}
      maxLength={2}
      disabled={disabled}
      spellCheck={false}
      onChange={(e) => setDraft(e.target.value.replace(/[^0-9a-f]/gi, ''))}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          commit();
          e.currentTarget.blur();
        }
        if (e.key === 'Escape') {
          setDraft(value);
          e.currentTarget.blur();
        }
      }}
    />
  );
}
export function HexGrid({
  original,
  value,
  offset,
  onChange,
  writable,
  rangeStart,
  rangeLength,
  onRead,
  loading,
}: {
  original: string;
  value: string;
  offset: number;
  onChange: (v: string) => void;
  writable: boolean;
  rangeStart: number;
  rangeLength: number;
  onRead: (offset: number) => void;
  loading: boolean;
}) {
  const [page, setPage] = useState(Math.floor((offset - rangeStart) / 256)),
    [jump, setJump] = useState('');
  useEffect(() => {
    setPage(Math.floor((offset - rangeStart) / 256));
    setJump('');
  }, [original, offset, rangeStart]);
  const length = value.length / 2,
    pageSize = 256,
    total = Math.ceil(rangeLength / pageSize),
    absolute = rangeStart + page * pageSize,
    start = absolute - offset,
    end = Math.min(start + pageSize, length);
  const [pending, setPending] = useState<number | null>(null);
  useEffect(() => {
    if (
      pending !== null &&
      rangeStart + pending * 256 >= offset &&
      rangeStart + pending * 256 < offset + length
    ) {
      setPage(pending);
      setPending(null);
      setJump('');
    }
  }, [offset, original, pending, length, rangeStart]);
  const navigate = (n: number) => {
    if (loading || !Number.isInteger(n) || n < 0 || n >= total) return;
    const address = hexPageOffset(rangeStart, rangeLength, n + 1);
    if (
      address >= offset &&
      address + Math.min(256, rangeStart + rangeLength - address) <= offset + length
    ) {
      setPage(n);
      setJump('');
      return;
    }
    if (
      value !== original &&
      !window.confirm(t('当前有未保存的字节修改，跳页将放弃这些修改。继续？'))
    )
      return;
    setPending(n);
    onRead(rangeStart + Math.floor(n / 256) * 65536);
  };
  const edit = (index: number, byte: string) =>
    onChange(value.slice(0, index * 2) + byte + value.slice(index * 2 + 2));
  const changed = Array.from(
    { length },
    (_, i) => value.slice(i * 2, i * 2 + 2) !== original.slice(i * 2, i * 2 + 2),
  ).filter(Boolean).length;
  return (
    <>
      <div className="hex-grid-controls">
        <span>
          {t('直接编辑 HEX 或 ASCII · Enter / 离开单元格提交 ·')}
          {changed}
          {t('字节已修改')}
        </span>
        <div>
          <button
            className="button secondary small"
            disabled={loading || !page}
            onClick={() => navigate(page - 1)}
          >
            {t('上一页')}
          </button>
          <span>
            {t('第')}
            {(page + 1).toLocaleString()} / {total.toLocaleString()}
            {t('页')}
          </span>
          <button
            className="button secondary small"
            disabled={loading || page + 1 >= total}
            onClick={() => navigate(page + 1)}
          >
            {t('下一页')}
          </button>
        </div>
        <form
          className="hex-page-jump"
          onSubmit={(e) => {
            e.preventDefault();
            navigate(Number(jump) - 1);
          }}
        >
          <label>
            {t('跳转页码')}
            <input
              aria-label={t('跳转页码')}
              type="number"
              min={1}
              max={total}
              step={1}
              value={jump}
              onChange={(e) => setJump(e.target.value)}
              placeholder={`1–${total}`}
            />
          </label>
          <button
            className="button secondary small"
            disabled={
              loading || !Number.isInteger(Number(jump)) || Number(jump) < 1 || Number(jump) > total
            }
          >
            {t('跳转')}
          </button>
          <button
            type="button"
            className="button secondary small"
            disabled={loading || page === 0}
            onClick={() => navigate(0)}
          >
            {t('首页')}
          </button>
          <button
            type="button"
            className="button secondary small"
            disabled={loading || page === total - 1}
            onClick={() => navigate(total - 1)}
          >
            {t('末页')}
          </button>
        </form>
        <small>
          {t('每页 256 字节，页码覆盖整个选定读取范围。当前范围内第')}
          {(page * 256 + 1).toLocaleString()}–
          {Math.min((page + 1) * 256, rangeLength).toLocaleString()}
          {t('字节，共')} {rangeLength.toLocaleString()}
          {t('字节；按需加载，不限制总页数。ASCII 支持可打印字符。')}
        </small>
      </div>
      <div className="hex-grid-scroll">
        <div className="direct-hex-grid">
          <div className="direct-hex-head">
            <span>OFFSET</span>
            <span>HEX · 00 → 0F</span>
            <span>ASCII</span>
          </div>
          {Array.from({ length: Math.ceil((end - start) / 16) }, (_, row) => {
            const base = start + row * 16;
            return (
              <div className="direct-hex-row" key={base}>
                <span className="hex-offset">{(offset + base).toString(16).padStart(8, '0')}</span>
                <div className="hex-byte-row">
                  {Array.from({ length: Math.min(16, length - base) }, (_, col) => {
                    const i = base + col,
                      byte = value.slice(i * 2, i * 2 + 2);
                    return (
                      <HexByte
                        key={i}
                        value={byte}
                        label={'HEX 0x' + (offset + i).toString(16)}
                        onChange={(v) => edit(i, v)}
                        changed={byte !== original.slice(i * 2, i * 2 + 2)}
                        disabled={!writable}
                      />
                    );
                  })}
                </div>
                <div className="ascii-byte-row">
                  {Array.from({ length: Math.min(16, length - base) }, (_, col) => {
                    const i = base + col,
                      n = parseInt(value.slice(i * 2, i * 2 + 2), 16);
                    return (
                      <input
                        key={i}
                        aria-label={'ASCII 0x' + (offset + i).toString(16)}
                        className={
                          'ascii-byte ' +
                          (value.slice(i * 2, i * 2 + 2) !== original.slice(i * 2, i * 2 + 2)
                            ? 'changed'
                            : '')
                        }
                        value={n >= 32 && n <= 126 ? String.fromCharCode(n) : ''}
                        placeholder="·"
                        maxLength={1}
                        disabled={!writable}
                        onChange={(e) => {
                          const c = e.target.value.charCodeAt(0);
                          if (c >= 32 && c <= 126) edit(i, c.toString(16).padStart(2, '0'));
                        }}
                      />
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
