"""Texto de los tickets ESC/POS: renglones por palabra y signos que la impresora sí tiene."""

from app.services.impresion import ESC, Ticket, _partir, limpiar, vista_previa


def test_parte_por_palabras_sin_cortar_salvo_si_no_cabe():
    assert _partir("COMPROBANTE AUXILIAR DE FACTURA ELECTRONICA", 42) == [
        "COMPROBANTE AUXILIAR DE FACTURA",
        "ELECTRONICA",
    ]
    assert _partir("A" * 50, 42) == ["A" * 42, "A" * 8]
    assert _partir("", 42) == [""]
    assert _partir("   + Arroz con guandú", 42) == ["   + Arroz con guandú"]
    assert _partir("  * " + "nota " * 12, 24)[1].startswith("  ")


def test_signos_tipograficos_y_control():
    assert limpiar("PRUEBA — SIN VALIDEZ “demo”") == 'PRUEBA - SIN VALIDEZ "demo"'
    assert ESC not in limpiar("cliente\x1bp\x00\x19").encode()


def test_ticket_no_pierde_caracteres_del_espanol():
    t = Ticket().linea("Ñame con guandú — sí").bytes()
    texto = vista_previa(t)
    assert "Ñame con guandú - sí" in texto and "?" not in texto


def test_vista_previa_de_la_gaveta():
    assert (
        vista_previa(Ticket().gaveta().bytes(cortar=False))
        == "(pulso de apertura de gaveta)"
    )
