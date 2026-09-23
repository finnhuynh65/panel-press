import { copyFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const apiOrigin = (process.env.VERCEL ? '' : (process.env.PANEL_API_ORIGIN || 'http://127.0.0.1:8080')).replace(/\/$/, '');
if (apiOrigin && !/^https?:\/\/[^/]+$/.test(apiOrigin)) {
  throw new Error('PANEL_API_ORIGIN must be an origin such as https://example.vercel.app');
}

mkdirSync('dist', { recursive: true });
copyFileSync(join('src', 'index.html'), join('dist', 'index.html'));
writeFileSync(join('dist', 'config.js'), `(() => {
  const origin = ${JSON.stringify(apiOrigin)};
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, options) => originalFetch(
    typeof input === 'string' && input.startsWith('/api/') ? origin + input : input,
    options
  );
})();\n`);
