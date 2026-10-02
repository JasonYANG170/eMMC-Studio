import { Languages } from 'lucide-react';
import { languageKey, storedLanguage, t, type LanguagePreference } from './i18n';

export function LanguageSelector({ dirty = false }: { dirty?: boolean }) {
  return (
    <label className="language-selector">
      <Languages size={16} aria-hidden="true" />
      <select
        aria-label={t('语言')}
        value={storedLanguage()}
        onChange={(event) => {
          if (dirty && !window.confirm(t('切换语言将重新加载界面，未保存的编辑会丢失。继续？')))
            return;
          const preference = event.target.value as LanguagePreference;
          try {
            localStorage.setItem(languageKey, preference);
          } catch {
            return;
          }
          window.location.reload();
        }}
      >
        <option value="auto">{t('跟随浏览器')}</option>
        <option value="zh-CN">简体中文</option>
        <option value="en">English</option>
      </select>
    </label>
  );
}
