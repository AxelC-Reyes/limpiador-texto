"""Duplicados exactos y casi-duplicados con MinHash + LSH (escala a cientos de miles)."""
from __future__ import annotations

import re
import unicodedata
import zlib
from collections import defaultdict

import numpy as np

N_PERM, BANDAS = 128, 32             # 32 bandas x 4 filas -> candidatos desde ~0.4 de similitud
PRIMO = np.uint64((1 << 61) - 1)
_rng = np.random.default_rng(42)
_A = _rng.integers(1, 1 << 31, N_PERM, dtype=np.uint64)
_B = _rng.integers(0, 1 << 31, N_PERM, dtype=np.uint64)


_ACENTOS = re.compile(r"[\u0300-\u036f]")
_PALABRA = re.compile(r"\w+")


def _tokens(texto: str) -> list[str]:
    return _PALABRA.findall(_ACENTOS.sub("", unicodedata.normalize("NFKD", texto.lower())))


class _Vocab(dict):
    def __missing__(self, palabra):
        h = self[palabra] = zlib.crc32(palabra.encode())
        return h


_VOCAB = _Vocab()


def _tejas(tok: list[str], k: int = 5) -> np.ndarray:
    """Hash de cada k-grama de palabras, vectorizado (rolling hash en numpy)."""
    if not tok:
        return np.empty(0, dtype=np.uint64)
    ids = np.array([_VOCAB[t] for t in tok], dtype=np.uint64)
    if len(ids) < k:
        return np.unique(ids[:1] ^ np.uint64(len(ids)))
    h = np.zeros(len(ids) - k + 1, dtype=np.uint64)
    for j in range(k):  # el overflow de uint64 es intencional: es un hash
        h = h * np.uint64(1_000_003) + ids[j:len(ids) - k + 1 + j]
    return np.unique(h & np.uint64(0xFFFFFFFF))


def _firma(x: np.ndarray) -> np.ndarray:
    return ((np.outer(_A, x) + _B[:, None]) % PRIMO).min(axis=1)


def _jaccard(a: np.ndarray, b: np.ndarray) -> float:
    if not len(a) or not len(b):
        return 0.0
    inter = len(np.intersect1d(a, b, assume_unique=True))
    return inter / (len(a) + len(b) - inter)


def huellas(n: dict) -> None:
    """Precalcula lo caro (tokens, tejas, firma). Se puede correr en paralelo por nota."""
    tok = _tokens(n["titulo"] + " " + n["cuerpo"])
    plano = " ".join(tok)
    n["_huella"] = f"t:{zlib.crc32(plano.encode())}:{len(plano)}" if plano else ""
    n["_tejas"] = _tejas(tok)
    n["_firma"] = _firma(n["_tejas"]) if len(n["_tejas"]) >= 3 else None


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, i):
        while self.p[i] != i:
            self.p[i] = self.p[self.p[i]]
            i = self.p[i]
        return i

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def agrupar(noticias: list[dict], umbral: float = 0.8, umbral_gris: float = 0.5
            ) -> tuple[list[int], list[tuple[int, int, float]]]:
    """
    Regresa:
      grupo[i]  -> representante del grupo de duplicados al que pertenece i
      grises    -> pares (i, j, sim) en zona gris, para revisión humana
    """
    n = len(noticias)
    uf = _UF(n)

    for x in noticias:
        if "_tejas" not in x:
            huellas(x)

    # 1) Exactos: misma URL canónica o mismo título+cuerpo normalizado.
    vistos: dict[str, int] = {}
    for i, x in enumerate(noticias):
        for k in (f'u:{x["url"]}' if x["url"] else "", x["_huella"]):
            if not k:
                continue
            if k in vistos:
                uf.union(i, vistos[k])
            else:
                vistos[k] = i

    # 2) Casi-duplicados: MinHash + LSH, luego verificación con Jaccard real.
    tejas = [x["_tejas"] for x in noticias]
    filas = N_PERM // BANDAS
    cubetas: dict[bytes, list[int]] = defaultdict(list)
    for i, x in enumerate(noticias):
        if x["_firma"] is None:
            continue
        crudo = x["_firma"].tobytes()
        paso = filas * 8
        for b in range(BANDAS):
            cubetas[bytes([b]) + crudo[b * paso:(b + 1) * paso]].append(i)

    revisados, grises = set(), []
    for miembros in cubetas.values():
        if len(miembros) < 2 or len(miembros) > 500:  # cubetas gigantes = texto genérico
            continue
        for a in range(len(miembros)):
            for b in range(a + 1, len(miembros)):
                i, j = miembros[a], miembros[b]
                if (i, j) in revisados or uf.find(i) == uf.find(j):
                    continue
                revisados.add((i, j))
                sim = _jaccard(tejas[i], tejas[j])
                if sim >= umbral:
                    uf.union(i, j)
                elif sim >= umbral_gris:
                    grises.append((i, j, round(sim, 3)))

    grupo = [uf.find(i) for i in range(n)]
    grises = [(i, j, s) for i, j, s in grises if grupo[i] != grupo[j]]
    return grupo, grises
