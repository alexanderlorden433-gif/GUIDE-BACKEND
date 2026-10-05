#!/usr/bin/env node
// Catches real bugs (not style): undefined names, duplicate functions/keys,
// assignments to constants, impossible comparisons — in the backend (src/)
// and in the website's main script (web/index.html).
// Usage: node ops/lint.js   (exit 1 on any error)
const fs = require('fs');
const path = require('path');
const { ESLint } = require(path.join(__dirname, 'node_modules', 'eslint'));

const ROOT = path.resolve(__dirname, '..');
const RULES = {
  'no-undef': 'error', 'no-dupe-keys': 'error', 'no-redeclare': 'error', 'no-const-assign': 'error',
  'no-func-assign': 'error', 'no-unsafe-negation': 'error', 'use-isnan': 'error', 'valid-typeof': 'error',
  'no-dupe-else-if': 'error', 'no-duplicate-case': 'error', 'no-self-assign': 'error', 'no-unreachable': 'warn',
};
const base = { parserOptions: { ecmaVersion: 'latest', sourceType: 'script' }, rules: RULES };

(async () => {
  let errors = 0;
  const show = (results, label) => {
    for (const r of results) for (const m of r.messages) {
      if (m.severity === 2) errors++;
      console.log(`  ${m.severity === 2 ? '✗' : '!'} ${label || path.relative(ROOT, r.filePath)}:${m.line}  ${m.message}`);
    }
  };
  console.log('Lint (bug-level rules only)');
  const node = new ESLint({ useEslintrc: false, overrideConfig: { ...base, env: { node: true, es2022: true } } });
  show(await node.lintFiles([path.join(ROOT, 'src', '**', '*.js')]));

  // The website is one HTML file; lint its main <script> with the same line numbers.
  const html = fs.readFileSync(path.join(ROOT, 'web', 'index.html'), 'utf8');
  const a = html.indexOf('<script>') + '<script>'.length;
  const b = html.indexOf('</script>', a);
  const code = '\n'.repeat(html.slice(0, a).split('\n').length - 1) + html.slice(a, b);
  const web = new ESLint({ useEslintrc: false, overrideConfig: { ...base, env: { browser: true, es2022: true } } });
  show(await web.lintText(code, { filePath: path.join(ROOT, 'web', 'app-script.js') }), 'web/index.html');

  console.log(errors ? `${errors} lint error(s)` : 'Lint OK');
  process.exit(errors ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
