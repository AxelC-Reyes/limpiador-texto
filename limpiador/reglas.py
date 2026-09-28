"""Puntaje de calidad por reglas: rápido, gratis y explicable."""
from __future__ import annotations

import re
from dataclasses import dataclass

CLICKBAIT = re.compile(
    r"(no vas a creer|no creerás|te sorprenderá|lo que pasó después|esto es lo que|"
    r"\bimpactante\b|\bincreíble\b|\bviral\b|you won't believe|shocking)")
# Frases se buscan como subcadena; palabras sueltas como palabra completa (sin regex: es más rápido).
FRASES_NO_NOTICIA = ("horóscopo", "horoscopo", "compra ahora", "oferta exclusiva", "page not found",
                     "acceso denegado", "inicia sesión para", "contenido exclusivo para suscriptores")
PALABRAS_NO_NOTICIA = frozenset({"cupón", "promoción", "descuento", "patrocinado", "sponsored",
                                 "casino", "apuestas", "404"})
CATEGORIAS = ["política", "economía", "seguridad", "internacional", "sociedad", "salud",
              "ciencia y tecnología", "deportes", "cultura y espectáculos", "medio ambiente",
              "opinión", "otro"]

_PUNTUACION = str.maketrans({c: " " for c in ".,;:!?¡¿\"'()[]{}«»“”‘’/\\|-–—…*#@%&+=<>"})



@dataclass
class Config:
    min_palabras: int = 60          # menos que esto no suele ser nota completa
    umbral_conservar: float = 0.70
    umbral_descartar: float = 0.35


def evaluar(n: dict, cfg: Config) -> tuple[float, list[str]]:
    """Regresa (puntaje 0-1, motivos). Cada motivo resta puntos."""
    motivos, puntaje = [], 1.0
    palabras = len(n["cuerpo"].split())
    # La publicidad y las páginas de error se delatan al principio; no hace falta leer todo.
    # Minúsculas una sola vez: las regex con re.I sobre unicode son lentas en Python.
    texto = f'{n["titulo"]}\n{n["cuerpo"][:1500]}'.lower()

    if not n["titulo"]:
        puntaje -= 0.25; motivos.append("sin título")
    elif len(n["titulo"]) < 15:
        puntaje -= 0.10; motivos.append("título muy corto")
    if palabras == 0:
        puntaje -= 0.70; motivos.append("sin cuerpo")
    elif palabras < cfg.min_palabras:
        puntaje -= 0.35 * (1 - palabras / cfg.min_palabras) + 0.10
        motivos.append(f"cuerpo corto ({palabras} palabras)")
    if not n["fecha"]:
        puntaje -= 0.10; motivos.append("fecha ilegible o ausente")
    if not n["fuente"] and not n["url"]:
        puntaje -= 0.10; motivos.append("sin fuente ni URL")
    if (any(f in texto for f in FRASES_NO_NOTICIA)
            or not PALABRAS_NO_NOTICIA.isdisjoint(texto.translate(_PUNTUACION).split())):
        puntaje -= 0.35; motivos.append("parece publicidad o página de error")
    if CLICKBAIT.search(n["titulo"].lower()):
        puntaje -= 0.10; motivos.append("título clickbait")
    if n["titulo"] and n["titulo"].isupper() and len(n["titulo"]) > 20:
        puntaje -= 0.05; motivos.append("título en mayúsculas")
    muestra = n["cuerpo"][:3000]
    if muestra and sum(map(str.isalpha, muestra)) / len(muestra) < 0.6:
        puntaje -= 0.25; motivos.append("cuerpo con mucho ruido (símbolos/código)")
    if "�" in texto:
        puntaje -= 0.10; motivos.append("caracteres corruptos")
    return round(max(0.0, min(1.0, puntaje)), 3), motivos


def decidir(puntaje: float, cfg: Config) -> str:
    if puntaje >= cfg.umbral_conservar:
        return "conservar"
    if puntaje <= cfg.umbral_descartar:
        return "descartar"
    return "dudoso"
