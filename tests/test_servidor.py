"""Prueba el servidor de verdad: lo levanta en un hilo y le habla por HTTP."""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError

import pytest

import servidor
from limpiador import modelo


@pytest.fixture()
def url(tmp_path, monkeypatch):
    monkeypatch.setattr(modelo, "CARPETA", tmp_path)
    monkeypatch.setattr(servidor, "E", servidor.Estado())
    srv = ThreadingHTTPServer(("127.0.0.1", 0), servidor.Manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def pedir(url, ruta, datos=None, crudo=None, cabeceras=None):
    cuerpo = crudo if crudo is not None else (json.dumps(datos).encode() if datos is not None else None)
    req = urllib.request.Request(url + ruta, data=cuerpo, headers=cabeceras or {},
                                 method="POST" if cuerpo is not None else "GET")
    with urllib.request.urlopen(req) as r:
        return r.read(), r.headers


def pj(*a, **k):
    return json.loads(pedir(*a, **k)[0])


def test_pagina_y_estaticos(url):
    html, h = pedir(url, "/")
    assert b"Limpiador de noticias" in html and "text/html" in h["Content-Type"]
    assert b"function" in pedir(url, "/app.js")[0]
    with pytest.raises(HTTPError) as e:
        pedir(url, "/../servidor.py")          # no se puede salir de la carpeta web
    assert e.value.code == 404


def test_flujo_completo(url):
    with pytest.raises(HTTPError) as e:
        pedir(url, "/api/procesar", {})
    assert e.value.code == 400 and "sube" in json.loads(e.value.read())["error"]

    notas = [{"title": "Congreso aprueba presupuesto 2027", "content": "El pleno aprobó el gasto. " * 30,
              "date": "2026-09-01", "url": "https://a.mx/1"},
             {"title": "Becas nuevas", "content": "Detalles la próxima semana. " * 5,
              "date": "2026-09-02", "url": "https://a.mx/2"}]
    pj(url, "/api/subir", crudo=json.dumps(notas).encode(), cabeceras={"X-Nombre": "d%C3%ADa.json"})
    r = pj(url, "/api/procesar", {"opciones": {"min_palabras": 60}})
    assert r["conteos"]["conservar"] == 1 and r["conteos"]["dudoso"] == 1

    todo = pj(url, "/api/notas")
    assert todo["archivos"][0]["nombre"] == "día.json"
    dudosa = next(n for n in todo["notas"] if n["decision"] == "dudoso")
    detalle = pj(url, f"/api/nota?id={dudosa['id']}")
    assert detalle["nota"]["cuerpo"].startswith("Detalles")

    r = pj(url, "/api/decidir", {"id": dudosa["id"], "decision": "conservar", "categoria": "política"})
    assert r["conteos"] == {"conservar": 2, "descartar": 0, "dudoso": 0}
    assert r["nota"]["origen"] == "humano" and r["modelo"]["conservar"] == 1

    # deshacer: vuelve a dudosa y la etiqueta se retira
    r = pj(url, "/api/decidir", {"id": dudosa["id"], "deshacer": {"decision": "dudoso", "origen": "reglas",
                                                                  "motivo": dudosa["motivo"]}})
    assert r["conteos"]["dudoso"] == 1 and r["nota"]["origen"] == "reglas" and r["modelo"]["conservar"] == 0
    pj(url, "/api/decidir", {"id": dudosa["id"], "decision": "conservar"})

    limpias, h = pedir(url, "/api/exportar?tipo=limpias")
    assert len(json.loads(limpias)) == 2 and "attachment" in h["Content-Disposition"]
    csv, _ = pedir(url, "/api/exportar?tipo=csv")
    assert csv.startswith("﻿".encode()) and b"Congreso" in csv


def test_errores_legibles(url):
    for ruta, datos, codigo in [("/api/decidir", {"id": "nada", "decision": "conservar"}, 404),
                                ("/api/exportar?tipo=limpias", None, 400)]:
        with pytest.raises(HTTPError) as e:
            pedir(url, ruta, datos)
        assert e.value.code == codigo and "error" in json.loads(e.value.read())


def test_entrenar_sin_datos_explica_que_falta(url):
    r = pj(url, "/api/entrenar", {})
    assert r["resultado"]["decision"] is None and r["resultado"]["falta"]
