/* Service worker de ComandaPOS.
   · Si el servidor no responde, muestra la pantalla propia «sin servidor» en lugar del error del
     navegador o de una página guardada por otro programa que usó esta misma dirección y puerto.
   · Al activarse borra las cachés que no son suyas (p. ej., las de otra app servida antes en
     127.0.0.1:5000), para que nunca se mezclen pantallas ni archivos ajenos.
   · Nunca guarda pantallas con datos del negocio: solo la página sin servidor y sus archivos. */
var VERSION = "comandapos-1.2.0";
var SIN_SERVIDOR = "/sin-servidor";
var SIN_SERVIDOR_ENVIO = "/sin-servidor?envio=1";
var ARCHIVOS = [
  "/static/css/comanda.css",
  "/static/js/sin-servidor.js",
  "/static/img/logo.svg",
  "/static/fonts/Inter-Regular.woff",
  "/static/fonts/Inter-SemiBold.woff",
  "/static/fonts/Inter-Bold.woff",
  "/static/fonts/InterDisplay-ExtraBold.woff",
  "/static/fonts/InterDisplay-Black.woff",
];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches
      .open(VERSION)
      .then(function (cache) {
        // Las pantallas sin servidor se piden SIN cookies: nunca guardan datos de una sesión.
        var paginas = [SIN_SERVIDOR, SIN_SERVIDOR_ENVIO].map(function (ruta) {
          return fetch(new Request(ruta, { credentials: "omit" })).then(
            function (r) {
              if (r.ok) return cache.put(ruta, r);
            },
          );
        });
        return Promise.all(paginas.concat(cache.addAll(ARCHIVOS)));
      })
      .then(function () {
        return self.skipWaiting();
      }),
  );
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches
      .keys()
      .then(function (claves) {
        return Promise.all(
          claves
            .filter(function (k) {
              return k !== VERSION;
            })
            .map(function (k) {
              return caches.delete(k);
            }),
        );
      })
      .then(function () {
        return self.clients.claim();
      }),
  );
});

self.addEventListener("fetch", function (e) {
  var req = e.request;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === "navigate") {
    // Pantallas: siempre del servidor. Si no responde, la pantalla propia.
    // Un formulario enviado (POST) recibe la variante que avisa que la acción puede no haberse guardado.
    var respaldo = req.method === "GET" ? SIN_SERVIDOR : SIN_SERVIDOR_ENVIO;
    e.respondWith(
      fetch(req).catch(function () {
        return caches.open(VERSION).then(function (cache) {
          return cache.match(respaldo);
        });
      }),
    );
    return;
  }

  if (req.method === "GET" && url.pathname.indexOf("/static/") === 0) {
    // Archivos: primero el servidor (así una actualización se ve de inmediato);
    // la copia guardada solo sirve para dibujar la pantalla sin servidor.
    e.respondWith(
      fetch(req).catch(function () {
        return caches.open(VERSION).then(function (cache) {
          return cache.match(req, { ignoreSearch: true });
        });
      }),
    );
  }
});
