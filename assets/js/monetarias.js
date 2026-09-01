/* ============================================================
   ECO GO — Página Monetarias · Gráficos y KPIs
   ============================================================ */
(function(){
  const D = window.MONETARIAS_DATA;
  if (!D) { console.error("MONETARIAS_DATA no disponible"); return; }

  // Paleta Eco Go
  const TEAL_DARK = '#1B5F5E';
  const TEAL      = '#3C9794';
  const TEAL_LITE = '#8FCCCA';
  const RED       = '#DA4531';
  const ORANGE    = '#FE8B5F';
  const GREEN     = '#89C442';
  const CHARCOAL  = '#333333';
  const GRAY      = '#B8BEC0';

  const AGREGADOS_ORDER  = ['Circulante', 'M0', 'M1', 'M2', 'M3'];
  const AGREGADOS_COLORS = { 'Circulante': TEAL_LITE, 'M0': TEAL, 'M1': ORANGE, 'M2': RED, 'M3': TEAL_DARK };

  const PRESTAMOS_ORDER  = ['Empresas', 'Garantía real', 'Consumo', 'Tarjeta de crédito', 'Otros'];
  const PRESTAMOS_COLORS = {
    'Empresas': TEAL_DARK, 'Garantía real': TEAL,
    'Consumo': ORANGE, 'Tarjeta de crédito': ORANGE, 'Otros': GRAY
  };

  const MONET_TOTAL_ORDER  = ['Circulante', 'Depósitos a la vista', 'Depósitos a plazo'];
  const MONET_TOTAL_COLORS = { 'Circulante': TEAL_LITE, 'Depósitos a la vista': TEAL, 'Depósitos a plazo': TEAL_DARK };

  const MONET_FX_ORDER  = ['Circulante', 'Depósitos en pesos', 'Depósitos en dólares'];
  const MONET_FX_COLORS = { 'Circulante': TEAL_LITE, 'Depósitos en pesos': TEAL, 'Depósitos en dólares': ORANGE };

  const MESES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
  const MESES_LONG = ['enero','febrero','marzo','abril','mayo','junio',
                       'julio','agosto','septiembre','octubre','noviembre','diciembre'];

  function fmtPct(v, digits) {
    digits = (digits === undefined) ? 1 : digits;
    if (v === null || v === undefined || isNaN(v)) return '—';
    return (v*100).toFixed(digits).replace('.', ',') + '%';
  }
  function fmtNum(v, digits) {
    digits = (digits === undefined) ? 1 : digits;
    if (v === null || v === undefined || isNaN(v)) return '—';
    return v.toFixed(digits).replace('.', ',');
  }
  function fmtMonthShort(iso){
    if (!iso) return '';
    var m = String(iso).match(/^(\d{4})-(\d{2})/);
    return m ? MESES[+m[2]-1] + '-' + String(m[1]).slice(2) : iso;
  }
  function fmtMonthLong(iso){
    if (!iso) return '';
    var m = String(iso).match(/^(\d{4})-(\d{2})/);
    return m ? MESES_LONG[+m[2]-1] + ' ' + m[1] : iso;
  }

  /* ---------- Chart.js defaults + helpers de eje ---------- */
  function setupChart(){
    Chart.defaults.font.family = "'HK Grotesk', system-ui, sans-serif";
    Chart.defaults.color = CHARCOAL;
    Chart.defaults.borderColor = '#E2E8E8';
  }
  function timeAxis(){
    return {
      type:'time',
      time:{ unit:'month', tooltipFormat:'MMM yyyy', displayFormats:{ month:'MMM yyyy' } },
      ticks:{ color:'#6E7679', maxRotation:0, autoSkip:true, maxTicksLimit:12 },
      grid:{ color:'rgba(0,0,0,0.04)' }
    };
  }
  function pctAxis(opts){
    opts = opts || {};
    return Object.assign({
      ticks:{ color:'#6E7679', callback: function(v){ return (v*100).toFixed(0)+'%'; } },
      grid:{ color:'rgba(0,0,0,0.06)' }
    }, opts);
  }
  function numAxis(opts){
    opts = opts || {};
    return Object.assign({
      ticks:{ color:'#6E7679' },
      grid:{ color:'rgba(0,0,0,0.06)' }
    }, opts);
  }

  /* ---------- Tabs (Préstamos: Pesos / Dólares / Totales) ---------- */
  function setupTabs(){
    const nav = document.getElementById('prestamosTabsNav');
    if (!nav) return;
    nav.addEventListener('click', function(e){
      const btn = e.target.closest('.eg-tabs__btn');
      if (!btn) return;
      const tab = btn.dataset.tab;
      nav.querySelectorAll('.eg-tabs__btn').forEach(function(b){
        b.classList.toggle('is-active', b === btn);
      });
      document.querySelectorAll('#panelPrestamos .eg-tab-panel').forEach(function(p){
        p.hidden = (p.id !== 'panel-prestamos-' + tab);
      });
    });
  }

  /* ---------- KPIs ---------- */
  function renderKpis(){
    const ag = D.agregados;
    const nAg = ag.dates.length;
    const lastPib = function(key){ return ag.pib[key] ? ag.pib[key][nAg-1] : null; };

    document.getElementById('ultimoMesTag').textContent = 'Último dato: ' + fmtMonthLong(ag.dates[nAg-1]);

    let prestamosSub = '—';
    let prestamosTotal = null;
    const tot = D.prestamos && D.prestamos.totales;
    if (tot && tot.dates.length) {
      const nT = tot.dates.length;
      prestamosTotal = 0;
      Object.keys(tot.series).forEach(function(k){
        const v = tot.series[k][nT-1];
        if (typeof v === 'number') prestamosTotal += v;
      });
      prestamosSub = 'Empresas + consumo + hipotecarios + otros · ' + fmtMonthShort(tot.dates[nT-1]);
    }

    const stats = [
      { val: fmtPct(lastPib('M3')), label:'M3 (agregado más amplio)', sub:'% del PIB · s.e.', featured:true },
      { val: fmtPct(lastPib('M2')), label:'M2 privado', sub:'% del PIB · s.e.', featured:false },
      { val: fmtPct(lastPib('Circulante')), label:'Circulante', sub:'% del PIB · s.e.', featured:false },
      { val: prestamosTotal !== null ? fmtPct(prestamosTotal) : '—', label:'Préstamos privados totales', sub: prestamosSub, featured:false }
    ];
    document.getElementById('kpiGrid').innerHTML = stats.map(function(s){
      const cls = 'eg-stat' + (s.featured ? ' is-featured' : '');
      return '<div class="' + cls + '">' +
        '<div class="eg-stat__value">' + s.val + '</div>' +
        '<div class="eg-stat__label">' + s.label + '</div>' +
        '<div class="eg-stat__sub">' + s.sub + '</div>' +
      '</div>';
    }).join('');
  }

  /* ---------- Helpers para armar datasets multi-serie ---------- */
  function orderedKeys(order, series){
    const present = order.filter(function(k){ return series[k]; });
    Object.keys(series).forEach(function(k){ if (present.indexOf(k) < 0) present.push(k); });
    return present;
  }

  function lineDatasets(block, order, colors, opts){
    opts = opts || {};
    const keys = orderedKeys(order, block.series);
    return keys.map(function(k){
      return {
        label: k, data: block.series[k],
        borderColor: colors[k] || GRAY, backgroundColor: colors[k] || GRAY,
        borderWidth: opts.bold && opts.bold === k ? 3 : 2,
        tension: .3, pointRadius: 0, fill: false
      };
    });
  }

  function stackedAreaDatasets(block, order, colors){
    const keys = orderedKeys(order, block.series);
    return keys.map(function(k){
      const c = colors[k] || GRAY;
      return {
        label: k, data: block.series[k],
        borderColor: c, backgroundColor: c + '55',
        borderWidth: 1.5, tension: .25, pointRadius: 0, fill: true, stack: 'total'
      };
    });
  }

  function tooltipPct(c){ return c.dataset.label + ': ' + fmtPct(c.parsed.y, 2); }
  function tooltipNum(c){ return c.dataset.label + ': ' + fmtNum(c.parsed.y, 1); }
  function tooltipFooterTotal(items){ var s = items.reduce(function(acc,i){ return acc + i.parsed.y; }, 0); return 'Total: ' + fmtPct(s, 2); }

  /* ---------- Agregados monetarios ---------- */
  function buildAgregados(){
    const ag = D.agregados;
    if (!ag || !ag.dates.length) return;
    new Chart(document.getElementById('chartAgregadosNiveles'), {
      type:'line',
      data:{ labels: ag.dates, datasets: lineDatasets({series: ag.niveles}, AGREGADOS_ORDER, AGREGADOS_COLORS, {bold:'M3'}) },
      options:{
        responsive:true, maintainAspectRatio:false,
        interaction:{ mode:'index', intersect:false },
        plugins:{
          legend:{ position:'bottom', labels:{ usePointStyle:true, padding:12 } },
          tooltip:{ callbacks:{ label: tooltipNum } }
        },
        scales:{ x: timeAxis(), y: numAxis({ title:{ display:true, text:'Billones de pesos de hoy' } }) }
      }
    });

    new Chart(document.getElementById('chartAgregadosPib'), {
      type:'line',
      data:{ labels: ag.dates, datasets: lineDatasets({series: ag.pib}, AGREGADOS_ORDER, AGREGADOS_COLORS, {bold:'M3'}) },
      options:{
        responsive:true, maintainAspectRatio:false,
        interaction:{ mode:'index', intersect:false },
        plugins:{
          legend:{ position:'bottom', labels:{ usePointStyle:true, padding:12 } },
          tooltip:{ callbacks:{ label: tooltipPct } }
        },
        scales:{ x: timeAxis(), y: pctAxis({ title:{ display:true, text:'% del PIB' } }) }
      }
    });
  }

  /* ---------- Préstamos al sector privado ---------- */
  function buildPrestamos(){
    const p = D.prestamos;
    if (!p) return;
    const map = { pesos:'chartPrestamosPesos', dolares:'chartPrestamosDolares', totales:'chartPrestamosTotales' };
    Object.keys(map).forEach(function(key){
      const block = p[key];
      const el = document.getElementById(map[key]);
      if (!block || !block.dates.length || !el) return;
      new Chart(el, {
        type:'line',
        data:{ labels: block.dates, datasets: stackedAreaDatasets(block, PRESTAMOS_ORDER, PRESTAMOS_COLORS) },
        options:{
          responsive:true, maintainAspectRatio:false,
          interaction:{ mode:'index', intersect:false },
          plugins:{
            legend:{ position:'bottom', labels:{ usePointStyle:true, padding:12 } },
            tooltip:{ callbacks:{ label: tooltipPct, footer: tooltipFooterTotal } }
          },
          scales:{
            x: timeAxis(),
            y: pctAxis({ stacked:true, title:{ display:true, text:'% del PIB' } })
          }
        }
      });
    });
  }

  /* ---------- Monetización de la economía ---------- */
  function buildMonetizacion(){
    const m = D.monetizacion;
    if (!m) return;
    if (m.total && m.total.dates.length) {
      new Chart(document.getElementById('chartMonetizacionTotal'), {
        type:'line',
        data:{ labels: m.total.dates, datasets: stackedAreaDatasets(m.total, MONET_TOTAL_ORDER, MONET_TOTAL_COLORS) },
        options:{
          responsive:true, maintainAspectRatio:false,
          interaction:{ mode:'index', intersect:false },
          plugins:{
            legend:{ position:'bottom', labels:{ usePointStyle:true, padding:12 } },
            tooltip:{ callbacks:{ label: tooltipPct, footer: tooltipFooterTotal } }
          },
          scales:{ x: timeAxis(), y: pctAxis({ stacked:true, title:{ display:true, text:'% del PIB' } }) }
        }
      });
    }
    if (m.pesos_dolares && m.pesos_dolares.dates.length) {
      new Chart(document.getElementById('chartMonetizacionFX'), {
        type:'line',
        data:{ labels: m.pesos_dolares.dates, datasets: stackedAreaDatasets(m.pesos_dolares, MONET_FX_ORDER, MONET_FX_COLORS) },
        options:{
          responsive:true, maintainAspectRatio:false,
          interaction:{ mode:'index', intersect:false },
          plugins:{
            legend:{ position:'bottom', labels:{ usePointStyle:true, padding:12 } },
            tooltip:{ callbacks:{ label: tooltipPct, footer: tooltipFooterTotal } }
          },
          scales:{ x: timeAxis(), y: pctAxis({ stacked:true, title:{ display:true, text:'% del PIB' } }) }
        }
      });
    }
  }

  /* ---------- Descargas CSV ---------- */
  function setupDownloads(){
    if (!window.EcoGo) return;
    const pct = function(v){ return (v !== null && v !== undefined && !isNaN(v)) ? +(v*100).toFixed(2) : ''; };
    const num = function(v){ return (v !== null && v !== undefined && !isNaN(v)) ? +v.toFixed(2) : ''; };

    function dlBlock(anchorSel, filename, block, order, valFmt){
      EcoGo.dlBtn(anchorSel, filename, function(){
        const keys = orderedKeys(order, block.series);
        return {
          headers: ['Fecha'].concat(keys),
          rows: block.dates.map(function(d, i){
            return [d].concat(keys.map(function(k){ return valFmt(block.series[k][i]); }));
          })
        };
      });
    }

    if (D.agregados) {
      dlBlock('#chartAgregadosNiveles', 'monetarias_agregados_niveles.csv', {dates:D.agregados.dates, series:D.agregados.niveles}, AGREGADOS_ORDER, num);
      dlBlock('#chartAgregadosPib', 'monetarias_agregados_pib.csv', {dates:D.agregados.dates, series:D.agregados.pib}, AGREGADOS_ORDER, pct);
    }
    if (D.prestamos) {
      if (D.prestamos.pesos) dlBlock('#chartPrestamosPesos', 'monetarias_prestamos_pesos.csv', D.prestamos.pesos, PRESTAMOS_ORDER, pct);
      if (D.prestamos.dolares) dlBlock('#chartPrestamosDolares', 'monetarias_prestamos_dolares.csv', D.prestamos.dolares, PRESTAMOS_ORDER, pct);
      if (D.prestamos.totales) dlBlock('#chartPrestamosTotales', 'monetarias_prestamos_totales.csv', D.prestamos.totales, PRESTAMOS_ORDER, pct);
    }
    if (D.monetizacion) {
      if (D.monetizacion.total) dlBlock('#chartMonetizacionTotal', 'monetarias_monetizacion_total.csv', D.monetizacion.total, MONET_TOTAL_ORDER, pct);
      if (D.monetizacion.pesos_dolares) dlBlock('#chartMonetizacionFX', 'monetarias_monetizacion_pesos_dolares.csv', D.monetizacion.pesos_dolares, MONET_FX_ORDER, pct);
    }
  }

  document.addEventListener('DOMContentLoaded', function(){
    setupChart();
    setupTabs();
    renderKpis();
    buildAgregados();
    buildPrestamos();
    buildMonetizacion();
    setupDownloads();
  });
})();
