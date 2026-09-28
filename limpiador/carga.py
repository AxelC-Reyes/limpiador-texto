"""Carga tolerante de noticias desde .json / .jsonl, venga como venga."""
from __future__ import annotations

import json
from pathlib import Path
from typing import IO, Iterable

# Llaves típicas donde las APIs de noticias esconden la lista de artículos.
LLAVES_CONTENEDOR = ("articles", "articulos", "noticias", "news", "data", "items",
                     "results", "resultados", "entries", "docs", "hits", "posts")


def _decodificar(crudo: bytes) -> str:
    for cod in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return crudo.decode(cod)
        except UnicodeDecodeError:
            continue
    return crudo.decode("utf-8", errors="replace")


def _aplanar(obj) -> Iterable[dict]:
    """Encuentra artículos dentro de listas, objetos contenedores o anidados."""
    if isinstance(obj, list):
        for x in obj:
            yield from _aplanar(x)
    elif isinstance(obj, dict):
        for llave in LLAVES_CONTENEDOR:
            if isinstance(obj.get(llave), list):
                yield from _aplanar(obj[llave])
                return
        # Elasticsearch: {"hits": {"hits": [{"_source": {...}}]}}
        if isinstance(obj.get("hits"), dict):
            yield from _aplanar(obj["hits"])
            return
        if "_source" in obj and isinstance(obj["_source"], dict):
            yield obj["_source"]
            return
        yield obj


def _formato(obj) -> str:
    """Describe en palabras cómo venía el archivo, para mostrarlo en la interfaz."""
    if isinstance(obj, list):
        return "Lista JSON"
    if isinstance(obj, dict):
        for llave in LLAVES_CONTENEDOR:
            if isinstance(obj.get(llave), list):
                return f"Objeto con la lista «{llave}»"
        if isinstance(obj.get("hits"), dict):
            return "Respuesta de Elasticsearch"
        return "Un solo objeto"
    return "Desconocido"


def parsear_texto(texto: str) -> tuple[list[dict], list[str]]:
    """Regresa (artículos, errores). Soporta JSON normal y JSON Lines."""
    return leer(texto)[:2]


def leer(texto: str) -> tuple[list[dict], list[str], str]:
    """Como parsear_texto, pero además dice qué formato encontró."""
    texto = texto.strip()
    if not texto:
        return [], ["archivo vacío"], "Vacío"
    try:
        obj = json.loads(texto)
        return list(_aplanar(obj)), [], _formato(obj)
    except json.JSONDecodeError:
        pass
    # JSON Lines: un objeto por renglón; los renglones rotos se reportan, no truenan todo.
    articulos, errores = [], []
    for n, linea in enumerate(texto.splitlines(), 1):
        linea = linea.strip().rstrip(",")
        if not linea or linea in ("[", "]"):
            continue
        try:
            articulos.extend(_aplanar(json.loads(linea)))
        except json.JSONDecodeError as e:
            errores.append(f"renglón {n}: {e.msg}")
    if not articulos and errores:
        return [], [f"no es JSON válido ({errores[0]})"], "No es JSON válido"
    return articulos, errores, "JSON Lines (un objeto por renglón)"


def cargar(fuentes: Iterable[str | Path | IO[bytes]], info: list | None = None) -> tuple[list[dict], list[str]]:
    """Acepta rutas, carpetas o archivos subidos (objetos con .read() y .name).
    Si se pasa `info`, agrega un resumen por archivo (formato, registros, errores)."""
    todos, errores = [], []
    for f in fuentes:
        if isinstance(f, (str, Path)):
            p = Path(f)
            archivos = sorted([*p.rglob("*.json"), *p.rglob("*.jsonl")]) if p.is_dir() else [p]
            pares = [(a.name, a.read_bytes()) for a in archivos]
        else:
            pares = [(getattr(f, "name", "subido"), f.read())]
        for nombre, crudo in pares:
            arts, errs, formato = leer(_decodificar(crudo))
            if info is not None:
                info.append({"nombre": nombre, "formato": formato, "registros": len(arts),
                             "bytes": len(crudo), "errores": errs[:20], "total_errores": len(errs)})
            for a in arts:
                a.setdefault("_archivo", nombre)
            todos.extend(arts)
            errores.extend(f"{nombre}: {e}" for e in errs)
    return todos, errores
