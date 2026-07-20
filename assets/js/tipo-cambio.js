/* ============================================================
   ECO GO — Tipo de Cambio · TCR + Rofex
   ============================================================ */
(function(){
  const D = window.TC_DATA;
  if (!D) { console.error("TC_DATA no disponible"); return; }

  const TEAL_DARK='#1B5F5E', TEAL='#3C9794', TEAL_LITE='#8FCCCA';
  const RED='#DA4531', ORANGE='#FE8B5F', GREEN='#89C442', CHARCOAL='#333333';
  const GRAY = '#A8B0B1', PURPLE='#7E5CCB', BLUE_COLOR='#3A82C4';

  /* Helpers */
  function fmtMoney(v, dec){
    dec = (dec===undefined) ? 1 : dec;
    if (v === null || v === undefined || isNaN(v)) return '—';
    return '$' + Number(v).toLocaleString('es-AR', {minimumFractionDigits:dec, maximumFractionDigits:dec});
  }
  function fmtNum(v, dec){
    dec = (dec===undefined) ? 0 : dec;
    if (v === null || v === undefined || isNaN(v)) return '—';
    return Number(v).toLocaleString('es-AR', {minimumFractionDigits:dec, maximumFractionDigits:dec});
  }
  function fmtPct(v, dec){
    dec = (dec===undefined) ? 2 : dec;
    if (v === null || v === undefined || isNaN(v)) return '—';
    return (v*100).toFixed(dec).replace('.', ',') + '%';
  }
  function fmtMes(iso){
    if (!iso) return '';
    const MESES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
    const m = String(iso).match(/^(\d{4})-(\d{2})/);
    if (m) return MESES[+m[2]-1] + '-' + String(m[1]).slice(2);
    return iso;
  }
  function fmtDateLong(iso){
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleDateString('es-AR', {day:'2-digit', month:'long', year:'numeric'});
  }

  /* Tabs */
  function setupTabs(){
    const nav = document.getElementById('tcTabsNav');
    nav.addEventListener('click', function(e){
      const btn = e.target.closest('.eg-tabs__btn'); if (!btn) return;
      const tab = btn.dataset.tab;
      nav.querySelectorAll('.eg-tabs__btn').forEach(function(b){ b.classList.toggle('is-active', b === btn); });
      document.querySelectorAll('.eg-tab-panel').forEach(function(p){ p.hidden = (p.id !== 'panel-' + tab); });
    });
  }

  function setupLastUpdate(){
    const withData = D.tcn_series.filter(function(p){ return p.oficial !== null && p.oficial !== undefined; });
    if (!withData.length) return;
    const last = withData[withData.length-1];
    document.getElementById('tcLastUpdate').textContent = 'Último: ' + fmtDateLong(last.fecha);
  }

  /* ===== KPIs lateral ===== */
  function renderKpis(){
    const withData = D.tcn_series.filter(function(p){ return p.oficial !== null; });
    const last = withData[withData.length-1] || {};
    const html =
      '<div class="tc-kpi"><div class="tc-kpi__label">TCN Oficial</div>' +
        '<div class="tc-kpi__value">' + fmtMoney(last.oficial, 2) + '</div>' +
        '<div class="tc-kpi__sub">' + fmtDateLong(last.fecha) + '</div></div>' +
      '<div class="tc-kpi"><div class="tc-kpi__label">CCL</div>' +
        '<div class="tc-kpi__value">' + fmtMoney(last.ccl, 2) + '</div>' +
        '<div class="tc-kpi__sub">Brecha CCL/Oficial: ' +
        (last.oficial && last.ccl ? ((last.ccl/last.oficial - 1)*100).toFixed(1).replace('.', ',') + '%' : '—') +
        '</div></div>' +
      '<div class="tc-kpi"><div class="tc-kpi__label">Banda superior actual</div>' +
        '<div class="tc-kpi__value">' + fmtMoney(last.banda_sup, 2) + '</div>' +
        '<div class="tc-kpi__sub">Distancia: ' +
        (last.banda_sup && last.oficial ? ((last.oficial/last.banda_sup - 1)*100).toFixed(1).replace('.', ',') + '%' : '—') +
        '</div></div>';
    document.getElementById('tcKpis').innerHTML = html;
  }

  /* ===== Chart TCR (Gráfico def) ===== */
  function buildChartTCRDef(){
    Chart.defaults.font.family = "'HK Grotesk', system-ui, sans-serif";
    Chart.defaults.color = CHARCOAL;

    const d = D.tcn_series;
    // Col F = banda_inf (Banda inferior), Col G = banda_sup (Banda superior)
    // Sin Rofex hoy ni Rofex oct-24
    const SERIES = [
      { key:'oficial',   label:'Oficial',         color: TEAL_DARK,  width: 2.5, dash: null },
      { key:'ccl',       label:'CCL',             color: ORANGE,     width: 2,   dash: null },
      { key:'banda_inf', label:'Banda inferior',  color: GREEN,      width: 2,   dash: [6,4] },
      { key:'banda_sup', label:'Banda superior',  color: RED,        width: 2,   dash: [6,4] }
    ];

    new Chart(document.getElementById('chartTCRDef'), {
      data: {
        labels: d.map(function(p){ return p.fecha; }),
        datasets: SERIES.map(function(s){
          return {
            type:'line', label: s.label,
            data: d.map(function(p){ return p[s.key]; }),
            borderColor: s.color, backgroundColor: s.color,
            borderWidth: s.width, borderDash: s.dash || [],
            tension: .15, pointRadius: 0, spanGaps: true
          };
        })
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode:'index', intersect: false },
        plugins: {
          legend: { position:'bottom', labels:{ usePointStyle:true, padding:14, boxWidth:8, boxHeight:8 } },
          tooltip: {
            callbacks: {
              title: function(items){
                if (!items.length) return '';
                const dt = new Date(items[0].parsed.x);
                return dt.toLocaleDateString('es-AR', {day:'2-digit', month:'short', year:'numeric'});
              },
              label: function(c){ return c.dataset.label + ': ' + fmtMoney(c.parsed.y, 2); }
            }
          }
        },
        scales: {
          x: { type:'time', time:{ unit:'month', displayFormats:{month:'MMM yy'} },
               ticks:{ color:'#6E7679', maxTicksLimit:14, autoSkip:true },
               grid:{ color:'rgba(0,0,0,0.04)' } },
          y: { ticks:{ color:'#6E7679', callback:function(v){ return '$' + fmtNum(v, 0); } },
               grid:{ color:'rgba(0,0,0,0.06)' } }
        }
      }
    });
  }

  /* ===== Modales — helper genérico ===== */
  function buildLongSeriesChart(canvasId, seriesLabel, color, longData, keyValor, logarithmic){
    const d = longData.filter(function(p){ return p[keyValor] !== null && p[keyValor] !== undefined; });
    return new Chart(document.getElementById(canvasId), {
      data: {
        labels: d.map(function(p){ return p.fecha; }),
        datasets: [{
          type:'line', label: seriesLabel,
          data: d.map(function(p){ return p[keyValor]; }),
          borderColor: color, backgroundColor: color + '22',
          borderWidth: 2, tension:.15, pointRadius:0, fill:'origin', spanGaps:true
        }]
      },
      options: {
        responsive:true, maintainAspectRatio:false,
        interaction:{ mode:'index', intersect:false },
        plugins:{
          legend:{ display:false },
          tooltip:{
            callbacks:{
              title: function(items){
                if (!items.length) return '';
                const dt = new Date(items[0].parsed.x);
                return dt.toLocaleDateString('es-AR', {day:'2-digit', month:'short', year:'numeric'});
              },
              label: function(c){ return seriesLabel + ': ' + fmtMoney(c.parsed.y, 2); }
            }
          }
        },
        scales:{
          x:{ type:'time', time:{ unit:'year', displayFormats:{year:'yyyy'} },
              ticks:{ color:'#6E7679', maxTicksLimit:14, autoSkip:true },
              grid:{ color:'rgba(0,0,0,0.04)' } },
          y:{ type: logarithmic ? 'logarithmic' : 'linear',
              ticks:{ color:'#6E7679', callback:function(v){ return '$' + fmtNum(v, 0); } },
              grid:{ color:'rgba(0,0,0,0.06)' } }
        }
      }
    });
  }

  /* ===== Modal serie TCN Oficial (com3500) ===== */
  var modalChart = null;
  function buildModalChart(){
    if (modalChart) return;
    const longSeries = (D.tcn_long && D.tcn_long.length) ? D.tcn_long : D.tcn_series;
    modalChart = buildLongSeriesChart('chartTCNonly', 'TCN A3500 (Mayorista BCRA)', TEAL_DARK, longSeries, 'oficial', true);
  }

  /* ===== Modal serie CCL ===== */
  var cclChart = null;
  function buildCclModal(){
    if (cclChart) return;
    const series = (D.ccl_long && D.ccl_long.length) ? D.ccl_long : D.tcn_series.map(function(p){ return {fecha:p.fecha, valor:p.ccl}; });
    cclChart = buildLongSeriesChart('chartCCLonly', 'CCL (Copia de Blue)', ORANGE, series, 'valor', false);
  }

  /* ===== Modal serie Blue ===== */
  var blueChart = null;
  function buildBlueModal(){
    if (blueChart) return;
    if (!D.blue_long || !D.blue_long.length) return;
    blueChart = buildLongSeriesChart('chartBlueonly', 'Dólar Blue', BLUE_COLOR, D.blue_long, 'valor', false);
  }

  /* ===== Modal serie MEP ===== */
  var mepChart = null;
  function buildMepModal(){
    if (mepChart) return;
    if (!D.mep_long || !D.mep_long.length) return;
    mepChart = buildLongSeriesChart('chartMEPonly', 'Dólar MEP', PURPLE, D.mep_long, 'valor', false);
  }

  /* ===== Setup modales ===== */
  function setupModal(){
    // TCN
    var modal = document.getElementById('tcnModal');
    document.getElementById('btnVerTCN').addEventListener('click', function(){
      modal.classList.add('is-open'); buildModalChart();
    });
    document.getElementById('tcnModalClose').addEventListener('click', function(){ modal.classList.remove('is-open'); });
    modal.addEventListener('click', function(e){ if (e.target === modal) modal.classList.remove('is-open'); });

    // CCL
    var modalCCL = document.getElementById('cclModal');
    document.getElementById('btnVerCCL').addEventListener('click', function(){
      modalCCL.classList.add('is-open'); buildCclModal();
    });
    document.getElementById('cclModalClose').addEventListener('click', function(){ modalCCL.classList.remove('is-open'); });
    modalCCL.addEventListener('click', function(e){ if (e.target === modalCCL) modalCCL.classList.remove('is-open'); });

    // Blue
    var modalBlue = document.getElementById('blueModal');
    document.getElementById('btnVerBlue').addEventListener('click', function(){
      modalBlue.classList.add('is-open'); buildBlueModal();
    });
    document.getElementById('blueModalClose').addEventListener('click', function(){ modalBlue.classList.remove('is-open'); });
    modalBlue.addEventListener('click', function(e){ if (e.target === modalBlue) modalBlue.classList.remove('is-open'); });

    // MEP
    var modalMEP = document.getElementById('mepModal');
    document.getElementById('btnVerMEP').addEventListener('click', function(){
      modalMEP.classList.add('is-open'); buildMepModal();
    });
    document.getElementById('mepModalClose').addEventListener('click', function(){ modalMEP.classList.remove('is-open'); });
    modalMEP.addEventListener('click', function(e){ if (e.target === modalMEP) modalMEP.classList.remove('is-open'); });

    // Cerrar todos con Escape
    document.addEventListener('keydown', function(e){
      if (e.key === 'Escape'){
        ['tcnModal','cclModal','blueModal','mepModal'].forEach(function(id){
          var m = document.getElementById(id);
          if (m) m.classList.remove('is-open');
        });
      }
    });
  }

  /* ===== Rofex picker ===== */
  function setupRofex(){
    const picker = document.getElementById('rofexPicker');
    picker.addEventListener('click', function(e){
      const btn = e.target.closest('button'); if (!btn) return;
      picker.querySelectorAll('button').forEach(function(b){ b.classList.toggle('is-active', b === btn); });
      renderRofex(btn.dataset.id);
    });
    renderRofex('nominal');
  }

  function renderRofex(id){
    const block = D.rofex[id];
    if (!block) return;

    document.getElementById('rofexTitle').textContent = 'Monitor Rofex · ' + block.label;
    var sub = 'Curva de futuros · valores por contrato (mes de cierre)';
    if (block.fmt === 'pct') sub = 'TNA implícita o variación mensual por contrato';
    if (block.fmt === 'int') sub = 'Interés abierto · cantidad de contratos';
    document.getElementById('rofexSub').textContent = sub;

    const fmt = block.fmt;
    function f(v){
      if (v === null || v === undefined) return '—';
      if (fmt === 'pct')   return fmtPct(v, 2);
      if (fmt === 'int')   return fmtNum(v, 0);
      return fmtNum(v, 2);
    }

    var html = '<thead><tr><th>Fecha cotización</th>';
    block.meses.forEach(function(m){
      html += '<th class="num">' + fmtMes(m) + '</th>';
    });
    html += '</tr></thead><tbody>';

    block.filas.forEach(function(f_row){
      html += '<tr><td>' + fmtDateLong(f_row.fecha) + '</td>';
      f_row.valores.forEach(function(v){
        html += '<td class="num">' + f(v) + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody>';
    document.getElementById('rofexTable').innerHTML = html;
  }


  function setupDownloads() {
    var D = window.TC_DATA;
    if (!D || !window.EcoGo) return;
    EcoGo.dlBtn('#chartTCRDef', 'tipo_cambio_series.csv', function(){
      return {
        headers: ['Fecha','TCN Oficial','CCL','Banda Inf.','Banda Sup.'],
        rows: (D.tcn_series||[]).map(function(r){
          return [r.fecha, r.oficial, r.ccl, r.banda_inf, r.banda_sup];
        })
      };
    });
    EcoGo.dlBtn('#chartTCNonly', 'tcn_historico.csv', function(){
      return {
        headers: ['Fecha','TCN Mayorista'],
        rows: (D.tcn_long||[]).map(function(r){ return [r.fecha, r.oficial]; })
      };
    });
    EcoGo.dlBtn('#chartCCLonly', 'ccl_historico.csv', function(){
      return {
        headers: ['Fecha','CCL'],
        rows: (D.ccl_long||[]).map(function(r){ return [r.fecha, r.valor]; })
      };
    });
    EcoGo.dlBtn('#chartBlueonly', 'blue_historico.csv', function(){
      return {
        headers: ['Fecha','Dolar Blue'],
        rows: (D.blue_long||[]).map(function(r){ return [r.fecha, r.valor]; })
      };
    });
    EcoGo.dlBtn('#chartMEPonly', 'mep_historico.csv', function(){
      return {
        headers: ['Fecha','Dolar MEP'],
        rows: (D.mep_long||[]).map(function(r){ return [r.fecha, r.valor]; })
      };
    });
  }

  /* Boot */
  document.addEventListener('DOMContentLoaded', function(){
    setupTabs();
    setupLastUpdate();
    renderKpis();
    buildChartTCRDef();
    setupModal();
    setupRofex();
    setupDownloads();
  });
})();
