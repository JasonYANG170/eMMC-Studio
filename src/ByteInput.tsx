import { t, locale } from './i18n.js';
import { useEffect, useState } from 'react';
import { byteUnits, ByteUnit, fromBytes, toBytes } from './units';

export function ByteInput({
  label,
  value,
  onChange,
  initialUnit = 'B',
  min = 0,
  max = Number.MAX_SAFE_INTEGER,
  alignment = 1,
}: {
  label: string;
  value: number;
  onChange: (bytes: number) => void;
  initialUnit?: ByteUnit;
  min?: number;
  max?: number;
  alignment?: number;
}) {
  const [unit, setUnit] = useState<ByteUnit>(initialUnit);
  const [raw, setRaw] = useState(() => fromBytes(value, initialUnit));
  useEffect(() => {
    if (!Object.is(toBytes(raw, unit), value)) setRaw(fromBytes(value, unit));
  }, [value, unit]);
  const bytes = toBytes(raw, unit);
  const valid =
    Number.isSafeInteger(bytes) && bytes >= min && bytes <= max && bytes % alignment === 0;
  return (
    <div className="field byte-field">
      <label>
        {label}
        <div className="byte-controls">
          <input
            aria-label={label}
            value={raw}
            aria-invalid={!valid}
            placeholder={unit === 'B' ? t('字节数或 0x 十六进制') : t('数值')}
            onChange={(e) => {
              setRaw(e.target.value);
              onChange(toBytes(e.target.value, unit));
            }}
          />
          <select
            aria-label={label + t('单位')}
            value={unit}
            onChange={(e) => {
              const next = e.target.value as ByteUnit;
              setRaw(fromBytes(bytes, next));
              setUnit(next);
            }}
          >
            {Object.keys(byteUnits).map((u) => (
              <option key={u} value={u}>
                {u === '扇区' ? t('扇区（512 B）') : u}
              </option>
            ))}
          </select>
        </div>
      </label>
      <small aria-live="polite">
        {valid
          ? t('{0} 字节 · 0x{1}{2}', [
              bytes.toLocaleString(locale),
              bytes.toString(16).toUpperCase(),
              alignment > 1
                ? ' · ' + (bytes / 512).toLocaleString(locale) + ' ' + t('扇区（1 MiB 对齐）')
                : '',
            ])
          : Number.isSafeInteger(bytes)
            ? bytes % alignment !== 0
              ? t('需按 1 MiB 对齐，请填写整数个 MiB')
              : t('允许 {0}–{1} 字节', [min.toLocaleString(locale), max.toLocaleString(locale)])
            : t('请输入可换算为整数个字节的非负数值')}
      </small>
    </div>
  );
}
