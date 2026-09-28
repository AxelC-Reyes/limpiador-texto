"""Unifica el esquema y limpia texto, fechas y URLs."""
from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import ftfy
from bs4 import BeautifulSoup
from dateutil import parser as dparser

# Campo canónico -> nombres con los que suele venir.
ALIAS = {
    "titulo": ["titulo", "título", "title", "headline", "encabezado", "titular", "name"],
    "resumen": ["resumen", "summary", "description", "descripcion", "descripción", "bajada",
                "lead", "abstract", "excerpt"],
    "cuerpo": ["cuerpo", "body", "content", "contenido", "text", "texto", "article",
               "articulo", "full_text", "articleBody"],
    "fecha": ["fecha", "date", "published", "published_at", "publishedAt", "pubDate",
              "fecha_publicacion", "datetime", "timestamp", "created_at", "time"],
    "fuente": ["fuente", "source", "medio", "publisher", "site", "sitio", "outlet"],
    "url": ["url", "link", "enlace", "href", "permalink", "canonical_url"],
    "autor": ["autor", "author", "authors", "autores", "byline", "creator"],
    "categoria": ["categoria", "categoría", "category", "section", "seccion", "sección", "tags"],
}
_ALIAS_MIN = {c: [a.lower() for a in v] for c, v in ALIAS.items()}

# Renglones de relleno que meten los medios dentro del cuerpo.
BASURA = re.compile(
    r"^\s*(lee también|leer también|te puede interesar|también te puede interesar|"
    r"te recomendamos|relacionad[oa]s?:|mira también|ver también|suscr[ií]bete|"
    r"s[ií]guenos en|síguenos|únete a nuestro canal|publicidad|anuncio|"
    r"todos los derechos reservados|©|foto:|imagen:|video:|con información de|"
    r"aceptar cookies|este sitio usa cookies|comparte esta nota|haz clic aquí|"
    r"descarga nuestra app|newsletter|click here|read more|advertisement).*$",
    re.IGNORECASE,
)

MESES = {"enero": "january", "febrero": "february", "marzo": "march", "abril": "april",
         "mayo": "may", "junio": "june", "julio": "july", "agosto": "august",
         "septiembre": "september", "setiembre": "september", "octubre": "october",
         "noviembre": "november", "diciembre": "december", "ene": "jan", "abr": "apr",
         "ago": "aug", "sept": "sep", "dic": "dec"}
DIAS = r"\b(lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo),?\s*"
RELATIVA = re.compile(r"hace\s+(\d+|un|una)\s+(minuto|hora|d[ií]a|semana|mes)", re.I)
UNIDAD = {"minuto": "minutes", "hora": "hours", "dia": "days", "día": "days", "semana": "weeks"}
_MOJIBAKE = re.compile(r"[ÃÂâð][\u0080-\u00ff\u2000-\u206f]|\ufffd")
PARAMS_BASURA = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_|source$|amp$|outputType)", re.I)


def _valor(reg: dict, campo: str):
    llaves = {str(k).lower(): k for k in reg}
    for alias in _ALIAS_MIN[campo]:
        if alias in llaves and reg[llaves[alias]] not in (None, "", [], {}):
            return reg[llaves[alias]]
    return None


def campos_usados(reg: dict) -> dict[str, str]:
    """De qué llave del archivo original salió cada campo limpio (para explicarlo en la interfaz)."""
    llaves = {str(k).lower(): k for k in reg}
    usados = {}
    for campo, alias in _ALIAS_MIN.items():
        for a in alias:
            if a in llaves and reg[llaves[a]] not in (None, "", [], {}):
                usados[campo] = str(llaves[a])
                break
    return usados


def _a_texto(v) -> str:
    """Aplana dicts/listas típicos: {"name": "El Universal"}, ["Ana", "Luis"]."""
    if v is None:
        return ""
    if isinstance(v, dict):
        for k in ("name", "nombre", "title", "text", "value", "rendered"):
            if k in v:
                return _a_texto(v[k])
        return " ".join(_a_texto(x) for x in v.values())
    if isinstance(v, list):
        return ", ".join(t for t in (_a_texto(x) for x in v) if t)
    return str(v)


def limpiar_texto(t, quitar_basura: bool = False) -> str:
    t = _a_texto(t)
    if not t:
        return ""
    if _MOJIBAKE.search(t):
        t = ftfy.fix_text(t)  # arregla "NoticiÃ³n" -> "Notición"
    if "<" in t and ">" in t:
        sopa = BeautifulSoup(t, "html.parser")
        for tag in sopa(["script", "style", "iframe", "noscript", "figure", "aside"]):
            tag.decompose()
        for br in sopa.find_all(["br", "p", "div", "li", "h1", "h2", "h3"]):
            br.insert_after("\n")
        t = sopa.get_text()
    t = html.unescape(t)
    t = unicodedata.normalize("NFC", t)
    t = t.replace(" ", " ").replace("​", "")
    renglones = [re.sub(r"[ \t]+", " ", r).strip() for r in t.splitlines()]
    if quitar_basura:
        renglones = [r for r in renglones if not BASURA.match(r)]
    t = "\n".join(r for r in renglones if r)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def normalizar_fecha(v, ahora: datetime | None = None) -> str | None:
    """Devuelve ISO 8601 en UTC o None si no se pudo entender."""
    if v in (None, ""):
        return None
    ahora = ahora or datetime.now(timezone.utc)
    try:
        if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip().isdigit()):
            n = float(v)
            n = n / 1000 if n > 1e11 else n  # milisegundos
            return datetime.fromtimestamp(n, tz=timezone.utc).isoformat()
        s = _a_texto(v).strip().lower()
        if s in ("hoy", "today"):
            return ahora.replace(microsecond=0).isoformat()
        if s in ("ayer", "yesterday"):
            return (ahora - timedelta(days=1)).replace(microsecond=0).isoformat()
        m = RELATIVA.search(s)
        if m:
            n = 1 if m[1] in ("un", "una") else int(m[1])
            unidad = m[2].replace("í", "i")
            delta = timedelta(days=30 * n) if unidad == "mes" else timedelta(**{UNIDAD[unidad]: n})
            return (ahora - delta).replace(microsecond=0).isoformat()
        s = re.sub(DIAS, "", s)
        s = re.sub(r"\bde(l)?\b", " ", s)
        s = re.sub(r"\b(" + "|".join(sorted(MESES, key=len, reverse=True)) + r")\b",
                   lambda m: MESES[m[1]], s)
        s = re.sub(r"\b(a las|hrs?\.?|horas)\b", " ", s)
        iso = bool(re.match(r"^\d{4}-\d{2}-\d{2}", s))
        d = dparser.parse(s, dayfirst=not iso, fuzzy=True)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        d = d.astimezone(timezone.utc)
        if not (1990 <= d.year <= ahora.year + 1):
            return None
        return d.isoformat()
    except (ValueError, OverflowError, TypeError, KeyError):
        return None


def canonizar_url(u) -> str:
    u = _a_texto(u).strip()
    if not u:
        return ""
    if u.startswith("//"):
        u = "https:" + u
    if not re.match(r"^https?://", u, re.I):
        return u
    p = urlsplit(u)
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.").removeprefix("amp.")
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not PARAMS_BASURA.match(k)))
    ruta = re.sub(r"/(amp/?)?$", "", p.path) or "/"
    return urlunsplit(("https", host, ruta, query, ""))


def normalizar(reg: dict, ahora: datetime | None = None) -> dict:
    fecha_cruda = _valor(reg, "fecha")
    fuente = limpiar_texto(_valor(reg, "fuente"))
    url = canonizar_url(_valor(reg, "url"))
    if not fuente and url.startswith("https://"):
        fuente = urlsplit(url).netloc
    out = {
        "titulo": limpiar_texto(_valor(reg, "titulo")).replace("\n", " "),
        "resumen": limpiar_texto(_valor(reg, "resumen"), quitar_basura=True),
        "cuerpo": limpiar_texto(_valor(reg, "cuerpo"), quitar_basura=True),
        "fecha": normalizar_fecha(fecha_cruda, ahora),
        "fecha_original": _a_texto(fecha_cruda),
        "fuente": fuente,
        "url": url,
        "autor": re.sub(r"^(por|by)\s+", "", limpiar_texto(_valor(reg, "autor")), flags=re.I),
        "categoria_original": limpiar_texto(_valor(reg, "categoria")),
        "archivo": reg.get("_archivo", ""),
    }
    # Si no hay cuerpo pero sí resumen, el resumen hace de cuerpo.
    if not out["cuerpo"] and out["resumen"]:
        out["cuerpo"] = out["resumen"]
    base = out["url"] or (out["titulo"] + out["cuerpo"][:500])
    out["id"] = hashlib.sha1(base.encode()).hexdigest()[:12]
    return out
