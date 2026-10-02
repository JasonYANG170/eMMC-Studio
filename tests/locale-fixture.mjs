// Keep legacy Chinese assertions independent of the CI runner's OS language.
// The bilingual suite explicitly selects both languages in separate module instances.
globalThis.localStorage = { getItem: (key) => (key === 'emmc-studio-language' ? 'zh-CN' : null) };
