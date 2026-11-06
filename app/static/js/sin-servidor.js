/* ComandaPOS — pantalla «sin servidor»: busca el servidor cada pocos segundos y vuelve sola. */
(function () {
  "use strict";

  var raiz = document.querySelector("[data-sin-servidor]");
  if (!raiz) return;
  var estado = raiz.querySelector("[data-estado]");
  var boton = raiz.querySelector("[data-reintentar]");
  var envio = raiz.hasAttribute("data-envio");
  var ESPERA = 4000;
  var temporizador = null;
  var buscando = false;

  function dos(n) {
    return (n < 10 ? "0" : "") + n;
  }

  function volver() {
    // Tras un formulario que no llegó, NO se repite el envío: se vuelve al inicio para revisar.
    if (envio) window.location.replace("/");
    else window.location.reload();
  }

  function buscar() {
    if (buscando) return;
    buscando = true;
    clearTimeout(temporizador);
    if (estado) estado.textContent = "Buscando el servidor…";
    fetch("/salud", {
      cache: "no-store",
      credentials: "same-origin",
      headers: { "X-Sondeo": "1" },
    })
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
      .then(function (datos) {
        if (datos && datos.app === "ComandaPOS") return volver();
        throw new Error("sin servidor");
      })
      .catch(function () {
        var d = new Date();
        if (estado)
          estado.textContent =
            "Sin respuesta (" +
            dos(d.getHours()) +
            ":" +
            dos(d.getMinutes()) +
            ":" +
            dos(d.getSeconds()) +
            "). Se vuelve a intentar sola.";
        temporizador = setTimeout(buscar, ESPERA);
      })
      .then(function () {
        buscando = false;
      });
  }

  if (boton) boton.addEventListener("click", buscar);
  window.addEventListener("online", buscar);
  temporizador = setTimeout(buscar, 1500);
})();
