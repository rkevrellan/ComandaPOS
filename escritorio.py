"""ComandaPOS como programa de escritorio (lo que abre el ComandaPOS.exe).

- Levanta el servidor (Waitress) en un hilo, solo en 127.0.0.1, y abre una ventana propia
  (pywebview / WebView2 de Windows). Si pywebview no está disponible, usa el navegador.
- Una sola instancia: si ya hay un ComandaPOS respondiendo en el puerto, solo abre otra ventana.
- Al cerrar la ventana se detiene el servidor y se sellan los registros de auditoría pendientes.
- Terminal de otra PC:  ComandaPOS.exe --servidor http://192.168.1.10:5000
  (solo abre la ventana; el servidor es la PC de caja con «ComandaPOS-servidor.exe --red»).
- Pantalla de cocina:   ComandaPOS.exe --cocina   (abre directamente la pantalla de cocina).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
import webbrowser

from app.config import NOMBRE, VERSION

ANCHO, ALTO = 1366, 820


def _responde(url: str, ca: str | None = None) -> bool:
    """¿Hay un ComandaPOS escuchando en esa dirección? (https: valida el certificado)."""
    import ssl

    contexto = ssl.create_default_context(cafile=ca) if url.startswith("https") else None
    try:  # url es http(s)://host:puerto validada aquí (no viene de fuera)
        with urllib.request.urlopen(  # nosec B310
            f"{url}/salud", timeout=1.5, context=contexto
        ) as r:
            return json.load(r).get("app") == NOMBRE
    except (OSError, ValueError):
        return False


def _ca_local() -> str | None:
    """Certificado de la CA de ComandaPOS de ESTE equipo (si el servidor de red ya lo creó)."""
    import os

    from app.config import carpeta_datos

    ruta = os.path.join(carpeta_datos(os.path.expanduser("~")), "tls", "ca.crt")
    return ruta if os.path.exists(ruta) else None


def _local(puerto: int) -> str | None:
    """Dirección del ComandaPOS que ya corre en este equipo: http (local) o https (servidor de red)."""
    for url in (f"http://127.0.0.1:{puerto}", f"https://127.0.0.1:{puerto}"):
        if _responde(url, _ca_local() if url.startswith("https") else None):
            return url
    return None


def _url_servidor(texto: str) -> str | None:
    """Solo http(s)://host[:puerto], sin rutas ni credenciales. None si no es válida."""
    from urllib.parse import urlparse

    partes = urlparse(texto.strip())
    if (
        partes.scheme not in ("http", "https")
        or not partes.hostname
        or partes.username
        or partes.path not in ("", "/")
        or partes.query
    ):
        return None
    return f"{partes.scheme}://{partes.netloc}"


def _responde_https_sin_confianza(remoto_http: str) -> bool:
    """¿Contesta TLS en esa dirección? (solo para dar el mensaje correcto; no se usa la conexión)."""
    import socket
    import ssl
    from urllib.parse import urlparse

    partes = urlparse(remoto_http)
    contexto = ssl.create_default_context()
    contexto.check_hostname = False
    contexto.verify_mode = ssl.CERT_NONE  # nosec - solo detecta si hay TLS; no envía datos
    try:
        with socket.create_connection((partes.hostname, partes.port or 80), timeout=1.5) as c:
            with contexto.wrap_socket(c):
                return True
    except (OSError, ssl.SSLError):
        return False


def _puerto_libre(puerto: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", puerto))
        except OSError:
            return False
    return True


def _abrir_ventana(url: str, al_cerrar=None) -> None:
    try:
        import webview  # pywebview
    except ImportError:
        webbrowser.open(url)
        if al_cerrar is not None:  # sin ventana propia: el servidor sigue hasta Ctrl+C
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
        return
    ventana = webview.create_window(
        f"{NOMBRE} {VERSION}",
        url,
        width=ANCHO,
        height=ALTO,
        min_size=(1024, 680),
        confirm_close=True,
        text_select=False,
    )
    ventana.events.closed += lambda: None
    webview.start(
        private_mode=True
    )  # sin caché ni cookies persistentes entre aperturas


def _mensaje(texto: str) -> None:
    """Aviso visible aunque el .exe no tenga consola."""
    print(texto)
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, texto, NOMBRE, 0x30)


def _bitacora_sin_consola() -> None:
    """El .exe de ventana no tiene consola: lo que se imprime va a un archivo en la carpeta de datos."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    import os

    from app.config import carpeta_datos

    archivo = open(  # noqa: SIM115 - vive lo que vive el proceso
        os.path.join(carpeta_datos(os.path.expanduser("~")), "escritorio.log"),
        "a",
        encoding="utf-8",
        buffering=1,
    )
    sys.stdout = sys.stdout or archivo
    sys.stderr = sys.stderr or archivo


def main(argv: list | None = None) -> int:
    _bitacora_sin_consola()
    p = argparse.ArgumentParser(description=f"{NOMBRE} {VERSION} (escritorio)")
    p.add_argument("--puerto", type=int, default=5000)
    p.add_argument(
        "--servidor", help="URL del servidor de la red local (terminal de otra PC)"
    )
    p.add_argument("--cocina", action="store_true", help="abrir la pantalla de cocina")
    args = p.parse_args(argv)
    pagina = "/cocina" if args.cocina else ""

    if args.servidor:  # terminal: no levanta servidor propio, solo la ventana
        remoto = _url_servidor(args.servidor)
        if remoto is None:
            _mensaje("La dirección del servidor debe ser como http://192.168.1.10:5000")
            return 2
        if not _responde(remoto):
            if remoto.startswith("http://") and _responde_https_sin_confianza(remoto):
                _mensaje(
                    f"El servidor usa HTTPS. Abre ComandaPOS con «--servidor https://{remoto[7:]}» "
                    "e instala antes su certificado (ca.crt) en esta terminal."
                )
            elif remoto.startswith("https://"):
                _mensaje(
                    f"No se pudo conectar con {remoto} de forma segura. Si la PC de caja está "
                    "encendida con el servidor de red, instala en esta terminal su certificado "
                    "«ca.crt» (doble clic → Instalar certificado → Entidades de certificación raíz "
                    "de confianza) y comprueba la huella que muestra el servidor."
                )
            else:
                _mensaje(
                    f"No se encontró {NOMBRE} en {remoto}. Revisa que la PC de caja esté encendida "
                    "con el servidor de red local abierto y que esta terminal esté en su lista de "
                    "«Terminales permitidas»."
                )
            return 1
        _abrir_ventana(remoto + pagina)
        return 0

    url = f"http://127.0.0.1:{args.puerto}"

    ya = _local(args.puerto)
    if ya:  # ya abierto (aquí o como servidor de red): solo otra ventana
        _abrir_ventana(ya + pagina)
        return 0
    if not _puerto_libre(args.puerto):
        _mensaje(
            f"El puerto {args.puerto} está ocupado por otro programa.\n"
            "Cierra ese programa o inicia ComandaPOS con otro puerto (--puerto 5050)."
        )
        return 1

    from waitress.server import create_server

    from app import create_app
    from app.services.auditoria import sellar_pendientes
    from run import preparar

    app = create_app()
    codigo = preparar(app)
    if codigo is not None:
        from run import SALIDA_BASE_DEMO

        if codigo == SALIDA_BASE_DEMO:
            _mensaje(
                "Este equipo está en producción pero la base es de demostración.\n"
                "Menú Inicio > ComandaPOS > «Empezar con una base nueva» la aparta en un\n"
                "respaldo (no borra nada) y después podrás crear el primer administrador."
            )
        else:
            _mensaje(
                "Hay cuentas con credenciales de prueba en una instalación de producción.\n"
                "Ejecuta «ComandaPOS-servidor.exe --nuevas-claves» antes de usar el sistema."
            )
        return codigo

    servidor = create_server(
        app, host="127.0.0.1", port=args.puerto, threads=8, ident=None
    )
    hilo = threading.Thread(target=servidor.run, name="waitress", daemon=True)
    hilo.start()
    for _ in range(50):  # hasta 10 s para que responda
        if _responde(url):
            break
        time.sleep(0.2)
    try:
        _abrir_ventana(url + pagina, al_cerrar=True)
    finally:
        servidor.close()
        with app.app_context():
            sellar_pendientes()
    return 0


if __name__ == "__main__":
    sys.exit(main())
