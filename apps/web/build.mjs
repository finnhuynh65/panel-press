import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { build } from 'esbuild';

const apiOrigin = (process.env.VERCEL ? '' : (process.env.PANEL_API_ORIGIN || 'http://127.0.0.1:8080')).replace(/\/$/, '');
if (apiOrigin && !/^https?:\/\/[^/]+$/.test(apiOrigin)) {
  throw new Error('PANEL_API_ORIGIN must be an origin such as https://example.vercel.app');
}

mkdirSync('dist', { recursive: true });
copyFileSync(join('src', 'index.html'), join('dist', 'index.html'));
await build({ entryPoints: ['src/local_import.js'], bundle: true, format: 'iife', platform: 'browser', target: ['es2020'], outfile: 'dist/local-import.js' });
await build({ entryPoints: ['../../node_modules/pdfjs-dist/legacy/build/pdf.worker.mjs'], bundle: true, format: 'esm', platform: 'browser', target: ['es2022'], outfile: 'dist/pdf.worker.js' });
const htmlPath = join('dist', 'index.html');
writeFileSync(htmlPath, readFileSync(htmlPath, 'utf8').replace('<script>', '<script src="/local-import.js"></script><script>'));
writeFileSync(join('dist', 'config.js'), `(() => {
  const origin = ${JSON.stringify(apiOrigin)};
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, options) => originalFetch(
    typeof input === 'string' && input.startsWith('/api/') ? origin + input : input,
    options
  );
})();\n`);
