/* ============================================================
   ECO GO — Registro de uso del tablero (Google Apps Script)

   Recibe los eventos que manda assets/js/layout.js (secciones vistas,
   tiempo a la vista, descargas) y los anota en la pestaña Eventos de esta
   planilla. WordPress, por su lado, manda los datos de cada cliente que
   abre la página de clientes y quedan en la pestaña Usuarios.

   Instalación: ver SEGUIMIENTO.md. Primero se corre configurar() una vez
   desde el editor; después se implementa como aplicación web.
   ============================================================ */

const ZONA = 'America/Argentina/Buenos_Aires';
const HOJA_EVENTOS = 'Eventos';
const HOJA_USUARIOS = 'Usuarios';
const HOJA_RESUMEN = 'Resumen';
const COLS_EVENTOS = ['Fecha', 'ID usuario', 'Cliente', 'Empresa', 'Acceso', 'Evento', 'Sección',
                      'Detalle', 'Segundos', 'Dispositivo', 'Sesión', 'Vista'];
const COLS_USUARIOS = ['ID usuario', 'Nombre', 'Email', 'Empresa', 'Alta en WordPress', 'Actualizado'];
const COL = nombre => COLS_EVENTOS.indexOf(nombre) + 1;

/* ---------- Se corre una vez a mano desde el editor ---------- */
function configurar() {
  const libro = SpreadsheetApp.getActive();
  libro.setSpreadsheetTimeZone(ZONA);
  hoja(HOJA_EVENTOS, COLS_EVENTOS).getRange('A:A').setNumberFormat('dd/mm/yyyy hh:mm:ss');
  hoja(HOJA_USUARIOS, COLS_USUARIOS);
  armarResumen();
  // Resumen adelante y fuera la hoja vacía que trae la planilla nueva
  libro.setActiveSheet(libro.getSheetByName(HOJA_RESUMEN));
  libro.moveActiveSheet(1);
  libro.getSheets().forEach(s => {
    if ([HOJA_EVENTOS, HOJA_USUARIOS, HOJA_RESUMEN].indexOf(s.getName()) < 0 && s.getLastRow() === 0) {
      libro.deleteSheet(s);
    }
  });

  const props = PropertiesService.getScriptProperties();
  let clave = props.getProperty('CLAVE_WORDPRESS');
  if (!clave) {
    clave = Utilities.getUuid();
    props.setProperty('CLAVE_WORDPRESS', clave);
  }
  console.log('Clave para el snippet de WordPress ($registro_clave): ' + clave);
}

/* ---------- Punto de entrada de la aplicación web ---------- */
function doPost(e) {
  let datos;
  try {
    datos = JSON.parse(e.postData.contents);
  } catch (err) {
    return respuesta('json invalido');
  }
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) return respuesta('ocupado');
  try {
    if (datos.tipo === 'usuario') guardarUsuario(datos);
    else if (datos.evento === 'tiempo') anotarTiempo(datos);
    else anotarEvento(datos);
  } finally {
    lock.releaseLock();
  }
  return respuesta('ok');
}

function doGet() {
  return respuesta('Registro Eco Go funcionando');
}

function respuesta(txt) {
  return ContentService.createTextOutput(txt).setMimeType(ContentService.MimeType.TEXT);
}

/* ---------- Eventos del tablero ---------- */
function anotarEvento(d) {
  const evento = texto(d.evento, 30);
  if (!/^[a-z_-]+$/.test(evento)) return;
  const u = idUsuario(d.u);
  const usuario = u ? buscarUsuario(u) : null;
  hoja(HOJA_EVENTOS, COLS_EVENTOS).appendRow([
    new Date(),
    u,
    usuario ? usuario.nombre : '',
    usuario ? usuario.empresa : '',
    d.acceso === 'cliente' ? 'Cliente' : 'Público',
    evento,
    texto(d.seccion, 80),
    texto(d.detalle, 200),
    '',
    texto(d.dispositivo, 20),
    texto(d.sesion, 20),
    texto(d.vista, 20)
  ]);
}

/* El tablero manda el tiempo acumulado de una vista; se escribe en la fila
   de esa vista (se busca entre las últimas, porque es reciente). */
function anotarTiempo(d) {
  const vista = texto(d.vista, 20);
  const seg = Math.round(Number(d.segundos));
  if (!vista || !(seg > 0) || seg > 86400) return;
  const sh = hoja(HOJA_EVENTOS, COLS_EVENTOS);
  const ultima = sh.getLastRow();
  if (ultima < 2) return;
  const desde = Math.max(2, ultima - 499);
  const filas = sh.getRange(desde, 1, ultima - desde + 1, COLS_EVENTOS.length).getValues();
  for (let i = filas.length - 1; i >= 0; i--) {
    const f = filas[i];
    if (String(f[COL('Vista') - 1]) === vista && f[COL('Evento') - 1] === 'vista') {
      if (seg > (Number(f[COL('Segundos') - 1]) || 0)) sh.getRange(desde + i, COL('Segundos')).setValue(seg);
      return;
    }
  }
}

/* ---------- Usuarios (los manda WordPress, con la clave) ---------- */
function guardarUsuario(d) {
  const clave = PropertiesService.getScriptProperties().getProperty('CLAVE_WORDPRESS');
  if (!clave || d.clave !== clave) return;
  const u = idUsuario(d.u);
  if (!u) return;

  const sh = hoja(HOJA_USUARIOS, COLS_USUARIOS);
  const n = sh.getLastRow();
  const ids = n > 1 ? sh.getRange(2, 1, n - 1, 1).getValues().map(r => String(r[0])) : [];
  const i = ids.indexOf(u);
  const fila = i >= 0 ? i + 2 : n + 1;
  const antes = i >= 0 ? sh.getRange(fila, 1, 1, COLS_USUARIOS.length).getValues()[0] : [];
  // Si WordPress no tiene la empresa, se respeta la que se haya cargado a mano
  sh.getRange(fila, 1, 1, COLS_USUARIOS.length).setValues([[
    u,
    texto(d.nombre, 120) || antes[1] || '',
    texto(d.email, 120) || antes[2] || '',
    texto(d.empresa, 120) || antes[3] || '',
    texto(d.alta, 30) || antes[4] || '',
    new Date()
  ]]);
  CacheService.getScriptCache().remove('usuarios');
}

function mapaUsuarios(releer) {
  const cache = CacheService.getScriptCache();
  if (!releer) {
    const guardado = cache.get('usuarios');
    if (guardado) return JSON.parse(guardado);
  }
  const sh = hoja(HOJA_USUARIOS, COLS_USUARIOS);
  const n = sh.getLastRow();
  const mapa = {};
  if (n > 1) {
    sh.getRange(2, 1, n - 1, 4).getValues().forEach(f => {
      if (f[0] !== '') mapa[String(f[0])] = { nombre: f[1], empresa: f[3] };
    });
  }
  cache.put('usuarios', JSON.stringify(mapa), 600);
  return mapa;
}

function buscarUsuario(u) {
  return mapaUsuarios(false)[u] || mapaUsuarios(true)[u] || null;
}

/* Completa Cliente y Empresa en las filas de Eventos que quedaron sin nombre
   (por ejemplo, si el cliente se cargó en Usuarios después). Se corre a mano
   desde el menú Eco Go de la planilla. */
function completarNombres() {
  const sh = hoja(HOJA_EVENTOS, COLS_EVENTOS);
  const n = sh.getLastRow();
  if (n < 2) return;
  const mapa = mapaUsuarios(true);
  const rango = sh.getRange(2, COL('ID usuario'), n - 1, 3);
  const valores = rango.getValues().map(f => {
    const usuario = mapa[String(f[0])];
    return usuario ? [f[0], usuario.nombre, usuario.empresa] : f;
  });
  rango.setValues(valores);
}

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Eco Go')
    .addItem('Completar nombres en Eventos', 'completarNombres')
    .addToUi();
}

/* ---------- Pestaña Resumen (fórmulas, se actualiza sola) ---------- */
function armarResumen() {
  const sh = hoja(HOJA_RESUMEN, []);
  sh.clear();
  const E = HOJA_EVENTOS + '!';

  sh.getRange('A1').setValue('Por cliente').setFontWeight('bold');
  sh.getRange('A2').setFormula(
    '=IFERROR(ARRAYFORMULA(QUERY({' + E + 'B2:D, ' + E + 'A2:A, (' + E + 'F2:F="vista")*1, (' +
    E + 'F2:F="descarga")*1, ' + E + 'I2:I/60}, ' +
    '"select Col1, Col2, Col3, sum(Col5), sum(Col6), sum(Col7), max(Col4) where Col1 is not null ' +
    'group by Col1, Col2, Col3 order by max(Col4) desc ' +
    'label Col1 \'ID usuario\', Col2 \'Cliente\', Col3 \'Empresa\', sum(Col5) \'Secciones vistas\', ' +
    'sum(Col6) \'Descargas\', sum(Col7) \'Minutos\', max(Col4) \'Última actividad\'", 0)), "Sin datos todavía")');
  sh.getRange('F:F').setNumberFormat('0.0');
  sh.getRange('G:G').setNumberFormat('dd/mm/yyyy hh:mm');

  sh.getRange('I1').setValue('Secciones vistas').setFontWeight('bold');
  sh.getRange('I2').setFormula(
    '=IFERROR(QUERY(' + E + 'A2:L, "select G, count(A) where F = \'vista\' group by G pivot E ' +
    'label G \'Sección\'", 0), "Sin datos todavía")');

  sh.getRange('M1').setValue('Descargas por archivo').setFontWeight('bold');
  sh.getRange('M2').setFormula(
    '=IFERROR(QUERY(' + E + 'A2:L, "select H, count(A) where F = \'descarga\' group by H ' +
    'order by count(A) desc label H \'Archivo\', count(A) \'Descargas\'", 0), "Sin datos todavía")');
}

/* ---------- Auxiliares ---------- */
function hoja(nombre, columnas) {
  const libro = SpreadsheetApp.getActive();
  let sh = libro.getSheetByName(nombre);
  if (!sh) {
    sh = libro.insertSheet(nombre);
    if (columnas.length) {
      sh.getRange(1, 1, 1, columnas.length).setValues([columnas]).setFontWeight('bold');
      sh.setFrozenRows(1);
    }
  }
  return sh;
}

/* Recorta y evita que un texto que empieza con = + - @ se tome como fórmula */
function texto(v, max) {
  let s = (v === undefined || v === null) ? '' : String(v).trim().slice(0, max);
  if (/^[=+\-@]/.test(s)) s = "'" + s;
  return s;
}

function idUsuario(v) {
  const s = String(v === undefined || v === null ? '' : v).trim();
  return /^\d{1,10}$/.test(s) ? s : '';
}
