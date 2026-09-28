import random

import pytest

from limpiador import modelo

random.seed(1)
POLITICA = "senado diputados reforma votación congreso iniciativa ley gobierno oposición bancada".split()
DEPORTES = "partido gol selección torneo liga entrenador delantero estadio afición campeonato".split()
SPAM = "oferta descuento gana dinero rápido clic regístrate premio gratis exclusivo promoción".split()
RELLENO = "el la de que en los se por con para una sus al lo como más pero".split()


def _nota(i, vocab, decision, categoria=None):
    palabras = [random.choice(vocab + RELLENO) for _ in range(random.randint(60, 140))]
    return {"id": f"n{i}", "titulo": " ".join(random.sample(vocab, 4)).capitalize(),
            "cuerpo": " ".join(palabras), "fuente": "prueba", "palabras": len(palabras),
            "puntaje": 0.55, "motivos": ["cuerpo corto"], "decision": "dudoso",
            "origen": "reglas", "motivo": "cuerpo corto", "categoria": "",
            "_etiqueta": (decision, categoria)}


@pytest.fixture(autouse=True)
def carpeta_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(modelo, "CARPETA", tmp_path)


def _etiquetar(notas):
    for n in notas:
        modelo.guardar_etiqueta(n, *n["_etiqueta"])


def test_sin_ejemplos_no_entrena():
    res = modelo.entrenar()
    assert res["decision"] is None and res["falta"]
    assert modelo.cargar() is None


def test_aprende_decision_y_categoria():
    ejemplos = ([_nota(i, POLITICA, "conservar", "política") for i in range(15)]
                + [_nota(i + 100, DEPORTES, "conservar", "deportes") for i in range(15)]
                + [_nota(i + 200, SPAM, "descartar") for i in range(15)])
    _etiquetar(ejemplos)
    res = modelo.entrenar()
    assert res["decision"]["precision"] >= 0.9
    assert res["categoria"]["precision"] >= 0.9

    nuevas = [_nota(900, SPAM, None), _nota(901, DEPORTES, None), _nota(902, POLITICA, None)]
    conteo = modelo.aplicar(nuevas, modelo.cargar(), umbral=0.6)
    assert all(n["sugerencia"] for n in nuevas)
    spam, dep, pol = nuevas
    assert spam["sugerencia"] == "descartar" and dep["sugerencia"] == "conservar"
    assert dep["categoria"] == "deportes" and pol["categoria"] == "política"
    decididas = [n for n in nuevas if n["origen"] == "modelo"]
    assert decididas and all("seguro" in n["motivo"] for n in decididas)


def test_umbral_alto_solo_sugiere():
    _etiquetar([_nota(i, POLITICA, "conservar") for i in range(12)]
               + [_nota(i + 50, SPAM, "descartar") for i in range(12)])
    modelo.entrenar()
    n = _nota(999, POLITICA + SPAM, None)  # mitad y mitad: el modelo no debería estar seguro
    modelo.aplicar([n], modelo.cargar(), umbral=0.999)
    assert n["decision"] == "dudoso" and n["sugerencia"] in ("conservar", "descartar")


def test_la_ultima_etiqueta_gana_y_dudoso_retira():
    n = _nota(1, POLITICA, None)
    modelo.guardar_etiqueta(n, "conservar")
    modelo.guardar_etiqueta(n, None, "política")      # solo categoría: no borra la decisión
    et = modelo.cargar_etiquetas()
    assert et.iloc[0].decision == "conservar" and et.iloc[0].categoria == "política"
    modelo.guardar_etiqueta(n, "dudoso")              # se arrepintió
    assert modelo.cargar_etiquetas().iloc[0].decision is None


def test_modelo_de_otra_version_se_ignora(monkeypatch):
    _etiquetar([_nota(i, POLITICA, "conservar") for i in range(12)]
               + [_nota(i + 50, SPAM, "descartar") for i in range(12)])
    modelo.entrenar()
    monkeypatch.setattr(modelo.sklearn, "__version__", "0.0.1")
    assert modelo.cargar() is None  # mejor reentrenar que cargar algo incompatible


def test_spam_que_pasa_las_reglas_vuelve_a_revision_y_se_puede_deshacer():
    _etiquetar([_nota(i, POLITICA, "conservar") for i in range(12)]
               + [_nota(i + 50, SPAM, "descartar") for i in range(12)])
    modelo.entrenar()
    spam = _nota(700, SPAM, None)
    spam.update(decision="conservar", motivo="pasa todas las reglas")    # las reglas no lo detectaron
    humana = _nota(701, SPAM, None)
    humana.update(decision="conservar", origen="humano")                 # una persona ya decidió: no se toca
    conteo = modelo.aplicar([spam, humana], modelo.cargar(), umbral=0.6)
    assert conteo["a_revision"] == 1
    assert spam["decision"] == "dudoso" and "las reglas la aceptaron" in spam["motivo"]
    assert spam["categoria"] == ""                                         # no se categoriza lo que no se conserva
    assert humana["decision"] == "conservar" and "sugerencia" not in humana

    modelo.deshacer([spam, humana])
    assert spam["decision"] == "conservar" and spam["origen"] == "reglas" and spam["motivo"] == "pasa todas las reglas"
