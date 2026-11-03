/* ComandaPOS — comportamiento de la interfaz (sin JavaScript en línea: CSP estricta). */
(function () {
  "use strict";

  /* ---------- reloj de la cabecera (hora de la terminal) ---------- */
  var fecha = document.querySelector("[data-fecha]");
  var hora = document.querySelector("[data-hora]");
  function dos(n) {
    return (n < 10 ? "0" : "") + n;
  }
  function reloj() {
    var d = new Date();
    if (fecha)
      fecha.textContent =
        dos(d.getDate()) + "/" + dos(d.getMonth() + 1) + "/" + d.getFullYear();
    if (hora) {
      var h = d.getHours(),
        ampm = h >= 12 ? "PM" : "AM";
      h = h % 12 || 12;
      hora.textContent = dos(h) + ":" + dos(d.getMinutes()) + " " + ampm;
    }
  }
  if (fecha || hora) {
    reloj();
    setInterval(reloj, 15000);
  }

  /* ---------- teclado en pantalla ---------- */
  var form = document.querySelector("[data-teclado-form]");
  if (form) {
    var campos = Array.prototype.slice.call(
      form.querySelectorAll("[data-campo-teclado]"),
    );
    var activo = campos[0];
    function marcar(c) {
      activo = c;
      campos.forEach(function (x) {
        x.classList.toggle("activo", x === c);
      });
    }
    campos.forEach(function (c) {
      c.addEventListener("focus", function () {
        marcar(c);
      });
      c.addEventListener("pointerdown", function () {
        marcar(c);
      });
    });
    if (activo) {
      if (activo.value && campos[1]) {
        marcar(campos[1]);
      } else {
        marcar(activo);
      }
      activo.focus({ preventScroll: true });
    }
    form.addEventListener("click", function (e) {
      var b = e.target.closest("button[data-tecla], button[data-accion]");
      if (!b || !activo) return;
      e.preventDefault();
      var limite = parseInt(activo.getAttribute("maxlength") || "128", 10);
      if (b.dataset.tecla) {
        if (activo.value.length < limite) {
          activo.value +=
            activo.id === "usuario"
              ? b.dataset.tecla.toLowerCase()
              : b.dataset.tecla;
        }
      } else if (b.dataset.accion === "borrar") {
        activo.value = activo.value.slice(0, -1);
      } else if (b.dataset.accion === "limpiar") {
        activo.value = "";
      }
      activo.focus({ preventScroll: true });
    });
    /* Enter en el usuario pasa a la clave en vez de enviar el formulario incompleto. */
    var usuario = form.querySelector("#usuario"),
      clave = form.querySelector("#clave");
    if (usuario && clave) {
      usuario.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !clave.value) {
          e.preventDefault();
          clave.focus();
        }
      });
    }
    document.querySelectorAll("[data-usar-cuenta]").forEach(function (b) {
      b.addEventListener("click", function () {
        if (usuario) usuario.value = b.dataset.usarCuenta;
        if (clave) {
          clave.value = "";
          clave.focus();
        }
      });
    });
  }

  /* ---------- bloqueo por inactividad (el servidor también lo exige) ---------- */
  var segundos = parseInt(document.body.dataset.inactividad || "0", 10);
  var salir = document.getElementById("form-salir");
  if (segundos > 0 && salir) {
    var limite = segundos * 1000,
      temporizador = null;
    function reiniciar() {
      clearTimeout(temporizador);
      temporizador = setTimeout(function () {
        salir.submit();
      }, limite);
    }
    ["pointerdown", "keydown", "wheel", "touchstart"].forEach(function (ev) {
      document.addEventListener(ev, reiniciar, { passive: true });
    });
    reiniciar();
  }
})();
