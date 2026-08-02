/**
 * hatbook Service Worker —— 由 build.py 注入版本号后产出根目录 sw.js,不要直接改 sw.js
 *
 * 目标:加到手机主屏后能像 App 一样秒开、离线可读;书稿更新时不打断阅读,
 * 只在页面上提示一次「有更新」,点了才换新版。
 */
const VERSION = '870ab5effddf';
const CACHE   = 'hatbook-' + VERSION;
const BASE    = self.registration.scope;          // https://…/hatbook/
const PAGE    = BASE + 'index.html';

const CORE = [
  PAGE,
  BASE + 'manifest.webmanifest',
  BASE + 'icons/icon-192.png',
  BASE + 'icons/icon-512.png',
  BASE + 'icons/apple-touch-icon.png',
  'https://cdnjs.cloudflare.com/ajax/libs/marked/9.1.6/marked.min.js',
];

/** 用户数据 / 助教接口:一律不碰缓存 */
const isApi = url => url.hostname.endsWith('.workers.dev');
/** 允许运行时缓存的第三方(字体与 markdown 解析器) */
const cacheableThirdParty = url =>
  url.hostname === 'cdnjs.cloudflare.com' ||
  url.hostname === 'fonts.googleapis.com' ||
  url.hostname === 'fonts.gstatic.com';

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // 逐个 add:某个 CDN 挂了不能拖垮整次安装
    await Promise.allSettled(CORE.map(u => cache.add(new Request(u, {cache: 'reload'}))));
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.filter(k => k.startsWith('hatbook-') && k !== CACHE).map(k => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

// 页面点了「刷新」才切到新版本
self.addEventListener('message', event => {
  if (event.data === 'skipWaiting') self.skipWaiting();
});

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;

  let url;
  try { url = new URL(req.url); } catch (e) { return; }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
  if (isApi(url)) return;                       // 走网络,不插手

  // 打开应用:先给缓存(离线也能读),同时后台悄悄更新
  if (req.mode === 'navigate') {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE);
      const hit = await cache.match(PAGE);
      const fresh = fetch(req)
        .then(r => { if (r && r.ok) cache.put(PAGE, r.clone()); return r; })
        .catch(() => null);
      if (hit) { event.waitUntil(fresh); return hit; }
      return (await fresh) || new Response(
        '<meta charset="utf-8"><p style="font-family:sans-serif;padding:40px">离线了,而且这本书还没缓存过。连上网再打开一次就好。</p>',
        {status: 200, headers: {'Content-Type': 'text/html; charset=utf-8'}}
      );
    })());
    return;
  }

  // 其余静态资源:缓存优先
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(req);
    if (hit) return hit;
    try {
      const res = await fetch(req);
      if (res && res.ok && (url.origin === self.location.origin || cacheableThirdParty(url))) {
        cache.put(req, res.clone());
      }
      return res;
    } catch (e) {
      return new Response('', {status: 504, statusText: 'offline'});
    }
  })());
});
