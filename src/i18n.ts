import translations from './locales.js';

export type Language = 'zh-CN' | 'en';
export type LanguagePreference = Language | 'auto';
export const languageKey = 'emmc-studio-language';
export function resolveLanguage(preference: string | null, languages: readonly string[]): Language {
  if (preference === 'zh-CN' || preference === 'en') return preference;
  return (languages[0] || '').toLowerCase().startsWith('zh') ? 'zh-CN' : 'en';
}
export function storedLanguage(): LanguagePreference {
  try {
    const saved = localStorage.getItem(languageKey);
    return saved === 'zh-CN' || saved === 'en' ? saved : 'auto';
  } catch {
    return 'auto';
  }
}
export const language = resolveLanguage(
  storedLanguage(),
  typeof navigator === 'undefined' ? ['zh-CN'] : navigator.languages,
);
export const locale = language === 'en' ? 'en-US' : 'zh-CN';
const english: Record<string, string> = translations;
export function t(message: string, values: readonly unknown[] = []): string {
  const template = language === 'en' ? english[message] || message : message;
  return template.replace(/\{(\d+)\}/g, (match, index: string) =>
    Number(index) < values.length ? String(values[Number(index)]) : match,
  );
}
// Translate known server messages only. Files, paths, IDs and register values are untouched.
const patterns = Object.entries(english)
  .filter(([key]) => /\{\d+\}/.test(key))
  .map(([key, value]) => {
    const indexes: number[] = [];
    const source = key
      .split(/(\{\d+\})/)
      .map((part) => {
        if (/^\{\d+\}$/.test(part)) {
          indexes.push(Number(part.slice(1, -1)));
          return '(.*?)';
        }
        return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      })
      .join('');
    return { regex: new RegExp('^' + source + '$', 's'), value, indexes };
  });
export function serverText(message: string): string {
  if (language !== 'en' || !message) return message;
  if (english[message]) return english[message];
  for (const { regex, value, indexes } of patterns) {
    const match = regex.exec(message);
    if (match)
      return value.replace(/\{(\d+)\}/g, (token, index: string) => {
        const position = indexes.indexOf(Number(index));
        return position < 0 ? token : match[position + 1];
      });
  }
  return message;
}
if (typeof document !== 'undefined') {
  document.documentElement.lang = language;
  document.title = 'eMMC Studio';
}
