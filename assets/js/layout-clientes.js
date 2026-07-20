/* ============================================================
   ECO GO — Layout & Navegación · Dashboard Clientes
   ============================================================ */

const SECTIONS = [
  { id:'home',       label:'Inicio',     href:'index-clientes.html',          group:'General',  icon:'home',       desc:'Resumen y acceso rápido a las secciones.' },
  { id:'precios',    label:'Precios RPM',href:'pages/precios-clientes.html',   group:'Monitor',  icon:'tag',        desc:'IPC, núcleo, regulados y proyecciones RPM.' },
  { id:'actividad',  label:'Actividad',  href:'pages/actividad-clientes.html', group:'Monitor',  icon:'activity',   desc:'Monitor de actividad económica y proyecciones.' },
  { id:'rigi',           label:'RIGI',                     href:'pages/rigi-clientes.html',      group:'Monitor',  icon:'pie-chart',  desc:'Régimen de Incentivo para Grandes Inversiones.' },
  { id:'reservas',       label:'Reservas',                 href:'pages/reservas-clientes.html',  group:'Monitor',  icon:'shield',     desc:'Composición RIN, reservas brutas y depósitos.' },
  { id:'internacional2', label:'Internacional · Consensus', href:'pages/internacional2.html',     group:'Externo',  icon:'map',        desc:'LatinFocus Consensus Forecast — resumen y detalle por país.' },
];

const ICONS = {
  home:        '<path d="M3 9.5L12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1V9.5z"/>',
  activity:    '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  tag:         '<path d="M20.59 13.41 13.42 20.58a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><circle cx="7" cy="7" r="1.5"/>',
  'pie-chart': '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/>',
  shield:      '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  map:         '<polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/><line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/>',
  menu:        '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>'
};

function icon(name, cls) {
  cls = cls || 'eg-nav__icon';
  return '<svg class="' + cls + '" xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + (ICONS[name] || '') + '</svg>';
}

function resolve(href) {
  const depth = (document.body.dataset.depth || '0') | 0;
  return depth === 0 ? href : '../'.repeat(depth) + href;
}

function buildSidebar(activeId) {
  const groups = {};
  for (const s of SECTIONS) {
    (groups[s.group] = groups[s.group] || []).push(s);
  }
  let html = '<div class="eg-sidebar__brand">' +
      '<img src="' + resolve('assets/img/logo-ecogo.jpg') + '" alt="Eco Go" />' +
      '<span>Eco Go</span>' +
    '</div>' +
    '<ul class="eg-nav">';
  for (const g of Object.keys(groups)) {
    html += '<li class="eg-nav__group">' + g + '</li>';
    for (const s of groups[g]) {
      const active = s.id === activeId ? ' is-active' : '';
      html += '<li class="eg-nav__item">' +
        '<a href="' + resolve(s.href) + '" class="' + active.trim() + '">' +
          icon(s.icon) + ' <span>' + s.label + '</span>' +
        '</a>' +
      '</li>';
    }
  }
  html += '</ul>' +
    '<div class="eg-sidebar__footer">© ' + new Date().getFullYear() + ' Eco Go · Dashboard Clientes</div>';
  return html;
}

function buildHeader(activeId, noSidebar) {
  const section = SECTIONS.find(s => s.id === activeId) || SECTIONS[0];
  const today = new Date().toLocaleDateString('es-AR', {
    day: '2-digit', month: 'long', year: 'numeric'
  });

  if (noSidebar) {
    return '<div class="eg-header__brand">' +
        '<img src="' + resolve('assets/img/logo-ecogo.jpg') + '" alt="Eco Go" />' +
        '<strong>Eco Go · Dashboard Clientes</strong>' +
      '</div>' +
      '<div class="eg-header__spacer"></div>' +
      '<div class="eg-header__meta">Actualizado · ' + today + '</div>';
  }

  return '<button class="eg-header__toggle eg-header__toggle--mobile" id="egMobileToggle" aria-label="Abrir menú">' +
      icon('menu','') + '</button>' +
    '<div>' +
      '<div class="eg-header__crumb">Dashboard Clientes · Eco Go</div>' +
      '<div class="eg-header__title">' + section.label + '</div>' +
    '</div>' +
    '<div class="eg-header__spacer"></div>' +
    '<div class="eg-header__meta">Actualizado · ' + today + '</div>';
}

function mountLayout() {
  const activeId = document.body.dataset.activeSection || 'home';
  const noSidebar = document.body.dataset.noSidebar === 'true';

  const app = document.querySelector('.eg-app');
  const sb = document.getElementById('egSidebar');
  const hd = document.getElementById('egHeader');

  if (noSidebar) {
    if (app) app.classList.add('is-no-sidebar');
    if (hd)  hd.innerHTML = buildHeader(activeId, true);
    return;
  }

  if (sb) sb.innerHTML = buildSidebar(activeId);
  if (hd) hd.innerHTML = buildHeader(activeId, false);

  const toggle = document.getElementById('egMobileToggle');
  if (toggle && sb) {
    toggle.addEventListener('click', function(){ sb.classList.toggle('is-open'); });
  }
  document.addEventListener('click', function(e){
    if (window.innerWidth > 860) return;
    if (!sb || !sb.classList.contains('is-open')) return;
    if (sb.contains(e.target) || (toggle && toggle.contains(e.target))) return;
    sb.classList.remove('is-open');
  });
}

document.addEventListener('DOMContentLoaded', mountLayout);

/* ================================================================
   Descarga XLSX
   ================================================================ */
function _doDownloadXLSX(filename, headers, rows) {
  var xlsxFn = filename.replace(/\.csv$/i, '.xlsx');
  var wsData = [headers].concat(rows.map(function(r){
    return r.map(function(v){ return (v === '' || v === null || v === undefined) ? null : v; });
  }));
  var ws = XLSX.utils.aoa_to_sheet(wsData);
  var colWidths = headers.map(function(h, ci){
    var max = String(h).length;
    rows.forEach(function(r){ var s = String(r[ci] || ''); if(s.length > max) max = s.length; });
    return { wch: Math.min(max + 2, 40) };
  });
  ws['!cols'] = colWidths;
  var wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, ws, 'Datos');
  XLSX.writeFile(wb, xlsxFn);
}

function downloadCSV(filename, headers, rows) {
  if (typeof XLSX !== 'undefined') {
    _doDownloadXLSX(filename, headers, rows);
  } else {
    var s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js';
    s.onload = function(){ _doDownloadXLSX(filename, headers, rows); };
    document.head.appendChild(s);
  }
}

function dlBtn(anchorSel, filename, getFn) {
  var anchor = typeof anchorSel === 'string'
    ? document.querySelector(anchorSel) : anchorSel;
  if (!anchor) return;

  var btn = document.createElement('button');
  btn.className = 'eg-dl-btn';
  btn.title     = 'Descargar datos (Excel .xlsx)';
  btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"'
    + ' fill="none" stroke="currentColor" stroke-width="2.2"'
    + ' stroke-linecap="round" stroke-linejoin="round">'
    + '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
    + '<polyline points="7 10 12 15 17 10"/>'
    + '<line x1="12" y1="15" x2="12" y2="3"/></svg>'
    + ' <span>Descargar</span>';
  btn.addEventListener('click', function(){
    var d = getFn();
    downloadCSV(filename, d.headers, d.rows);
  });

  var CARD = ['chart-card','tc-chart-card','res-card','intl-chart-card',
              'eg-card','eg-chart-card','rofex-card'];
  var card = null;
  var node = anchor.parentElement;
  while (node && node !== document.body) {
    var cls = (node.className && typeof node.className === 'string') ? node.className : '';
    if (CARD.some(function(c){ return cls.indexOf(c) >= 0; })) { card = node; break; }
    node = node.parentElement;
  }

  var titleEl = card
    ? (card.querySelector('h3')
       || card.querySelector('.res-title')
       || card.querySelector('.intl-chart-card__title'))
    : null;

  if (titleEl) {
    if (titleEl.parentNode && titleEl.parentNode.dataset && titleEl.parentNode.dataset.dlRow) {
      titleEl.parentNode.appendChild(btn);
      return;
    }
    var row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:4px';
    row.dataset.dlRow = '1';
    titleEl.parentNode.insertBefore(row, titleEl);
    row.appendChild(titleEl);
    titleEl.style.margin = '0';
    row.appendChild(btn);
  } else if (anchor.tagName === 'CANVAS' || anchor.tagName === 'TABLE') {
    anchor.parentNode.insertBefore(btn, anchor);
  } else {
    anchor.appendChild(btn);
  }
}

window.EcoGo = { SECTIONS: SECTIONS, icon: icon, resolve: resolve, mountLayout: mountLayout,
                 downloadCSV: downloadCSV, dlBtn: dlBtn };
