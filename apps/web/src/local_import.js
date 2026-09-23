import JSZip from 'jszip';
import * as pdfjsLib from 'pdfjs-dist/legacy/build/pdf.mjs';

const DB_NAME = 'panel-press-local';
const STORE = 'imports';
const MAX_FILES = 300;
const MAX_FILE_BYTES = 16 * 1024 * 1024;
const MAX_TOTAL_BYTES = 128 * 1024 * 1024;
const MAX_PDF_BYTES = 32 * 1024 * 1024;
const MAX_PDF_PAGES = 300;
const MAX_BUNDLE_BYTES = 256 * 1024 * 1024;
const IMAGE_EXTENSIONS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.gif']);
const PDF_EXTENSION = '.pdf';
pdfjsLib.GlobalWorkerOptions.workerSrc = '/pdf.worker.js';
const PROFILES = {
  'kindle-basic': [600, 800], 'kindle-paperwhite-legacy': [758, 1024],
  'kindle-voyage': [1072, 1448], 'kindle-oasis': [1264, 1680],
  'kindle-paperwhite': [1236, 1648], 'kindle-paperwhite-6': [1272, 1696],
  'kindle-colorsoft': [1272, 1696], 'kindle-scribe': [1860, 2480],
  'kobo-mini': [600, 800], 'kobo-glo': [768, 1024], 'kobo-glo-hd': [1072, 1448],
  'kobo-aura': [758, 1024], 'kobo-aura-hd': [1080, 1440], 'kobo-aura-h2o': [1080, 1430],
  'kobo-aura-one': [1404, 1872], 'kobo-nia': [758, 1024], 'kobo-clara': [1072, 1448],
  'kobo-clara-colour': [1072, 1448], 'kobo-libra': [1264, 1680], 'kobo-libra-colour': [1264, 1680],
  'kobo-forma': [1440, 1920], 'kobo-sage': [1440, 1920], 'kobo-elipsa': [1404, 1872], original: [0, 0],
};
const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function transact(mode, callback) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE, mode);
    const store = transaction.objectStore(STORE);
    let result;
    try { result = callback(store); } catch (error) { reject(error); return; }
    transaction.oncomplete = () => { db.close(); resolve(result); };
    transaction.onerror = () => { db.close(); reject(transaction.error); };
    transaction.onabort = () => { db.close(); reject(transaction.error); };
  });
}

export async function save(files) {
  const records = await prepareImportFiles(files);
  return saveRecords(records, 'ltr');
}

async function prepareImportFiles(files) {
  if (!files.length) throw new Error('Choose images or PDF files first.');
  let pageCount = 0, totalBytes = 0;
  const records = [];
  for (const file of files) {
    const path = file.webkitRelativePath || file.name;
    if (extension(file.name) !== PDF_EXTENSION) {
      if (!IMAGE_EXTENSIONS.has(extension(file.name))) throw new Error('Choose JPG, PNG, WebP, GIF, or PDF files.');
      if (pageCount >= MAX_FILES) throw new Error(`Imports are limited to ${MAX_FILES} total pages.`);
      if (!file.size || file.size > MAX_FILE_BYTES) throw new Error('Each image must be 16 MiB or smaller.');
      totalBytes += file.size;
      if (totalBytes > MAX_TOTAL_BYTES) throw new Error('Imported pages must total 128 MiB or less.');
      records.push({ blob: file, name: file.name, type: file.type, lastModified: file.lastModified, relativePath: path });
      pageCount++;
      continue;
    }
    if (!file.size || file.size > MAX_PDF_BYTES) throw new Error(`PDF “${file.name}” exceeds the 32 MiB per-file limit.`);
    const basePath = path.replace(/\.pdf$/i, '');
    let loadingTask, pdfDocument;
    try {
      loadingTask = pdfjsLib.getDocument({ data: await file.arrayBuffer() });
      pdfDocument = await loadingTask.promise;
    } catch (error) {
      if (loadingTask) await loadingTask.destroy().catch(() => {});
      throw new Error(`Could not open PDF “${file.name}”: ${error.message}`);
    }
    if (pdfDocument.numPages > MAX_PDF_PAGES || pageCount + pdfDocument.numPages > MAX_FILES) {
      await loadingTask.destroy();
      throw new Error(`PDF imports are limited to ${MAX_PDF_PAGES} pages total.`);
    }
    try {
      for (let pageNumber = 1; pageNumber <= pdfDocument.numPages; pageNumber++) {
        const page = await pdfDocument.getPage(pageNumber);
        const viewport = page.getViewport({ scale: 1.5 });
        const canvas = document.createElement('canvas');
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        const context = canvas.getContext('2d', { alpha: false });
        if (!context) throw new Error('This browser could not create a PDF page canvas.');
        context.fillStyle = '#fff';
        context.fillRect(0, 0, canvas.width, canvas.height);
        await page.render({ canvasContext: context, viewport }).promise;
        const blob = await new Promise((resolve, reject) => canvas.toBlob(
          result => result ? resolve(result) : reject(new Error('Could not render a PDF page in this browser.')),
          'image/jpeg', 0.92,
        ));
        canvas.width = canvas.height = 0;
        if (!blob.size || blob.size > MAX_FILE_BYTES) throw new Error(`A rendered PDF page from “${file.name}” exceeds the 16 MiB per-page limit.`);
        totalBytes += blob.size;
        if (totalBytes > MAX_TOTAL_BYTES) throw new Error('Rendered PDF pages and images must total 128 MiB or less.');
        const name = `${basePath.split('/').pop()} - page ${String(pageNumber).padStart(4, '0')}.jpg`;
        const relativeBase = path.includes('/') ? basePath : `${basePath}/${basePath}`;
        records.push({ blob, name, type: blob.type, lastModified: file.lastModified, relativePath: `${relativeBase}/${name}` });
        pageCount++;
        page.cleanup();
      }
    } finally {
      await loadingTask.destroy();
    }
  }
  if (!records.length || records.length > MAX_FILES) throw new Error(`Imports are limited to ${MAX_FILES} total pages.`);
  return records;
}

export async function saveRecords(records, sourceDirection = 'ltr') {
  await transact('readwrite', store => {
    store.put(records, 'current');
    store.put(sourceDirection, 'direction');
  });
  return records;
}

export async function saveSourceBatch(records, chapterIndex, partIndex, sourceDirection = 'ltr') {
  await transact('readwrite', store => {
    const prefix = `source:${String(chapterIndex).padStart(5, '0')}:${String(partIndex).padStart(5, '0')}:`;
    records.forEach((record, index) => store.put(record, `${prefix}${String(index).padStart(5, '0')}`));
    store.put(sourceDirection, 'direction');
  });
}

export async function saveOutput(output) {
  const id = `${String(Date.now()).padStart(13, '0')}-${crypto.randomUUID()}`;
  await transact('readwrite', store => {
    store.put(output.name, `output:${id}:name`);
    store.put(output.blob, `output:${id}:data`);
    store.put(output.blob.size, `output:${id}:size`);
  });
  return id;
}

export async function listOutputs() {
  const keysRequest = await transact('readonly', store => store.getAllKeys());
  const ids = keysRequest.result.filter(key => typeof key === 'string' && key.startsWith('output:') && key.endsWith(':name'));
  const outputs = [];
  for (const key of ids) {
    const id = key.slice('output:'.length, -':name'.length);
    const nameRequest = await transact('readonly', store => store.get(key));
    const sizeRequest = await transact('readonly', store => store.get(`output:${id}:size`));
    let size = sizeRequest.result;
    if (!Number.isFinite(size)) {
      const dataRequest = await transact('readonly', store => store.get(`output:${id}:data`));
      size = dataRequest.result?.size || 0;
      if (size) await transact('readwrite', store => store.put(size, `output:${id}:size`));
    }
    outputs.push({ id, name: nameRequest.result, size: size || 0 });
  }
  return outputs;
}

export async function loadOutput(id) {
  const dataRequest = await transact('readonly', store => store.get(`output:${id}:data`));
  const nameRequest = await transact('readonly', store => store.get(`output:${id}:name`));
  return dataRequest.result ? { blob: dataRequest.result, name: nameRequest.result } : null;
}

export async function bundleOutputs(progress = () => {}) {
  const outputs = await listOutputs();
  if (!outputs.length) throw new Error('There are no chapter files to bundle yet.');
  const size = outputs.reduce((sum, output) => sum + output.size, 0);
  if (size > MAX_BUNDLE_BYTES) throw new Error('The batch exceeds 256 MiB. Download the chapter files individually.');
  const zip = new JSZip();
  const names = new Set();
  for (let index = 0; index < outputs.length; index++) {
    const output = outputs[index];
    const file = await loadOutput(output.id);
    if (!file) throw new Error(`The saved chapter file “${output.name}” is missing.`);
    const dot = output.name.lastIndexOf('.');
    const stem = dot > 0 ? output.name.slice(0, dot) : output.name;
    const extension = dot > 0 ? output.name.slice(dot) : '';
    let name = output.name, suffix = 2;
    while (names.has(name)) name = `${stem} (${suffix++})${extension}`;
    names.add(name);
    zip.file(name, file.blob);
    progress(index + 1, outputs.length, output.name);
  }
  return zip.generateAsync({ type: 'blob', mimeType: 'application/zip', compression: 'STORE', streamFiles: true }, event => {
    progress(outputs.length, outputs.length, `Packing ZIP · ${Math.round(event.percent)}%`);
  });
}

export async function restore() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE, 'readonly');
    const store = transaction.objectStore(STORE);
    const recordsRequest = store.get('current');
    const directionRequest = store.get('direction');
    let records = [], direction = 'ltr';
    recordsRequest.onsuccess = () => { records = recordsRequest.result || []; };
    directionRequest.onsuccess = () => { direction = directionRequest.result || 'ltr'; };
    recordsRequest.onerror = directionRequest.onerror = () => reject(recordsRequest.error || directionRequest.error);
    transaction.oncomplete = () => { db.close(); resolve({ records, direction }); };
    transaction.onerror = () => { db.close(); reject(transaction.error); };
  });
}

export async function clear() {
  await transact('readwrite', store => {
    store.delete('current');
    store.delete('direction');
    const request = store.openCursor();
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) return;
      if (typeof cursor.key === 'string' && (cursor.key.startsWith('source:') || cursor.key.startsWith('output:'))) cursor.delete();
      cursor.continue();
    };
  });
}

function splitChapters(records, defaultTitle) {
  const paths = records.map(row => row.relativePath.replaceAll('\\', '/').split('/').filter(Boolean));
  const roots = paths.filter(parts => parts.length > 1).map(parts => parts[0]);
  const rooted = paths.length > 0 && paths.every(parts => parts.length > 1) && new Set(roots).size === 1;
  let rows = records.map((record, i) => ({ record, parts: rooted ? paths[i].slice(1) : paths[i] }));
  const crawler = rows.some(row => row.parts[0]?.toLowerCase() === 'chapters');
  if (crawler) rows = rows.filter(row => row.parts[0]?.toLowerCase() === 'chapters').map(row => ({ ...row, parts: row.parts.slice(1) }));
  const hasChapterDirectories = rows.some(row => row.parts.length > 1);
  const groups = new Map();
  for (const row of rows) {
    const label = hasChapterDirectories && row.parts.length > 1 ? row.parts[0] : defaultTitle;
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(row.record);
  }
  return [...groups].map(([label, pages]) => ({
    title: label === defaultTitle ? defaultTitle : label.replace(/[_-]+/g, ' ').trim(),
    pages: pages.sort((a, b) => collator.compare(a.relativePath, b.relativePath)),
  })).sort((a, b) => collator.compare(a.title, b.title));
}

function xml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char]);
}

function extension(name) {
  return name.slice(name.lastIndexOf('.')).toLowerCase();
}

async function jpegPage(blob, size, quality) {
  const bitmap = await createImageBitmap(blob);
  try {
    const [maxWidth, maxHeight] = size;
    const scale = maxWidth && maxHeight ? Math.min(1, maxWidth / bitmap.width, maxHeight / bitmap.height) : 1;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext('2d', { alpha: false });
    context.fillStyle = '#fff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    return await new Promise((resolve, reject) => canvas.toBlob(
      result => result ? resolve(result) : reject(new Error('Could not process an image in this browser.')),
      'image/jpeg', quality,
    ));
  } finally {
    bitmap.close();
  }
}

function naturalOrder(records) {
  return [...records].sort((a, b) => collator.compare(a.relativePath, b.relativePath));
}

async function createEpub(chapters, options, progress) {
  const zip = new JSZip();
  const title = options.title || 'Comic';
  const pageSize = PROFILES[options.profile] || PROFILES.original;
  const quality = { best: 0.92, balanced: 0.85, compact: 0.72 }[options.quality] || 0.85;
  const direction = options.direction === 'rtl' || (options.direction === 'auto' && options.sourceDirection === 'rtl') ? 'rtl' : 'ltr';
  zip.file('mimetype', 'application/epub+zip', { compression: 'STORE' });
  zip.file('META-INF/container.xml', '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>');
  const manifest = [], spine = [], nav = [];
  let pageIndex = 0;
  for (const [chapterIndex, chapter] of chapters.entries()) {
    const firstHref = `p${pageIndex + 1}.xhtml`;
    nav.push(`<li><a href="${firstHref}">${xml(chapter.title)}</a></li>`);
    for (const record of naturalOrder(chapter.pages)) {
      pageIndex++;
      const imageName = `page-${String(pageIndex).padStart(4, '0')}.jpg`;
      const pageName = `p${pageIndex}.xhtml`;
      progress(pageIndex, chapters.reduce((n, row) => n + row.pages.length, 0), record.name);
      const image = await jpegPage(record.blob, pageSize, quality);
      zip.file(`OEBPS/${imageName}`, image);
      zip.file(`OEBPS/${pageName}`, `<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>${xml(chapter.title)}</title><style>html,body{margin:0;padding:0;text-align:center;background:#000}img{max-width:100%;max-height:100vh;object-fit:contain}</style></head><body><img src="${imageName}" alt="Page ${pageIndex}"/></body></html>`);
      manifest.push(`<item id="i${pageIndex}" href="${imageName}" media-type="image/jpeg"/><item id="p${pageIndex}" href="${pageName}" media-type="application/xhtml+xml"/>`);
      spine.push(`<itemref idref="p${pageIndex}"/>`);
    }
  }
  zip.file('OEBPS/nav.xhtml', `<?xml version="1.0" encoding="utf-8"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>${xml(title)}</title></head><body><nav epub:type="toc" id="toc"><h1>${xml(title)}</h1><ol>${nav.join('')}</ol></nav></body></html>`);
  zip.file('OEBPS/content.opf', `<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">panel-press-${crypto.randomUUID()}</dc:identifier><dc:title>${xml(title)}</dc:title><dc:creator>${xml(options.author || '')}</dc:creator><dc:language>en</dc:language><meta property="rendition:layout">pre-paginated</meta><meta property="rendition:orientation">auto</meta></metadata><manifest>${manifest.join('')}<item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/></manifest><spine page-progression-direction="${direction}">${spine.join('')}</spine></package>`);
  const total = Math.max(1, pageIndex);
  return zip.generateAsync({ type: 'blob', mimeType: 'application/epub+zip', compression: 'DEFLATE', compressionOptions: { level: 5 } }, event => progress(Math.round(total * event.percent / 100), total, 'Packing EPUB'));
}

async function createCbz(chapters, options, progress) {
  const zip = new JSZip();
  const title = options.title || 'Comic';
  let pageIndex = 0;
  const total = chapters.reduce((n, row) => n + row.pages.length, 0);
  for (const chapter of chapters) {
    for (const record of naturalOrder(chapter.pages)) {
      pageIndex++;
      progress(pageIndex, total, record.name);
      const suffix = IMAGE_EXTENSIONS.has(extension(record.name)) ? extension(record.name) : '.jpg';
      zip.file(`images/${String(pageIndex).padStart(4, '0')}${suffix}`, record.blob);
    }
  }
  zip.file('ComicInfo.xml', `<?xml version="1.0"?><ComicInfo><Title>${xml(title)}</Title><PageCount>${total}</PageCount><Manga>${options.direction === 'rtl' ? 'Yes' : 'No'}</Manga></ComicInfo>`);
  return zip.generateAsync({ type: 'blob', mimeType: 'application/vnd.comicbook+zip', compression: 'DEFLATE', compressionOptions: { level: 4 } }, event => progress(Math.round(total * event.percent / 100), Math.max(1, total), 'Packing CBZ'));
}

export async function convert(records, options, progress = () => {}) {
  if (!records.length || records.length > MAX_FILES) throw new Error(`Choose between 1 and ${MAX_FILES} images.`);
  const totalBytes = records.reduce((sum, row) => sum + row.blob.size, 0);
  if (totalBytes > MAX_TOTAL_BYTES || records.some(row => row.blob.size > MAX_FILE_BYTES)) {
    throw new Error('Choose images up to 16 MiB each and 128 MiB total.');
  }
  const supported = records.filter(row => IMAGE_EXTENSIONS.has(extension(row.name)));
  if (supported.length !== records.length) throw new Error('Only JPG, PNG, WebP, and GIF images are supported.');
  const title = options.title || supported[0].name.replace(/\.[^.]+$/, '');
  const chapters = splitChapters(supported, title);
  const format = options.format === 'auto'
    ? (options.profile === 'original' ? 'cbz' : 'epub') : options.format;
  if (!['epub', 'cbz'].includes(format)) throw new Error('Browser conversion supports EPUB and CBZ.');
  if (options.packaging === 'separate' && chapters.length > 1) {
    const outputs = [];
    for (const chapter of chapters) {
      const blob = format === 'epub'
        ? await createEpub([chapter], { ...options, title: `${title} - ${chapter.title}` }, progress)
        : await createCbz([chapter], { ...options, title: `${title} - ${chapter.title}` }, progress);
      outputs.push({ name: `${safeName(title)} - ${safeName(chapter.title)}.${format}`, blob });
    }
    return outputs;
  }
  const blob = format === 'epub' ? await createEpub(chapters, { ...options, title }, progress) : await createCbz(chapters, { ...options, title }, progress);
  return [{ name: `${safeName(options.exportName || title)}.${format}`, blob }];
}

function safeName(value) {
  return String(value || 'Comic').replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').replace(/\s+/g, ' ').trim().slice(0, 120) || 'Comic';
}

window.panelPressLocal = { save, saveRecords, saveSourceBatch, saveOutput, listOutputs, loadOutput, bundleOutputs, restore, clear, convert, limits: { files: MAX_FILES, fileBytes: MAX_FILE_BYTES, pdfFileBytes: MAX_PDF_BYTES, pdfPages: MAX_PDF_PAGES, totalBytes: MAX_TOTAL_BYTES, bundleBytes: MAX_BUNDLE_BYTES } };
