import { useState } from 'react';
const presets = ['BOOT', 'ROOTFS', 'DATA', 'BACKUP', 'EMMC', 'USB'];
export function VolumeLabel({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [custom, setCustom] = useState(Boolean(value && !presets.includes(value)));
  return (
    <div className="field">
      <label>
        {label}
        <select
          aria-label="卷标预设"
          value={custom ? 'custom' : value}
          onChange={(e) => {
            setCustom(e.target.value === 'custom');
            if (e.target.value !== 'custom') onChange(e.target.value);
          }}
        >
          <option value="">无卷标</option>
          {presets.map((v) => (
            <option value={v} key={v}>
              {v}
            </option>
          ))}
          <option value="custom">自定义卷标</option>
        </select>
        <input
          aria-label="自定义卷标"
          value={value}
          maxLength={11}
          placeholder="选择预设或输入自定义卷标"
          onChange={(e) => {
            setCustom(true);
            onChange(e.target.value);
          }}
        />
      </label>
      <small>预设可直接使用，也可修改为自定义卷标；最多 11 字符。</small>
    </div>
  );
}
