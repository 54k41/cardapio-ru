/* Service worker do Cardápio RU.
 *
 * Objetivo: o site abrir no subsolo (ICC, Minhocão) e em qualquer lugar sem
 * sinal. Estratégia por tipo de recurso:
 *   - navegação e JSONs do cardápio: rede primeiro, cache como rede de
 *     segurança (dado de cardápio é o que muda; nunca servir semana velha
 *     escondendo a nova);
 *   - CSS, JS, fontes e ícones: cache primeiro com revalidação em segundo
 *     plano (rápido e imune a queda de rede);
 *   - qualquer outra coisa: rede, sem cache.
 *
 * Ao publicar mudanças relevantes nos estáticos, troque VERSION: o
 * `activate` apaga os caches antigos.
 */

const VERSION = "2026-11-12a";
const CACHE = `cardapio-ru-${VERSION}`;
const CORE = [
  "./",
  "index.html",
  "styles.css",
  "app.js",
  "fonts/lexend-latin.woff2",
  "fonts/lexend-latin-ext.woff2"
];

self.addEventListener("install", event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // um recurso ausente não pode derrubar a instalação inteira
    await Promise.all(CORE.map(path => cache.add(path).catch(() => {})));
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

function isData(url) {
  return /\/data\/cardapio-[a-z]+\.json$/.test(url.pathname);
}

function isStatic(url) {
  return /\.(css|js|woff2|svg|png|ico)$/.test(url.pathname);
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(request);
    if (response && response.ok) cache.put(request, response.clone());
    return response;
  } catch (err) {
    const hit = await cache.match(request, { ignoreSearch: true });
    if (hit) return hit;
    // sem rede e sem o JSON: entrega a casca do app, que mostra o cardápio
    // salvo no localStorage
    const shell = await cache.match("index.html");
    if (shell) return shell;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const hit = await cache.match(request, { ignoreSearch: true });
  const network = fetch(request)
    .then(response => {
      if (response && response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => hit);
  return hit || network;
}

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate" || isData(url)) {
    event.respondWith(networkFirst(request));
    return;
  }
  if (isStatic(url)) {
    event.respondWith(cacheFirst(request));
  }
});
