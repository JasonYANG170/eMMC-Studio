import { useEffect, useLayoutEffect, useState } from 'react';
export type ThemeMode = 'system' | 'light' | 'dark';
const key = 'emmc-theme-mode';
const valid = (value: unknown): ThemeMode =>
  value === 'light' || value === 'dark' ? value : 'system';
function savedMode() {
  try {
    return valid(localStorage.getItem(key));
  } catch {
    return 'system' as const;
  }
}
export function useTheme() {
  const [mode, setMode] = useState<ThemeMode>(savedMode);
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia('(prefers-color-scheme: dark)').matches,
  );
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => setSystemDark(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    const update = (event: StorageEvent) => {
      if (event.key === key || event.key === null) setMode(savedMode());
    };
    window.addEventListener('storage', update);
    return () => window.removeEventListener('storage', update);
  }, []);
  const theme = mode === 'system' ? (systemDark ? 'dark' : 'light') : mode;
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.themeMode = mode;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', theme === 'dark' ? '#0e1828' : '#f3f7fd');
  }, [theme, mode]);
  const choose = (value: ThemeMode) => {
    setMode(value);
    try {
      localStorage.setItem(key, value);
    } catch {}
  };
  return { mode, theme, setMode: choose };
}
