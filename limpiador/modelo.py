"""Modelo que aprende de las decisiones humanas (scikit-learn, sin GPU ni internet).

Cada vez que alguien decide una nota a mano se guarda como ejemplo en etiquetas.jsonl.
Con suficientes ejemplos se entrena:
  - decisión: conservar / descartar     (regresión logística sobre TF-IDF del texto + fuente)
  - categoría: política, deportes, ...  (regresión logística sobre TF-IDF)
Solo mira el contenido, no las señales de las reglas: si las viera, aprendería atajos
("título corto = basura") en vez de leer. Lo que hace con cada nota:
  - dudosa y el modelo muy seguro       -> la decide
  - conservada por reglas, pero el modelo
    está muy seguro de que es basura    -> la regresa a dudosa (nunca descarta solo)
  - conservada                          -> le sugiere categoría
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from joblib import Parallel, delayed
from scipy import sparse
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline

CARPETA = Path(os.getenv("LIMPIADOR_DATOS", Path(__file__).resolve().parent.parent / "datos_modelo"))
MIN_EJEMPLOS = 20          # total de notas etiquetadas para entrenar la decisión
MIN_POR_CLASE = 5          # de cada lado (conservar y descartar)
MIN_POR_CATEGORIA = 3
_lock = threading.Lock()

# Palabras que no dicen nada del contenido (sin acentos: el vectorizador los quita antes de comparar).
VACIAS = sorted(set("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun bajo bien cada casi como con contra
cual cuales cuando de del desde donde dos e el ella ellas ello ellos en entre era eran es esa esas ese eso
esos esta estaba estado estan estar estas este esto estos fue fueron ha habia han hasta hay la las le les
lo los mas me mi mientras muy nada ni no nos o otra otras otro otros para pero poco por porque que quien
se sea segun ser si sido sin sobre solo son su sus tambien tanto te tiene tienen todo todos tras tu u un
una unas uno unos y ya yo
""".split()))


# ------------------------------------------------------------------ ejemplos etiquetados
def _ruta_etiquetas() -> Path:
    return CARPETA / "etiquetas.jsonl"


def guardar_etiqueta(n: dict, decision: str | None = None, categoria: str | None = None) -> None:
    """Agrega una decisión humana. Si la misma nota se corrige después, gana la última.
    decision="dudoso" retira una decisión anterior (la persona se arrepintió)."""
    if decision not in (None, "conservar", "descartar", "dudoso"):
        return
    CARPETA.mkdir(parents=True, exist_ok=True)
    fila = {"id": n["id"], "titulo": n["titulo"], "cuerpo": n["cuerpo"][:4000], "fuente": n["fuente"],
            "palabras": n["palabras"], "puntaje": n["puntaje"], "motivos": n["motivos"],
            "decision": decision, "categoria": categoria or None,
            "cuando": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with _lock, open(_ruta_etiquetas(), "a", encoding="utf-8") as f:
        f.write(json.dumps(fila, ensure_ascii=False) + "\n")


def cargar_etiquetas() -> pd.DataFrame:
    ruta = _ruta_etiquetas()
    if not ruta.exists():
        return pd.DataFrame(columns=["id", "decision", "categoria"])
    filas = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(linea)
        except json.JSONDecodeError:
            continue
        prev = filas.get(r["id"], {})
        # Una etiqueta de solo-categoría no borra la decisión anterior, ni al revés.
        r["decision"] = None if r.get("decision") == "dudoso" else r.get("decision") or prev.get("decision")
        r["categoria"] = r.get("categoria") or prev.get("categoria")
        filas[r["id"]] = r
    return pd.DataFrame(list(filas.values()))


# ------------------------------------------------------------------ rasgos
FORMATO = 2            # súbelo si cambia la forma del modelo guardado: los viejos se ignoran
LARGO_TEXTO = 2000     # el arranque de la nota basta para saber de qué trata (y es 2x más rápido)
PARALELO_DESDE = 4000


def _tabla(filas) -> pd.DataFrame:
    df = pd.DataFrame(filas)
    return pd.DataFrame({
        # el título pesa doble: dice mucho de qué trata la nota
        "texto": (df.titulo.fillna("") + " ") * 2 + df.cuerpo.fillna("").str.slice(0, LARGO_TEXTO),
        "fuente": "fuente:" + df.fuente.fillna("").str.lower().str.replace(r"\W+", "_", regex=True),
    })


def _vectorizador() -> ColumnTransformer:
    """Uno solo para los dos modelos: el texto se procesa una vez aunque se decida y categorice."""
    return ColumnTransformer([
        ("texto", TfidfVectorizer(ngram_range=(1, 2), max_features=50000, stop_words=VACIAS,
                                  sublinear_tf=True, strip_accents="unicode"), "texto"),
        ("fuente", CountVectorizer(binary=True, token_pattern=r"\S+", lowercase=False), "fuente"),
    ])


def _clasificador(C: float) -> LogisticRegression:
    return LogisticRegression(C=C, class_weight="balanced", max_iter=2000)


def _transformar(vec: ColumnTransformer, X: pd.DataFrame):
    """TF-IDF es Python puro en scikit: con muchas notas se reparte entre núcleos."""
    if len(X) < PARALELO_DESDE:
        return vec.transform(X).tocsr()
    nucleos = max(1, (os.cpu_count() or 2) - 1)
    tam = -(-len(X) // nucleos)
    partes = Parallel(n_jobs=nucleos)(delayed(vec.transform)(X.iloc[i:i + tam]) for i in range(0, len(X), tam))
    return sparse.vstack(partes).tocsr()


def _evaluar(X, y, C: float) -> dict:
    """Validación cruzada: cómo le va con notas que NO vio al entrenar (el vectorizador se
    reajusta en cada parte, para no hacer trampa viendo el vocabulario de la prueba)."""
    pipe = Pipeline([("rasgos", _vectorizador()), ("clf", _clasificador(C))])
    minimo = int(pd.Series(y).value_counts().min())
    k = max(2, min(5, minimo))
    pred = cross_val_predict(pipe, X, y, cv=StratifiedKFold(k, shuffle=True, random_state=0))
    por_clase = {c: round(float((pred[y == c] == c).mean()), 3) for c in sorted(set(y))}
    return {"precision": round(float((pred == y).mean()), 3), "por_clase": por_clase, "pliegues": k}


# ------------------------------------------------------------------ entrenar / cargar
def entrenar() -> dict:
    """Entrena con todo lo etiquetado y guarda el modelo. Regresa un resumen legible."""
    et = cargar_etiquetas()
    res = {"ejemplos": len(et), "decision": None, "categoria": None, "falta": []}
    if not len(et):
        res["falta"] = ["todavía no hay notas decididas a mano"]
        return res

    dec = et[et.decision.isin(["conservar", "descartar"])]
    conteo = dec.decision.value_counts().to_dict()
    usar_dec = len(dec) >= MIN_EJEMPLOS and min(conteo.get("conservar", 0), conteo.get("descartar", 0)) >= MIN_POR_CLASE
    if not usar_dec:
        res["falta"].append(
            f"decisión: van {conteo.get('conservar', 0)} conservadas y {conteo.get('descartar', 0)} "
            f"descartadas; hacen falta {MIN_EJEMPLOS} en total y al menos {MIN_POR_CLASE} de cada una")

    cat = et[et.categoria.fillna("") != ""]
    cuenta_cat = cat.categoria.value_counts()
    validas = cuenta_cat[cuenta_cat >= MIN_POR_CATEGORIA].index
    cat = cat[cat.categoria.isin(validas)]
    usar_cat = len(validas) >= 2
    if not usar_cat:
        res["falta"].append(f"categoría: hacen falta al menos 2 categorías con {MIN_POR_CATEGORIA} "
                            f"notas cada una (hay {len(validas)})")
    if not (usar_dec or usar_cat):
        return res

    todas = et[et.id.isin((set(dec.id) if usar_dec else set()) | (set(cat.id) if usar_cat else set()))]
    vec = _vectorizador().fit(_tabla(todas.to_dict("records")))
    modelo = {"formato": FORMATO, "version_sklearn": sklearn.__version__,
              "entrenado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "vectorizador": vec, "nombres": vec.get_feature_names_out()}
    if usar_dec:
        X, y = _tabla(dec.to_dict("records")), dec.decision.to_numpy()
        res["decision"] = {**_evaluar(X, y, 4.0), "ejemplos": conteo}
        modelo["decision"] = _clasificador(4.0).fit(vec.transform(X), y)
        modelo["decision_eval"] = res["decision"]
    if usar_cat:
        X, y = _tabla(cat.to_dict("records")), cat.categoria.to_numpy()
        res["categoria"] = {**_evaluar(X, y, 8.0), "ejemplos": cuenta_cat[validas].to_dict()}
        modelo["categoria"] = _clasificador(8.0).fit(vec.transform(X), y)
        modelo["categoria_eval"] = res["categoria"]

    CARPETA.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, CARPETA / "modelo.joblib")
    return res


def cargar() -> dict | None:
    ruta = CARPETA / "modelo.joblib"
    if not ruta.exists():
        return None
    try:
        m = joblib.load(ruta)  # solo cargar modelos hechos aquí: joblib ejecuta código al abrir
    except Exception:
        return None
    ok = m.get("version_sklearn") == sklearn.__version__ and m.get("formato") == FORMATO
    return m if ok else None  # incompatible: mejor reentrenar que decidir con algo roto


def estado() -> dict:
    et = cargar_etiquetas()
    m = cargar()
    return {
        "ejemplos": len(et),
        "conservar": int((et.decision == "conservar").sum()) if len(et) else 0,
        "descartar": int((et.decision == "descartar").sum()) if len(et) else 0,
        "con_categoria": int(et.categoria.fillna("").ne("").sum()) if len(et) else 0,
        "entrenado": m.get("entrenado") if m else None,
        "decision": m.get("decision_eval") if m else None,
        "categoria": m.get("categoria_eval") if m else None,
        "minimos": {"total": MIN_EJEMPLOS, "por_clase": MIN_POR_CLASE, "por_categoria": MIN_POR_CATEGORIA},
    }


# ------------------------------------------------------------------ aplicar
def _por_que(x, clf: LogisticRegression, nombres, clase: str, k: int = 4) -> list[str]:
    """Rasgos que más empujaron hacia la clase elegida (modelo lineal: contribución = valor x peso)."""
    binario = clf.coef_.shape[0] == 1
    coef = clf.coef_[0] if binario else clf.coef_[list(clf.classes_).index(clase)]
    signo = -1 if binario and clase == clf.classes_[0] else 1
    vals = x.data * coef[x.indices] * signo
    top = sorted(zip(vals, x.indices), reverse=True)[:k]
    limpio = lambda s: s.split("__", 1)[1].replace("_", " ") if "__" in s else s
    return [limpio(nombres[i]) for v, i in top if v > 0]


def _marcar(n: dict, **cambios) -> None:
    """Guarda cómo estaba la nota antes de que el modelo la tocara, para poder deshacerlo."""
    n.setdefault("antes_modelo", {"decision": n["decision"], "origen": n["origen"], "motivo": n["motivo"]})
    n.update(cambios)


def deshacer(ns: list[dict]) -> None:
    """Quita todo lo que puso el modelo (antes de volver a aplicarlo tras reentrenar)."""
    for n in ns:
        antes = n.pop("antes_modelo", None)
        if antes and n["origen"] == "modelo":
            n.update(antes)
        n["sugerencia"] = n["confianza"] = None
        if n.get("categoria_modelo"):
            n["categoria"], n["categoria_modelo"] = "", None


def aplicar(ns: list[dict], modelo: dict, umbral: float = 0.85, umbral_categoria: float = 0.6) -> dict:
    """Nunca toca lo que decidió una persona ni lo que ya descartaron las reglas. Regresa conteos."""
    conteo = {"decididas": 0, "sugeridas": 0, "a_revision": 0, "categorizadas": 0}
    vivas = [n for n in ns if n["decision"] in ("dudoso", "conservar")]
    if not vivas:
        return conteo
    X = _transformar(modelo["vectorizador"], _tabla(vivas))   # una sola vez para ambos modelos
    fila = {id(n): i for i, n in enumerate(vivas)}

    if "decision" in modelo:
        clf = modelo["decision"]
        candidatas = [n for n in vivas if n["origen"] == "reglas"]
        if candidatas:
            filas = [fila[id(n)] for n in candidatas]
            probas = clf.predict_proba(X[filas])
            for n, f, p in zip(candidatas, filas, probas):
                j = int(np.argmax(p))
                clase, seguridad = str(clf.classes_[j]), float(p[j])
                n["sugerencia"], n["confianza"] = clase, round(seguridad, 3)
                if seguridad < umbral:
                    conteo["sugeridas"] += n["decision"] == "dudoso"
                    continue
                razones = ", ".join(_por_que(X[f], clf, modelo["nombres"], clase))
                pesos = f" (pesó: {razones})" if razones else ""
                if n["decision"] == "dudoso":
                    _marcar(n, decision=clase, origen="modelo",
                            motivo=f"el modelo está {seguridad:.0%} seguro{pesos} | reglas: {n['motivo']}")
                    conteo["decididas"] += 1
                elif clase == "descartar":  # las reglas la dejaron pasar, el modelo cree que es basura
                    _marcar(n, decision="dudoso", origen="modelo",
                            motivo=f"las reglas la aceptaron, pero el modelo cree {seguridad:.0%} que hay que "
                                   f"descartarla{pesos} | reglas: {n['motivo']}")
                    conteo["a_revision"] += 1

    if "categoria" in modelo:
        clf = modelo["categoria"]
        sin_cat = [n for n in vivas if not n.get("categoria") and n["decision"] == "conservar"]
        if sin_cat:
            probas = clf.predict_proba(X[[fila[id(n)] for n in sin_cat]])
            for n, p in zip(sin_cat, probas):
                j = int(np.argmax(p))
                if p[j] >= umbral_categoria:
                    n["categoria"], n["categoria_modelo"] = str(clf.classes_[j]), round(float(p[j]), 3)
                    conteo["categorizadas"] += 1
    return conteo
