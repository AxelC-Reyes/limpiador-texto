"""Orquesta: cargar -> normalizar -> reglas -> duplicados -> modelo (si ya aprendió) -> dudosas para revisión humana."""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from functools import partial

import pandas as pd

from . import duplicados, normaliza, reglas
from .carga import cargar

COLUMNAS = ["id", "decision", "origen", "motivo", "puntaje", "categoria", "titulo", "resumen",
            "cuerpo", "fecha", "fuente", "url", "autor", "palabras", "duplicado_de",
            "fecha_original", "categoria_original", "archivo", "sugerencia", "confianza",
            "categoria_modelo", "motivos", "antes_modelo"]


@dataclass
class Opciones:
    reglas: reglas.Config = field(default_factory=reglas.Config)
    umbral_duplicado: float = 0.8
    umbral_gris: float = 0.5
    usar_modelo: bool = True
    umbral_modelo: float = 0.85     # el modelo solo decide si está así de seguro


def _preparar(reg: dict, cfg: reglas.Config) -> dict | None:
    n = normaliza.normalizar(reg)
    if not (n["titulo"] or n["cuerpo"]):
        return None
    n["palabras"] = len(n["cuerpo"].split())
    n["puntaje"], n["motivos"] = reglas.evaluar(n, cfg)
    n["decision"] = reglas.decidir(n["puntaje"], cfg)
    n["origen"] = "reglas"
    n["motivo"] = "; ".join(n["motivos"]) or "pasa todas las reglas"
    n["categoria"] = ""
    n["duplicado_de"] = ""
    duplicados.huellas(n)
    return n


PARALELO_DESDE = 5000   # abajo de esto, arrancar procesos cuesta más de lo que ahorra


def procesar(fuentes, op: Opciones | None = None, progreso=None) -> tuple[pd.DataFrame, dict]:
    op = op or Opciones()
    t0 = time.perf_counter()
    avisar = progreso or (lambda *_: None)

    avisar("Cargando archivos", 0.05)
    info_archivos: list[dict] = []
    crudos, errores = cargar(fuentes, info_archivos)
    _explicar_archivos(crudos, info_archivos)

    avisar("Normalizando y aplicando reglas", 0.15)
    tarea = partial(_preparar, cfg=op.reglas)
    if len(crudos) >= PARALELO_DESDE:
        with ProcessPoolExecutor(max(1, (os.cpu_count() or 2) - 1)) as ex:
            ns = list(ex.map(tarea, crudos, chunksize=500))
    else:
        ns = [tarea(r) for r in crudos]
    ns = [n for n in ns if n]
    vacios = len(crudos) - len(ns)

    avisar("Buscando duplicados", 0.45)
    grupo, grises = duplicados.agrupar(ns, op.umbral_duplicado, op.umbral_gris)
    miembros = defaultdict(list)
    for i, g in enumerate(grupo):
        miembros[g].append(i)
    mejor = lambda i: (ns[i]["puntaje"], ns[i]["palabras"], bool(ns[i]["fecha"]))
    n_dups = 0
    for idxs in miembros.values():
        if len(idxs) < 2:
            continue
        rep = max(idxs, key=mejor)
        for i in idxs:
            if i != rep:
                n_dups += 1
                ns[i].update(decision="descartar", origen="duplicado", duplicado_de=ns[rep]["id"],
                             motivo=f'duplicado de "{ns[rep]["titulo"][:80]}"')
    for i, j, sim in grises:
        debil, fuerte = sorted((i, j), key=mejor)
        if ns[debil]["decision"] != "descartar":
            ns[debil].update(decision="dudoso", duplicado_de=ns[fuerte]["id"])
            ns[debil]["motivos"].append(f"parecida ({sim:.0%}) a otra nota")
            ns[debil]["motivo"] = "; ".join(ns[debil]["motivos"])

    uso_modelo = None
    m = None
    if op.usar_modelo:
        from . import modelo  # aquí y no arriba: scikit tarda ~2 s en importar y los procesos paralelos no lo usan
        m = modelo.cargar()
    if m:
        avisar("Aplicando lo que aprendió el modelo", 0.8)
        uso_modelo = modelo.aplicar(ns, m, op.umbral_modelo)

    avisar("Listo", 1.0)
    df = pd.DataFrame(ns, columns=COLUMNAS) if ns else pd.DataFrame(columns=COLUMNAS)
    orden = {"dudoso": 0, "conservar": 1, "descartar": 2}
    df = df.sort_values(["decision", "puntaje"], key=lambda s: s.map(orden) if s.name == "decision" else -s)
    reporte = {
        "registros_leidos": len(crudos),
        "sin_titulo_ni_cuerpo": vacios,
        "conservar": int((df.decision == "conservar").sum()),
        "descartar": int((df.decision == "descartar").sum()),
        "dudoso": int((df.decision == "dudoso").sum()),
        "duplicados": n_dups,
        "fechas_ilegibles": int(df.fecha.isna().sum()),
        "errores_de_archivo": errores,
        "archivos": info_archivos,
        "modelo": uso_modelo,
        "segundos": round(time.perf_counter() - t0, 2),
    }
    return df.reset_index(drop=True), reporte


MUESTRA = 300  # para describir un archivo basta con sus primeras notas


def _recortar(v, largo: int = 160):
    """Versión corta de un registro para enseñarlo como ejemplo sin inundar la pantalla."""
    if isinstance(v, str):
        return v if len(v) <= largo else v[:largo] + "…"
    if isinstance(v, list):
        return [_recortar(x, largo) for x in v[:4]] + (["…"] if len(v) > 4 else [])
    if isinstance(v, dict):
        return {k: _recortar(x, largo) for k, x in v.items()}
    return v


def _explicar_archivos(crudos: list[dict], info: list[dict]) -> None:
    """Por archivo: de qué llave salió cada campo, qué llaves se ignoraron y un antes/después real."""
    por_archivo = defaultdict(list)
    for r in crudos:
        if len(por_archivo[r.get("_archivo")]) < MUESTRA:
            por_archivo[r.get("_archivo")].append(r)
    for a in info:
        muestra = por_archivo.get(a["nombre"], [])
        usos: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        ignoradas: dict[str, int] = defaultdict(int)
        for r in muestra:
            usados = normaliza.campos_usados(r)
            for campo, llave in usados.items():
                usos[campo][llave] += 1
            for k in r:
                if k != "_archivo" and k not in usados.values() and r[k] not in (None, "", [], {}):
                    ignoradas[str(k)] += 1
        n = max(1, len(muestra))
        a["muestra"] = len(muestra)
        a["campos"] = {c: {"de": max(v, key=v.get), "cobertura": round(sum(v.values()) / n, 3),
                           "variantes": sorted(v, key=v.get, reverse=True)}
                       for c, v in usos.items()}
        a["ignoradas"] = sorted(ignoradas, key=ignoradas.get, reverse=True)[:12]
        ejemplo = next((r for r in muestra if normaliza.campos_usados(r).get("cuerpo")), muestra[0] if muestra else None)
        if ejemplo:
            limpio = normaliza.normalizar(ejemplo)
            a["antes"] = json.dumps(_recortar({k: v for k, v in ejemplo.items() if k != "_archivo"}),
                                    ensure_ascii=False, indent=2)
            a["despues"] = json.dumps(_recortar({k: limpio[k] for k in
                                                 ("titulo", "cuerpo", "fecha", "fuente", "url", "autor") if limpio[k]}, 300),
                                      ensure_ascii=False, indent=2)


def exportar(df: pd.DataFrame, solo: str = "conservar") -> str:
    cols = ["id", "titulo", "resumen", "cuerpo", "fecha", "fuente", "url", "autor", "categoria"]
    return df[df.decision == solo][cols].to_json(orient="records", force_ascii=False, indent=2)
