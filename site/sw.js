/* Removedor do service worker do Cardápio RU.
 *
 * Uma versão anterior deste site registrava um SW que guardava CSS, JS e os
 * JSONs no cache. Com a volta do layout anterior, esse cache passaria a servir
 * o styles.css novo para a página antiga (mesma URL, outro conteúdo) e o site
 * ficaria com HTML antigo + CSS novo.
 *
 * Este arquivo ocupa o mesmo endereço de propósito: quem já tem o SW antigo
 * recebe este na próxima checagem de atualização, ele apaga os caches, limpa o
 * registro e o site volta a ser servido direto pela rede. Para quem nunca abriu
 * a versão anterior, nada acontece — não há SW novo para instalar.
 */

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map(key => caches.delete(key)));
    try {
      await self.registration.unregister();
    } catch (err) {
      // sem registro para remover: nada a fazer
    }
    await self.clients.claim();
    const clients = await self.clients.matchAll({ type: "window" });
    for (const client of clients) {
      if ("navigate" in client) {
        try {
          await client.navigate(client.url);
        } catch (err) {
          // navegação bloqueada pelo navegador: o próximo load já vem limpo
        }
      }
    }
  })());
});

self.addEventListener("fetch", () => {
  // sem respondWith: todo pedido vai direto para a rede
});
