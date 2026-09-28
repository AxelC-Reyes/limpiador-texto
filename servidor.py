"""Interfaz web local.   Correr con:  python servidor.py   (abre el navegador solo)

Solo usa la biblioteca estándar de Python para servir la página: sin internet, sin frameworks.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import mimetypes
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import numpy as np
import pandas as pd

from limpiador import Opciones, exportar, procesar
from limpiador.pipeline import COLUMNAS
from limpiador.reglas import CATEGORIAS, Config

RAIZ = Path(__file__).resolve().parent
WEB = RAIZ / "web"
DATOS_PRUEBA = RAIZ / "datos_prueba"
LIGEROS = ["id", "decision", "origen", "motivo", "puntaje", "categoria", "titulo", "fuente", "fecha",
           "palabras", "duplicado_de", "sugerencia", "confianza", "categoria_modelo"]


class Estado:
    def __init__(self):
        self.lock = threading.RLock()
        self.archivos: dict[str, bytes] = {}   # se conservan para volver a limpiar con otros ajustes
        self.notas: list[dict] = []
        self.por_id: dict[str, dict] = {}
        self.reporte: dict | None = None
        self.opciones: dict = {}

    def cargar_notas(self, df: pd.DataFrame, rep: dict):
        self.notas = [{k: _limpio(v) for k, v in r.items()} for r in df.to_dict("records")]
        self.por_id = {n["id"]: n for n in self.notas}
        self.reporte = rep

    def conteos(self) -> dict:
        c = {"conservar": 0, "descartar": 0, "dudoso": 0}
        for n in self.notas:
            c[n["decision"]] = c.get(n["decision"], 0) + 1
        return c


E = Estado()


def _limpio(v):
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, np.generic):
        return v.item()
    if isinstance(v, np.ndarray):
        return v.tolist()
    return v


def _json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=_limpio).encode("utf-8")


def _opciones(o: dict) -> Opciones:
    bajo, alto = float(o.get("umbral_bajo", 0.35)), float(o.get("umbral_alto", 0.70))
    return Opciones(
        reglas=Config(min_palabras=int(o.get("min_palabras", 60)),
                      umbral_conservar=max(bajo, alto), umbral_descartar=min(bajo, alto)),
        umbral_duplicado=float(o.get("umbral_duplicado", 0.8)),
        umbral_gris=min(float(o.get("umbral_gris", 0.5)), float(o.get("umbral_duplicado", 0.8))),
        usar_modelo=bool(o.get("usar_modelo", True)),
        umbral_modelo=float(o.get("umbral_modelo", 0.85)),
    )


# ------------------------------------------------------------------ acciones
def api_subir(nombre: str, cuerpo: bytes) -> dict:
    with E.lock:
        E.archivos[nombre] = cuerpo
        return {"archivos": [{"nombre": k, "bytes": len(v)} for k, v in E.archivos.items()]}


def api_quitar_archivos(_):
    with E.lock:
        E.archivos.clear()
        return {"archivos": []}


def api_prueba(_):
    with E.lock:
        E.archivos = {p.name: p.read_bytes() for p in sorted(DATOS_PRUEBA.glob("*.json*"))
                      if not p.name.startswith("masivo")}
        return {"archivos": [{"nombre": k, "bytes": len(v)} for k, v in E.archivos.items()]}


def api_procesar(datos: dict) -> dict:
    with E.lock:
        if not E.archivos:
            raise ValueError("Primero sube al menos un archivo.")
        fuentes = []
        for nombre, crudo in E.archivos.items():
            b = io.BytesIO(crudo); b.name = nombre
            fuentes.append(b)
        E.opciones = datos.get("opciones", {})
        df, rep = procesar(fuentes, _opciones(E.opciones))
        E.cargar_notas(df, rep)
        return {"reporte": rep, "conteos": E.conteos()}


def api_notas(_q) -> dict:
    with E.lock:
        return {"notas": [{k: n.get(k) for k in LIGEROS} for n in E.notas],
                "reporte": E.reporte, "conteos": E.conteos(), "opciones": E.opciones,
                "archivos": [{"nombre": k, "bytes": len(v)} for k, v in E.archivos.items()]}


def api_nota(q) -> dict:
    with E.lock:
        n = E.por_id.get(q.get("id", [""])[0])
        if not n:
            raise KeyError("Esa nota ya no existe; vuelve a limpiar.")
        par = E.por_id.get(n.get("duplicado_de") or "")
        quitar = ("motivos", "antes_modelo")
        return {"nota": {k: v for k, v in n.items() if k not in quitar},
                "parecida": {k: v for k, v in par.items() if k not in quitar} if par else None}


def api_decidir(datos: dict) -> dict:
    from limpiador import modelo
    with E.lock:
        n = E.por_id.get(datos.get("id"))
        if not n:
            raise KeyError("Esa nota ya no existe; vuelve a limpiar.")
        anterior = datos.get("deshacer")
        if anterior:  # regresar la nota a como estaba antes de la última decisión
            if anterior.get("decision") not in ("conservar", "descartar", "dudoso"):
                raise ValueError("decisión inválida")
            n.update(decision=anterior["decision"], origen=anterior.get("origen") or "reglas")
            if anterior.get("motivo") is not None:
                n["motivo"] = anterior["motivo"]
            # la etiqueta vuelve a lo que había: si antes no la decidió una persona, se retira
            modelo.guardar_etiqueta(n, anterior["decision"] if n["origen"] == "humano" else "dudoso")
            return {"nota": {k: n.get(k) for k in LIGEROS}, "conteos": E.conteos(),
                    "modelo": modelo.estado()}
        decision, categoria = datos.get("decision"), datos.get("categoria")
        if decision:
            if decision not in ("conservar", "descartar", "dudoso"):
                raise ValueError("decisión inválida")
            n["decision"], n["origen"] = decision, "humano"
        if categoria is not None:
            if categoria and categoria not in CATEGORIAS:
                raise ValueError("categoría inválida")
            n["categoria"], n["categoria_modelo"] = categoria, None
        if decision or categoria:
            modelo.guardar_etiqueta(n, decision, categoria or None)
        return {"nota": {k: n.get(k) for k in LIGEROS}, "conteos": E.conteos(),
                "modelo": modelo.estado()}


def api_modelo(_q) -> dict:
    from limpiador import modelo
    return modelo.estado()


def api_entrenar(_d) -> dict:
    from limpiador import modelo
    res = modelo.entrenar()
    aplicado = None
    m = modelo.cargar()
    with E.lock:
        if m and E.notas:
            # Aplicar de inmediato a lo cargado, sin tocar lo que ya decidió una persona.
            modelo.deshacer(E.notas)
            umbral = float(E.opciones.get("umbral_modelo", 0.85))
            aplicado = modelo.aplicar(E.notas, m, umbral)
    return {"resultado": res, "estado": modelo.estado(), "aplicado": aplicado,
            "conteos": E.conteos()}


def api_config(_q) -> dict:
    return {"categorias": CATEGORIAS, "hay_prueba": DATOS_PRUEBA.exists()}


def api_exportar(q) -> tuple[bytes, str, str]:
    tipo = q.get("tipo", ["limpias"])[0]
    with E.lock:
        if not E.notas:
            raise ValueError("No hay nada que exportar todavía.")
        df = pd.DataFrame(E.notas, columns=COLUMNAS)
        if tipo == "limpias":
            return exportar(df, "conservar").encode(), "noticias_limpias.json", "application/json"
        if tipo == "dudosas":
            return exportar(df, "dudoso").encode(), "dudosas.json", "application/json"
        if tipo == "descartadas":
            cols = ["id", "titulo", "fuente", "url", "origen", "motivo", "duplicado_de"]
            return (df[df.decision == "descartar"][cols].to_json(orient="records", force_ascii=False, indent=2)
                    .encode(), "descartadas.json", "application/json")
        if tipo == "csv":
            return (df.drop(columns=["motivos", "antes_modelo"]).to_csv(index=False).encode("utf-8-sig"),
                    "noticias_todas.csv", "text/csv")
        if tipo == "reporte":
            return _json({**(E.reporte or {}), "conteos_finales": E.conteos()}), "reporte.json", "application/json"
    raise ValueError("tipo de exportación desconocido")


GET = {"/api/notas": api_notas, "/api/nota": api_nota, "/api/modelo": api_modelo, "/api/config": api_config}
POST = {"/api/procesar": api_procesar, "/api/decidir": api_decidir, "/api/entrenar": api_entrenar,
        "/api/prueba": api_prueba, "/api/quitar-archivos": api_quitar_archivos}
MAX_SUBIDA = 1024 * 1024 * 1024  # 1 GB por archivo


# ------------------------------------------------------------------ HTTP
class Manejador(BaseHTTPRequestHandler):
    server_version = "Limpiador/1.0"

    def log_message(self, *_):
        pass  # silencio: la consola es para errores

    def _responder(self, codigo: int, cuerpo: bytes, tipo="application/json; charset=utf-8", extra=None):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(cuerpo)

    def _error(self, e: Exception):
        codigo = 404 if isinstance(e, KeyError) else 400 if isinstance(e, ValueError) else 500
        if codigo == 500:
            traceback.print_exc()
        msg = e.args[0] if e.args and isinstance(e.args[0], str) else f"{type(e).__name__}: {e}"
        self._responder(codigo, _json({"error": msg}))

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path == "/api/exportar":
                cuerpo, nombre, tipo = api_exportar(q)
                return self._responder(200, cuerpo, tipo, {
                    "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nombre)}"})
            if url.path in GET:
                return self._responder(200, _json(GET[url.path](q)))
            ruta = (WEB / ("index.html" if url.path == "/" else url.path.lstrip("/"))).resolve()
            if WEB not in ruta.parents or not ruta.is_file():
                return self._responder(404, b"no encontrado", "text/plain")
            tipo = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
            if tipo.startswith("text/") or tipo.endswith("javascript"):
                tipo += "; charset=utf-8"
            self._responder(200, ruta.read_bytes(), tipo)
        except Exception as e:  # noqa: BLE001 — cualquier error vuelve como JSON, el servidor sigue vivo
            self._error(e)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            largo = int(self.headers.get("Content-Length") or 0)
            if largo > MAX_SUBIDA:
                raise ValueError("Archivo demasiado grande (máximo 1 GB).")
            crudo = self.rfile.read(largo) if largo else b""
            if url.path == "/api/subir":
                nombre = unquote(self.headers.get("X-Nombre") or "archivo.json")
                return self._responder(200, _json(api_subir(Path(nombre).name, crudo)))
            if url.path not in POST:
                return self._responder(404, _json({"error": "ruta desconocida"}))
            datos = json.loads(crudo) if crudo else {}
            self._responder(200, _json(POST[url.path](datos)))
        except Exception as e:  # noqa: BLE001
            self._error(e)


def main():
    ap = argparse.ArgumentParser(description="Interfaz web del limpiador de noticias")
    ap.add_argument("--puerto", type=int, default=8600)
    ap.add_argument("--sin-navegador", action="store_true")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.puerto), Manejador)  # solo esta máquina, no la red
    url = f"http://localhost:{a.puerto}"
    print(f"Limpiador listo en {url}  (Ctrl+C para salir)")
    if not a.sin_navegador:
        threading.Timer(0.6, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nAdiós.")


if __name__ == "__main__":  # obligatorio: los procesos paralelos reimportan este archivo en Mac/Windows
    main()
