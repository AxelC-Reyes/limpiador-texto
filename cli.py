"""Uso sin interfaz:

    python cli.py datos/ -o salida/
    python cli.py a.json b.jsonl -o salida/ --min-palabras 40
    python cli.py --entrenar                  # reentrena con lo que se ha decidido a mano en la interfaz
"""
import argparse
import json
from pathlib import Path

from limpiador import Opciones, exportar, procesar
from limpiador.reglas import Config


def main():
    ap = argparse.ArgumentParser(description="Limpia noticias en .json/.jsonl")
    ap.add_argument("entradas", nargs="*", help="archivos o carpetas")
    ap.add_argument("-o", "--salida", default="salida")
    ap.add_argument("--min-palabras", type=int, default=60)
    ap.add_argument("--umbral-duplicado", type=float, default=0.8)
    ap.add_argument("--sin-modelo", action="store_true", help="no usar lo que aprendió el modelo")
    ap.add_argument("--umbral-modelo", type=float, default=0.85)
    ap.add_argument("--entrenar", action="store_true", help="entrenar el modelo y salir")
    a = ap.parse_args()

    if a.entrenar:
        from limpiador import modelo
        print(json.dumps(modelo.entrenar(), ensure_ascii=False, indent=2))
        return
    if not a.entradas:
        ap.error("faltan archivos o carpetas")

    op = Opciones(reglas=Config(min_palabras=a.min_palabras), umbral_duplicado=a.umbral_duplicado,
                  usar_modelo=not a.sin_modelo, umbral_modelo=a.umbral_modelo)
    df, rep = procesar(a.entradas, op, progreso=lambda m, x: print(f"[{x:4.0%}] {m}"))

    out = Path(a.salida); out.mkdir(parents=True, exist_ok=True)
    (out / "noticias_limpias.json").write_text(exportar(df, "conservar"))
    (out / "dudosas.json").write_text(exportar(df, "dudoso"))
    df.to_csv(out / "noticias_todas.csv", index=False, encoding="utf-8-sig")
    (out / "reporte.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in rep.items() if k != "errores_de_archivo"}, ensure_ascii=False, indent=2))
    if rep["errores_de_archivo"]:
        print(f'{len(rep["errores_de_archivo"])} errores de lectura, ver reporte.json')


if __name__ == "__main__":  # obligatorio: los procesos paralelos reimportan este archivo en Mac/Windows
    main()
