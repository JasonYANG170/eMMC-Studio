import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import ts from 'typescript';
import { resolveLanguage } from '../.test-build/i18n.js';
const catalogue = JSON.parse(readFileSync('backend/locales/en.json', 'utf8'));
assert.equal(resolveLanguage('auto', ['zh-TW']), 'zh-CN');
assert.equal(resolveLanguage(null, ['en-US']), 'en');
assert.equal(resolveLanguage('en', ['zh-CN']), 'en');
assert.equal(resolveLanguage('zh-CN', ['en-US']), 'zh-CN');
assert.equal(resolveLanguage('auto', ['fr-FR']), 'en');
assert.equal(resolveLanguage('auto', []), 'en');
for (const [source, target] of Object.entries(catalogue)) {
  assert.deepEqual(
    [...new Set(source.match(/\{\d+\}/g))].sort(),
    [...new Set(target.match(/\{\d+\}/g))].sort(),
    source,
  );
  assert.ok(!/[\u3400-\u9fff]/.test(target), source);
}
for (const file of readdirSync('src').filter(
  (f) => /\.(tsx|ts)$/.test(f) && !['locales.ts', 'LanguageSelector.tsx'].includes(f),
)) {
  const tree = ts.createSourceFile(
    file,
    readFileSync('src/' + file, 'utf8'),
    ts.ScriptTarget.Latest,
    true,
    file.endsWith('tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const visit = (node) => {
    if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === 't' &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      const message = node.arguments[0].text;
      if (/[\u3400-\u9fff]/.test(message)) assert.ok(catalogue[message], file + ': ' + message);
    }
    if (ts.isJsxText(node))
      assert.ok(!/[\u3400-\u9fff]/.test(node.text), file + ': unlocalized JSX');
    ts.forEachChild(node, visit);
  };
  visit(tree);
}
// A fresh module resolves persisted preferences before translating any module-level labels.
globalThis.localStorage = { getItem: () => 'en' };
const english = await import('../.test-build/i18n.js?en');
assert.equal(english.t('磁盘概览'), 'Disk overview');
assert.equal(english.t('允许 {0}–{1} 字节', [1, 4194304]), 'Allowed: 1–4194304 bytes');
assert.equal(english.serverText('/dev/mmcblk2boot0'), '/dev/mmcblk2boot0');
assert.equal(english.serverText('我的文件.txt'), '我的文件.txt');
assert.equal(
  english.serverText('/dev/test 已被其他程序挂载：/媒体'),
  '/dev/test is mounted by another program: /媒体',
);
assert.equal(
  english.serverText('密码长度应为 8–128 个字符'),
  'Password must contain 8–128 characters',
);
globalThis.localStorage = { getItem: () => 'zh-CN' };
const chinese = await import('../.test-build/i18n.js?zh');
assert.equal(chinese.t('磁盘概览'), '磁盘概览');
assert.equal(chinese.t('允许 {0}–{1} 字节', [1, 64]), '允许 1–64 字节');
delete globalThis.localStorage;
console.log(
  'PASS: bilingual catalogue coverage, interpolation, locale selection and unchanged user data',
);
