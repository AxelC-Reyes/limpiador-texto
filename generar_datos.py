"""Genera noticias sucias de prueba en ./datos_prueba (y opcionalmente un lote masivo).

    python generar_datos.py            # 3 archivos con todos los tipos de mugre
    python generar_datos.py 50000      # además un .jsonl con 50 000 notas para medir velocidad
"""
import json
import random
import sys
from pathlib import Path

random.seed(7)
OUT = Path(__file__).parent / "datos_prueba"
OUT.mkdir(exist_ok=True)

TEMAS = [
    ("Banxico mantiene la tasa de interés en 7.5%",
     "La Junta de Gobierno del Banco de México decidió por unanimidad mantener la tasa de interés "
     "interbancaria en 7.5 por ciento, citando una inflación subyacente que todavía no converge a la meta. "
     "Analistas consultados esperaban el movimiento y anticipan recortes graduales en el primer trimestre. "
     "El peso reaccionó con una ligera apreciación frente al dólar tras el anuncio, mientras que los bonos "
     "de largo plazo registraron movimientos moderados. La institución señaló que vigilará de cerca la "
     "evolución de los precios de energéticos y alimentos en los próximos meses."),
    ("Sismo de magnitud 5.8 sacude Oaxaca sin reportes de daños graves",
     "Un sismo de magnitud 5.8 se registró la mañana de este martes con epicentro a 30 kilómetros al "
     "sur de Pinotepa Nacional, informó el Servicio Sismológico Nacional. Protección Civil estatal "
     "realizó recorridos en las comunidades cercanas y reportó daños menores en bardas y fachadas. "
     "La alerta sísmica se activó en la Ciudad de México, donde se desalojaron edificios de manera "
     "preventiva. Las autoridades pidieron a la población revisar sus viviendas y reportar grietas."),
    ("La UNAM presenta un satélite diseñado por estudiantes",
     "Estudiantes de la Facultad de Ingeniería de la UNAM presentaron un nanosatélite que medirá la "
     "humedad del suelo en zonas agrícolas del norte del país. El proyecto tomó tres años y contó con "
     "apoyo de la Agencia Espacial Mexicana. El dispositivo será lanzado el próximo año desde una "
     "plataforma internacional y enviará datos a una estación terrena instalada en Ciudad Universitaria. "
     "Los responsables esperan que la información ayude a planear el riego y reducir el desperdicio de agua."),
    ("Selección Mexicana vence 2-0 a Canadá en partido amistoso",
     "La Selección Mexicana derrotó 2-0 a Canadá en un encuentro amistoso disputado en Monterrey. "
     "Los goles llegaron en la segunda mitad, primero con un remate de cabeza tras un tiro de esquina "
     "y después con un disparo desde fuera del área. El director técnico destacó la intensidad del equipo "
     "en la presión alta y adelantó que probará variantes en el próximo compromiso frente a Estados Unidos. "
     "Más de 45 mil aficionados asistieron al estadio."),
    ("Suben casos de dengue en Veracruz; Salud pide eliminar criaderos",
     "La Secretaría de Salud estatal informó que los casos confirmados de dengue aumentaron 40 por ciento "
     "respecto al mismo periodo del año anterior. Las jurisdicciones de Poza Rica y Coatzacoalcos concentran "
     "la mayoría de los contagios. Brigadas sanitarias realizan fumigación y visitas casa por casa, y "
     "las autoridades insisten en eliminar recipientes con agua estancada en patios y azoteas."),
]


def base(i, titulo, cuerpo):
    return titulo, cuerpo, f"https://www.diario-ejemplo.mx/nota/{i}-{titulo[:20].lower().replace(' ', '-')}"


# Archivo 1: lista plana en inglés con HTML, entidades y fechas ISO.
a1 = []
for i, (t, c) in enumerate(TEMAS):
    t, c, u = base(i, t, c)
    a1.append({
        "title": t,
        "content": f"<p>{c.replace('. ', '.</p><p>', 2)}</p><p>Lee también: Otra nota que no tiene nada que ver</p>"
                   f"<script>trackUser()</script><p>&copy; Todos los derechos reservados</p>",
        "publishedAt": f"2026-09-{10 + i:02d}T14:{i}0:00Z",
        "source": {"id": None, "name": "Diario Ejemplo"},
        "url": u,
        "author": "Por Redacción",
    })
# Duplicado exacto con URL de tracking y versión AMP.
dup = dict(a1[0]); dup["url"] = a1[0]["url"].replace("www.", "m.") + "/amp?utm_source=twitter&fbclid=abc"
a1.append(dup)
a1.append({"title": "¡No vas a creer lo que pasó! Ofertas exclusivas en tu casino favorito",
           "content": "Compra ahora con 50% de descuento. Promoción patrocinado válida hoy. Click aquí.",
           "publishedAt": "2026-09-20", "source": {"name": "Spam Noticias"}, "url": "https://spam.biz/x"})
(OUT / "noticias_api.json").write_text(json.dumps(a1, ensure_ascii=False, indent=1))

# Archivo 2: contenedor {"data": [...]} en español, con mojibake, fechas raras y notas cortas.
a2 = {"status": "ok", "data": []}
for i, (t, c) in enumerate(TEMAS[:3]):
    # casi-duplicado: otro medio reescribe el arranque y el cierre
    reescrito = "De acuerdo con información oficial, " + c[0].lower() + c[1:].replace(
        "Las autoridades", "Los funcionarios").replace("El proyecto", "La iniciativa")
    a2["data"].append({"titulo": t.replace("presenta", "muestra"), "texto": reescrito,
                       "fecha": ["27 de septiembre de 2026", "martes 22 de sept. de 2026 a las 10:30",
                                 "hace 3 horas"][i],
                       "medio": "Noticias del Sur", "enlace": f"https://noticiasdelsur.com/{i}"})
a2["data"] += [
    {"titulo": "InflaciÃ³n repunta en la primera quincena de septiembre",
     "texto": "El Ã­ndice nacional de precios al consumidor subiÃ³ 0.4% en la primera quincena, "
              "impulsado por alimentos y energÃ©ticos, informÃ³ el INEGI.",
     "fecha": "15/09/2026", "medio": "Economía Hoy", "enlace": "https://economiahoy.mx/inflacion"},
    {"titulo": "Horóscopo de hoy: lo que dicen los astros para Escorpio",
     "texto": "Hoy la luna te sonríe. Tu número de la suerte es el 7. Suscríbete para leer más.",
     "fecha": "hoy", "medio": "Revista Astral"},
    {"titulo": "404", "texto": "Page not found. La página que buscas no existe.", "fecha": None},
    {"titulo": "Última hora", "texto": "", "fecha": "ayer"},
    {"titulo": "", "texto": "", "medio": "vacío total"},
    {"titulo": "Gobierno anuncia programa de becas", "texto":
     "El gobierno federal anunció un nuevo programa de becas para estudiantes de bachillerato. "
     "Los detalles se darán a conocer la próxima semana.", "fecha": 1790000000000,
     "medio": "Agencia MX", "enlace": "https://agenciamx.com/becas"},
]
(OUT / "export_cms.json").write_text(json.dumps(a2, ensure_ascii=False, indent=1))

# Archivo 3: JSON Lines estilo scraper, con un renglón roto.
lineas = [json.dumps({"headline": t.upper() if i == 4 else t, "body": c + "\n\nSíguenos en redes sociales",
                      "date": "Sep 2%d, 2026" % i, "site": "scraper.news", "link": f"https://scraper.news/{i}"},
                     ensure_ascii=False)
          for i, (t, c) in enumerate(TEMAS[3:])]
lineas.insert(1, '{"headline": "Renglón roto", "body": "sin cerrar')
(OUT / "scraper.jsonl").write_text("\n".join(lineas))

if len(sys.argv) > 1:
    n = int(sys.argv[1])
    palabras = " ".join(c for _, c in TEMAS).split()
    with open(OUT / f"masivo_{n}.jsonl", "w") as f:
        for i in range(n):
            random.shuffle(palabras)
            cuerpo = " ".join(palabras[:random.randint(20, 250)])
            if i % 10 == 0 and i:           # 10% de reenvíos de notas previas
                cuerpo = prev
            prev = cuerpo
            f.write(json.dumps({"title": f"Nota {i} " + " ".join(palabras[:6]), "content": cuerpo,
                                "date": f"2026-0{1 + i % 9}-1{i % 9}", "source": "masivo",
                                "url": f"https://m.com/{i}"}, ensure_ascii=False) + "\n")
    print(f"masivo_{n}.jsonl listo")
print("Datos de prueba en", OUT)
