# Limpiador de noticias

Limpia, deduplica y filtra noticias que vienen en archivos `.json` o `.jsonl`. Tiene una interfaz web propia para revisar a mano y un modelo de scikit-learn que aprende de esas decisiones. Todo corre en la máquina: no usa internet, servicios de IA ni llaves de API.

## Arrancar

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python servidor.py            # abre el navegador en http://localhost:8600
```

El servidor solo escucha en esta computadora (`127.0.0.1`), no en la red.

## Cómo decide

```
cargar -> normalizar -> reglas -> duplicados -> modelo (si ya aprendió) -> revisión humana
```

1. **Carga tolerante**: lee listas, objetos contenedores (`{"articles": [...]}`, `{"data": [...]}`, Elasticsearch), JSON Lines con renglones rotos, UTF-8 con BOM y latin-1.
2. **Normaliza** a un solo esquema (`titulo, resumen, cuerpo, fecha, fuente, url, autor`) aunque cada archivo use otros nombres. Quita HTML y scripts, arregla texto roto (`InflaciÃ³n` → `Inflación`), borra relleno como "Lee también", pasa las fechas a ISO 8601 (`hace 3 horas`, `martes 22 de sept.`, `15/09/2026`, epoch) y limpia las URLs de `utm_`, AMP y `m.`.
3. **Reglas**: dan un puntaje con los motivos por escrito. Cada nota queda en **conservar**, **descartar** o **dudosa**.
4. **Duplicados**: los exactos por URL o texto, y los casi idénticos con MinHash + LSH. De cada grupo se queda la mejor versión. Los pares medio parecidos van a revisión.
5. **Modelo** (scikit-learn), solo cuando está muy seguro (85 % por defecto):
   - decide las dudosas;
   - regresa a dudosa lo que las reglas aceptaron pero parece basura. Nunca descarta por su cuenta algo que las reglas aceptaron;
   - sugiere categoría para lo que se conserva;
   - nunca toca lo que decidió una persona.
6. **Humano**: decide lo que queda en la pestaña Revisar.

## La interfaz

- **Revisar**: una nota a la vez. Si tiene una parecida, las muestra lado a lado. Se decide con el teclado:

  | Tecla | Acción |
  |---|---|
  | `C` / `D` / `U` | conservar / descartar / dudosa |
  | `→` `J` / `←` `K` | siguiente / anterior |
  | `1`–`9` | categoría |
  | `Z` | deshacer la última decisión |
| `F` | mostrar u ocultar filtros |
| `/` | buscar |
  | `?` | ayuda |

- **Tabla**: todas las notas, con filtros y cambio de decisión en la misma fila.
- **Panorama**: gráficas por fuente, por motivo, por quién decidió y por mes.
- **Archivos**: cómo se integró cada JSON: qué formato se detectó, de qué campo salió el título, el cuerpo, la fecha, etc., qué llaves no se usaron, y una nota real antes y después de limpiarla. Incluye la guía de formatos que acepta.
- **Modelo**: cuántos ejemplos lleva, qué tan bien acierta con notas que no vio al entrenar (validación cruzada) y el botón para entrenar.
- **Exportar**: noticias limpias, dudosas, descartadas con su motivo, CSV completo y reporte.

Se pueden soltar archivos arrastrándolos a la ventana. Hay tema claro (blanco azulado) y oscuro. Los filtros (`F`), el resumen y cada sección se pliegan, y el navegador recuerda cómo los dejaste, igual que los ajustes.

## El modelo

- **Qué aprende**: cada decisión o categoría que se pone a mano se guarda en `datos_modelo/etiquetas.jsonl`. Si una nota se corrige después, cuenta la última decisión.
- **Cuándo se puede entrenar** la decisión: con 20 ejemplos, y al menos 5 conservados y 5 descartados.
- **Cuándo se pueden entrenar las categorías**: con 2 categorías de al menos 3 notas cada una.
- **Qué mira**: solo el texto (TF-IDF de palabras y pares de palabras) y la fuente, con regresión logística. No mira las señales de las reglas, porque aprendería atajos como "título corto = basura" en vez de leer.
- **Por qué decidió**: cada decisión dice qué palabras pesaron más.
- **Dónde se guarda**: `datos_modelo/modelo.joblib`. Si se actualiza scikit-learn hay que reentrenar; el programa lo detecta y mientras tanto no usa el modelo viejo. Solo carga modelos hechos en esta misma instalación, porque abrir un `.joblib` ejecuta código.
- **Cómo pasarlo a otra máquina**: copiar la carpeta `datos_modelo/`.

## Línea de comandos

```bash
.venv/bin/python cli.py datos/ -o salida/            # limpiar (usa el modelo si existe)
.venv/bin/python cli.py datos/ -o salida/ --sin-modelo
.venv/bin/python cli.py --entrenar                   # reentrenar con lo etiquetado
.venv/bin/python generar_datos.py 50000              # datos sucios de prueba
.venv/bin/python -m pytest tests                     # pruebas
```

## Rendimiento

En una Mac con varios núcleos, 50,000 notas tardan unos 12 segundos solo con reglas, o unos 18 con el modelo entrenado. La interfaz carga esas 50,000 notas en menos de un segundo, y filtrar es instantáneo.

## Dónde mover cosas

- Palabras de relleno: `BASURA` en `limpiador/normaliza.py`
- Palabras de publicidad o spam: `FRASES_NO_NOTICIA` y `PALABRAS_NO_NOTICIA` en `limpiador/reglas.py`
- Categorías: `CATEGORIAS` en `limpiador/reglas.py`
- Mínimos de ejemplos del modelo: `MIN_EJEMPLOS`, `MIN_POR_CLASE` y `MIN_POR_CATEGORIA` en `limpiador/modelo.py`
