"""RN-01, RN-02, RN-03 y RN-06: dinero, impuestos y descuentos (sin Flask ni base de datos)."""

from decimal import Decimal as D

import pytest

from app.services.calculos import (
    LineaCalculo,
    ReglaNegocioError,
    a_decimal,
    calcular_linea,
    redondear,
    totalizar,
    validar_cantidad,
    validar_precio,
    validar_tasa,
    vuelto,
)


def L(cant, precio, tasa=7, desc=0, jub=False):
    return LineaCalculo.crear(cant, precio, tasa, desc, jub)


# ---------------------------------------------------------------- RN-01 redondeo
@pytest.mark.parametrize(
    "valor, esperado",
    [
        ("0.005", "0.01"),
        ("0.004", "0.00"),
        ("2.675", "2.68"),
        ("1.115", "1.12"),
        ("-0.005", "-0.01"),
        ("10", "10.00"),
    ],
)
def test_rn01_redondeo_half_up(valor, esperado):
    assert redondear(valor) == D(esperado)


def test_rn01_itbms_por_linea_y_total_es_suma_de_lineas():
    # 3 × 0.35 al 7 %: por línea 0.07 cada una; si se calculara sobre el total daría 0.07 (1.05 × 7 %)
    lineas = [L(1, "0.35"), L(1, "0.35"), L(1, "0.35")]
    t = totalizar(lineas)
    assert [r.itbms for r in t.lineas] == [D("0.02")] * 3  # 0.0245 → 0.02
    assert t.itbms == D("0.06")  # suma de líneas, no 7 % del total (0.07)
    assert t.total == sum(r.total for r in t.lineas) == D("1.11")
    assert t.subtotal == D("1.05")


def test_rn01_nunca_usa_float():
    t = totalizar([L("3", "0.10"), L("1", "0.20")])
    assert t.subtotal == D("0.50")
    assert all(isinstance(v, D) for v in (t.subtotal, t.itbms, t.total))


def test_rn01_bases_e_itbms_por_tasa():
    t = totalizar([L(2, "8.95", 7), L(1, "5.50", 10), L(1, "1.00", 0)])
    assert t.base_por_tasa == {7: D("17.90"), 10: D("5.50"), 0: D("1.00")}
    assert t.itbms_por_tasa == {7: D("1.25"), 10: D("0.55"), 0: D("0.00")}
    assert t.base_gravable == D("23.40") and t.base_exenta == D("1.00")
    assert t.total == D("26.20")


# ---------------------------------------------------------------- RN-02 descuentos
def test_rn02_descuento_reduce_la_base_antes_del_itbms():
    r = calcular_linea(L(1, "10.00", 7, desc=10))
    assert (r.bruto, r.descuento, r.base, r.itbms, r.total) == (
        D("10.00"),
        D("1.00"),
        D("9.00"),
        D("0.63"),
        D("9.63"),
    )


# ---------------------------------------------------------------- RN-03 validaciones
@pytest.mark.parametrize(
    "malo", ["NaN", "nan", "Infinity", "-Infinity", "abc", "", None, True, "1e999999"]
)
def test_rn03_montos_no_finitos_o_basura(malo):
    with pytest.raises(ReglaNegocioError):
        validar_precio(malo)


@pytest.mark.parametrize("malo", ["0", "-1", "0.0001", "1000"])
def test_rn03_cantidades_invalidas(malo):
    with pytest.raises(ReglaNegocioError):
        validar_cantidad(malo)


def test_rn03_precio_con_mas_de_dos_decimales_o_enorme():
    with pytest.raises(ReglaNegocioError):
        validar_precio("1.001")
    with pytest.raises(ReglaNegocioError):
        validar_precio("100000")
    assert validar_precio("1,234.50") == D("1234.50")


@pytest.mark.parametrize("tasa", ["5", "7.5", "-7", "100", "x"])
def test_rn03_tasas_no_permitidas(tasa):
    with pytest.raises(ReglaNegocioError):
        validar_tasa(tasa)


def test_rn03_tasas_permitidas():
    assert [validar_tasa(t) for t in ("0", "7", "7.0", 10, D("15"))] == [
        0,
        7,
        7,
        10,
        15,
    ]


def test_a_decimal_no_pasa_por_float():
    assert a_decimal(0.1) == D("0.1")  # str(0.1) == "0.1", no 0.1000000000000000055…


# ---------------------------------------------------------------- RN-06 jubilado
def test_rn06_jubilado_solo_en_productos_que_aplican():
    t = totalizar(
        [L(1, "8.00", jub=True), L(1, "2.00", 10, jub=False)], jubilado_pct=25
    )
    assert t.descuento_jubilado == D("2.00")
    assert t.descuento_producto == D("0.00")
    assert t.lineas[1].descuento == D("0.00")
    assert t.total == D("6.42") + D("2.20")


def test_rn06_no_se_combina_y_gana_el_mayor():
    menor = calcular_linea(L(1, "10.00", desc=10, jub=True), jubilado_pct=25)
    assert menor.es_jubilado and menor.descuento == D("2.50")
    mayor = calcular_linea(L(1, "10.00", desc=30, jub=True), jubilado_pct=25)
    assert not mayor.es_jubilado and mayor.descuento == D("3.00")


def test_rn06_porcentaje_invalido():
    with pytest.raises(ReglaNegocioError):
        totalizar([L(1, "1.00", jub=True)], jubilado_pct=125)


# ---------------------------------------------------------------- vuelto
def test_vuelto_y_falta_de_dinero():
    assert vuelto("7.95", "20") == D("12.05")
    with pytest.raises(ReglaNegocioError):
        vuelto("7.95", "5")
