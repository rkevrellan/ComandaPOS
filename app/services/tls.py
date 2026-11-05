"""HTTPS para la red local (H-06).

Al arrancar en modo red, ComandaPOS crea (una sola vez) su propia autoridad certificadora local
«ComandaPOS CA» y, con ella, el certificado del servidor para las IP actuales del equipo. Cada
terminal confía UNA vez en `ca.crt` (doble clic → Instalar certificado → «Entidades de certificación
raíz de confianza», o `certutil -user -addstore Root ca.crt`) y desde ahí todo viaja cifrado: PIN,
contraseñas, códigos 2FA y la cookie de sesión.

- La llave de la CA no sale de la carpeta de datos (permisos 0600; en Windows, grupo ComandaPOS).
- Si cambia la IP del equipo, el certificado del servidor se regenera solo (la CA es la misma, las
  terminales no tienen que hacer nada). Por eso conviene una IP fija igualmente.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import os
import socket

CARPETA = "tls"
DIAS_CA = 3650
DIAS_SERVIDOR = (
    397  # límite que aceptan los navegadores actuales para certificados de servidor
)


def _escribir(ruta: str, datos: bytes, privado: bool = False) -> None:
    temporal = ruta + ".tmp"
    fd = os.open(
        temporal, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if privado else 0o644
    )
    with os.fdopen(fd, "wb") as f:
        f.write(datos)
    os.replace(temporal, ruta)


def _llave():
    from cryptography.hazmat.primitives.asymmetric import ec

    return ec.generate_private_key(ec.SECP256R1())


def _nombre(texto: str):
    from cryptography import x509
    from cryptography.x509.oid import NameOID

    return x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ComandaPOS"),
            x509.NameAttribute(NameOID.COMMON_NAME, texto),
        ]
    )


def _crear_ca(carpeta: str):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization

    llave = _llave()
    ahora = dt.datetime.now(dt.timezone.utc)
    nombre = _nombre(f"ComandaPOS CA ({socket.gethostname()[:30]})")
    cert = (
        x509.CertificateBuilder()
        .subject_name(nombre)
        .issuer_name(nombre)
        .public_key(llave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - dt.timedelta(minutes=5))
        .not_valid_after(ahora + dt.timedelta(days=DIAS_CA))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(llave.public_key()),
            critical=False,
        )
        .sign(llave, hashes.SHA256())
    )
    _escribir(
        os.path.join(carpeta, "ca.key"),
        llave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        privado=True,
    )
    _escribir(
        os.path.join(carpeta, "ca.crt"), cert.public_bytes(serialization.Encoding.PEM)
    )


def _cargar_ca(carpeta: str):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    with open(os.path.join(carpeta, "ca.key"), "rb") as f:
        llave = serialization.load_pem_private_key(f.read(), password=None)
    with open(os.path.join(carpeta, "ca.crt"), "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    return llave, cert


def _nombres_validos(cert) -> set:
    from cryptography import x509

    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return set()
    return {str(ip) for ip in san.get_values_for_type(x509.IPAddress)} | set(
        san.get_values_for_type(x509.DNSName)
    )


def asegurar(datos: str, ips: list) -> tuple:
    """Devuelve (certificado, llave, ca) del servidor para estas IP, creándolos si hace falta."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import ExtendedKeyUsageOID

    carpeta = os.path.join(datos, CARPETA)
    os.makedirs(carpeta, exist_ok=True)
    if not os.path.exists(os.path.join(carpeta, "ca.key")):
        _crear_ca(carpeta)
    ca_llave, ca_cert = _cargar_ca(carpeta)

    ruta_cert = os.path.join(carpeta, "servidor.crt")
    ruta_llave = os.path.join(carpeta, "servidor.key")
    host = socket.gethostname().lower()[:60] or "comandapos"
    deseados = {"127.0.0.1", "localhost", host} | {
        str(ipaddress.ip_address(ip)) for ip in ips
    }
    ahora = dt.datetime.now(dt.timezone.utc)
    if os.path.exists(ruta_cert) and os.path.exists(ruta_llave):
        with open(ruta_cert, "rb") as f:
            actual = x509.load_pem_x509_certificate(f.read())
        vence = actual.not_valid_after_utc
        if deseados <= _nombres_validos(actual) and vence - ahora > dt.timedelta(
            days=30
        ):
            return ruta_cert, ruta_llave, os.path.join(carpeta, "ca.crt")

    llave = _llave()
    nombres = [x509.DNSName("localhost"), x509.DNSName(host)] + [
        x509.IPAddress(ipaddress.ip_address(ip))
        for ip in sorted(deseados - {"localhost", host})
    ]
    cert = (
        x509.CertificateBuilder()
        .subject_name(_nombre(f"ComandaPOS {host}"))
        .issuer_name(ca_cert.subject)
        .public_key(llave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(ahora - dt.timedelta(minutes=5))
        .not_valid_after(ahora + dt.timedelta(days=DIAS_SERVIDOR))
        .add_extension(x509.SubjectAlternativeName(nombres), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_llave.public_key()),
            critical=False,
        )
        .sign(ca_llave, hashes.SHA256())
    )
    _escribir(
        ruta_llave,
        llave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        privado=True,
    )
    _escribir(ruta_cert, cert.public_bytes(serialization.Encoding.PEM))
    return ruta_cert, ruta_llave, os.path.join(carpeta, "ca.crt")


def huella_ca(ruta_ca: str) -> str:
    """SHA-256 de la CA, para comprobar en cada terminal que se instaló la correcta."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    with open(ruta_ca, "rb") as f:
        cert = x509.load_pem_x509_certificate(f.read())
    hexa = cert.fingerprint(hashes.SHA256()).hex().upper()
    return ":".join(hexa[i : i + 2] for i in range(0, len(hexa), 2))


def servir(app, host: str, puerto: int, cert: str, llave: str) -> None:
    """Servidor WSGI con TLS 1.2+ (cheroot). Bloquea hasta Ctrl+C."""
    import ssl

    from cheroot import wsgi
    from cheroot.ssl.builtin import BuiltinSSLAdapter

    servidor = wsgi.Server((host, puerto), app, numthreads=8, server_name="ComandaPOS")
    adaptador = BuiltinSSLAdapter(cert, llave)
    adaptador.context.minimum_version = ssl.TLSVersion.TLSv1_2
    servidor.ssl_adapter = adaptador
    try:
        servidor.start()
    except KeyboardInterrupt:
        servidor.stop()
