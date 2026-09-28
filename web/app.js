"use strict";

// ------------------------------------------------------------------ estado
const S = {
  notas: [], porId: new Map(), conteos: {}, reporte: null, opciones: {}, categorias: [],
  vista: "revisar", actual: null, detalle: null, pagina: 0, modelo: null,
  historial: [],          // para deshacer: [{id, anterior: {decision, origen, motivo}}]
  dudosasIniciales: 0,    // para la barra de progreso de revisión
  direccion: 1,           // hacia dónde anima la tarjeta
};
const POR_PAGINA = 100;
const DECISIONES = ["conservar", "dudoso", "descartar"];
const NOMBRES = { conservar: "Conservar", descartar: "Descartar", dudoso: "Dudosa" };
const PLURAL = { conservar: "Conservar", descartar: "Descartar", dudoso: "Dudosas" };
const ICONO = { conservar: "i-check", dudoso: "i-duda", descartar: "i-x" };
const COLOR = (d) => `var(--c-${d})`;
const ORIGENES = { reglas: "Reglas", duplicado: "Duplicado", modelo: "Modelo", humano: "Una persona" };
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// Todo texto que venga de las noticias pasa por aquí: nunca se inserta HTML crudo.
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (n) => (n ?? 0).toLocaleString("es-MX");
const pct = (x) => `${Math.round((x ?? 0) * 100)}%`;
const icono = (id) => `<svg aria-hidden="true"><use href="#${id}"/></svg>`;
const estado = (d) => `<span class="icono-estado e-${d}">${icono(ICONO[d])}</span>`;
const fechaLarga = (iso) => {
  if (!iso) return "Sin fecha";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleDateString("es-MX", { day: "numeric", month: "long", year: "numeric" });
};
const bytes = (b) => b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`;
const reducirMovimiento = matchMedia("(prefers-reduced-motion: reduce)").matches;

// ------------------------------------------------------------------ red
async function api(ruta, opciones = {}) {
  const r = await fetch(ruta, opciones);
  let datos = null;
  try { datos = await r.json(); } catch { /* respuesta vacía */ }
  if (!r.ok) throw new Error(datos?.error || `Error ${r.status}`);
  return datos;
}
const post = (ruta, cuerpo) => api(ruta, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo ?? {}),
});

// ------------------------------------------------------------------ avisos (tipo iOS, con acción opcional)
function aviso(texto, { error = false, accion = null, ms } = {}) {
  const el = document.createElement("div");
  el.className = "aviso" + (error ? " error" : "") + (accion ? "" : " solo");
  const t = document.createElement("span");
  t.textContent = texto;
  el.append(t);
  if (accion) {
    const b = document.createElement("button");
    b.innerHTML = (accion.icono ? icono(accion.icono) : "") + esc(accion.texto);
    b.onclick = () => { cerrar(); accion.fn(); };
    el.append(b);
  }
  const cont = $("#avisos");
  while (cont.children.length > 2) cont.firstChild.remove();
  cont.append(el);
  const cerrar = () => { el.classList.add("sale"); setTimeout(() => el.remove(), 250); };
  setTimeout(cerrar, ms ?? (error ? 6000 : accion ? 5000 : 2600));
}

async function conCarga(texto, fn) {
  $("#cargando-texto").textContent = texto;
  $("#cargando").hidden = false;
  try { return await fn(); }
  catch (e) { aviso(e.message, { error: true }); }
  finally { $("#cargando").hidden = true; }
}

// Números que cuentan hasta su valor (se siente vivo sin distraer).
function contar(el, valor) {
  const desde = Number(el.dataset.v ?? 0);
  el.dataset.v = valor;
  if (reducirMovimiento || desde === valor) { el.textContent = num(valor); return; }
  const t0 = performance.now(), dur = 550;
  const paso = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = num(Math.round(desde + (valor - desde) * e));
    if (k < 1) requestAnimationFrame(paso);
  };
  requestAnimationFrame(paso);
}

// ------------------------------------------------------------------ secciones plegables
const guardado = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { return null; } };
function seccion(id, titulo, sub, contenido, abierta = true) {
  const estado = guardado(`limpiador-seccion-${id}`);
  const abrir = estado === null ? abierta : estado === "1";
  return `<details class="seccion" data-seccion="${id}" ${abrir ? "open" : ""}>
    <summary><h2>${titulo}</h2><span class="sub">${sub || ""}</span>${icono("i-abajo").replace("<svg", '<svg class="chevron"')}</summary>
    <div class="contenido">${contenido}</div></details>`;
}
document.addEventListener("toggle", (e) => {
  const d = e.target;
  if (!d.matches?.("details[data-seccion]")) return;
  guardado(`limpiador-seccion-${d.dataset.seccion}`, d.open ? "1" : "0");
  if (d.open && d.querySelector(".lienzo")) redibujarGraficas();  // al abrir, la gráfica ya tiene ancho
}, true);

// ------------------------------------------------------------------ tema claro / oscuro
function aplicarTema(t) {
  if (t) document.documentElement.dataset.tema = t; else delete document.documentElement.dataset.tema;
  const actual = t || (matchMedia("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro");
  $$(".tema button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tema === actual)));
}
function iniciarTema() {
  aplicarTema(guardado("limpiador-tema"));
  $$(".tema button").forEach((b) => b.onclick = () => { guardado("limpiador-tema", b.dataset.tema); aplicarTema(b.dataset.tema); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => aplicarTema(guardado("limpiador-tema")));
}

// ------------------------------------------------------------------ filtros plegables
function plegarFiltros(plegar) {
  document.body.classList.toggle("filtros-plegados", plegar);
  $("#btn-filtros").setAttribute("aria-expanded", String(!plegar));
  $("#btn-filtros span").textContent = plegar ? "Mostrar filtros" : "Filtros";
  guardado("limpiador-filtros-plegados", plegar ? "1" : "0");
}

// ------------------------------------------------------------------ tooltip compartido
const tip = () => $("#tip");
function mostrarTip(ev, titulo, filas, ancla) {
  const el = tip();
  el.innerHTML = `<div class="tip-titulo">${esc(titulo)}</div>` + filas.map((f) => `
    <div class="tip-fila"><i style="background:${f.color || "var(--texto-3)"}"></i><span>${esc(f.nombre)}</span><b>${esc(f.valor)}</b></div>`).join("");
  el.hidden = false;
  const r = ancla ? ancla.getBoundingClientRect() : null;
  const x = ev?.clientX ?? (r.left + r.width / 2), y = ev?.clientY ?? r.top;
  const w = el.offsetWidth, h = el.offsetHeight;
  el.style.left = `${Math.min(innerWidth - w - 10, Math.max(10, x + 14))}px`;
  el.style.top = `${Math.max(10, y - h - 12 < 10 ? y + 18 : y - h - 12)}px`;
}
const ocultarTip = () => { tip().hidden = true; };

// ------------------------------------------------------------------ ajustes (hoja lateral)
const AJUSTES_BASE = { min_palabras: 60, umbral_bajo: 0.35, umbral_alto: 0.7, umbral_duplicado: 0.8,
                       umbral_gris: 0.5, usar_modelo: true, umbral_modelo: 0.85 };
function leerAjustes() {
  const o = {};
  $$("#ajustes input").forEach((i) => { o[i.name] = i.type === "checkbox" ? i.checked : Number(i.value); });
  return o;
}
function pintarAjustes(o) {
  $$("#ajustes input").forEach((i) => {
    if (!(i.name in o)) return;
    if (i.type === "checkbox") i.checked = !!o[i.name]; else i.value = o[i.name];
  });
  $$("#ajustes output").forEach((out) => {
    const k = out.dataset.para, v = o[k];
    out.textContent = k === "min_palabras" ? `${v} palabras` : k.startsWith("umbral_d") || k === "umbral_gris" || k === "umbral_modelo" ? pct(v) : Number(v).toFixed(2);
  });
  // Dibujo de las tres zonas del puntaje: se entiende de un vistazo qué hace cada deslizador.
  const bajo = Math.min(o.umbral_bajo, o.umbral_alto), alto = Math.max(o.umbral_bajo, o.umbral_alto);
  const zonas = [["descartar", bajo], ["dudoso", alto - bajo], ["conservar", 1 - alto]];
  $("#zonas").innerHTML = zonas.map(([d, w]) =>
    `<span class="b-${d}" style="flex-grow:${Math.max(w, 0.001)}">${w >= 0.18 ? NOMBRES[d] : ""}</span>`).join("");
}
function guardarAjustes() {
  const o = leerAjustes();
  pintarAjustes(o);
  try { localStorage.setItem("limpiador-ajustes", JSON.stringify(o)); } catch { /* modo privado */ }
}
function abrirAjustes(abrir) {
  $("#ajustes").hidden = !abrir;
  $("#velo").hidden = !abrir;
  $("#btn-ajustes").setAttribute("aria-expanded", String(abrir));
  if (abrir) $("#ajustes").focus({ preventScroll: true });  // el panel, no un control: sin anillo de foco
}
function iniciarAjustes() {
  let o = { ...AJUSTES_BASE };
  try { o = { ...o, ...JSON.parse(localStorage.getItem("limpiador-ajustes") || "{}") }; } catch { /* nada */ }
  pintarAjustes(o);
  $("#ajustes").addEventListener("input", guardarAjustes);
  $("#btn-restablecer").onclick = () => { pintarAjustes(AJUSTES_BASE); guardarAjustes(); };
  $("#btn-ajustes").onclick = () => abrirAjustes($("#ajustes").hidden);
  $("#btn-cerrar-ajustes").onclick = () => abrirAjustes(false);
  $("#velo").onclick = () => abrirAjustes(false);
  $("#btn-aplicar").onclick = () => { abrirAjustes(false); limpiar(); };
}

// ------------------------------------------------------------------ archivos
function pintarArchivos(lista) {
  $("#btn-limpiar").disabled = !lista.length;
  $("#archivos").innerHTML = lista.map((a) =>
    `<span class="archivo">${icono("i-doc")}${esc(a.nombre)} <small>${bytes(a.bytes)}</small></span>`).join("")
    + (lista.length ? `<button class="enlace" id="btn-quitar">Quitar archivos</button>` : "");
  const q = $("#btn-quitar");
  if (q) q.onclick = async () => {
    pintarArchivos((await post("/api/quitar-archivos")).archivos);
    aviso("Archivos quitados. Sube otros para volver a limpiar.");
  };
}

async function subir(archivos) {
  archivos = [...archivos].filter((f) => /\.(json|jsonl)$/i.test(f.name));
  if (!archivos.length) return aviso("Solo se aceptan archivos .json o .jsonl", { error: true });
  await conCarga(`Subiendo ${archivos.length} archivo${archivos.length > 1 ? "s" : ""}…`, async () => {
    let r;
    for (const f of archivos) {
      r = await api("/api/subir", { method: "POST", headers: { "X-Nombre": encodeURIComponent(f.name) }, body: f });
    }
    pintarArchivos(r.archivos);
  });
  await limpiar();
}

async function limpiar() {
  await conCarga("Limpiando…", async () => {
    const r = await post("/api/procesar", { opciones: leerAjustes() });
    S.historial = [];
    await recargar(true);
    const m = r.reporte.modelo;
    aviso(`Listo en ${r.reporte.segundos} s` + (m?.decididas ? ` · el modelo decidió ${m.decididas}` : ""));
    for (const e of r.reporte.errores_de_archivo || []) aviso(e, { error: true });
  });
}

async function recargar(nuevo = false) {
  const r = await api("/api/notas");
  S.notas = r.notas;
  S.porId = new Map(S.notas.map((n) => [n.id, n]));
  S.conteos = r.conteos;
  S.reporte = r.reporte;
  S.opciones = { ...AJUSTES_BASE, ...(r.opciones || {}) };
  if (nuevo || !S.dudosasIniciales) S.dudosasIniciales = r.conteos.dudoso || 0;
  pintarArchivos(r.archivos);
  const hay = S.notas.length > 0 || !!S.reporte;
  $("#vacio").hidden = hay;
  $("#trabajo").hidden = !hay;
  $(".pestanas").hidden = !hay;
  if (!hay) return;
  llenarSelect("#f-origen", S.notas.map((n) => n.origen), "Todos", ORIGENES);
  llenarSelect("#f-fuente", S.notas.map((n) => n.fuente || "(sin fuente)"), "Todas");
  S.pagina = 0;
  if (!S.porId.has(S.actual)) S.actual = null;
  S.detalle = null;
  pintarTodo();
  moverSegmento();
}

function llenarSelect(sel, valores, todos, nombres = {}) {
  const el = $(sel), previo = el.value;
  const cuenta = new Map();
  valores.forEach((v) => cuenta.set(v, (cuenta.get(v) || 0) + 1));
  const orden = [...cuenta].sort((a, b) => b[1] - a[1]);
  el.innerHTML = `<option value="">${todos}</option>` +
    orden.map(([v, c]) => `<option value="${esc(v)}">${esc(nombres[v] || v)} · ${num(c)}</option>`).join("");
  el.value = cuenta.has(previo) ? previo : "";
}

// ------------------------------------------------------------------ filtros
function decisionesVisibles() { return $$("input[name=f-decision]:checked").map((i) => i.value); }
function filtradas() {
  const decisiones = decisionesVisibles();
  const q = $("#f-buscar").value.trim().toLowerCase();
  const origen = $("#f-origen").value, fuente = $("#f-fuente").value;
  const [campo, dir] = $("#f-orden").value.split("-");
  const lista = S.notas.filter((n) =>
    decisiones.includes(n.decision)
    && (!origen || n.origen === origen)
    && (!fuente || (n.fuente || "(sin fuente)") === fuente)
    && (!q || (n.titulo || "").toLowerCase().includes(q) || (n.fuente || "").toLowerCase().includes(q)));
  const val = (n) => campo === "fecha" ? (n.fecha || "") : (n[campo] ?? -1);
  lista.sort((a, b) => (val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0) * (dir === "desc" ? -1 : 1));
  return lista;
}

function iniciarFiltros() {
  let espera;
  $("#f-buscar").addEventListener("input", () => { clearTimeout(espera); espera = setTimeout(alFiltrar, 150); });
  $$("#filtros select, input[name=f-decision]").forEach((el) => el.addEventListener("change", alFiltrar));
}
function alFiltrar() { S.pagina = 0; S.actual = null; S.direccion = 1; pintarResumen(); pintarVista(); }

function soloDecision(d) {
  $$("input[name=f-decision]").forEach((i) => { i.checked = i.value === d; });
  alFiltrar();
}

// ------------------------------------------------------------------ pintar
function pintarTodo() { pintarResumen(); pintarVista(); }

function pintarResumen() {
  const c = S.conteos, r = S.reporte || {};
  const total = DECISIONES.reduce((s, d) => s + (c[d] || 0), 0) || 1;
  const soloUna = decisionesVisibles().length === 1 ? decisionesVisibles()[0] : null;
  const pies = {
    conservar: `${pct((c.conservar || 0) / total)} del total`,
    dudoso: c.dudoso ? "por revisar" : "nada pendiente",
    descartar: `${num(r.duplicados)} duplicados incluidos`,
  };
  if (!$("#cifras").children.length) {
    $("#cifras").innerHTML = `
      <div class="cifra"><div class="cifra-cabeza">${icono("i-doc")}Leídas</div>
        <div class="cifra-valor" data-k="leidas">0</div><div class="cifra-pie" data-p="leidas"></div></div>
      ${["conservar", "dudoso", "descartar"].map((d) => `
      <button class="cifra" type="button" data-d="${d}" title="Ver solo ${PLURAL[d].toLowerCase()}">
        <div class="cifra-cabeza">${estado(d)}${PLURAL[d]}</div>
        <span class="ir">${icono("i-der")}</span>
        <div class="cifra-valor" data-k="${d}">0</div><div class="cifra-pie" data-p="${d}"></div></button>`).join("")}`;
    $$("#cifras button.cifra").forEach((el) => el.onclick = () => {
      cambiarVista("revisar");
      soloDecision(el.dataset.d);
    });
  }
  contar($('[data-k="leidas"]'), r.registros_leidos || 0);
  $('[data-p="leidas"]').textContent = `${num(r.fechas_ilegibles)} con fecha ilegible · ${r.segundos ?? 0} s`;
  for (const d of DECISIONES) {
    contar($(`[data-k="${d}"]`), c[d] || 0);
    $(`[data-p="${d}"]`).textContent = pies[d];
    $(`.cifra[data-d="${d}"]`).classList.toggle("activa", soloUna === d);
  }

  $("#composicion").innerHTML = `
    <div class="comp-barra" role="img" aria-label="${DECISIONES.map((d) => `${NOMBRES[d]}: ${c[d] || 0}`).join(", ")}">
      ${DECISIONES.filter((d) => c[d]).map((d) => `<span class="b-${d}" data-d="${d}" style="flex-grow:${c[d]}"></span>`).join("")}
    </div>
    <div class="comp-leyenda">${DECISIONES.map((d) => `
      <span><i class="muestra b-${d}"></i>${NOMBRES[d]} <b>${pct((c[d] || 0) / total)}</b></span>`).join("")}
      ${r.modelo?.decididas || r.modelo?.a_revision ? `<span>· El modelo decidió <b>${num(r.modelo.decididas)}</b> y mandó a revisión <b>${num(r.modelo.a_revision)}</b></span>` : ""}
    </div>`;
  $$(".comp-barra span").forEach((el) => {
    const d = el.dataset.d;
    el.onpointermove = (e) => mostrarTip(e, "Composición", [{ color: COLOR(d), nombre: NOMBRES[d], valor: `${num(c[d])} · ${pct(c[d] / total)}` }]);
    el.onpointerleave = ocultarTip;
  });
  $$(".cuenta").forEach((el) => { el.textContent = num(c[el.dataset.c]); });
  $("#resumen-compacto").innerHTML = `<span><b>${num(r.registros_leidos)}</b> leídas</span>` + DECISIONES.map((d) =>
    `<span><i class="muestra b-${d}"></i><b>${num(c[d])}</b> ${PLURAL[d].toLowerCase()}</span>`).join("");
  $("#insignia-dudosas").textContent = c.dudoso ? num(c.dudoso) : "";
}

const VISTAS = ["revisar", "tabla", "panorama", "archivos", "modelo", "exportar"];
function cambiarVista(v) {
  if (!VISTAS.includes(v)) v = "revisar";
  S.vista = v;
  if (location.hash.slice(1) !== v) history.replaceState(null, "", `#${v}`);
  $$(".pestanas button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.vista === v)));
  $$(".vista").forEach((s) => { s.hidden = s.dataset.vista !== v; });
  document.body.classList.toggle("sin-filtros", ["panorama", "archivos", "modelo", "exportar"].includes(v));
  ocultarTip();
  moverSegmento();
  pintarVista();
}

function moverSegmento() { /* las pestañas nuevas no llevan indicador deslizante */ }

function pintarVista() {
  const lista = filtradas();
  $("#f-total").textContent = `${num(lista.length)} de ${num(S.notas.length)} notas`;
  if (S.vista !== "revisar") $("#herramientas-texto").innerHTML = "";
  ({ revisar: pintarRevisar, tabla: pintarTabla, panorama: pintarPanorama, archivos: pintarVistaArchivos,
     modelo: pintarModelo, exportar: pintarExportar })[S.vista](lista);
}

// ---- Revisar: una nota a la vez
function porQue(motivo) {
  const [modelo, reglas] = motivo.includes(" | reglas: ") ? motivo.split(" | reglas: ") : [null, motivo];
  const items = (reglas || "").split("; ").filter(Boolean);
  return [...(modelo ? [modelo[0].toUpperCase() + modelo.slice(1)] : []),
          ...items.map((m) => m === "pasa todas las reglas" ? "Pasa todas las reglas" : m[0].toUpperCase() + m.slice(1))];
}

async function pintarRevisar(lista) {
  const cont = $("#tarjeta");
  const quedan = S.conteos.dudoso || 0;
  if (!lista.length) {
    const listo = !quedan;
    $("#herramientas-texto").innerHTML = "";
    cont.innerHTML = `<div class="fin">
      <div class="icono-grande ${listo ? "e-conservar" : ""}" style="${listo ? "" : "background:var(--relleno)"}">${icono(listo ? "i-check" : "i-buscar")}</div>
      <h2>${listo ? "Todo revisado" : "Sin resultados"}</h2>
      <p>${listo ? "No quedan notas dudosas. Ya puedes exportar tus noticias limpias." : "Ninguna nota coincide con los filtros."}</p>
      ${listo ? `<button class="boton primario grande" id="ir-exportar">${icono("i-bajar")}Exportar</button>` : ""}
    </div>`;
    const b = $("#ir-exportar");
    if (b) b.onclick = () => cambiarVista("exportar");
    return;
  }
  if (!S.actual || !lista.some((n) => n.id === S.actual)) S.actual = lista[0].id;
  const i = lista.findIndex((n) => n.id === S.actual);
  const ligera = S.porId.get(S.actual);
  if (S.detalle?.nota.id !== S.actual) {
    const pedido = S.actual;
    try { S.detalle = await api(`/api/nota?id=${encodeURIComponent(pedido)}`); }
    catch (e) { aviso(e.message, { error: true }); return; }
    if (S.actual !== pedido) return; // el usuario ya avanzó
  }
  const n = { ...S.detalle.nota, ...ligera }, par = S.detalle.parecida;
  const soloDudosas = decisionesVisibles().join() === "dudoso";
  const hechas = Math.max(0, S.dudosasIniciales - quedan);

  const sugerencia = n.sugerencia && n.origen !== "humano" ? `
    <span class="pastilla" title="Lo que cree el modelo">${icono("i-cerebro")}Modelo: <b>${esc(NOMBRES[n.sugerencia])}</b>
      <span class="medidor m-${esc(n.sugerencia)}"><i style="width:${pct(n.confianza)}"></i></span>${pct(n.confianza)}</span>` : "";
  const cuerpo = (x, titulo) => `<div class="cuerpo">${titulo ? `<h3>${titulo}</h3>` : ""}${
    x.cuerpo ? `<p>${esc(x.cuerpo)}</p>` : '<span class="vacia">Sin cuerpo</span>'}</div>`;
  $("#herramientas-texto").innerHTML = soloDudosas && S.dudosasIniciales ? `
    <div class="revisar-cabeza"><span>${num(hechas)} de ${num(S.dudosasIniciales)} revisadas</span>
      <div class="progreso"><i style="width:${pct(hechas / S.dudosasIniciales)}"></i></div></div>` : "";

  cont.innerHTML = `
    <article class="tarjeta ${S.direccion < 0 ? "entra-atras" : S.direccion > 0 ? "entra" : ""}">
      <div class="tarjeta-cabeza">
        <div class="posicion"><span>Nota ${num(i + 1)} de ${num(lista.length)}</span>
          <button class="enlace-suave" type="button" data-ayuda>${icono("i-teclado")}Atajos</button></div>
        <h2>${esc(n.titulo) || '<span style="color:var(--texto-3)">Sin título</span>'}</h2>
        <div class="meta">
          <span>${esc(n.fuente) || "Sin fuente"}</span><span>${esc(fechaLarga(n.fecha))}</span>
          <span>${num(n.palabras)} palabras</span>${n.autor ? `<span>${esc(n.autor)}</span>` : ""}
          ${n.url && /^https?:\/\//.test(n.url) ? `<a href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">${icono("i-enlace")}Ver original</a>` : ""}
        </div>
        <div class="etiquetas">
          <span class="pastilla">${estado(n.decision)}<b>${esc(NOMBRES[n.decision])}</b></span>
          <span class="pastilla">Decidió: <b>${esc(ORIGENES[n.origen] || n.origen)}</b></span>
          <span class="pastilla" title="Puntaje de las reglas, de 0 a 1">Puntaje <span class="medidor"><i style="width:${pct(n.puntaje)}"></i></span><b>${Number(n.puntaje).toFixed(2)}</b></span>
          ${sugerencia}
        </div>
        <details class="porque" ${guardado("limpiador-porque") === "0" ? "" : "open"}><summary>${icono("i-abajo")}¿Por qué está aquí?</summary>
          <ul>${porQue(n.motivo || "").map((m) => `<li>${esc(m)}</li>`).join("")}</ul></details>
      </div>
      <div class="cuerpos ${par ? "lado-a-lado" : ""}">
        ${cuerpo(n, par ? "Esta nota" : "")}
        ${par ? cuerpo(par, `Se parece a · ${esc(par.fuente || "sin fuente")} · ${esc(NOMBRES[par.decision])}`) : ""}
      </div>
      <div class="tarjeta-pie">
        <div class="decidir">${DECISIONES.map((d) => `
          <button class="btn-decidir ${n.decision === d ? "activo" : ""}" data-decidir="${d}">${estado(d)}${NOMBRES[d]}<kbd>${{ conservar: "C", dudoso: "U", descartar: "D" }[d]}</kbd></button>`).join("")}
        </div>
        <div class="pie-der">
          <select id="sel-categoria" aria-label="Categoría">
            <option value="">Sin categoría</option>
            ${S.categorias.map((c, k) => `<option value="${esc(c)}" ${c === n.categoria ? "selected" : ""}>${k < 9 ? `${k + 1}  ` : ""}${esc(c[0].toUpperCase() + c.slice(1))}${c === n.categoria && n.categoria_modelo ? ` (modelo ${pct(n.categoria_modelo)})` : ""}</option>`).join("")}
          </select>
          <button class="boton-icono" data-mover="-1" title="Anterior (← o K)" aria-label="Anterior">${icono("i-izq")}</button>
          <button class="boton-icono" data-mover="1" title="Siguiente (→ o J)" aria-label="Siguiente">${icono("i-der")}</button>
        </div>
      </div>
    </article>`;
  $$("[data-decidir]", cont).forEach((b) => b.onclick = () => decidir(b.dataset.decidir));
  $$("[data-mover]", cont).forEach((b) => b.onclick = () => mover(Number(b.dataset.mover)));
  $("[data-ayuda]", cont).onclick = () => $("#ayuda").showModal();
  $("#sel-categoria").onchange = (e) => ponerCategoria(e.target.value);
  $(".porque", cont).ontoggle = (e) => guardado("limpiador-porque", e.target.open ? "1" : "0");
}

function mover(paso) {
  const lista = filtradas();
  const i = lista.findIndex((n) => n.id === S.actual);
  const j = Math.min(lista.length - 1, Math.max(0, i + paso));
  if (lista[j] && j !== i) { S.actual = lista[j].id; S.direccion = paso; pintarRevisar(lista); }
}

async function decidir(decision, id = S.actual) {
  if (!id) return;
  const nota = S.porId.get(id);
  if (!nota) return;
  const anterior = { decision: nota.decision, origen: nota.origen, motivo: nota.motivo };
  const antes = filtradas(), i = antes.findIndex((n) => n.id === id);
  try {
    const r = await post("/api/decidir", { id, decision });
    Object.assign(nota, r.nota);
    S.conteos = r.conteos;
    S.modelo = r.modelo;
  } catch (e) { return aviso(e.message, { error: true }); }
  if (anterior.decision !== decision || anterior.origen !== "humano") {
    S.historial.push({ id, anterior });
    const t = nota.titulo || "nota";
    aviso(`${NOMBRES[decision]}: ${t.length > 48 ? t.slice(0, 48) + "…" : t}`,
          { accion: { texto: "Deshacer", icono: "i-deshacer", fn: deshacer } });
  }
  pintarResumen();
  if (S.vista !== "revisar") return pintarVista();
  // Avanzar: si la nota salió del filtro, la siguiente ocupa su lugar.
  const despues = filtradas();
  const sigue = despues.some((n) => n.id === id);
  const sig = despues[sigue ? i + 1 : i] || despues[despues.length - 1];
  S.actual = sig ? sig.id : null;
  S.direccion = 1;
  $("#f-total").textContent = `${num(despues.length)} de ${num(S.notas.length)} notas`;
  pintarRevisar(despues);
}

async function deshacer() {
  const ultimo = S.historial.pop();
  if (!ultimo) return aviso("No hay nada que deshacer");
  try {
    const r = await post("/api/decidir", { id: ultimo.id, deshacer: ultimo.anterior });
    Object.assign(S.porId.get(ultimo.id), r.nota);
    S.conteos = r.conteos;
  } catch (e) { return aviso(e.message, { error: true }); }
  // Volver a mostrar la nota, aunque el filtro la hubiera ocultado.
  const d = ultimo.anterior.decision, casilla = $(`input[name=f-decision][value=${d}]`);
  if (!casilla.checked) casilla.checked = true;
  S.actual = ultimo.id; S.direccion = -1;
  pintarResumen();
  if (S.vista === "revisar") pintarRevisar(filtradas()); else pintarVista();
  aviso("Deshecho");
}

async function ponerCategoria(categoria, id = S.actual) {
  if (!id) return;
  try {
    const r = await post("/api/decidir", { id, categoria });
    Object.assign(S.porId.get(id), r.nota);
    S.modelo = r.modelo;
    aviso(categoria ? `Categoría: ${categoria}` : "Sin categoría");
  } catch (e) { aviso(e.message, { error: true }); }
  if (S.vista === "revisar") { S.direccion = 0; pintarRevisar(filtradas()); }
}

// ---- Tabla
function pintarTabla(lista) {
  const paginas = Math.max(1, Math.ceil(lista.length / POR_PAGINA));
  S.pagina = Math.min(S.pagina, paginas - 1);
  const vis = lista.slice(S.pagina * POR_PAGINA, (S.pagina + 1) * POR_PAGINA);
  $("#tabla").innerHTML = `
    <thead><tr><th>Estado</th><th>Nota</th><th>Fecha</th><th style="text-align:right">Palabras</th><th>Puntaje</th><th>Decidió</th><th>Motivo</th></tr></thead>
    <tbody>${vis.map((n) => `
      <tr data-id="${esc(n.id)}">
        <td><span class="sel-estado" style="--c:${COLOR(n.decision)}"><select data-accion="decision" aria-label="Decisión">${DECISIONES
          .map((d) => `<option value="${d}" ${d === n.decision ? "selected" : ""}>${NOMBRES[d]}</option>`).join("")}</select></span></td>
        <td class="titulo"><button data-accion="abrir">${esc(n.titulo) || "Sin título"}</button><small>${esc(n.fuente) || "Sin fuente"}</small></td>
        <td class="num" style="text-align:left">${esc(n.fecha ? n.fecha.slice(0, 10) : "—")}</td>
        <td class="num">${num(n.palabras)}</td>
        <td class="num"><span class="medidor"><i style="width:${pct(n.puntaje)}"></i></span> ${Number(n.puntaje).toFixed(2)}</td>
        <td>${esc(ORIGENES[n.origen] || n.origen)}</td>
        <td class="motivo-c">${esc(porQue(n.motivo || "").join(" · "))}</td>
      </tr>`).join("")}</tbody>`;
  $("#paginacion").innerHTML = `
    <span>${num(lista.length)} notas · página ${S.pagina + 1} de ${paginas}</span>
    <span><button class="boton" id="pag-ant" ${S.pagina ? "" : "disabled"}>${icono("i-izq")}Anterior</button>
    <button class="boton" id="pag-sig" ${S.pagina < paginas - 1 ? "" : "disabled"}>Siguiente${icono("i-der")}</button></span>`;
  $("#pag-ant").onclick = () => { S.pagina--; pintarTabla(filtradas()); scrollTo({ top: 0, behavior: "smooth" }); };
  $("#pag-sig").onclick = () => { S.pagina++; pintarTabla(filtradas()); scrollTo({ top: 0, behavior: "smooth" }); };
}

function iniciarTabla() {
  $("#tabla").addEventListener("change", (e) => {
    if (e.target.dataset.accion !== "decision") return;
    e.target.parentElement.style.setProperty("--c", COLOR(e.target.value));
    decidir(e.target.value, e.target.closest("tr").dataset.id);
  });
  $("#tabla").addEventListener("click", (e) => {
    if (!e.target.closest("[data-accion=abrir]")) return;
    S.actual = e.target.closest("tr").dataset.id;
    const d = S.porId.get(S.actual).decision;
    const casilla = $(`input[name=f-decision][value=${d}]`);
    if (!casilla.checked) casilla.checked = true;
    S.direccion = 1;
    cambiarVista("revisar");
  });
}

// ---- Panorama: gráficas
const leyenda = () => `<div class="leyenda">${DECISIONES.map((d) => `<span><i class="muestra b-${d}"></i>${NOMBRES[d]}</span>`).join("")}</div>`;

function agrupar(clave, limite = 10, conOtras = false) {
  const m = new Map();
  for (const n of S.notas) {
    for (const k of [].concat(clave(n))) {
      const g = m.get(k) || { nombre: k, total: 0, conservar: 0, descartar: 0, dudoso: 0 };
      g.total++; g[n.decision]++;
      m.set(k, g);
    }
  }
  const todos = [...m.values()].sort((a, b) => b.total - a.total);
  if (!conOtras || todos.length <= limite) return todos.slice(0, limite);
  const otras = { nombre: `Otras ${num(todos.length - limite + 1)}`, total: 0, conservar: 0, descartar: 0, dudoso: 0, otras: true };
  for (const g of todos.slice(limite - 1)) DECISIONES.concat("total").forEach((k) => { otras[k] += g[k]; });
  return [...todos.slice(0, limite - 1), otras];
}

// Barras horizontales apiladas: 2px de aire entre segmentos, valor al final, detalle al pasar el mouse.
function filasApiladas(grupos, { clic = false, nombres = {} } = {}) {
  const max = Math.max(1, ...grupos.map((g) => g.total));
  return `<div class="filas">${grupos.map((g, k) => `
    <div class="fila ${clic && !g.otras ? "clicable" : ""}" data-valor="${esc(g.nombre)}" title="${esc(nombres[g.nombre] || g.nombre)}">
      <span class="nombre">${esc(nombres[g.nombre] || g.nombre)}</span>
      <span class="carril"><span class="pila" style="width:calc(${(100 * g.total) / max}% - 48px);animation-delay:${k * 35}ms">${DECISIONES
        .filter((d) => g[d]).map((d) => `<i class="b-${d}" data-d="${d}" style="flex:${g[d]} 1 0"></i>`).join("")}</span>
        <span class="n">${num(g.total)}</span></span>
    </div>`).join("")}</div>`;
}
function conectarFilas(cont, grupos, nombres = {}) {
  $$(".fila", cont).forEach((fila, k) => {
    const g = grupos[k];
    $$(".pila i", fila).forEach((seg) => {
      seg.onpointermove = (e) => mostrarTip(e, nombres[g.nombre] || g.nombre, DECISIONES.filter((d) => g[d]).map((d) =>
        ({ color: COLOR(d), nombre: NOMBRES[d], valor: num(g[d]) })).concat([{ nombre: "Total", valor: num(g.total), color: "transparent" }]));
      seg.onpointerleave = ocultarTip;
    });
  });
}

// Eje con marcas enteras y parejas: paso 1, 2, 5, 10, 20, 50… y un tope múltiplo del paso.
function escala(maxDato, marcas = 4) {
  const bruto = Math.max(1, maxDato) / marcas;
  const p = Math.pow(10, Math.floor(Math.log10(bruto))), f = bruto / p;
  const paso = Math.max(1, (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p);
  const max = Math.max(paso, Math.ceil(Math.max(1, maxDato) / paso) * paso);
  const ticks = [];
  for (let t = 0; t <= max + 1e-9; t += paso) ticks.push(t);
  return { max, ticks };
}
// Rectángulo con esquinas de arriba redondeadas (4px) y base recta, como pide la guía.
function barraRedonda(x, y, w, h, r = 4) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

// Columnas apiladas por decisión en el tiempo.
function graficaFechas(lienzo) {
  const conFecha = S.notas.filter((n) => n.fecha);
  if (!conFecha.length) { lienzo.innerHTML = `<p class="vacio-panel">Ninguna nota tiene fecha legible.</p>`; return null; }
  const dias = conFecha.map((n) => n.fecha.slice(0, 10)).sort();
  const t0 = new Date(dias[0] + "T00:00:00Z"), t1 = new Date(dias[dias.length - 1] + "T00:00:00Z");
  const porMes = (t1 - t0) / 864e5 > 62;
  const clave = (iso) => porMes ? iso.slice(0, 7) : iso.slice(0, 10);
  const cubetas = new Map();
  const d = new Date(t0);
  if (porMes) d.setUTCDate(1);
  let tope = 0;
  while (d <= t1 && tope++ < 400) {  // llenar huecos: un día sin notas también es información
    cubetas.set(d.toISOString().slice(0, porMes ? 7 : 10), { conservar: 0, dudoso: 0, descartar: 0, total: 0 });
    porMes ? d.setUTCMonth(d.getUTCMonth() + 1) : d.setUTCDate(d.getUTCDate() + 1);
  }
  for (const n of conFecha) {
    const c = cubetas.get(clave(n.fecha));
    if (c) { c[n.decision]++; c.total++; }
  }
  let datos = [...cubetas.entries()];
  if (datos.length > 60) datos = datos.slice(-60);
  const etiqueta = (k) => porMes
    ? new Date(k + "-01T12:00:00Z").toLocaleDateString("es-MX", { month: "short", year: "2-digit" })
    : new Date(k + "T12:00:00Z").toLocaleDateString("es-MX", { day: "numeric", month: "short" });

  const W = Math.max(320, lienzo.clientWidth), H = 230, m = { t: 12, r: 8, b: 26, l: 40 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const { max, ticks } = escala(Math.max(...datos.map(([, c]) => c.total)));
  const paso = iw / datos.length, bw = Math.min(24, Math.max(3, paso * 0.62));
  const y = (v) => m.t + ih - (v / max) * ih;
  const cadaEtq = Math.ceil(datos.length / Math.max(2, Math.floor(iw / 70)));
  let svg = `<svg class="grafica" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Notas por ${porMes ? "mes" : "día"}">`;
  svg += ticks.map((t) => `<line class="${t ? "grid" : "eje"}" x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}"/>
    <text x="${m.l - 8}" y="${y(t) + 4}" text-anchor="end">${num(Math.round(t))}</text>`).join("");
  datos.forEach(([k, c], i) => {
    const x = m.l + i * paso + (paso - bw) / 2;
    let base = y(0);
    const presentes = DECISIONES.filter((dd) => c[dd]);
    presentes.forEach((dd, j) => {
      const h = (c[dd] / max) * ih, gap = j ? 2 : 0;
      const alto = Math.max(0, h - gap), top = base - gap - alto;
      const ultima = j === presentes.length - 1;
      svg += ultima
        ? `<path class="col-anim" style="fill:${COLOR(dd)};animation-delay:${i * 12}ms" d="${barraRedonda(x, top, bw, alto)}"/>`
        : `<rect class="col-anim" style="fill:${COLOR(dd)};animation-delay:${i * 12}ms" x="${x}" y="${top}" width="${bw}" height="${alto}"/>`;
      base = top;
    });
    if (i % cadaEtq === 0) svg += `<text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${esc(etiqueta(k))}</text>`;
    svg += `<rect class="banda" tabindex="0" data-i="${i}" x="${m.l + i * paso}" y="${m.t}" width="${paso}" height="${ih}" rx="4"/>`;
  });
  svg += `</svg>`;
  lienzo.innerHTML = svg;
  $$(".banda", lienzo).forEach((b) => {
    const [k, c] = datos[Number(b.dataset.i)];
    const filas = () => DECISIONES.map((dd) => ({ color: COLOR(dd), nombre: NOMBRES[dd], valor: num(c[dd]) }))
      .concat([{ color: "transparent", nombre: "Total", valor: num(c.total) }]);
    const titulo = porMes ? etiqueta(k) : fechaLarga(k + "T12:00:00Z");
    b.onpointermove = (e) => mostrarTip(e, titulo, filas());
    b.onfocus = () => mostrarTip(null, titulo, filas(), b);
    b.onpointerleave = b.onblur = ocultarTip;
  });
  return { porMes, sinFecha: S.notas.length - conFecha.length };
}

// Histograma del puntaje de las reglas, con las dos líneas de corte.
function graficaPuntaje(lienzo) {
  const bajo = Math.min(S.opciones.umbral_bajo, S.opciones.umbral_alto);
  const alto = Math.max(S.opciones.umbral_bajo, S.opciones.umbral_alto);
  const N = 20, bins = Array.from({ length: N }, () => 0);
  S.notas.forEach((n) => { bins[Math.min(N - 1, Math.floor((n.puntaje ?? 0) * N))]++; });
  const zona = (i) => { const c = (i + 0.5) / N; return c < bajo ? "descartar" : c >= alto ? "conservar" : "dudoso"; };
  const W = Math.max(320, lienzo.clientWidth), H = 220, m = { t: 26, r: 8, b: 26, l: 40 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b, { max, ticks } = escala(Math.max(1, ...bins), 3);
  const paso = iw / N, bw = Math.min(24, paso - 2);
  const y = (v) => m.t + ih - (v / max) * ih, xv = (v) => m.l + v * iw;
  let svg = `<svg class="grafica" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Distribución del puntaje">`;
  svg += ticks.map((t) => `<line class="${t ? "grid" : "eje"}" x1="${m.l}" x2="${W - m.r}" y1="${y(t)}" y2="${y(t)}"/>
    <text x="${m.l - 8}" y="${y(t) + 4}" text-anchor="end">${num(Math.round(t))}</text>`).join("");
  bins.forEach((v, i) => {
    const x = m.l + i * paso + (paso - bw) / 2, h = (v / max) * ih;
    if (v) svg += `<path class="col-anim" style="fill:${COLOR(zona(i))};animation-delay:${i * 18}ms" d="${barraRedonda(x, y(0) - h, bw, h)}"/>`;
    svg += `<rect class="banda" tabindex="0" data-i="${i}" x="${m.l + i * paso}" y="${m.t}" width="${paso}" height="${ih}" rx="4"/>`;
  });
  for (const [v, t] of [[bajo, "descartar ←"], [alto, "→ conservar"]]) {
    const x = xv(v);
    svg += `<line class="umbral" x1="${x}" x2="${x}" y1="${m.t - 6}" y2="${y(0)}"/>
      <text class="etq-umbral" x="${x + (t.startsWith("→") ? 6 : -6)}" y="${m.t - 10}" text-anchor="${t.startsWith("→") ? "start" : "end"}">${t} ${v.toFixed(2)}</text>`;
  }
  svg += [0, 0.25, 0.5, 0.75, 1].map((v) => `<text x="${xv(v)}" y="${H - 8}" text-anchor="middle">${v.toFixed(2)}</text>`).join("");
  svg += `</svg>`;
  lienzo.innerHTML = svg;
  $$(".banda", lienzo).forEach((b) => {
    const i = Number(b.dataset.i), z = zona(i);
    const titulo = `Puntaje ${(i / N).toFixed(2)}–${((i + 1) / N).toFixed(2)}`;
    const filas = () => [{ color: COLOR(z), nombre: `Notas · zona ${NOMBRES[z].toLowerCase()}`, valor: num(bins[i]) }];
    b.onpointermove = (e) => mostrarTip(e, titulo, filas());
    b.onfocus = () => mostrarTip(null, titulo, filas(), b);
    b.onpointerleave = b.onblur = ocultarTip;
  });
}

function pintarPanorama() {
  const motivos = (n) => n.origen === "duplicado" ? ["Duplicado"]
    : porQue(n.motivo || "").map((m) => m.replace(/\s*\([^)]*\)/g, "").replace(/^El modelo.*|^Las reglas la aceptaron.*/, "Señalada por el modelo"))
      .filter((m) => m !== "Pasa todas las reglas");
  const fuentes = agrupar((n) => n.fuente || "(sin fuente)", 10, true);
  const porMotivo = agrupar(motivos, 10);
  const quien = agrupar((n) => n.origen, 6);
  S.graficas = { fuentes, porMotivo, quien };
  $("#panorama").innerHTML =
    seccion("tiempo", "Notas en el tiempo", '<span id="sub-fechas"></span>', `${leyenda()}<div class="lienzo" id="lienzo-fechas"></div>`)
    + `<div class="rejilla-2"><div>`
    + seccion("puntaje", "Puntaje de las reglas", "Dónde caen los cortes de Ajustes", `${leyenda()}<div class="lienzo" id="lienzo-puntaje"></div>`)
    + seccion("motivos", "Por qué se marcan", "Una nota puede tener varias alertas", `${leyenda()}<div id="filas-motivo">${porMotivo.length ? filasApiladas(porMotivo) : '<p class="vacio-panel">Ninguna alerta. Todo pasó las reglas.</p>'}</div>`)
    + `</div><div>`
    + seccion("fuentes", "Por fuente", "Toca una para ver sus notas", `${leyenda()}<div id="filas-fuente">${filasApiladas(fuentes, { clic: true })}</div>`)
    + seccion("quien", "Quién decidió", "Reglas, duplicados, modelo o una persona", `${leyenda()}<div id="filas-quien">${filasApiladas(quien, { nombres: ORIGENES })}</div>`)
    + `</div></div>`;
  redibujarGraficas();
  conectarFilas($("#filas-fuente"), fuentes);
  conectarFilas($("#filas-motivo"), porMotivo);
  conectarFilas($("#filas-quien"), quien, ORIGENES);
  $$("#filas-fuente .clicable").forEach((el) => el.onclick = () => {
    $("#f-fuente").value = el.dataset.valor;
    $$("input[name=f-decision]").forEach((i) => { i.checked = true; });
    cambiarVista("tabla");
    alFiltrar();
  });
}
function redibujarGraficas() {
  if (!$("#lienzo-fechas")) return;
  const info = graficaFechas($("#lienzo-fechas"));
  $("#sub-fechas").textContent = info
    ? `Por ${info.porMes ? "mes" : "día"}, según la fecha de publicación${info.sinFecha ? ` · ${num(info.sinFecha)} sin fecha legible` : ""}`
    : "Según la fecha de publicación";
  graficaPuntaje($("#lienzo-puntaje"));
}

// ---- Archivos: cómo se integró cada JSON
const CAMPOS = [["titulo", "Título"], ["cuerpo", "Cuerpo"], ["resumen", "Resumen"], ["fecha", "Fecha"],
                ["fuente", "Fuente"], ["url", "URL"], ["autor", "Autor"], ["categoria", "Categoría"]];
const ALIAS_GUIA = {
  "Título": "title · titulo · headline · titular", "Cuerpo": "content · body · text · texto · articleBody",
  "Resumen": "description · summary · resumen · bajada", "Fecha": "date · publishedAt · pubDate · fecha · timestamp",
  "Fuente": "source · medio · publisher · site", "URL": "url · link · enlace · permalink",
  "Autor": "author · authors · autor · byline", "Categoría": "category · section · seccion · tags",
};
function guiaHTML() {
  const ej = (t, c) => `<div><p class="codigo-titulo">${t}</p><pre class="codigo">${esc(c)}</pre></div>`;
  return `<p class="explica">Sube los archivos como vengan. El limpiador reconoce la forma y los nombres de los campos por su cuenta; no hay que convertir nada.</p>
    <div class="guia-formatos">
      ${ej("Lista", '[\n  {"title": "…", "content": "…"},\n  {"title": "…", "content": "…"}\n]')}
      ${ej("Objeto con lista (APIs, CMS)", '{\n  "status": "ok",\n  "articles": [\n    {"headline": "…", "body": "…"}\n  ]\n}')}
      ${ej("JSON Lines (.jsonl)", '{"titulo": "…", "texto": "…"}\n{"titulo": "…", "texto": "…"}\n{"titulo": "…", "texto": "…"}')}
    </div>
    <p class="codigo-titulo">Nombres que reconoce para cada campo (sin importar mayúsculas)</p>
    <div class="alias">${Object.entries(ALIAS_GUIA).map(([k, v]) => `<b>${k}</b><span>${v}</span>`).join("")}</div>
    <p class="aviso-suave">También entiende contenedores como <code>data</code>, <code>items</code>, <code>results</code>, <code>noticias</code> y respuestas de Elasticsearch. Los renglones rotos de un .jsonl se saltan y se reportan; el resto se procesa.</p>`;
}
function pintarVistaArchivos() {
  const archivos = S.reporte?.archivos || [];
  const cont = $("#vista-archivos");
  const flujo = `<div class="flujo"><span>${icono("i-doc")}Tus JSON</span>${icono("i-flecha")}<span>Detecta la forma</span>${icono("i-flecha")}
    <span>Reconoce los campos</span>${icono("i-flecha")}<span>Limpia texto, fechas y URLs</span>${icono("i-flecha")}<span>${icono("i-check")}JSON limpio</span></div>`;
  const porArchivo = archivos.map((a, k) => {
    const filas = CAMPOS.map(([c, nombre]) => {
      const u = a.campos?.[c];
      return u ? `<code>${esc(u.de)}</code>${icono("i-flecha").replace("<svg", '<svg class="flecha"')}<b>${nombre}</b>
          <span class="cobertura"><span class="medidor"><i style="width:${pct(u.cobertura)}"></i></span>${pct(u.cobertura)} de las notas${u.variantes.length > 1 ? ` · también ${esc(u.variantes.slice(1).join(", "))}` : ""}</span>`
        : `<span class="falta">no viene</span>${icono("i-flecha").replace("<svg", '<svg class="flecha"')}<b style="color:var(--texto-3)">${nombre}</b><span></span>`;
    }).join("");
    const errores = a.total_errores ? `<ul class="error-lista">${a.errores.map((e) => `<li>${esc(e)}</li>`).join("")}${a.total_errores > a.errores.length ? `<li>… y ${num(a.total_errores - a.errores.length)} más</li>` : ""}</ul>` : "";
    const sub = `<span class="formato">${esc(a.formato)}</span> &nbsp;${num(a.registros)} notas${a.total_errores ? ` · ${num(a.total_errores)} ${a.total_errores === 1 ? "renglón" : "renglones"} con error` : ""}`;
    const cuerpo = `${errores}
      <div class="mapa">${filas}</div>
      ${a.ignoradas?.length ? `<p class="ignoradas">Llaves que no se usan: ${a.ignoradas.map((x) => `<code>${esc(x)}</code>`).join("")}</p>` : ""}
      ${a.antes ? `<div class="rejilla-2">
        <div><p class="codigo-titulo">Así venía una nota</p><pre class="codigo">${esc(a.antes)}</pre></div>
        <div><p class="codigo-titulo">${icono("i-check")}Así quedó</p><pre class="codigo">${esc(a.despues)}</pre></div></div>` : ""}`;
    return seccion(`archivo-${k}`, esc(a.nombre), sub, cuerpo, k === 0);
  }).join("");
  cont.innerHTML = flujo + (porArchivo || '<p class="vacio-panel">No hay archivos cargados.</p>')
    + seccion("guia", "Qué formatos acepta", "Formas y nombres de campo que reconoce", guiaHTML(), false);
}

// ---- Modelo
async function pintarModelo() {
  const cont = $("#modelo");
  try { S.modelo = await api("/api/modelo"); } catch (e) { return aviso(e.message, { error: true }); }
  const m = S.modelo, min = m.minimos;
  const listoDec = m.conservar >= min.por_clase && m.descartar >= min.por_clase && m.conservar + m.descartar >= min.total;
  const barra = (v, meta, clase = "") => `<div class="progreso ${clase}"><i style="width:${Math.min(100, (100 * v) / meta)}%"></i></div>`;
  const num2 = (a, b) => `${num(Math.min(a, b))} de ${num(b)}`;
  const precision = (ev, colorClase) => ev ? `<div class="heroe">${pct(ev.precision)}</div>
      <div class="heroe-sub">de acierto con notas que no vio al entrenar</div>
      <div class="filas">${Object.entries(ev.por_clase).map(([c, v]) => `
        <div class="fila"><span class="nombre">${esc(NOMBRES[c] || c[0].toUpperCase() + c.slice(1))}</span>
          <span class="carril"><span class="pila" style="width:calc(${v * 100}% - 48px)"><i style="flex:1;background:${colorClase(c)}"></i></span>
          <span class="n">${pct(v)}</span></span></div>`).join("")}</div>
      <p class="aviso-suave">Medido con validación cruzada en ${ev.pliegues} partes.</p>`
    : `<p class="vacio-panel">Todavía no hay suficientes ejemplos.</p>`;
  const pasos = `
    <ol class="pasos-modelo">
      <li><span class="paso-num ${listoDec ? "hecho" : ""}">${listoDec ? icono("i-check") : "1"}</span><div>
        <b>Decide notas a mano</b><p>Cada decisión es un ejemplo. Hacen falta ${min.total}, con al menos ${min.por_clase} de cada tipo.</p>
        <p style="margin-top:10px">Conservadas · ${num2(m.conservar, min.por_clase)}</p>${barra(m.conservar, min.por_clase)}
        <p>Descartadas · ${num2(m.descartar, min.por_clase)}</p>${barra(m.descartar, min.por_clase, "p-descartar")}
        <p>Con categoría · ${num(m.con_categoria)}</p></div></li>
      <li><span class="paso-num ${m.entrenado ? "hecho" : ""}">${m.entrenado ? icono("i-check") : "2"}</span><div>
        <b>Entrénalo</b><p>${m.entrenado ? `Último entrenamiento: ${esc(new Date(m.entrenado).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" }))}.` : "Tarda unos segundos."}</p></div></li>
      <li><span class="paso-num">3</span><div>
        <b>Deja que ayude</b><p>Al limpiar, decide las dudosas cuando está muy seguro y te avisa de lo que parece basura. Nunca cambia lo que decidiste tú.</p></div></li>
    </ol>
    <button class="boton primario grande" id="btn-entrenar">${icono("i-cerebro")}${m.entrenado ? "Volver a entrenar" : "Entrenar"}</button>`;
  cont.innerHTML = seccion("ensenale", "Enséñale a decidir", m.entrenado ? "Entrenado" : `${num(m.conservar + m.descartar)} de ${min.total} ejemplos`, pasos)
    + `<div class="rejilla-2"><div>`
    + seccion("acierto-decision", "Conservar o descartar", m.decision ? `${pct(m.decision.precision)} de acierto` : "Sin entrenar", precision(m.decision, (c) => COLOR(c === "descartar" ? "descartar" : "conservar")))
    + `</div><div>`
    + seccion("acierto-categoria", "Poner categoría", m.categoria ? `${pct(m.categoria.precision)} de acierto` : "Sin entrenar", precision(m.categoria, () => "var(--texto-2)"))
    + `</div></div>`;
  $("#btn-entrenar").onclick = entrenar;
}

async function entrenar() {
  await conCarga("Entrenando…", async () => {
    const r = await post("/api/entrenar");
    const faltas = r.resultado.falta || [];
    if (!r.resultado.decision && !r.resultado.categoria) {
      aviso(`Aún no: ${faltas[0] || "faltan ejemplos"}`, { error: true, ms: 7000 });
      return;
    }
    await recargar();
    const a = r.aplicado;
    aviso(`Entrenado con ${num(r.resultado.ejemplos)} ejemplos` + (a ? ` · decidió ${num(a.decididas)} y categorizó ${num(a.categorizadas)}` : ""));
  });
}

// ---- Exportar
function pintarExportar() {
  const c = S.conteos, d = c.dudoso || 0;
  const item = (tipo, ico, titulo, texto, principal = false) => `
    <a class="descarga ${principal ? "principal" : ""}" href="/api/exportar?tipo=${tipo}" download>
      <span class="ico">${icono(ico)}</span><div><b>${titulo}</b><span>${texto}</span></div>${icono("i-bajar")}</a>`;
  $("#exportar").innerHTML = `
    ${d ? `<div class="alerta">${estado("dudoso")}<span>Quedan <b>${num(d)}</b> dudosas sin decidir. No entran al archivo limpio; puedes exportarlas aparte.</span></div>` : ""}
    <div class="lista-exportar">
      ${item("limpias", "i-check", "Noticias limpias", `${num(c.conservar)} notas · JSON listo para usar`, true)}
      ${item("dudosas", "i-duda", "Dudosas", `${num(d)} notas pendientes · JSON`)}
      ${item("descartadas", "i-x", "Descartadas", `${num(c.descartar)} notas con su motivo · JSON`)}
      ${item("csv", "i-tabla", "Todo con decisiones", "CSV para Excel o Sheets")}
      ${item("reporte", "i-doc", "Reporte", "Números del proceso y errores · JSON")}
    </div>`;
}

// ------------------------------------------------------------------ teclado
function iniciarTeclado() {
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#ajustes").hidden) return abrirAjustes(false);
    const escribiendo = e.target.closest?.("input, select, textarea") && e.target.type !== "checkbox" && e.target.type !== "range";
    if (e.key === "Escape" && escribiendo) return e.target.blur();
    if (escribiendo || e.metaKey || e.ctrlKey || e.altKey || $("#trabajo").hidden || $("#ayuda").open || !$("#ajustes").hidden) return;
    const k = e.key.toLowerCase();
    if (k === "?") { e.preventDefault(); return $("#ayuda").showModal(); }
    if (k === "/") { e.preventDefault(); return $("#f-buscar").focus(); }
    if (k === "z") { e.preventDefault(); return deshacer(); }
    if (k === "f" && !document.body.classList.contains("sin-filtros")) { e.preventDefault(); return plegarFiltros(!document.body.classList.contains("filtros-plegados")); }
    if (S.vista !== "revisar" || !S.actual) return;
    const accion = { c: () => decidir("conservar"), d: () => decidir("descartar"), u: () => decidir("dudoso"),
                     arrowright: () => mover(1), j: () => mover(1), arrowleft: () => mover(-1), k: () => mover(-1) }[k];
    if (accion) { e.preventDefault(); return accion(); }
    if (/^[1-9]$/.test(k) && S.categorias[Number(k) - 1]) { e.preventDefault(); ponerCategoria(S.categorias[Number(k) - 1]); }
  });
}

// ------------------------------------------------------------------ arrastrar y soltar
function iniciarSoltar() {
  let n = 0;
  const tieneArchivos = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  window.addEventListener("dragenter", (e) => { if (tieneArchivos(e)) { n++; document.body.classList.add("arrastrando"); } });
  window.addEventListener("dragleave", () => { if (--n <= 0) { n = 0; document.body.classList.remove("arrastrando"); } });
  window.addEventListener("dragover", (e) => { if (tieneArchivos(e)) e.preventDefault(); });
  window.addEventListener("drop", (e) => {
    if (!tieneArchivos(e)) return;
    e.preventDefault(); n = 0; document.body.classList.remove("arrastrando");
    subir(e.dataTransfer.files);
  });
}

// ------------------------------------------------------------------ arranque
async function iniciar() {
  iniciarAjustes(); iniciarFiltros(); iniciarTabla(); iniciarTeclado(); iniciarSoltar();
  $$(".pestanas button").forEach((b) => b.onclick = () => cambiarVista(b.dataset.vista));
  iniciarTema();
  const r = $(".resumen-plegable"), g = guardado("limpiador-seccion-resumen");
  if (g !== null) r.open = g === "1";
  plegarFiltros(guardado("limpiador-filtros-plegados") === "1");
  $("#btn-filtros").onclick = () => plegarFiltros(!document.body.classList.contains("filtros-plegados"));
  addEventListener("scroll", () => document.body.classList.toggle("desplazado", scrollY > 8), { passive: true });
  $$("[data-guia]").forEach((el) => { el.innerHTML = guiaHTML(); });
  $("#entrada-archivos").onchange = (e) => { subir(e.target.files); e.target.value = ""; };
  $("#btn-limpiar").onclick = limpiar;
  $("#btn-atajos").onclick = () => $("#ayuda").showModal();
  $("#btn-prueba").onclick = async () => {
    const r = await post("/api/prueba").catch((e) => aviso(e.message, { error: true }));
    if (r) { pintarArchivos(r.archivos); await limpiar(); }
  };
  let espera;
  addEventListener("resize", () => {
    moverSegmento();
    clearTimeout(espera);
    espera = setTimeout(() => { if (S.vista === "panorama" && !$("#trabajo").hidden) redibujarGraficas(); }, 200);
  });
  try {
    const cfg = await api("/api/config");
    S.categorias = cfg.categorias;
    $("#btn-prueba").hidden = !cfg.hay_prueba;
    await recargar(true);
    if (!$("#trabajo").hidden) cambiarVista(location.hash.slice(1));
  } catch (e) { aviso(`No se pudo conectar con el servidor: ${e.message}`, { error: true }); }
}
iniciar();
