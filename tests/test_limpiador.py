import io
import json
from datetime import datetime, timezone

import pytest

from limpiador import Opciones, exportar, procesar
from limpiador.carga import parsear_texto
from limpiador.normaliza import canonizar_url, limpiar_texto, normalizar, normalizar_fecha

AHORA = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)
LARGO = ("El Congreso aprobó la reforma con 300 votos a favor y 150 en contra tras una sesión de "
         "doce horas en la que la oposición presentó más de cuarenta reservas. ") * 4


def subir(nombre, obj):
    f = io.BytesIO(json.dumps(obj, ensure_ascii=False).encode() if not isinstance(obj, bytes) else obj)
    f.name = nombre
    return f


# --- carga ---------------------------------------------------------------------------------
@pytest.mark.parametrize("texto,esperado", [
    ('[{"a":1},{"a":2}]', 2),
    ('{"articles":[{"a":1}]}', 1),
    ('{"hits":{"hits":[{"_source":{"a":1}}]}}', 1),
    ('{"a":1}\n{"a":2}\n{"a":3}', 3),
    ('{"a":1}\n{roto\n{"a":3}', 2),
])
def test_formatos(texto, esperado):
    arts, _ = parsear_texto(texto)
    assert len(arts) == esperado


def test_renglon_roto_se_reporta():
    _, errores = parsear_texto('{"a":1}\n{roto')
    assert errores and "renglón 2" in errores[0]


def test_bom_y_latin1():
    df, rep = procesar([subir("a.json", '﻿[{"title":"Título largo de prueba","content":"x"}]'.encode("utf-8")),
                        subir("b.json", '[{"title":"Año nuevo en León, Guanajuato"}]'.encode("latin-1"))])
    assert set(df.titulo) == {"Título largo de prueba", "Año nuevo en León, Guanajuato"}
    assert rep["errores_de_archivo"] == []


# --- normalización -------------------------------------------------------------------------
def test_limpia_html_entidades_y_basura():
    t = limpiar_texto("<p>Hola&nbsp;mundo &amp; más</p><script>x()</script><p>Lee también: otra</p>",
                      quitar_basura=True)
    assert t == "Hola mundo & más"


def test_mojibake():
    assert limpiar_texto("InflaciÃ³n en MÃ©xico") == "Inflación en México"


@pytest.mark.parametrize("entrada,esperado", [
    ("2026-09-10T14:00:00Z", "2026-09-10T14:00:00+00:00"),
    ("27 de septiembre de 2026", "2026-09-27T00:00:00+00:00"),
    ("martes 22 de sept. de 2026 a las 10:30", "2026-09-22T10:30:00+00:00"),
    ("15/09/2026", "2026-09-15T00:00:00+00:00"),
    ("03/04/2026", "2026-04-03T00:00:00+00:00"),       # día primero, como en México
    ("hace 3 horas", "2026-09-27T09:00:00+00:00"),
    ("ayer", "2026-09-26T12:00:00+00:00"),
    (1790000000000, "2026-09-21T14:13:20+00:00"),      # epoch en milisegundos
    ("no es fecha", None),
    ("1850-01-01", None),
])
def test_fechas(entrada, esperado):
    assert normalizar_fecha(entrada, AHORA) == esperado


def test_url_canonica():
    a = canonizar_url("https://www.diario.mx/nota/1/amp?utm_source=tw&fbclid=x&id=5")
    b = canonizar_url("http://m.diario.mx/nota/1?id=5")
    assert a == b == "https://diario.mx/nota/1?id=5"


def test_alias_y_campos_anidados():
    n = normalizar({"headline": "Hola", "articleBody": "cuerpo", "source": {"name": "El Medio"},
                    "authors": [{"name": "Ana"}, {"name": "Luis"}], "link": "https://x.mx/a"})
    assert (n["titulo"], n["cuerpo"], n["fuente"], n["autor"]) == ("Hola", "cuerpo", "El Medio", "Ana, Luis")


def test_fuente_desde_url():
    assert normalizar({"title": "t", "url": "https://www.eluniversal.com.mx/x"})["fuente"] == "eluniversal.com.mx"


# --- reglas y duplicados -------------------------------------------------------------------
def test_pipeline_decide():
    datos = [
        {"title": "Aprueban reforma judicial en la Cámara", "content": LARGO, "date": "2026-09-01",
         "url": "https://a.mx/1"},
        {"title": "Aprueban reforma judicial en la Cámara", "content": LARGO, "date": "2026-09-01",
         "url": "https://www.a.mx/1?utm_source=fb"},                        # duplicado exacto
        {"title": "Casino con 50% de descuento", "content": "Compra ahora", "url": "https://spam.mx"},
        {"title": "", "content": ""},
    ]
    df, rep = procesar([subir("x.json", datos)])
    assert rep["registros_leidos"] == 4 and rep["sin_titulo_ni_cuerpo"] == 1
    assert rep["duplicados"] == 1 and rep["conservar"] == 1
    spam = df[df.titulo.str.startswith("Casino")].iloc[0]
    assert spam.decision == "descartar" and "publicidad" in spam.motivo
    salida = json.loads(exportar(df))
    assert len(salida) == 1 and salida[0]["titulo"].startswith("Aprueban")


NOTA = ("La Junta de Gobierno del Banco de México decidió por unanimidad mantener la tasa de interés "
        "en 7.5 por ciento, citando una inflación subyacente que todavía no converge a la meta. Analistas "
        "consultados esperaban el movimiento y anticipan recortes graduales en el primer trimestre. El peso "
        "reaccionó con una ligera apreciación frente al dólar tras el anuncio, mientras que los bonos de largo "
        "plazo registraron movimientos moderados. La institución señaló que vigilará de cerca la evolución de "
        "los precios de energéticos y alimentos en los próximos meses, y reiteró su compromiso con la "
        "estabilidad de precios. El próximo anuncio de política monetaria está previsto para noviembre, "
        "cuando también se publicará el informe trimestral con nuevas proyecciones de crecimiento.")


def _nota(t, c, u):
    return {"title": t, "content": c, "url": u, "date": "2026-09-01"}


def test_casi_duplicado():
    reescrita = "De acuerdo con un comunicado, l" + NOTA[1:] + " Con información de agencias."
    df, rep = procesar([subir("x.json", [
        _nota("Banxico mantiene la tasa en 7.5%", NOTA, "https://a.mx/1"),
        _nota("Banxico deja sin cambios la tasa", reescrita, "https://b.mx/9"),
        _nota("Tema distinto por completo", "Otra cosa que no tiene relación alguna con nada. " * 20, "https://c.mx/2"),
    ])])
    assert rep["duplicados"] == 1
    assert (df.decision == "conservar").sum() == 2


def test_parecidas_van_a_revision():
    mitad = NOTA[:len(NOTA) * 3 // 4] + " Sin embargo, otros especialistas advirtieron riesgos en el sector " \
            "exportador por la volatilidad cambiaria y pidieron cautela a las autoridades financieras del país."
    df, rep = procesar([subir("x.json", [_nota("Banxico mantiene la tasa", NOTA, "https://a.mx/1"),
                                         _nota("Banxico y el peso", mitad, "https://b.mx/2")])])
    assert rep["duplicados"] == 0 and rep["dudoso"] == 1
    assert "parecida" in df[df.decision == "dudoso"].iloc[0].motivo


def test_explica_como_se_integro_cada_archivo():
    _, rep = procesar([subir("api.json", {"status": "ok", "articles": [
                           {"headline": "Uno", "body": "texto", "extra": 1, "vacia": ""},
                           {"headline": "Dos", "body": "más texto", "extra": 2}]}),
                       subir("s.jsonl", b'{"titulo": "a", "texto": "b"}\n{roto')])
    api, jl = rep["archivos"]
    assert api["formato"] == "Objeto con la lista «articles»" and api["registros"] == 2
    assert api["campos"]["titulo"]["de"] == "headline" and api["campos"]["cuerpo"]["cobertura"] == 1.0
    assert api["ignoradas"] == ["extra"]                     # "vacia" no cuenta: no trae nada
    assert '"headline"' in api["antes"] and '"titulo"' in api["despues"]
    assert jl["formato"].startswith("JSON Lines") and jl["total_errores"] == 1
