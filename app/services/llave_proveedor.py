"""Llave pública con la que ComandaPOS verifica los códigos de suscripción.

La genera y reescribe el proveedor con `python proveedor/emitir_codigo.py crear-llave`
(la llave privada queda solo en su equipo, nunca en este repositorio).

Mientras ES_DE_DESARROLLO sea True, la llave es la de las pruebas automáticas: su parte privada
está publicada en tests/, así que cualquiera podría emitir códigos. `run.py --verificar` (y por
tanto build.bat) se niega a empaquetar con esta llave.
"""

ES_DE_DESARROLLO = True
LLAVE_PUBLICA = "df15fG6kNgzbd3Kp7mhlLH3qMMuRB7975AUVI1In20I="
