// Apply saved/system appearance before stylesheet paint; compatible with script-src 'self'.
(() => {
  let mode = 'system';
  try {
    const saved = localStorage.getItem('emmc-theme-mode');
    if (saved === 'light' || saved === 'dark') mode = saved;
  } catch {}
  const theme =
    mode === 'system'
      ? matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : mode;
  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.themeMode = mode;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', theme === 'dark' ? '#0e1828' : '#f3f7fd');
})();
