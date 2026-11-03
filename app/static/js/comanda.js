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

  /* ---------- doble toque: el botón se desactiva tras enviar (el servidor usa idempotencia) ---------- */
  document.addEventListener("submit", function (e) {
    var boton = e.submitter;
    if (!boton || e.target.method.toLowerCase() !== "post") return;
    /* Se desactiva DESPUÉS de armar el envío para que viaje su name/value (p. ej. «puestos»). */
    setTimeout(function () {
      boton.disabled = true;
      boton.classList.add("enviando");
    }, 0);
    setTimeout(function () {
      boton.disabled = false;
      boton.classList.remove("enviando");
    }, 8000);
  });

  /* ---------- color de cada sección del menú (sin estilos en línea: CSP) ---------- */
  document.querySelectorAll("[data-color]").forEach(function (el) {
    if (/^#[0-9a-fA-F]{6}$/.test(el.dataset.color))
      el.style.borderLeftColor = el.dataset.color;
  });

  /* ---------- calculadora de cobro: recibido, falta o vuelto ---------- */
  var formPago = document.querySelector(".form-pago");
  if (formPago) {
    var total = parseFloat(formPago.dataset.total || "0");
    var campos = formPago.querySelectorAll("[data-pago]");
    var efectivo = formPago.querySelector("#pago-efectivo");
    var recibidoEl = formPago.querySelector("[data-recibido]");
    var saldoEl = formPago.querySelector("[data-saldo]");
    var etiqueta = formPago.querySelector("[data-etiqueta-saldo]");
    function centavos(v) {
      var n = parseFloat(String(v).replace(/,/g, ""));
      return isFinite(n) ? Math.round(n * 100) : 0;
    }
    function recalcular() {
      var suma = 0;
      campos.forEach(function (c) {
        suma += centavos(c.value);
      });
      var diferencia = suma - Math.round(total * 100);
      recibidoEl.textContent = (suma / 100).toFixed(2);
      etiqueta.textContent = diferencia >= 0 ? "Vuelto" : "Falta";
      saldoEl.textContent = (Math.abs(diferencia) / 100).toFixed(2);
    }
    campos.forEach(function (c) {
      c.addEventListener("input", recalcular);
    });
    formPago.querySelectorAll("[data-efectivo]").forEach(function (b) {
      b.addEventListener("click", function () {
        var otros = 0;
        campos.forEach(function (c) {
          if (c !== efectivo) otros += centavos(c.value);
        });
        var monto = centavos(b.dataset.efectivo);
        /* «Exacto» cubre solo lo que falta después de tarjetas y Yappy. */
        if (b.textContent.trim() === "Exacto")
          monto = Math.max(0, Math.round(total * 100) - otros);
        efectivo.value = (monto / 100).toFixed(2);
        recalcular();
      });
    });
    var limpiar = formPago.querySelector("[data-limpiar-pago]");
    if (limpiar)
      limpiar.addEventListener("click", function () {
        campos.forEach(function (c) {
          c.value = "";
        });
        recalcular();
      });
    recalcular();
  }

  /* ---------- pantalla de cocina: se actualiza sola ---------- */
  var recarga = document.querySelector("[data-autorecarga]");
  if (recarga) {
    var seg = Math.max(5, parseInt(recarga.dataset.autorecarga || "15", 10));
    setTimeout(function () {
      window.location.reload();
    }, seg * 1000);
  }
})();
