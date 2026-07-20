/* ============================================================
   ECO GO — Empleo
   ============================================================ */
(function(){
  const D = window.EMPLEO_DATA;
  if (!D) { console.error("EMPLEO_DATA no disponible"); return; }

  const TEAL_DARK='#1B5F5E', TEAL='#3C9794', TEAL_LITE='#8FCCCA';
  const RED='#DA4531', ORANGE='#FE8B5F', GREEN='#89C442', CHARCOAL='#333333';
  const PURPLE='#7E5CCB', BROWN='#8C7456';

  function fmtPct(v, d){ d=d===undefined?1:d; if(v===null||v===undefined||isNaN(v)) return '—'; return v.toFixed(d).replace('.', ',') + '%'; }
  function fmtNum(v, d){ d=d===undefined?0:d; if(v===null||v===undefined||isNaN(v)) return '—'; return Number(v).toLocaleString('es-AR', {minimumFractionDigits:d, maximumFractionDigits:d}); }
  function fmtVarPct(v, d){ d=d===undefined?1:d; if(v===null||v===undefined||isNaN(v)) return '—'; const n=v*100; return (n>0?'+':'') + n.toFixed(d).replace('.', ',') + '%'; }
  function fmtVarNum(v, d){ d=d===undefined?1:d; if(v===null||v===undefined||isNaN(v)) return '—'; return (v>0?'+':'') + Number(v).toLocaleString('es-AR', {minimumFractionDigits:d, maximumFractionDigits:d}); }
  function norm(s){ return (s||'').toString().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]/g, ''); }

  /* ---------- Tabs ---------- */
  function setupTabs(){
    const nav = document.getElementById('tabsNav');
    nav.addEventListener('click', function(e){
      const btn = e.target.closest('.eg-tabs__btn'); if (!btn) return;
      const tab = btn.dataset.tab;
      nav.querySelectorAll('.eg-tabs__btn').forEach(function(b){ b.classList.toggle('is-active', b === btn); });
      document.querySelectorAll('.eg-tab-panel').forEach(function(p){ p.hidden = (p.id !== 'panel-' + tab); });
    });
  }

  /* ---------- Hero ---------- */
  function renderHero(){
    const last = D.eph_ultimo || (D.eph && D.eph[D.eph.length-1]);
    if (!last) return;
    document.getElementById('ultimoTag').textContent = 'Último dato: ' + last.label;
    document.getElementById('ephHero').innerHTML =
      '<div><div class="eph-hero__title">Último cuatrimestre</div>' +
      '<div class="eph-hero__period">' + last.label + '</div>' +
      '<div class="eph-hero__sub">Total aglomerados · EPH INDEC</div></div>' +
      '<div class="eph-hero__stat"><div class="eph-hero__stat-label">Actividad</div><div class="eph-hero__stat-value">' + fmtPct(last.actividad) + '</div></div>' +
      '<div class="eph-hero__stat"><div class="eph-hero__stat-label">Empleo</div><div class="eph-hero__stat-value">' + fmtPct(last.empleo) + '</div></div>' +
      '<div class="eph-hero__stat"><div class="eph-hero__stat-label">Desocupación</div><div class="eph-hero__stat-value">' + fmtPct(last.desocup) + '</div></div>' +
      '<div class="eph-hero__stat"><div class="eph-hero__stat-label">Subocupación</div><div class="eph-hero__stat-value">' + fmtPct(last.subocup) + '</div></div>';
  }

  /* ---------- Modal histórico ---------- */
  const SERIES_DEF = [
    { key:'actividad',     label:'Actividad',                color: TEAL_DARK },
    { key:'empleo',        label:'Empleo',                   color: TEAL },
    { key:'desocup',       label:'Desocupación',             color: RED },
    { key:'ocup_dem',      label:'Ocupada Demandante',       color: ORANGE },
    { key:'subocup',       label:'Subocupación',             color: GREEN },
    { key:'subocup_dem',   label:'Subocup. Demandante',      color: PURPLE },
    { key:'subocup_nodem', label:'Subocup. No Demandante',   color: BROWN }
  ];

  function setupHistoricoModal(){
    const modal = document.getElementById('ephModal');
    document.getElementById('btnHistorico').addEventListener('click', function(){
      modal.classList.add('is-open');
      buildEPHChart();
    });
    document.getElementById('ephModalClose').addEventListener('click', function(){ modal.classList.remove('is-open'); });
    modal.addEventListener('click', function(e){ if (e.target === modal) modal.classList.remove('is-open'); });
    document.addEventListener('keydown', function(e){ if (e.key === 'Escape') modal.classList.remove('is-open'); });

    const years = Array.from(new Set(D.eph.map(function(p){ return new Date(p.fecha).getUTCFullYear(); }))).sort();
    const selFrom = document.getElementById('ephFrom');
    const selTo   = document.getElementById('ephTo');
    selFrom.innerHTML = years.map(function(y){ return '<option value="'+y+'">'+y+'</option>'; }).join('');
    selTo.innerHTML   = years.map(function(y){ return '<option value="'+y+'">'+y+'</option>'; }).join('');
    selFrom.value = years[0];
    selTo.value   = years[years.length-1];
    selFrom.addEventListener('change', updateChart);
    selTo.addEventListener('change',   updateChart);
    document.querySelectorAll('.eph-range__quick button').forEach(function(b){
      b.addEventListener('click', function(){
        document.querySelectorAll('.eph-range__quick button').forEach(function(x){ x.classList.remove('is-active'); });
        b.classList.add('is-active');
        const q = b.dataset.q;
        const maxY = years[years.length-1];
        if (q === 'all') selFrom.value = years[0];
        else selFrom.value = Math.max(years[0], maxY - parseInt(q, 10));
        selTo.value = maxY;
        updateChart();
      });
    });
  }

  function updateChart(){
    buildEPHChart();
  }

  // Renderiza la TABLA histórica EPH (más recientes arriba, en porcentajes)
  function buildEPHChart(){
    const fromY = parseInt(document.getElementById('ephFrom').value, 10) || 1991;
    const toY   = parseInt(document.getElementById('ephTo').value, 10) || 2030;
    const data = D.eph.filter(function(p){
      const y = new Date(p.fecha).getUTCFullYear();
      return y >= fromY && y <= toY;
    }).slice().reverse();  // más recientes arriba

    let html = '<thead><tr><th>Período</th>';
    SERIES_DEF.forEach(function(s){
      html += '<th class="num"><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + s.color + ';margin-right:6px;"></span>' + s.label + '</th>';
    });
    html += '</tr></thead><tbody>';
    data.forEach(function(p){
      html += '<tr><td><strong>' + p.label + '</strong></td>';
      SERIES_DEF.forEach(function(s){
        const v = p[s.key];
        html += '<td class="num">' + (v !== null && v !== undefined ? fmtPct(v, 1) : '—') + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody>';
    document.getElementById('tablaEPH').innerHTML = html;
  }

  /* ---------- Cuadro empleo trim ---------- */
  function buildTablaTrim(){
    const t = D.trim;
    let html = '<thead><tr><th>Categoría</th>';
    t.periodos.forEach(function(p){ html += '<th class="num">' + p + '</th>'; });
    html += '</tr></thead><tbody>';
    const sections = new Set(['Activos','Ocupados','Asalariados','No asalariados','Desocupados','Inactivos']);
    t.filas.forEach(function(f){
      const isSection = sections.has(f.categoria);
      const isIndent = !isSection && (f.categoria.startsWith('Con desc') || f.categoria.startsWith('Sin desc') ||
                       f.categoria === 'Patrón' || f.categoria === 'Cuenta propia' ||
                       f.categoria.indexOf('Cuenta propistas') >= 0 ||
                       f.categoria.indexOf('Trabajador familiar') >= 0 ||
                       f.categoria === 'Formal' || f.categoria === 'Informal');
      const cls = isSection ? ' class="is-section"' : (isIndent ? ' class="is-indent"' : '');
      html += '<tr' + cls + '><td>' + f.categoria + '</td>';
      f.valores.forEach(function(v){
        if (v === null || v === undefined) { html += '<td class="num">—</td>'; return; }
        html += '<td class="num">' + (typeof v === 'number' ? fmtNum(v, 0) : v) + '</td>';
      });
      html += '</tr>';
    });
    html += '</tbody>';
    document.getElementById('tablaTrim').innerHTML = html;
  }

  /* ---------- Cuadro SIPA ---------- */
  function buildTablaSIPA(){
    const s = D.sipa;
    let html = '<thead><tr><th>Categoría</th>';
    s.cols.forEach(function(c, i){
      const isFirstDiff = c.tipo === 'diff' && (i === 0 || s.cols[i-1].tipo !== 'diff');
      const cls = isFirstDiff ? ' class="num col-sep-left"' : ' class="num"';
      html += '<th' + cls + '><div>' + c.header + '</div>' +
        '<div style="font-weight:400;font-size:.62rem;opacity:.7;text-transform:none;">' + c.sub + '</div></th>';
    });
    html += '</tr></thead><tbody>';
    const sections = new Set(['Total registrado','PEA**','Sector Privado','Sector Público']);
    s.filas.forEach(function(f){
      const isSection = sections.has(f.categoria) || f.categoria.startsWith('Sector ');
      const isIndent = !isSection && (f.categoria.indexOf('Asalariados') >= 0 ||
                                       f.categoria.indexOf('Monotributo') >= 0 ||
                                       f.categoria.indexOf('Independiente') >= 0);
      const cls = isSection ? ' class="is-section"' : (isIndent ? ' class="is-indent"' : '');
      html += '<tr' + cls + '><td>' + f.categoria + '</td>';
      f.valores.forEach(function(v, i){
        const c = s.cols[i];
        const isFirstDiff = c.tipo === 'diff' && (i === 0 || s.cols[i-1].tipo !== 'diff');
        const sepCls = isFirstDiff ? ' col-sep-left' : '';
        if (v === null || v === undefined) { html += '<td class="num' + sepCls + '">—</td>'; return; }
        if (c.tipo === 'diff') {
          const dcls = v > 0 ? ' is-positive' : (v < 0 ? ' is-negative' : '');
          html += '<td class="num diff' + dcls + sepCls + '">' + fmtVarNum(v) + '</td>';
        } else {
          html += '<td class="num' + sepCls + '">' + (typeof v === 'number' ? fmtNum(v, 1) : v) + '</td>';
        }
      });
      html += '</tr>';
    });
    html += '</tbody>';
    document.getElementById('tablaSIPA').innerHTML = html;
  }

  /* ============================================================
     SALARIOS · G Sal real, Cuadro INDEC, G real 21
     ============================================================ */
  function fmtIso(iso){
    if (!iso) return '';
    const d = new Date(iso);
    const MESES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
    return MESES[d.getUTCMonth()] + '-' + String(d.getUTCFullYear()).slice(2);
  }
  function fmtIsoLong(iso){
    if (!iso) return '';
    const d = new Date(iso);
    const MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
    return MESES[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
  }

  function chartTooltipTitle(items){
    if (!items.length) return '';
    return fmtIsoLong(items[0].label || new Date(items[0].parsed.x).toISOString());
  }

  function buildChartSalReal(){
    const S = window.SALARIOS_DATA;
    if (!S || !S.sal_real) return;
    const d = S.sal_real;
    new Chart(document.getElementById('chartSalReal'), {
      data: {
        labels: d.map(function(p){ return p.fecha; }),
        datasets: [
          { type:'line', label:'Sector registrado privado', data: d.map(function(p){ return p.priv; }),
            borderColor: TEAL_DARK, backgroundColor: TEAL_DARK, borderWidth: 2.5, tension:.25, pointRadius:0, spanGaps:true },
          { type:'line', label:'Sector registrado público', data: d.map(function(p){ return p.pub; }),
            borderColor: TEAL, backgroundColor: TEAL, borderWidth: 2, tension:.25, pointRadius:0, spanGaps:true },
          { type:'line', label:'Sector no registrado', data: d.map(function(p){ return p.nor; }),
            borderColor: ORANGE, backgroundColor: ORANGE, borderWidth: 2, tension:.25, pointRadius:0, spanGaps:true },
          { type:'line', label:'Total', data: d.map(function(p){ return p.tot; }),
            borderColor: RED, backgroundColor: RED, borderWidth: 2, borderDash:[5,3], tension:.25, pointRadius:0, spanGaps:true }
        ]
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
                const MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
                return MESES[dt.getUTCMonth()] + ' ' + dt.getUTCFullYear();
              },
              label: function(c){ return c.dataset.label + ': ' + (c.parsed.y!=null ? c.parsed.y.toFixed(1) : '—'); }
            }
          }
        },
        scales: {
          x: { type:'time', time:{unit:'year', displayFormats:{year:'yyyy'}},
               ticks:{color:'#6E7679', maxTicksLimit:14, autoSkip:true}, grid:{color:'rgba(0,0,0,0.04)'} },
          y: { ticks:{color:'#6E7679'}, grid:{color:'rgba(0,0,0,0.06)'},
               title:{display:true, text:'Índice (oct-16 = 100)'} }
        }
      }
    });
  }

  function buildTablaSalIndec(){
    const S = window.SALARIOS_DATA;
    if (!S || !S.cuadro) return;
    const c = S.cuadro;

    // Título y fuente con fechas
    document.getElementById('cuadroSalTitulo').textContent =
      'Evolución de los salarios — al ' + fmtIsoLong(c.fecha_actual);
    document.getElementById('cuadroSalFuente').textContent =
      'Fuente: Eco Go en base a INDEC · datos al ' + fmtIso(c.fecha_actual) +
      ' (comparación nominal con ' + fmtIso(c.fecha_comparacion) + ')';

    let html = '<thead><tr><th>Categoría</th>';
    c.headers.forEach(function(h){ html += '<th class="num">' + h + '</th>'; });
    html += '</tr></thead><tbody>';

    const sections = new Set(['Sector registrado','Sector no registrado','Total']);
    c.filas.forEach(function(f){
      const isSection = sections.has(f.categoria);
      const isIndent = !isSection && (f.categoria === 'Privado' || f.categoria === 'Público');
      const cls = isSection ? ' class="is-section"' : (isIndent ? ' class="is-indent"' : '');
      html += '<tr' + cls + '><td>' + f.categoria + '</td>';
      f.valores.forEach(function(v, i){
        if (v === null || v === undefined) { html += '<td class="num">—</td>'; return; }
        // Las columnas 0 son el índice (valor absoluto), el resto son variaciones
        const isIndex = i === 0;
        if (isIndex) {
          html += '<td class="num">' + fmtNum(v, 2) + '</td>';
        } else {
          const dcls = v > 0 ? ' is-positive' : (v < 0 ? ' is-negative' : '');
          html += '<td class="num diff' + dcls + '">' + fmtVarPct(v, 2) + '</td>';
        }
      });
      html += '</tr>';
    });
    html += '</tbody>';
    document.getElementById('tablaSalIndec').innerHTML = html;
  }

  function buildChartReal21(){
    const S = window.SALARIOS_DATA;
    if (!S || !S.real_21) return;
    const d = S.real_21;
    const series = [
      { key:'sal_priv',     label:'Sal. Privado',              color: TEAL_DARK },
      { key:'sal_pub_nac',  label:'Sal. Público Nacional',     color: TEAL },
      { key:'sal_pub_prov', label:'Sal. Público Provincial',   color: TEAL_LITE },
      { key:'jub_min',      label:'Jubilación mínima c/bono',  color: ORANGE },
      { key:'jub_no_min',   label:'Jubilación no mínima',      color: RED },
      { key:'no_reg',       label:'No registrados',            color: PURPLE },
      { key:'auh',          label:'AUH',                       color: GREEN }
    ];
    new Chart(document.getElementById('chartReal21'), {
      data: {
        labels: d.map(function(p){ return p.fecha; }),
        datasets: series.map(function(s){
          return { type:'line', label: s.label, data: d.map(function(p){ return p[s.key]; }),
            borderColor: s.color, backgroundColor: s.color, borderWidth: 2, tension: .25, pointRadius: 0, spanGaps: true };
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
                const MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
                return MESES[dt.getUTCMonth()] + ' ' + dt.getUTCFullYear();
              },
              label: function(c){ return c.dataset.label + ': ' + (c.parsed.y!=null ? c.parsed.y.toFixed(1) : '—'); }
            }
          }
        },
        scales: {
          x: { type:'time', time:{unit:'year', displayFormats:{year:'yyyy'}},
               ticks:{color:'#6E7679', maxTicksLimit:8, autoSkip:true}, grid:{color:'rgba(0,0,0,0.04)'} },
          y: { ticks:{color:'#6E7679'}, grid:{color:'rgba(0,0,0,0.06)'},
               title:{display:true, text:'Índice (dic-21 = 100)'} }
        }
      }
    });
  }


  function setupDownloads() {
    var D = window.EMPLEO_DATA;
    if (!D || !window.EcoGo) return;

    EcoGo.dlBtn('#ephHero', 'empleo_EPH.csv', function(){
      return {
        headers: ['Periodo','Actividad (%)','Empleo (%)','Desocupacion (%)','Subocupacion (%)'],
        rows: (D.eph||[]).map(function(r){ return [r.label, r.actividad, r.empleo, r.desocup, r.subocup]; })
      };
    });

    EcoGo.dlBtn('#chartSalReal', 'salarios_reales.csv', function(){
      var sal = (window.SALARIOS_DATA || {}).sal_real || [];
      return {
        headers: ['Fecha','Priv (indice)','Pub (indice)','No reg (indice)','Total (indice)'],
        rows: sal.map(function(r){ return [r.fecha, r.priv, r.pub, r.nor, r.tot]; })
      };
    });

    EcoGo.dlBtn('#chartReal21', 'salarios_indice21.csv', function(){
      var sal = (window.SALARIOS_DATA || {}).sal_real || [];
      return {
        headers: ['Fecha','Salario real (indice base=100)'],
        rows: sal.map(function(r){ return [r.fecha, r.tot]; })
      };
    });
  }

  document.addEventListener('DOMContentLoaded', function(){
    setupTabs();
    renderHero();
    setupHistoricoModal();
    buildTablaTrim();
    buildTablaSIPA();
    buildChartSalReal();
    buildTablaSalIndec();
    buildChartReal21();
    setupDownloads();
  });
})();
