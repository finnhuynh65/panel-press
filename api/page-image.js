import http from 'node:http';
import https from 'node:https';
import { lookup as dnsLookup } from 'node:dns/promises';
import { isIP } from 'node:net';

const MAX_BYTES = 16 * 1024 * 1024;
const MAX_REDIRECTS = 5;

function privateAddress(address) {
  const version = isIP(address);
  if (version === 4) {
    const [a, b, c] = address.split('.').map(Number);
    return a === 0 || a === 10 || a === 127 || a >= 224 || (a === 169 && b === 254)
      || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
      || (a === 100 && b >= 64 && b <= 127) || (a === 192 && b === 0 && (c === 0 || c === 2))
      || (a === 192 && b === 88 && c === 99)
      || (a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100)))
      || (a === 203 && b === 0 && c === 113);
  }
  if (version === 6) {
    const normalized = address.toLowerCase();
    if (normalized.startsWith('::ffff:')) {
      const mapped = normalized.slice(7);
      if (isIP(mapped) === 4) return privateAddress(mapped);
      const words = mapped.split(':').map(word => parseInt(word || '0', 16));
      const ipv4 = `${words.at(-2) >> 8}.${words.at(-2) & 255}.${words.at(-1) >> 8}.${words.at(-1) & 255}`;
      return privateAddress(ipv4);
    }
    return !(normalized.startsWith('2') || normalized.startsWith('3'));
  }
  return true;
}

async function publicAddress(hostname) {
  hostname = hostname.replace(/^\[|\]$/g, '');
  if (hostname === 'localhost' || hostname.endsWith('.localhost') || hostname.endsWith('.local')) {
    throw new Error('Private image hosts are not allowed.');
  }
  if (isIP(hostname)) {
    if (privateAddress(hostname)) throw new Error('Private image hosts are not allowed.');
    return { address: hostname, family: isIP(hostname) };
  }
  const addresses = await dnsLookup(hostname, { all: true, verbatim: true });
  if (!addresses.length || addresses.some(entry => privateAddress(entry.address))) {
    throw new Error('Private image hosts are not allowed.');
  }
  return addresses[0];
}

function requestImage(url, referer, address) {
  return new Promise((resolve, reject) => {
    const transport = url.protocol === 'https:' ? https : http;
    const request = transport.request(url, {
      method: 'GET',
      headers: {
        accept: 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'accept-encoding': 'identity',
        referer,
        'user-agent': 'Mozilla/5.0 (compatible; PanelPress/1.0)',
      },
      lookup: (_hostname, options, callback) => {
        if (options?.all) callback(null, [{ address: address.address, family: address.family }]);
        else callback(null, address.address, address.family);
      },
      timeout: 25_000,
    }, resolve);
    request.on('timeout', () => request.destroy(new Error('Image source timed out.')));
    request.on('error', reject);
    request.end();
  });
}

function json(response, status, message) {
  response.statusCode = status;
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.end(JSON.stringify({ error: message }));
}

function sniffImageType(bytes) {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'image/jpeg';
  if (bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) return 'image/png';
  if (bytes.length >= 6 && ['GIF87a', 'GIF89a'].includes(bytes.subarray(0, 6).toString('ascii'))) return 'image/gif';
  if (bytes.length >= 12 && bytes.subarray(0, 4).toString('ascii') === 'RIFF'
      && bytes.subarray(8, 12).toString('ascii') === 'WEBP') return 'image/webp';
  return null;
}

export default async function handler(request, response) {
  if (request.method !== 'GET') {
    response.setHeader('Allow', 'GET');
    return json(response, 405, 'Method not allowed.');
  }
  const appReferer = request.headers.referer;
  try {
    if (!appReferer || new URL(appReferer).host !== request.headers.host) {
      return json(response, 403, 'Use the Panel Press page to fetch images.');
    }
    const params = new URL(request.url, `https://${request.headers.host}`).searchParams;
    const referer = new URL(params.get('referer') || '');
    let target = new URL(params.get('url') || '');
    if (!['http:', 'https:'].includes(referer.protocol) || !['http:', 'https:'].includes(target.protocol)) {
      return json(response, 400, 'Image URLs must use HTTP or HTTPS.');
    }
    if (referer.username || referer.password || target.username || target.password
        || (referer.port && referer.port !== (referer.protocol === 'https:' ? '443' : '80'))
        || (target.port && target.port !== (target.protocol === 'https:' ? '443' : '80'))) {
      return json(response, 400, 'Image URLs cannot include credentials or custom ports.');
    }

    let upstream;
    for (let redirects = 0; redirects <= MAX_REDIRECTS; redirects++) {
      const address = await publicAddress(target.hostname);
      upstream = await requestImage(target, referer.href, address);
      if ([301, 302, 303, 307, 308].includes(upstream.statusCode)) {
        const location = upstream.headers.location;
        upstream.resume();
        if (!location || redirects === MAX_REDIRECTS) throw new Error('Image source redirected too many times.');
        target = new URL(location, target);
        if (!['http:', 'https:'].includes(target.protocol)) throw new Error('Image redirect URL is invalid.');
        if (target.username || target.password
            || (target.port && target.port !== (target.protocol === 'https:' ? '443' : '80'))) {
          throw new Error('Image redirects cannot include credentials or custom ports.');
        }
        continue;
      }
      break;
    }

    if (!upstream || upstream.statusCode < 200 || upstream.statusCode >= 300) {
      upstream?.resume();
      return json(response, 502, `Image source returned HTTP ${upstream?.statusCode || 'error'}.`);
    }
    const contentLength = Number(upstream.headers['content-length'] || 0);
    if (contentLength > MAX_BYTES) {
      upstream.resume();
      return json(response, 413, 'This image exceeds the 16 MiB page limit.');
    }
    const upstreamType = String(upstream.headers['content-type'] || '').split(';')[0].toLowerCase();
    if (upstreamType && !upstreamType.startsWith('image/') && upstreamType !== 'application/octet-stream') {
      upstream.resume();
      return json(response, 415, 'The selected page is not an image.');
    }

    const iterator = upstream[Symbol.asyncIterator]();
    const prefixChunks = [];
    let prefixSize = 0;
    let next = null;
    while (prefixSize < 12) {
      next = await iterator.next();
      if (next.done) break;
      prefixChunks.push(next.value);
      prefixSize += next.value.length;
    }
    const prefix = Buffer.concat(prefixChunks, prefixSize);
    const type = sniffImageType(prefix) || upstreamType || 'application/octet-stream';
    response.statusCode = 200;
    response.setHeader('Content-Type', type || 'application/octet-stream');
    response.setHeader('Cache-Control', 'no-store');
    response.setHeader('X-Content-Type-Options', 'nosniff');
    let received = prefix.length;
    if (received > MAX_BYTES) {
      response.destroy(new Error('This image exceeds the 16 MiB page limit.'));
      return;
    }
    if (prefix.length && !response.write(prefix)) await new Promise(resolve => response.once('drain', resolve));
    while (true) {
      next = await iterator.next();
      if (next.done) break;
      const chunk = next.value;
      received += chunk.length;
      if (received > MAX_BYTES) {
        response.destroy(new Error('This image exceeds the 16 MiB page limit.'));
        return;
      }
      if (!response.write(chunk)) await new Promise(resolve => response.once('drain', resolve));
    }
    response.end();
  } catch (error) {
    if (!response.headersSent) json(response, 400, error.message || 'Could not fetch this image.');
    else response.destroy(error);
  }
}
