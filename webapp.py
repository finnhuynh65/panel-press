#!/usr/bin/env python3
"""Small local web app for turning web comic chapters into reader files.

The downloader deliberately stays conservative. Use it only for material you
are allowed to download, and check the source site's terms and robots policy.
"""

from __future__ import annotations

import json
import html
import mimetypes
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
import cgi
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlparse

from crawler import Chapter, clean_chapter_label as strip_reader_metadata, discover_chapters, discover_pages, fetch, guess_extension, safe_name


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
EXPORTS = OUTPUT / "exports"
JOBS: dict[str, dict[str, object]] = {}
JOBS_LOCK = threading.Lock()
DOWNLOAD_WORKERS = 4

PROFILES = {
    # Device identifiers and target sizes mirror KCC's built-in profiles.
    "kindle-basic": {"label": "Kindle Basic (8th/10th gen)", "size": [600, 800], "format": "mobi", "kcc": "K810"},
    "kindle-paperwhite-legacy": {"label": "Kindle Paperwhite (1st/2nd gen)", "size": [758, 1024], "format": "mobi", "kcc": "KPW"},
    "kindle-voyage": {"label": "Kindle Voyage", "size": [1072, 1448], "format": "mobi", "kcc": "KV"},
    "kindle-oasis": {"label": "Kindle Oasis (2nd/3rd gen)", "size": [1264, 1680], "format": "mobi", "kcc": "KO"},
    "kindle-paperwhite": {"label": "Kindle Paperwhite 5 / Signature", "size": [1236, 1648], "format": "mobi", "kcc": "KPW5"},
    "kindle-paperwhite-6": {"label": "Kindle Paperwhite (6th gen)", "size": [1272, 1696], "format": "mobi", "kcc": "KPW6"},
    "kindle-colorsoft": {"label": "Kindle Colorsoft", "size": [1272, 1696], "format": "mobi", "kcc": "KCS"},
    "kindle-scribe": {"label": "Kindle Scribe", "size": [1860, 2480], "format": "mobi", "kcc": "KS"},
    "kobo-mini": {"label": "Kobo Mini / Touch", "size": [600, 800], "format": "epub", "kcc": "KoMT"},
    "kobo-glo": {"label": "Kobo Glo", "size": [768, 1024], "format": "epub", "kcc": "KoG"},
    "kobo-glo-hd": {"label": "Kobo Glo HD", "size": [1072, 1448], "format": "epub", "kcc": "KoGHD"},
    "kobo-aura": {"label": "Kobo Aura", "size": [758, 1024], "format": "epub", "kcc": "KoA"},
    "kobo-aura-hd": {"label": "Kobo Aura HD", "size": [1080, 1440], "format": "epub", "kcc": "KoAHD"},
    "kobo-aura-h2o": {"label": "Kobo Aura H2O", "size": [1080, 1430], "format": "epub", "kcc": "KoAH2O"},
    "kobo-aura-one": {"label": "Kobo Aura ONE", "size": [1404, 1872], "format": "epub", "kcc": "KoAO"},
    "kobo-nia": {"label": "Kobo Nia", "size": [758, 1024], "format": "epub", "kcc": "KoN"},
    "kobo-clara": {"label": "Kobo Clara", "size": [1072, 1448], "format": "epub", "kcc": "KoC"},
    "kobo-clara-colour": {"label": "Kobo Clara Colour", "size": [1072, 1448], "format": "epub", "kcc": "KoCC"},
    "kobo-libra": {"label": "Kobo Libra", "size": [1264, 1680], "format": "epub", "kcc": "KoL"},
    "kobo-libra-colour": {"label": "Kobo Libra Colour", "size": [1264, 1680], "format": "epub", "kcc": "KoLC"},
    "kobo-forma": {"label": "Kobo Forma", "size": [1440, 1920], "format": "epub", "kcc": "KoF"},
    "kobo-sage": {"label": "Kobo Sage", "size": [1440, 1920], "format": "epub", "kcc": "KoS"},
    "kobo-elipsa": {"label": "Kobo Elipsa", "size": [1404, 1872], "format": "epub", "kcc": "KoE"},
    "original": {"label": "Keep original size", "size": [0, 0], "format": "cbz"},
}

INDEX_HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Panel Press</title><style>
:root{--ink:#17221f;--muted:#70807b;--paper:#f7f5ef;--card:#fff;--line:#dfe6df;--accent:#dd6548;--accent2:#1f806d;--shadow:0 18px 50px #17382d12}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}main{max-width:1160px;margin:auto;padding:40px 28px 70px}.top{display:flex;justify-content:space-between;align-items:start;margin-bottom:42px}.brand{display:flex;gap:12px;align-items:center}.mark{background:var(--accent);color:white;width:42px;height:42px;border-radius:14px;display:grid;place-items:center;font-size:23px;box-shadow:5px 5px 0 #f0c7bb}.eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:11px;color:var(--accent2);font-weight:800}.brand h1{font:800 24px Georgia,serif;margin:2px 0}.top p{color:var(--muted);margin:4px 0 0}.pill{background:#e8f0eb;border-radius:999px;color:var(--accent2);padding:7px 12px;font-size:12px;font-weight:700}.hero{max-width:780px;margin-bottom:30px}.hero h2{font:800 clamp(40px,6vw,70px)/.98 Georgia,serif;letter-spacing:-.045em;margin:0 0 18px}.hero h2 em{color:var(--accent);font-style:normal}.hero p{font-size:18px;color:var(--muted);max-width:650px}.grid{display:grid;grid-template-columns:1.1fr .9fr;gap:20px}.card{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:25px;box-shadow:var(--shadow)}.card h3{margin:0 0 20px;font-size:17px}.field{margin-bottom:17px}.field label{display:block;font-weight:750;margin-bottom:7px}.hint{font-size:12px;color:var(--muted);margin-top:6px}.input,select{width:100%;border:1px solid var(--line);background:#fbfcfa;padding:13px 14px;border-radius:11px;color:var(--ink);font:inherit;outline:none}.input:focus,select:focus{border-color:var(--accent2);box-shadow:0 0 0 3px #1f806d18}.row{display:grid;grid-template-columns:1fr 1fr;gap:14px}.actions{display:flex;gap:10px;align-items:center;margin-top:23px}.button{border:0;border-radius:11px;padding:12px 16px;font:800 14px inherit;cursor:pointer}.primary{background:var(--accent);color:white}.secondary{background:#e8f0eb;color:var(--accent2)}.button:disabled{opacity:.5;cursor:wait}.status{color:var(--muted);font-size:13px}.chapters{display:grid;gap:8px;max-height:420px;overflow:auto}.chapter{display:flex;gap:11px;align-items:center;padding:11px 12px;border:1px solid var(--line);border-radius:12px}.chapter input{accent-color:var(--accent)}.chapter small{display:block;color:var(--muted)}.empty{border:1px dashed var(--line);border-radius:12px;padding:30px;text-align:center;color:var(--muted)}.log{background:#18231f;color:#cfe3d6;border-radius:12px;padding:15px;font:12px/1.7 ui-monospace,monospace;white-space:pre-wrap;min-height:90px}.footer{color:var(--muted);font-size:12px;margin-top:18px}.footer a{color:var(--accent2)}@media(max-width:800px){main{padding:25px 16px 50px}.top{margin-bottom:32px}.pill{display:none}.grid{grid-template-columns:1fr}.hero h2{font-size:48px}.row{grid-template-columns:1fr}}
</style></head><body><main>
<div class="top"><div class="brand"><div class="mark">▤</div><div><div class="eyebrow">Local web converter</div><h1>Panel Press</h1><p>From web page to reader-ready file.</p></div></div><div class="pill">Kindle · Kobo · CBZ</div></div>
<section class="hero"><div class="eyebrow">Your reading shelf, rebuilt</div><h2>Turn a chapter link into a <em>clean comic file.</em></h2><p>Paste a series URL, choose the pages you want, and package them for your e-reader. The parser is source-agnostic and can be tuned for other sites.</p></section>
<div class="grid"><section class="card"><h3>1 · Find your source</h3><div class="field"><label for="url">Series or chapter URL</label><input class="input" id="url" value="https://weebcentral.com/series/01J76XYBR7JHFW7Q80MHJP5VYW/Fire-Punch" placeholder="https://example.com/series/..." type="url"><div class="hint">The default adapter understands WeebCentral. Generic sites use visible chapter links and page images.</div></div><div class="field"><label for="files">Or import local images / PDF / folder</label><input class="input" id="files" type="file" multiple webkitdirectory directory accept=".pdf,.jpg,.jpeg,.png,.webp,.gif,.json"><div class="hint">Choose individual files or a crawler folder such as <code>output/crawled/Fire_Punch</code>. Crawler metadata preserves source and reading direction.</div></div><div class="row"><div class="field"><label for="title">Book name</label><input class="input" id="title" placeholder="Uses the source title if blank" type="text"><div class="hint">Used for the combined file and as the prefix for batch files.</div></div><div class="field"><label for="profile">Reader profile</label><select id="profile"><option value="kindle-paperwhite">Kindle Paperwhite · 1072×1448</option><option value="kindle-scribe">Kindle Scribe · 1860×2480</option><option value="kobo-clara">Kobo Clara · 1072×1448</option><option value="kobo-libra">Kobo Libra · 1264×1680</option><option value="original">Original dimensions</option></select></div></div><div class="row"><div class="field"><label for="format">Output format</label><select id="format"><option value="auto">Auto · use profile</option><option value="mobi">MOBI · requires KindleGen</option><option value="epub">EPUB · Send to Kindle / Kobo</option><option value="kepub">KEPUB · Kobo</option><option value="cbz">CBZ · archive</option><option value="pdf">PDF · fixed pages</option></select></div><div class="field"><label for="quality">Image quality</label><select id="quality"><option value="balanced">Balanced · KCC optimized</option><option value="best">Best quality · larger file</option><option value="compact">Compact · smaller file</option></select></div></div><div class="row"><div class="field"><label for="packaging">Packaging</label><select id="packaging"><option value="combined">One file · chapter navigation</option><option value="separate">Separate file per chapter</option></select></div><div class="field"><label for="direction">Reading direction</label><select id="direction"><option value="auto">Auto · detect from source</option><option value="ltr">Left to right</option><option value="rtl">Right to left · manga</option></select><div class="hint">Auto uses manga defaults for known manga sources and keeps webtoons left-to-right.</div></div></div><div class="row"><div class="field"><label for="webtoon">Processing mode</label><select id="webtoon"><option value="false">Manga / comic pages</option><option value="true">Webtoon · long strips</option></select></div><div class="field"><label for="divider">Chapter divider</label><select id="divider"><option value="false">No divider page</option><option value="true">Add divider before each chapter</option></select></div></div><div class="actions"><button class="button primary" id="scan">Scan chapters</button><span class="status" id="scanStatus"></span></div></section>
<section class="card"><h3>2 · Select & package</h3><div id="chapterList" class="empty">Scan a link or choose local files.</div><div class="actions"><button class="button secondary" id="all" disabled>Select all</button><button class="button primary" id="convert" disabled>Build reader file</button></div><div class="hint">KCC uses MOBI for Kindle only when KindleGen is available; otherwise it creates fixed-layout EPUB for Send to Kindle. Kobo profiles produce KEPUB/EPUB. A compatible CBZ/EPUB fallback is available if KCC dependencies are missing.</div></section></div>
<section class="card" style="margin-top:20px"><h3>Activity</h3><div class="log" id="log">Ready. Downloads happen on this machine, so the browser never needs direct access to the source site.</div><div class="footer">Use only material you are authorized to download. Based on the ordered-image, device-profile, and webtoon workflow documented by <a href="https://github.com/ciromattia/kcc" target="_blank">KCC</a>.</div></section>
</main><script>
let chapters=[];const $=id=>document.getElementById(id);const read=(id,fallback='')=>{const el=$(id);return el?el.value:fallback};const selectedFiles=()=>Array.from($('files')?.files||[]);function log(t){const el=$('log');if(el)el.textContent=t}
function updateCompatibility(capabilities={}){const profile=read('profile');const format=$('format');const kepub=format?.querySelector('option[value="kepub"]');const mobi=format?.querySelector('option[value="mobi"]');if(kepub){kepub.disabled=!profile.startsWith('kobo');if(kepub.disabled&&format.value==='kepub')format.value='auto'}if(mobi){mobi.disabled=capabilities.kindlegen===false;mobi.textContent=capabilities.kindlegen?'MOBI · requires KindleGen':'MOBI · unavailable (KindleGen missing)'}const direction=$('direction');if(direction){direction.disabled=read('webtoon')==='true';if(direction.disabled)direction.value='auto'}const divider=$('divider');if(divider){divider.disabled=read('packaging')==='separate';if(divider.disabled)divider.value='false'}}
['profile','format','packaging','webtoon'].forEach(id=>$(id)?.addEventListener('change',()=>updateCompatibility()));fetch('/api/capabilities').then(r=>r.json()).then(updateCompatibility).catch(()=>updateCompatibility());updateCompatibility();
function explainDisabledFormats(){const profile=read('profile');const kepub=$('format')?.querySelector('option[value="kepub"]');const mobi=$('format')?.querySelector('option[value="mobi"]');if(kepub)kepub.title=kepub.disabled?'Choose a Kobo profile to enable KEPUB.':'';if(mobi)mobi.title=mobi.disabled?'Install KindleGen or choose EPUB/CBZ/PDF instead.':''}['profile','format'].forEach(id=>$(id)?.addEventListener('change',explainDisabledFormats));explainDisabledFormats();
// Start with an empty source field; users choose the series URL explicitly.
$('url').value='';
function readLocator(){return {chapter_href_pattern:read('chapter_href_pattern'),chapter_number_pattern:read('chapter_number_pattern'),page_list_suffix:read('page_list_suffix')}}
function readChapterRange(){const from=Number.parseFloat(read('chapter_from'));const to=Number.parseFloat(read('chapter_to'));return {from:Number.isFinite(from)?from:null,to:Number.isFinite(to)?to:null}}
function chapterInRange(chapter){const range=readChapterRange();const number=Number.parseFloat(chapter.number);return !Number.isFinite(number)||(range.from===null||number>=range.from)&&(range.to===null||number<=range.to)}
function addLocatorFields(){const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Advanced source locator (optional)';details.append(summary);const hint=document.createElement('div');hint.className='hint';hint.textContent='Use regular expressions only for unusual sites. Leave blank for automatic detection. Example number pattern: Chapter\\s+(\\d+)';details.append(hint);const fields=[['chapter_href_pattern','Chapter link pattern','/chapters/'],['chapter_number_pattern','Chapter number pattern','Chapter\\s+(\\d+)'],['page_list_suffix','Page-list URL suffix','/images?is_prev=False']];for(const [id,labelText,placeholder] of fields){const field=document.createElement('div');field.className='field';const label=document.createElement('label');label.htmlFor=id;label.textContent=labelText;const input=document.createElement('input');input.className='input';input.id=id;input.type='text';input.placeholder=placeholder;field.append(label,input);details.append(field)}$('url')?.parentElement?.after(details)}
addLocatorFields();
function addChapterRangeFields(){const row=document.createElement('div');row.className='row';const fields=[['chapter_from','From chapter','1'],['chapter_to','To chapter','e.g. 10']];for(const [id,labelText,placeholder] of fields){const field=document.createElement('div');field.className='field';const label=document.createElement('label');label.htmlFor=id;label.textContent=labelText;const input=document.createElement('input');input.className='input';input.id=id;input.type='number';input.min='0';input.step='any';input.placeholder=placeholder;field.append(label,input);row.append(field)}const hint=document.createElement('div');hint.className='hint';hint.textContent='Optional: only chapters in this inclusive range will be selected for download.';row.append(hint);$('url')?.parentElement?.after(row);const saveField=document.createElement('div');saveField.className='field';const saveLabel=document.createElement('label');saveLabel.htmlFor='save_source';saveLabel.textContent='Source image folder';const save=document.createElement('select');save.id='save_source';save.innerHTML='<option value="false">Do not keep source images</option><option value="true">Keep folder + downloadable ZIP</option>';const saveHint=document.createElement('div');saveHint.className='hint';saveHint.textContent='By default, source images are temporary and removed after conversion.';saveField.append(saveLabel,save,saveHint);$('url')?.parentElement?.after(saveField);['chapter_from','chapter_to'].forEach(id=>$(id)?.addEventListener('input',()=>{if(chapters.length)render()}))}
addChapterRangeFields();
$('files')?.nextElementSibling?.replaceChildren(document.createTextNode('Choose images, one PDF, multiple PDFs, or a crawler folder. Multiple PDFs become ordered chapters using their filenames.'));
function addExportFields(){const row=document.createElement('div');row.className='row';const make=(id,label,placeholder)=>{const field=document.createElement('div');field.className='field';const labelNode=document.createElement('label');labelNode.textContent=label;labelNode.htmlFor=id;const input=document.createElement('input');input.className='input';input.id=id;input.placeholder=placeholder;input.type='text';field.append(labelNode,input);return field};row.append(make('author','Author','Optional author name'),make('export_name','Export filename','Uses book name if blank'));$('title')?.parentElement?.parentElement?.after(row)}addExportFields();
setTimeout(()=>{const previousFetch=window.fetch;window.fetch=(url,options={})=>{if(url==='/api/v1/conversions'&&options.body){if(options.body instanceof FormData){options.body.append('author',read('author'));options.body.append('export_name',read('export_name'))}else{const data=JSON.parse(options.body);data.author=read('author');data.export_name=read('export_name');options.body=JSON.stringify(data)}}return previousFetch(url,options)}},0);
// Keep the profile picker aligned with the device profiles supported by KCC.
const readerProfiles=[
  ['kindle-paperwhite','Kindle Paperwhite 5 / Signature · 1236×1648'],['kindle-paperwhite-6','Kindle Paperwhite 6 · 1272×1696'],['kindle-paperwhite-legacy','Kindle Paperwhite 1 / 2 · 758×1024'],['kindle-basic','Kindle Basic 8 / 10 · 600×800'],['kindle-voyage','Kindle Voyage · 1072×1448'],['kindle-oasis','Kindle Oasis 2 / 3 · 1264×1680'],['kindle-colorsoft','Kindle Colorsoft · 1272×1696'],['kindle-scribe','Kindle Scribe · 1860×2480'],['kobo-clara','Kobo Clara HD / 2E · 1072×1448'],['kobo-clara-colour','Kobo Clara Colour · 1072×1448'],['kobo-libra','Kobo Libra H2O / 2 · 1264×1680'],['kobo-libra-colour','Kobo Libra Colour · 1264×1680'],['kobo-forma','Kobo Forma · 1440×1920'],['kobo-sage','Kobo Sage · 1440×1920'],['kobo-elipsa','Kobo Elipsa · 1404×1872'],['kobo-mini','Kobo Mini / Touch · 600×800'],['kobo-glo','Kobo Glo · 768×1024'],['kobo-glo-hd','Kobo Glo HD · 1072×1448'],['kobo-nia','Kobo Nia · 758×1024'],['kobo-aura','Kobo Aura · 758×1024'],['kobo-aura-hd','Kobo Aura HD · 1080×1440'],['kobo-aura-h2o','Kobo Aura H2O · 1080×1430'],['kobo-aura-one','Kobo Aura ONE · 1404×1872'],['original','Original dimensions']
];$('profile').innerHTML=readerProfiles.map(([value,label])=>`<option value="${value}">${label}</option>`).join('');
const folderMode=document.createElement('select');folderMode.id='folder_mode';folderMode.innerHTML='<option value="combined">One folder for this job</option><option value="separate">Separate folder for each link</option>';const folderLabel=document.createElement('label');folderLabel.textContent='Download folders';folderLabel.htmlFor='folder_mode';const folderField=document.createElement('div');folderField.className='field';folderField.append(folderLabel,folderMode);const packagingField=$('packaging');if(packagingField?.parentElement?.parentElement)packagingField.parentElement.parentElement.appendChild(folderField);
const nativeFetch=window.fetch;window.fetch=(url,options={})=>{if(url==='/api/v1/conversions'&&options.body){if(options.body instanceof FormData){options.body.append('folder_mode',folderMode.value)}else{const data=JSON.parse(options.body);data.folder_mode=folderMode.value;options.body=JSON.stringify(data)}}return nativeFetch(url,options)};
const locatorFetch=window.fetch;window.fetch=(url,options={})=>{if(options.body&&(url==='/api/v1/scans'||url==='/api/v1/conversions')){if(options.body instanceof FormData){const locator=readLocator();for(const [key,value] of Object.entries(locator))options.body.append(key,value)}else{const data=JSON.parse(options.body);data.locator=readLocator();options.body=JSON.stringify(data)}}return locatorFetch(url,options)};
const sourceFetch=window.fetch;window.fetch=(url,options={})=>{if(url==='/api/v1/conversions'&&options.body){if(options.body instanceof FormData)options.body.append('save_source',read('save_source','false'));else{const data=JSON.parse(options.body);data.save_source=read('save_source','false');options.body=JSON.stringify(data)}}return sourceFetch(url,options)};
$('files').onchange=()=>{if($('files').files.length){chapters=[];const images=[...$('files').files].filter(f=>/\.(jpe?g|png|webp|gif|pdf)$/i.test(f.name));$('chapterList').className='empty';$('chapterList').textContent=images.length+' image/PDF file(s) ready. Build the reader file to continue.';$('all').disabled=true;$('convert').disabled=images.length===0;$('scanStatus').textContent='Local import selected'}};
$('scan').onclick=async()=>{const url=read('url').trim();if(!url)return; $('scan').disabled=true;$('scanStatus').textContent='Fetching metadata…';log('Scanning '+url+'\nRespecting the configured request delay.');try{const r=await fetch('/api/v1/scans',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({url,delay:Number(read('delay','1'))})});const d=await r.json();if(!r.ok)throw Error(d.error);chapters=d.chapters||[];render();$('scanStatus').textContent=d.title+' · '+chapters.length+' chapters';log('Found '+chapters.length+' chapters in “'+d.title+'”. Select what you want to package.')}catch(e){$('scanStatus').textContent='Scan failed';log('Error: '+e.message)}finally{$('scan').disabled=false}}
function render(){const box=$('chapterList');if(!chapters.length){box.className='empty';box.textContent='No chapters found automatically. Open “Advanced source locator” above and enter a pattern, then scan again. Example: Chapter\\s+(\\d+)';const details=document.querySelector('details');if(details)details.open=true;$('all').disabled=true;$('convert').disabled=true;return}const range=readChapterRange();const selectedCount=chapters.filter(chapterInRange).length;box.className='chapters';box.innerHTML=chapters.map((c,i)=>`<label class="chapter"><input type="checkbox" data-i="${i}" ${chapterInRange(c)?'checked':''}><span><strong>${c.title||'Chapter '+c.number}</strong><small>${c.number?'Chapter '+c.number+' · ':''}${c.url}</small></span></label>`).join('');$('all').disabled=false;$('all').textContent=range.from!==null||range.to!==null?'Select all in range':'Select all';$('convert').disabled=selectedCount===0;$('scanStatus').textContent=$('scanStatus').textContent.replace(/ · selected \d+ chapters$/,'')+(range.from!==null||range.to!==null?' · selected '+selectedCount+' chapters':'')}
$('all').onclick=()=>document.querySelectorAll('.chapter input').forEach((x,i)=>x.checked=chapterInRange(chapters[i]));
$('convert').onclick=async()=>{const selected=[...document.querySelectorAll('.chapter input:checked')].map(x=>chapters[Number(x.dataset.i)]);if(!selected.length && !selectedFiles().length)return; $('convert').disabled=true;log('Starting download and packaging…');try{let body,headers={};if(selectedFiles().length){body=new FormData();const files=[...selectedFiles()].filter(f=>/\.(jpe?g|png|webp|gif|pdf|json)$/i.test(f.name)).sort((a,b)=>(a.webkitRelativePath||a.name).localeCompare(b.webkitRelativePath||b.name,undefined,{numeric:true,sensitivity:'base'}));for(const file of files)body.append('files',file);body.append('relative_paths',JSON.stringify(files.map(file=>file.webkitRelativePath||file.name)));body.append('title',read('title')||files[0]?.webkitRelativePath?.split('/')[0]||files[0]?.name?.replace(/\.[^.]+$/,'')||'Comic');body.append('profile',read('profile'));body.append('format',read('format'));body.append('quality',read('quality'));body.append('packaging',read('packaging'));body.append('divider',read('divider'));body.append('delay',read('delay'));body.append('webtoon',read('webtoon'));body.append('direction',read('direction'))}else{headers={'content-type':'application/json'};body=JSON.stringify({url:read('url'),title:read('title'),profile:read('profile'),format:read('format'),quality:read('quality'),packaging:read('packaging'),divider:read('divider'),delay:Number(read('delay')),webtoon:read('webtoon')==='true',direction:read('direction'),chapters:selected})}const r=await fetch('/api/v1/conversions',{method:'POST',headers,body});const d=await r.json();if(!r.ok)throw Error(d.error);poll(d.job_id)}catch(e){log('Error: '+e.message);$('convert').disabled=false}}
async function poll(id){const r=await fetch('/api/v1/conversions/'+id),d=await r.json();log(d.message||'Working…');if(d.status==='done'){log(d.message+'\n\nDownload: '+d.files.join(', '));$('convert').disabled=false;return}if(d.status==='error'){$('convert').disabled=false;return}setTimeout(()=>poll(d.job_id||id),900)}
</script></body></html>'''


def generic_discover(series_url: str, delay: float, locator: dict[str, object] | None = None) -> tuple[str, list[Chapter]]:
    """Fallback parser for sites with conventional chapter links."""
    from html.parser import HTMLParser

    class Links(HTMLParser):
        def __init__(self): super().__init__(); self.rows=[]; self.href=None; self.text=[]; self.title=''
        def handle_starttag(self, tag, attrs):
            d=dict(attrs)
            if tag == 'h1' and not self.title: self.href='__title__'; self.text=[]
            if tag == 'a' and d.get('href'): self.href=d['href']; self.text=[]
        def handle_data(self, data):
            if self.href is not None: self.text.append(data)
        def handle_endtag(self, tag):
            if self.href == '__title__': self.title=' '.join(''.join(self.text).split()); self.href=None
            elif tag == 'a' and self.href: self.rows.append((self.href,' '.join(''.join(self.text).split()))); self.href=None
    locator = locator or {}
    href_pattern = str(locator.get('chapter_href_pattern') or r'(chapter|episode|volume|ch[- _]?[0-9])')
    number_pattern = str(locator.get('chapter_number_pattern') or r'(?:chapter|ch|episode|ep|volume|vol|meeting)[^0-9]*([0-9]+(?:[.][0-9]+)?)')
    try: href_re=re.compile(href_pattern,re.I)
    except re.error: href_re=re.compile(r'(chapter|episode|volume|ch[- _]?[0-9])',re.I)
    try: number_re=re.compile(number_pattern,re.I)
    except re.error: number_re=re.compile(r'(?:chapter|ch|episode|ep|volume|vol|meeting)[^0-9]*([0-9]+(?:[.][0-9]+)?)',re.I)
    parser=Links(); parser.feed(fetch(series_url, delay=delay).decode('utf-8','replace'))
    rows=[]; seen=set()
    for href,label in parser.rows:
        if not href_re.search(label+' '+href): continue
        url=urljoin(series_url,href)
        if url in seen: continue
        seen.add(url); m=number_re.search(label+' '+href)
        number=m.group(1) if m else str(len(rows)+1)
        rows.append(Chapter(number,strip_reader_metadata(label or 'Chapter '+number),url,url.rstrip('/').split('/')[-1]))
    return parser.title or Path(urlparse(series_url).path).name or 'Comic', rows


def scan(url: str, delay: float, locator: dict[str, object] | None = None):
    if 'weebcentral.com' in urlparse(url).netloc:
        return discover_chapters(url, delay, locator)
    return generic_discover(url, delay, locator)


def generic_discover_pages(chapter: Chapter, delay: float) -> list[str]:
    """Collect page images directly from a conventional chapter HTML page."""
    from html.parser import HTMLParser

    class Images(HTMLParser):
        def __init__(self): super().__init__(); self.urls=[]
        def handle_starttag(self, tag, attrs):
            if tag != 'img': return
            data=dict(attrs)
            value=data.get('data-src') or data.get('data-lazy-src') or data.get('src')
            if value and not value.startswith('data:'): self.urls.append(urljoin(chapter.url,value))
    parser=Images(); parser.feed(fetch(chapter.url, delay=delay).decode('utf-8','replace'))
    return list(dict.fromkeys(parser.urls))


def chapter_pages(chapter: Chapter, delay: float, locator: dict[str, object] | None = None) -> list[str]:
    if 'weebcentral.com' in urlparse(chapter.url).netloc:
        return discover_pages(chapter, delay, locator)
    return generic_discover_pages(chapter, delay)


def normalize_image(source: Path, target: Path, size: tuple[int, int]) -> None:
    try:
        from PIL import Image, ImageOps
        image=Image.open(source).convert('RGB')
        if size != (0, 0): image.thumbnail(size, Image.Resampling.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True); image.save(target, 'JPEG', quality=88, optimize=True)
    except ImportError:
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)


def image_suffix(path: Path) -> str:
    """Prefer the bytes' real format over a misleading source filename."""
    header=path.read_bytes()[:12]
    if header.startswith(b'\xff\xd8\xff'): return '.jpg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'): return '.png'
    if header.startswith((b'GIF87a',b'GIF89a')): return '.gif'
    if header[:4]==b'RIFF' and header[8:12]==b'WEBP': return '.webp'
    return path.suffix.lower() or '.jpg'


def make_cbz(folder: Path, title: str, out: Path) -> None:
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for page in sorted(folder.glob('*')):
            if page.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'}: z.write(page, 'images/'+page.name)


def make_pdf(folder: Path, out: Path) -> None:
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise RuntimeError('PDF fallback needs Pillow.') from exc
    pages=[]
    for page in sorted(folder.glob('*'), key=natural_sort_key):
        if page.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'}:
            with Image.open(page) as image:
                pages.append(image.convert('RGB'))
    if not pages:
        raise RuntimeError('No pages available for PDF output.')
    pages[0].save(out, 'PDF', save_all=True, append_images=pages[1:], resolution=150.0)
    for page in pages:
        page.close()


def make_epub(folder: Path, title: str, out: Path, size: tuple[int,int], direction: str = 'ltr') -> None:
    pages=sorted(p for p in folder.glob('*') if p.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'})
    try:
        import PIL.Image  # type: ignore
        pillow_available=True
    except ImportError:
        pillow_available=False
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('mimetype','application/epub+zip',compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml','<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        manifest=[]; spine=[]
        for i,page in enumerate(pages,1):
            suffix='.jpg' if pillow_available else image_suffix(page); name=f'page-{i:04d}{suffix}'; normalize_image(page, folder / name, size)
            media_type=mimetypes.guess_type(name)[0] or 'image/jpeg'
            z.write(folder/name,'OEBPS/'+name); manifest.append(f'<item id="i{i}" href="{name}" media-type="{media_type}"/>'); manifest.append(f'<item id="p{i}" href="p{i}.xhtml" media-type="application/xhtml+xml"/>'); spine.append(f'<itemref idref="p{i}"/>')
            z.writestr(f'OEBPS/p{i}.xhtml',f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title><style>html,body{{margin:0;padding:0;text-align:center;background:#000}}img{{max-width:100%;max-height:100vh}}</style></head><body><img src="{name}" alt="Page {i}"/></body></html>')
        nav_items=''.join(f'<li><a href="p{i}.xhtml">Page {i}</a></li>' for i in range(1,len(pages)+1))
        nav=(f'<?xml version="1.0" encoding="utf-8"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><head><title>{html.escape(title)}</title></head><body><nav epub:type="toc" id="toc"><h1>{html.escape(title)}</h1><ol>{nav_items}</ol></nav></body></html>')
        manifest.append('<item id="nav" href="nav.xhtml" properties="nav" media-type="application/xhtml+xml"/>')
        manifest_xml=''.join(manifest); spine_xml=''.join(spine)
        opf=f'<?xml version="1.0" encoding="utf-8"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="bookid">panel-press-{uuid.uuid4()}</dc:identifier><dc:title>{title}</dc:title><dc:language>en</dc:language><meta property="rendition:layout">pre-paginated</meta><meta property="rendition:orientation">auto</meta></metadata><manifest>{manifest_xml}</manifest><spine page-progression-direction="{direction}">{spine_xml}</spine></package>'
        z.writestr('OEBPS/content.opf',opf)
        z.writestr('OEBPS/nav.xhtml',nav)


def normalize_epub_reading_order(epub: Path, direction: str) -> None:
    """Make KCC EPUBs portable by removing reader-dependent spread hints."""
    if not epub.exists() or epub.suffix.lower() != '.epub':
        return
    with zipfile.ZipFile(epub, 'r') as archive:
        members = {info.filename: archive.read(info.filename) for info in archive.infolist()}
    opf_name = 'OEBPS/content.opf'
    if opf_name not in members:
        return
    opf = members[opf_name].decode('utf-8')
    opf = re.sub(r'\s+properties="(?:rendition:)?page-spread-(?:left|right)"', '', opf)
    opf = re.sub(r'(<spine\b[^>]*?)page-progression-direction="(?:ltr|rtl)"',
                 rf'\1page-progression-direction="{direction}"', opf, count=1)
    members[opf_name] = opf.encode('utf-8')
    temporary = epub.with_suffix(epub.suffix + '.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            compression = zipfile.ZIP_STORED if name == 'mimetype' else zipfile.ZIP_DEFLATED
            archive.writestr(name, data, compress_type=compression)
    temporary.replace(epub)


def find_kcc() -> list[str] | None:
    """Find the official KCC CLI without making it a hard dependency."""
    configured=os.environ.get('KCC_COMMAND')
    if configured: return shlex.split(configured)
    bundled=ROOT/'vendor'/'kcc'/'kcc-c2e.py'
    if bundled.exists():
        try:
            for module in ('PIL','psutil','slugify','packaging','natsort','pymupdf','numpy','mozjpeg_lossless_optimization'):
                __import__(module)
            return [sys.executable,str(bundled)]
        except ImportError:
            pass
    executable=shutil.which('kcc-c2e') or shutil.which('kcc-c2e.py')
    if executable: return [executable]
    return None


def extract_pdf(pdf: Path, target: Path) -> None:
    converter=shutil.which('pdftoppm')
    if not converter:
        raise RuntimeError('PDF import needs KCC/PyMuPDF or the pdftoppm command.')
    target.mkdir(parents=True,exist_ok=True)
    subprocess.run([converter,'-jpeg','-r','150',str(pdf),str(target/'page')],check=True,capture_output=True)
    for index,page in enumerate(sorted(target.glob('page-*.jpg')),1): page.rename(target/f'{index:04d}.jpg')


def uploaded_metadata(paths: list[Path], relative_paths: list[str] | None = None) -> dict[str, object]:
    """Read crawler metadata included with a browser folder upload."""
    for index,path in enumerate(paths):
        relative=Path(relative_paths[index]) if relative_paths and index < len(relative_paths) else path
        if relative.name.lower() != 'series.json': continue
        try:
            data=json.loads(path.read_text(encoding='utf-8'))
            return data if isinstance(data,dict) else {}
        except (OSError,UnicodeDecodeError,json.JSONDecodeError):
            return {}
    return {}


def prepare_local_import(paths: list[Path], target: Path, relative_paths: list[str] | None = None) -> None:
    target.mkdir(parents=True,exist_ok=True)
    pdfs=[p for p in paths if p.suffix.lower()=='.pdf']
    if pdfs:
        media=[p for p in paths if p.suffix.lower() in {'.pdf','.jpg','.jpeg','.png','.webp','.gif'}]
        if len(media) != len(pdfs): raise RuntimeError('PDF files cannot be mixed with image files. Upload PDFs together or upload images separately.')
        if len(pdfs)==1:
            extract_pdf(pdfs[0],target)
            return
        # Multiple PDFs become ordered chapter folders based on their upload
        # paths/names, so the existing KCC chapter and batch packaging logic
        # can process them without merging page streams out of order.
        relative_by_path={path: (relative_paths[index] if relative_paths and index < len(relative_paths) else path.name) for index,path in enumerate(paths)}
        for chapter_index,pdf in enumerate(sorted(pdfs,key=lambda pdf: volume_sort_key(relative_by_path[pdf])),1):
            volume=extract_volume_number(pdf.stem)
            label=f'volume-{volume:03d}' if volume is not None else safe_name(pdf.stem)
            chapter_dir=target/f'{chapter_index:04d}-{label}'
            extract_pdf(pdf,chapter_dir)
        return
    image_rows=[]
    for index,path in enumerate(paths):
        if path.suffix.lower() not in {'.jpg','.jpeg','.png','.webp','.gif'}: continue
        relative=Path(relative_paths[index]) if relative_paths and index < len(relative_paths) else Path(f'{index+1:04d}{path.suffix.lower()}')
        # Browser directory uploads include the selected folder as their first
        # path segment; KCC should receive the tree beneath that folder.
        parts=[safe_name(part) for part in relative.parts if part not in {'','.','..'}]
        if relative_paths and len(parts)>1: parts=parts[1:]
        image_rows.append((path,parts))
    if not image_rows: raise RuntimeError('No supported images or PDF found.')

    # Crawler exports may contain old preview files beside their canonical
    # chapters tree. Feed only chapters/<chapter>/<page> to KCC and remove the
    # wrapper so every direct child is one ordered chapter.
    crawler_layout=any(parts and parts[0].lower()=='chapters' for _,parts in image_rows)
    if crawler_layout:
        image_rows=[(path,parts[1:]) for path,parts in image_rows if parts and parts[0].lower()=='chapters']
    for index,(path,parts) in enumerate(image_rows,1):
        destination=target.joinpath(*parts) if parts else target/f'{index:04d}{image_suffix(path)}'
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination)


def natural_sort_key(path: Path | str):
    value=str(path)
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)',value)]


def extract_volume_number(value: str) -> int | None:
    match=re.search(r'\b(?:vol(?:ume)?|v)\s*[._-]?\s*(\d+)\b',str(value),re.I)
    return int(match.group(1)) if match else None


def volume_sort_key(path: Path | str):
    value=str(path)
    volume=extract_volume_number(value)
    return (0,volume,natural_sort_key(value)) if volume is not None else (1,0,natural_sort_key(value))


def export_paths(title: str) -> tuple[Path,Path,Path]:
    """Return isolated export, ebook-file, and batch-chapter directories."""
    root=EXPORTS/safe_name(title)
    return root,root/'files',root/'chapters'


def chapter_directories(source: Path) -> list[Path]:
    return sorted((directory for directory in source.rglob('*') if directory.is_dir() and any(p.is_file() and p.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'} for p in directory.iterdir())),key=natural_sort_key)


def copy_ordered_tree(source: Path, destination: Path) -> None:
    """Copy a KCC input tree in natural order, independent of filesystem order."""
    destination.mkdir(parents=True,exist_ok=True)
    entries=sorted(source.iterdir(),key=natural_sort_key)
    for entry in entries:
        target=destination/entry.name
        if entry.is_dir():
            copy_ordered_tree(entry,target)
        elif entry.is_file():
            shutil.copy2(entry,target)


def add_chapter_dividers(source: Path) -> None:
    """Add an image page at the start of every chapter."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError('Chapter divider pages require Pillow.') from exc
    chapters=chapter_directories(source)
    for directory in sorted(chapters,key=natural_sort_key):
        page=directory/'0000-divider.jpg'
        image=Image.new('RGB',(1600,2400),'white'); draw=ImageDraw.Draw(image); font=ImageFont.load_default()
        label=directory.name.replace('_',' ')
        draw.text((120,1120),label,fill='black',font=font)
        image.save(page,quality=90)


def clean_chapter_label(label: str) -> str:
    """Turn KCC's folder-style chapter labels into reader-friendly labels."""
    label=html.unescape(label).replace('_',' ').replace('-',' ').strip()
    label=re.sub(r'^\d+[\s._]+','',label)
    label=re.sub(r'^chapter\s*[._-]*\s*(\d+(?:\.\d+)?)$',r'Chapter \1',label,flags=re.I)
    label=re.sub(r'^volume\s*[._-]*\s*0*(\d+)$',r'Volume \1',label,flags=re.I)
    label=re.sub(r'\s+',' ',label)
    return label[:1].upper()+label[1:] if label else 'Chapter'


def update_epub_navigation(epub: Path, source: Path | None = None) -> None:
    """Keep KCC's native clickable TOC without adding a physical contents page."""
    if not epub.exists() or not epub.name.endswith('.epub'): return
    with zipfile.ZipFile(epub,'r') as archive:
        entries={name:archive.read(name) for name in archive.namelist()}
    nav_name='OEBPS/nav.xhtml'
    opf_name='OEBPS/content.opf'
    if nav_name not in entries or opf_name not in entries: return
    nav=entries[nav_name].decode('utf-8')
    # KCC currently writes a page-list containing the same chapter links as
    # the TOC. It is not a real page index and some readers surface it as a
    # second, misleading contents view.
    nav=re.sub(r'<nav\b[^>]*epub:type="page-list"[^>]*>.*?</nav>\s*','',nav,flags=re.S)
    chapter_dirs=sorted(chapter_directories(source),key=natural_sort_key) if source and source.is_dir() else []
    labels={}
    chapter_index=0
    for href,old_label in re.findall(r'<li>\s*<a href="([^"]+)">([^<]+)</a>\s*</li>',nav):
        if not href.startswith('Text/') or href.count('/') < 2: continue
        if chapter_index < len(chapter_dirs):
            label=clean_chapter_label(chapter_dirs[chapter_index].name)
        else:
            label=clean_chapter_label(old_label)
        labels[href]=label
        chapter_index+=1

    def replace_nav_item(match: re.Match[str]) -> str:
        href,label=match.group(1),match.group(2)
        return match.group(0).replace(f'>{label}</a>',f'>{html.escape(labels.get(href,clean_chapter_label(label)))}</a>')

    nav=re.sub(r'<li>\s*<a href="([^"]+)">([^<]+)</a>\s*</li>',replace_nav_item,nav)
    nav=re.sub(r'<li>\s*<a href="Text/panel-contents\.xhtml">[^<]*</a>\s*</li>\s*','',nav)
    entries[nav_name]=nav.encode('utf-8')

    opf=entries[opf_name].decode('utf-8')
    opf=re.sub(r'<item\s+id="panel-contents"[^>]*/>\s*','',opf)
    opf=re.sub(r'<itemref\s+idref="panel-contents"[^>]*/>\s*','',opf)
    entries[opf_name]=opf.encode('utf-8')
    entries.pop('OEBPS/Text/panel-contents.xhtml',None)

    ncx_name='OEBPS/toc.ncx'
    if ncx_name in entries and labels:
        ncx=entries[ncx_name].decode('utf-8')
        def replace_ncx_item(match: re.Match[str]) -> str:
            block=match.group(0)
            href_match=re.search(r'<content\s+src="([^"]+)"',block)
            if not href_match: return block
            href=href_match.group(1)
            return re.sub(r'(<navLabel>\s*<text>).*?(</text>)',rf'\1{html.escape(labels.get(href, "Chapter"))}\2',block,count=1,flags=re.S)
        entries[ncx_name]=re.sub(r'<navPoint\b.*?</navPoint>',replace_ncx_item,ncx,flags=re.S).encode('utf-8')

    temporary=epub.with_suffix(epub.suffix+'.tmp')
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in entries.items(): archive.writestr(name,data)
    temporary.replace(epub)


def add_pdf_navigation(pdf: Path, source: Path, title: str, profile: dict[str, object], divider_pages: bool) -> None:
    """Add PDF bookmarks and links from physical contents pages to chapters."""
    try:
        import fitz  # type: ignore
    except ImportError:
        return
    chapters=sorted(chapter_directories(source),key=natural_sort_key)
    if not chapters: return
    counts=[sum(1 for page in chapter.iterdir() if page.is_file() and page.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'}) for chapter in chapters]
    width,height=tuple(profile.get('size',(1200,1600)))
    lines_per_page=max(12,(height-220)//34)
    contents_pages=(len(chapters)+lines_per_page-1)//lines_per_page if divider_pages else 0
    toc=[]
    page_cursor=contents_pages
    targets=[]
    for index,(chapter,count) in enumerate(zip(chapters,counts)):
        if divider_pages: page_cursor += 1
        target=page_cursor
        targets.append(target)
        toc.append([1,chapter.name, target+1])
        page_cursor += count
    document=fitz.open(pdf)
    existing_toc=document.get_toc()
    if existing_toc:
        toc=existing_toc
        targets=[entry[2]-1 for entry in toc[:len(chapters)]]
    else:
        document.set_toc(toc)
    if divider_pages and contents_pages:
        for item_index,(chapter,target) in enumerate(zip(chapters,targets)):
            contents_index=item_index//lines_per_page
            line_index=item_index%lines_per_page+1
            page=document[contents_index]
            scale_x=page.rect.width/float(width); scale_y=page.rect.height/float(height)
            y1=(100+line_index*34-8)*scale_y; y2=(100+line_index*34+22)*scale_y
            page.insert_link({'kind':fitz.LINK_GOTO,'from':fitz.Rect(60*scale_x,y1,(width-60)*scale_x,y2),'page':target})
    temporary=pdf.with_suffix(pdf.suffix+'.tmp')
    document.save(temporary,garbage=4,deflate=True)
    document.close()
    temporary.replace(pdf)


def kcc_source_root(source: Path) -> Path:
    """Remove one browser-upload wrapper when it is not a chapter itself."""
    if not source.is_dir(): return source
    root_images=[p for p in source.iterdir() if p.is_file() and p.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'}]
    directories=[p for p in source.iterdir() if p.is_dir()]
    if not root_images:
        chapter_containers=[candidate for candidate in directories if any(
            child.is_dir() and any(q.is_file() and q.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'} for q in child.iterdir())
            for child in candidate.iterdir()
        )]
        if len(chapter_containers)==1:
            return chapter_containers[0]
    return source


def run_kcc(source: Path, title: str, profile: dict[str, object], output_root: Path, webtoon: bool, direction: str, requested_format: str = 'auto', packaging: str = 'combined', quality: str = 'balanced', divider_pages: bool = False, author: str = '') -> list[Path] | None:
    command=find_kcc()
    if not command: return None
    output_root.mkdir(parents=True,exist_ok=True)
    run_output=Path(tempfile.mkdtemp(prefix='.kcc-',dir=output_root))
    run_input=None
    kcc_profile=profile.get('kcc')
    if not kcc_profile:
        shutil.rmtree(run_output,ignore_errors=True)
        return None
    requested_format=requested_format.lower()
    output_format=str(profile['format']).upper() if requested_format=='auto' else requested_format.upper()
    kepub_output=output_format=='KEPUB'
    if kepub_output: output_format='EPUB'
    kindle_epub_fallback=requested_format=='auto' and output_format=='MOBI' and not shutil.which('kindlegen')
    if kindle_epub_fallback: output_format='EPUB'
    args=command+['-p',str(kcc_profile),'-f',output_format,'-o',str(run_output),'-t',title,'-a',author.strip()]
    if kindle_epub_fallback or (output_format=='EPUB' and not kepub_output): args.append('--nokepub')
    if webtoon: args.append('--webtoon')
    if direction=='rtl': args.append('--manga-style')
    if packaging=='separate': args.extend(['-b','2'])
    if quality=='best': args.extend(['-q','--jpeg-quality','92'])
    elif quality=='compact': args.extend(['--jpeg-quality','72'])
    else: args.extend(['--jpeg-quality','85'])
    try:
        if source.is_dir():
            run_input_root=Path(tempfile.mkdtemp(prefix='.input-',dir=output_root))
            run_input=run_input_root/source.name
            copy_ordered_tree(source,run_input)
            if divider_pages:
                add_chapter_dividers(run_input)
            source_for_kcc=run_input
        else:
            source_for_kcc=source
        result=subprocess.run(args+[str(source_for_kcc)],text=True,capture_output=True)
        if result.returncode:
            detail=(result.stderr or result.stdout or 'KCC conversion failed').strip()
            raise RuntimeError('KCC failed: '+detail[-1200:])
        extensions={'.mobi','.epub','.cbz','.pdf','.kfx'}
        generated=[p for p in run_output.iterdir() if p.is_file() and p.suffix.lower() in extensions]
        files=[]
        for path in sorted(generated,key=lambda p:p.stat().st_mtime,reverse=True):
            destination=output_root/path.name
            if destination.exists(): destination.unlink()
            path.replace(destination)
            files.append(destination)
        return files
    finally:
        if run_input is not None:
            shutil.rmtree(run_input.parent,ignore_errors=True)
        shutil.rmtree(run_output,ignore_errors=True)


def rename_outputs(files: list[Path], output_root: Path, title: str, source: Path, packaging: str, name_prefix: str | None = None) -> list[Path]:
    """Give KCC's generated files stable, user-selected names."""
    def natural(path: Path): return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)',path.name)]
    ordered=sorted(files,key=natural)
    chapters=chapter_directories(source)
    prefix=safe_name(name_prefix or title)
    renamed=[]
    for index,path in enumerate(ordered):
        suffix=''.join(path.suffixes) or path.suffix
        if packaging=='separate' and index < len(chapters):
            name=f'{prefix} - {safe_name(chapters[index].name)}{suffix}'
        else:
            name=f'{prefix}{suffix}' if index==0 else f'{prefix} - part-{index+1}{suffix}'
        destination=output_root/name
        if destination != path and destination.exists(): destination=output_root/f'{prefix} - {index+1}{suffix}'
        if destination != path: path.replace(destination)
        renamed.append(destination)
    return renamed


MANGA_SOURCE_HOSTS = {'weebcentral.com'}


def resolve_direction(requested: str, source_url: str = '', title: str = '', webtoon: bool = False) -> str:
    """Resolve safe reading direction while keeping explicit choices authoritative."""
    requested = requested.lower().strip()
    if requested in {'ltr', 'rtl'}:
        return requested
    if webtoon:
        return 'ltr'
    host = (urlparse(source_url).hostname or '').lower().removeprefix('www.')
    if host in MANGA_SOURCE_HOSTS:
        return 'rtl'
    # Local imports cannot identify their original site, so Auto stays conservative.
    return 'ltr'


def request_delay(value: object, default: float = 1.0) -> float:
    """Parse an optional form/API delay, treating blank values as the default."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def update_job(job_id: str, message: str) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update({'status': 'working', 'message': message})


def download_to_path(url: str, target: Path, delay: float) -> Path:
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(fetch(url, delay=delay))
    return target


def save_source_folder(source: Path, title: str) -> tuple[Path, Path] | None:
    if not source.is_dir():
        return None
    saved = OUTPUT / 'crawled' / safe_name(title)
    saved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, saved, dirs_exist_ok=True)
    zip_path = EXPORTS / safe_name(title) / 'files' / f'{safe_name(title)}.source.zip'
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(saved.rglob('*'), key=lambda item: natural_sort_key(str(item))):
            if path.is_file():
                archive.write(path, path.relative_to(saved.parent))
    return saved, zip_path


def convert_job(job_id: str, payload: dict[str, object]) -> None:
    temp: Path | None = None
    upload_dir=Path(str(payload['_upload_dir'])) if payload.get('_upload_dir') else None
    try:
        folder_mode=str(payload.get('folder_mode','combined')); save_source=str(payload.get('save_source','false')).lower()=='true' if isinstance(payload.get('save_source'),str) else bool(payload.get('save_source',False))
        profile=PROFILES.get(str(payload.get('profile')),PROFILES['original']); delay=request_delay(payload.get('delay')); webtoon=str(payload.get('webtoon',False)).lower()=='true' if isinstance(payload.get('webtoon'),str) else bool(payload.get('webtoon',False)); direction=str(payload.get('direction','auto')); requested_format=str(payload.get('format','auto')); packaging=str(payload.get('packaging','combined')); quality=str(payload.get('quality','balanced')); divider=str(payload.get('divider',False)).lower()=='true' if isinstance(payload.get('divider'),str) else bool(payload.get('divider',False)); author=str(payload.get('author') or '').strip(); export_name=safe_name(str(payload.get('export_name') or '').strip()) if str(payload.get('export_name') or '').strip() else ''
        selected=payload.get('chapters',[]); requested_title=safe_name(str(payload.get('title') or '')); title='Comic'; source_url=''; temp=Path(tempfile.mkdtemp(prefix='panel-press-')); source=temp/'source'; all_pages=[]; source_archive=None
        if payload.get('files'):
            paths=[Path(p) for p in payload['files']]
            relative_paths=payload.get('relative_paths')
            relative_paths=relative_paths if isinstance(relative_paths,list) else None
            metadata=uploaded_metadata(paths,relative_paths)
            title=requested_title or safe_name(str(metadata.get('title') or paths[0].stem))
            source_url=str(metadata.get('source') or '')
            if len(paths)==1 and paths[0].suffix.lower()=='.pdf' and find_kcc() and profile.get('kcc'):
                source=paths[0]
            else:
                prepare_local_import(paths,source,relative_paths)
        else:
            url=str(payload['url']); source_url=url; locator=payload.get('locator') if isinstance(payload.get('locator'),dict) else None
            # The browser already scanned the series. Reuse the selected rows
            # instead of fetching and parsing the entire series a second time.
            discovered_title=Path(urlparse(url).path.rstrip('/')).name or 'Comic'
            title=requested_title or safe_name(discovered_title); source.mkdir(parents=True,exist_ok=True)
            update_job(job_id, f'Preparing {len(selected)} selected chapter(s)…')
            page_jobs=[]
            for ci,row in enumerate(selected,1):
                chapter=Chapter(str(row.get('number','')),str(row.get('title','Chapter')),str(row['url']),str(row.get('chapter_id','')))
                update_job(job_id, f'Discovering pages for chapter {chapter.number} ({ci}/{len(selected)})…')
                folder=source/f'{ci:04d}-{safe_name(chapter.title or "chapter-"+chapter.number)}'; folder.mkdir(exist_ok=True)
                pages=chapter_pages(chapter,delay,locator)
                page_jobs.extend((ci,chapter.number,page,folder/f'{pi:04d}.{guess_extension(page)}') for pi,page in enumerate(pages,1))
            total_pages=len(page_jobs); completed=0
            update_job(job_id, f'Downloading 0/{total_pages} pages with {DOWNLOAD_WORKERS} workers…')
            with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
                futures=[pool.submit(download_to_path,page,target,delay) for _,_,page,target in page_jobs]
                for future in as_completed(futures):
                    future.result(); completed+=1
                    if completed==total_pages or completed%5==0:
                        update_job(job_id, f'Downloading {completed}/{total_pages} pages…')
            all_pages=sorted((p for p in source.rglob('*') if p.is_file()),key=natural_sort_key)
            if not all_pages: raise RuntimeError('No pages were found in the selected chapters.')
        if save_source:
            saved_source=save_source_folder(source,title)
            if saved_source:
                source_archive=saved_source[1]
                update_job(job_id, f'Saved source images to output/crawled/{saved_source[0].name}/…')
        direction=resolve_direction(direction, source_url, title, webtoon)
        kcc_input=kcc_source_root(source)
        export_root,output_dir,chapter_output_dir=export_paths(title)
        separate_folders=folder_mode=='separate' and not payload.get('files') and kcc_input.is_dir()
        if separate_folders:
            chapter_output_dir.mkdir(parents=True,exist_ok=True)
            for chapter_folder in chapter_directories(kcc_input):
                destination=chapter_output_dir/chapter_folder.name
                if destination.exists(): shutil.rmtree(destination)
                shutil.copytree(chapter_folder,destination)
        output_dir.mkdir(parents=True,exist_ok=True)
        pdf_output=requested_format.lower()=='pdf'
        navigation_pages=divider and packaging=='combined' and not pdf_output
        update_job(job_id, f'Packaging {len(all_pages)} pages with {profile["label"]}…')
        kcc_files=run_kcc(kcc_input,title,profile,output_dir,webtoon,direction,requested_format,packaging,quality,navigation_pages,author)
        if kcc_files:
            kcc_files=rename_outputs(kcc_files,output_dir,title,kcc_input,packaging,export_name or title)
            for generated in kcc_files:
                normalize_epub_reading_order(generated, direction)
            if packaging=='combined' and requested_format.lower() in {'auto','epub','kepub'}:
                for generated in kcc_files: update_epub_navigation(generated,kcc_input)
            if packaging=='combined':
                for generated in kcc_files:
                    if generated.suffix.lower()=='.pdf': add_pdf_navigation(generated,kcc_input,title,profile,False)
            files=['/downloads/'+p.name for p in kcc_files]
            message=f'KCC built {kcc_files[0].name} using the {profile["label"]} profile ({direction.upper()} reading).'
        else:
            pages=sorted((p for p in kcc_input.rglob('*') if p.suffix.lower() in {'.jpg','.jpeg','.png','.webp','.gif'}),key=natural_sort_key)
            flat=output_dir/'pages'; flat.mkdir(exist_ok=True)
            for i,p in enumerate(pages,1): shutil.copyfile(p,flat/f'{i:04d}{p.suffix.lower()}')
            export_prefix=export_name or title
            ext='pdf' if requested_format=='pdf' else ('epub' if requested_format in {'auto','epub','kepub'} and str(profile['format'])=='epub' else 'cbz'); out=output_dir/f'{safe_name(export_prefix)}.{ext}'
            if ext=='epub': make_epub(flat,title,out,tuple(profile['size']),direction)
            elif ext=='pdf': make_pdf(flat,out)
            else: make_cbz(flat,title,out)
            files=['/downloads/'+out.name]; message=f'Built {out.name} with {len(pages)} pages using the built-in fallback. Install KCC to enable native MOBI/KEPUB output.'
        if source_archive:
            files.append('/downloads/'+source_archive.name)
            message += f' Source images saved under output/crawled/{safe_name(title)}/.'
        if separate_folders:
            message += f' Separate chapter folders were created under output/exports/{safe_name(title)}/chapters/.'
        with JOBS_LOCK: JOBS[job_id]={'status':'done','message':message,'files':files}
    except Exception as exc:
        with JOBS_LOCK: JOBS[job_id]={'status':'error','message':str(exc)}
    finally:
        if temp is not None: shutil.rmtree(temp,ignore_errors=True)
        if upload_dir is not None: shutil.rmtree(upload_dir,ignore_errors=True)


def _has_pillow() -> bool:
    try:
        import PIL  # type: ignore
        return True
    except ImportError:
        return False


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        raw=json.dumps(data).encode(); self.send_response(status); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path == '/favicon.ico':
            self.send_response(204); self.end_headers(); return
        if self.path in {'/','/index.html'}: raw=INDEX_HTML.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if self.path in {'/api/v1/capabilities','/api/capabilities'}:
            self.send_json({'kcc': find_kcc() is not None, 'kindlegen': shutil.which('kindlegen') is not None, 'pillow': _has_pillow()}); return
        if self.path.startswith('/api/v1/conversions/') or self.path.startswith('/api/jobs/'):
            with JOBS_LOCK: self.send_json(JOBS.get(self.path.rsplit('/',1)[-1],{'status':'error','message':'Unknown job'})); return
        if self.path.startswith('/downloads/'):
            path=(OUTPUT/self.path.split('/')[-1]).resolve(); candidates=list(OUTPUT.rglob(path.name))
            if candidates and candidates[0].is_file(): path=candidates[0]; raw=path.read_bytes(); self.send_response(200); self.send_header('Content-Type',mimetypes.guess_type(str(path))[0] or 'application/octet-stream'); self.send_header('Content-Disposition',f'attachment; filename="{path.name}"'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        self.send_error(404)
    def do_POST(self):
        length=int(self.headers.get('Content-Length','0')); content_type=self.headers.get('Content-Type',''); raw=self.rfile.read(length)
        payload={}
        if content_type.startswith('multipart/form-data'):
            form=cgi.FieldStorage(fp=__import__('io').BytesIO(raw),headers=self.headers,environ={'REQUEST_METHOD':'POST','CONTENT_TYPE':content_type,'CONTENT_LENGTH':str(length)})
            upload_dir=Path(tempfile.mkdtemp(prefix='panel-upload-')); paths=[]
            fields={'profile':'original','delay':'1','webtoon':'false','direction':'auto','title':'Comic','author':'','export_name':'','relative_paths':'[]','format':'auto','packaging':'combined','quality':'balanced','divider':'false','chapter_href_pattern':'','chapter_number_pattern':'','page_list_suffix':'','save_source':'false'}
            for key in fields:
                if key in form: fields[key]=form.getfirst(key)
            items=form['files'] if 'files' in form and isinstance(form['files'],list) else ([form['files']] if 'files' in form else [])
            for item_index,item in enumerate(items,1):
                name=safe_name(Path(item.filename or 'upload').name)
                path=upload_dir/f'{item_index:06d}-{name}'
                path.write_bytes(item.file.read()); paths.append(str(path))
            payload={**fields,'files':paths,'webtoon':fields['webtoon']=='true','locator':{key:fields[key] for key in ('chapter_href_pattern','chapter_number_pattern','page_list_suffix') if fields[key].strip()},'_upload_dir':str(upload_dir)}
            try: payload['relative_paths']=json.loads(fields['relative_paths'])
            except json.JSONDecodeError: payload['relative_paths']=[]
        else:
            payload=json.loads(raw or b'{}')
        try:
            if self.path in {'/api/v1/scans','/api/scan'}:
                title, chapters=scan(str(payload['url']),request_delay(payload.get('delay')),payload.get('locator') if isinstance(payload.get('locator'),dict) else None); self.send_json({'title':title,'chapters':[c.__dict__ for c in chapters]}); return
            if self.path in {'/api/v1/conversions','/api/convert'}:
                job_id=uuid.uuid4().hex; with_lock={'status':'working','message':'Queued…'}
                with JOBS_LOCK: JOBS[job_id]=with_lock
                threading.Thread(target=convert_job,args=(job_id,payload),daemon=True).start(); self.send_json({'job_id':job_id}); return
            self.send_error(404)
        except Exception as exc: self.send_json({'error':str(exc)},400)
    def log_message(self, *_): pass


if __name__ == '__main__':
    port=int(os.environ.get('PORT','8080')); print(f'Panel Press running at http://127.0.0.1:{port}'); ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
