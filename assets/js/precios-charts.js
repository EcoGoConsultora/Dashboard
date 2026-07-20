/* ============================================================
   ECO GO — Página Precios · Gráficos, KPIs, Tabs y Filtros
   ============================================================ */
(function(){
  const D = window.PRECIOS_DATA;
  if (!D) { console.error("PRECIOS_DATA no disponible"); return; }

  // Paleta Eco Go
  const TEAL_DARK = '#1B5F5E';
  const TEAL      = '#3C9794';
  const TEAL_LITE = '#8FCCCA';
  const RED       = '#DA4531';
  const ORANGE    = '#FE8B5F';
  const GREEN     = '#89C442';
  const CHARCOAL  = '#333333';
  const GRAY      = '#B8BEC0';

  // Colores por categoría (paleta Eco Go)
  const CAT_COLORS = {
    'Bienes':       TEAL,
    'Servicios':    ORANGE,
    'Regulados':    RED,
    'Salarios':     GREEN,
    'Dólar':        TEAL_DARK,
    'Construcción': '#A5896C',
    'Mayorista':    TEAL_LITE,
    'Otros':        GRAY
  };

  const MESES_LONG = ['enero','febrero','marzo','abril','mayo','junio',
                      'julio','agosto','septiembre','octubre','noviembre','diciembre'];

  function fmtPct(v, digits) {
    digits = (digits === undefined) ? 1 : digits;
    if (v === null || v === undefined || isNaN(v)) return '—';
    return (v*100).toFixed(digits).replace('.', ',') + '%';
  }
  function fmtMonthLong(iso){
    if (!iso) return '';
    const d = new Date(iso);
    return MESES_LONG[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
  }

  /* ---------- TABS (estilo Mercado Laboral) ---------- */
  function setupTabs(){
    const nav = document.getElementById('tabsNav');
    if (!nav) return;
    nav.addEventListener('click', function(e){
      const btn = e.target.closest('.eg-tabs__btn');
      if (!btn) return;
      const tab = btn.dataset.tab;
      nav.querySelectorAll('.eg-tabs__btn').forEach(function(b){
        b.classList.toggle('is-active', b === btn);
      });
      document.querySelectorAll('.eg-tab-panel').forEach(function(p){
        p.hidden = (p.id !== 'panel-' + tab);
      });
    });
  }

  /* ---------- Stat cards ---------- */
  function renderKpis(){
    const u = D.ultimo;
    document.getElementById('ultimoMesTag').textContent =
      'Último dato: ' + fmtMonthLong(u.fecha);

    // IPC General es el destacado
    const stats = [
      { val: fmtPct(u.general_mm),    label:'IPC General',  sub:'Var. mensual', featured:true  },
      { val: fmtPct(u.nucleo_mm),     label:'IPC Núcleo',   sub:'Var. mensual', featured:false },
      { val: fmtPct(u.estacional_mm), label:'Estacionales', sub:'Var. mensual', featured:false },
      { val: fmtPct(u.regulados_mm),  label:'Regulados',    sub:'Var. mensual', featured:false }
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

  /* ---------- Defaults Chart.js + helpers de eje ---------- */
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

  /* ---------- Gráfico 21 ---------- */
  function buildChart21(){
    const d = D.chart21.filter(function(p){ return p.fecha; });
    const labels = d.map(function(p){ return p.fecha; });
    new Chart(document.getElementById('chart21'), {
      data:{
        labels: labels,
        datasets: [
          { type:'bar',  label:'Inflación mensual', data:d.map(function(p){return p.mensual;}),
            backgroundColor:TEAL, borderColor:TEAL, yAxisID:'y' },
          { type:'line', label:'Promedio anual', data:d.map(function(p){return p.promedio_anual;}),
            borderColor:ORANGE, backgroundColor:ORANGE, tension:.3, borderWidth:2, pointRadius:0, yAxisID:'y' },
          { type:'line', label:'Var. i.a. (eje der.)', data:d.map(function(p){return p.var_ia;}),
            borderColor:RED, backgroundColor:RED, tension:.3, borderWidth:2, pointRadius:0, yAxisID:'y2' }
        ]
      },
      options:{
        responsive:true, maintainAspectRatio:false,
        interaction:{ mode:'index', intersect:false },
        plugins:{
          legend:{ position:'bottom', labels:{ usePointStyle:true, padding:14 } },
          tooltip:{ callbacks:{ label: function(c){ return c.dataset.label + ': ' + fmtPct(c.parsed.y, 2); } } }
        },
        scales:{
          x: timeAxis(),
          y:  pctAxis({ position:'left',  title:{ display:true, text:'Mensual / promedio' } }),
          y2: pctAxis({ position:'right', grid:{ drawOnChartArea:false }, title:{ display:true, text:'Interanual' } })
        }
      }
    });
  }

  /* ---------- Gráfico 23 ---------- */
  function buildChart23(){
    const d = D.chart23.filter(function(p){ return p.fecha; });
    const labels = d.map(function(p){ return p.fecha; });
    new Chart(document.getElementById('chart23'), {
      data:{
        labels: labels,
        datasets: [
          { type:'bar', label:'Var. mensual (eje der.)', data:d.map(function(p){return p.var_men;}),
            backgroundColor:TEAL_LITE, borderColor:TEAL_LITE, yAxisID:'y2', order:5 },
          { type:'line', label:'IPC Var. i.a.', data:d.map(function(p){return p.var_ia;}),
            borderColor:TEAL_DARK, backgroundColor:TEAL_DARK, borderWidth:2.5, tension:.3, pointRadius:0, yAxisID:'y', order:1 },
          { type:'line', label:'Núcleo i.a.', data:d.map(function(p){return p.nucleo_ia;}),
            borderColor:RED, backgroundColor:RED, borderWidth:2, tension:.3, pointRadius:0, yAxisID:'y', order:2 },
          { type:'line', label:'Regulados i.a.', data:d.map(function(p){return p.regulados_ia;}),
            borderColor:ORANGE, backgroundColor:ORANGE, borderWidth:2, tension:.3, pointRadius:0, yAxisID:'y', order:3 },
          { type:'line', label:'Var. mensual promedio (eje der.)', data:d.map(function(p){return p.prom_men;}),
            borderColor:GREEN, backgroundColor:GREEN, borderWidth:1.5, borderDash:[5,4], tension:.3, pointRadius:0, yAxisID:'y2', order:4 }
        ]
      },
      options:{
        responsive:true, maintainAspectRatio:false,
        interaction:{ mode:'index', intersect:false },
        plugins:{
          legend:{ position:'bottom', labels:{ usePointStyle:true, padding:12 } },
          tooltip:{ callbacks:{ label: function(c){ return c.dataset.label + ': ' + fmtPct(c.parsed.y, 2); } } }
        },
        scales:{
          x: timeAxis(),
          y:  pctAxis({ position:'left',  title:{ display:true, text:'Interanual' } }),
          y2: pctAxis({ position:'right', grid:{ drawOnChartArea:false }, title:{ display:true, text:'Mensual' } })
        }
      }
    });
  }

  /* ---------- Gráfico 5 (con filtros + leader lines) ---------- */
  function fmtScatterLabel(raw) {
    // 'Nov23-Jun26' → 'Nov 2023 – Jun 2026 (gap vs Nivel general)'
    var m = (raw || '').match(/^([A-Za-z]+)(\d{2})-([A-Za-z]+)(\d{2})$/);
    if (m) return m[1] + ' 20' + m[2] + ' – ' + m[3] + ' 20' + m[4] + ' (gap vs Nivel general)';
    return raw || '';
  }
  var c5XLabel = fmtScatterLabel(D.chart5.x_label);
  var c5YLabel = fmtScatterLabel(D.chart5.y_label);

  let chart5Instance = null;
  let activeCat = null;  // null = todas

  function getCategorias(){
    const set = new Set();
    D.chart5.points.forEach(function(p){ set.add(p.categoria || 'Otros'); });
    // Orden deseado
    const orden = ['Bienes','Servicios','Regulados','Salarios','Dólar','Construcción','Mayorista','Otros'];
    return orden.filter(function(c){ return set.has(c); });
  }

  function renderChips(){
    const cats = getCategorias();
    const wrap = document.getElementById('chart5Filters');
    let html = '<button class="eg-chip is-active" data-cat="__all__">' +
      '<span class="eg-chip__dot" style="background:' + CHARCOAL + '"></span>Todas</button>';
    cats.forEach(function(c){
      html += '<button class="eg-chip" data-cat="' + c + '">' +
        '<span class="eg-chip__dot" style="background:' + CAT_COLORS[c] + '"></span>' + c + '</button>';
    });
    wrap.innerHTML = html;
    wrap.addEventListener('click', function(e){
      const btn = e.target.closest('.eg-chip');
      if (!btn) return;
      wrap.querySelectorAll('.eg-chip').forEach(function(b){ b.classList.toggle('is-active', b === btn); });
      activeCat = btn.dataset.cat === '__all__' ? null : btn.dataset.cat;
      buildChart5();
    });
  }

  /* Plugin: dibuja labels con leader lines — placement multidireccional */
  const leaderLabels = {
    id:'leaderLabels',
    afterDatasetDraw: function(chart){
      const ctx = chart.ctx;
      const xs = chart.scales.x, ys = chart.scales.y;
      const ds = chart.data.datasets[0].data;
      if (!ds || !ds.length) return;

      ctx.save();
      ctx.font = '11px HK Grotesk';
      ctx.textBaseline = 'middle';

      const H = 15, POINT_R = 6;
      // Ángulos: derecha, izquierda, arriba-derecha, arriba-izquierda, abajo-derecha,
      //          abajo-izquierda, arriba, abajo
      var ANGLES = [0, Math.PI, -Math.PI*0.35, Math.PI*1.35, Math.PI*0.35,
                    Math.PI*0.65, -Math.PI*0.5, Math.PI*0.5];
      var DISTS  = [12, 18, 26, 36, 48];

      var items = ds.map(function(p){
        var px = xs.getPixelForValue(p.x);
        var py = ys.getPixelForValue(p.y);
        var text = (p.label || '').length > 26 ? p.label.slice(0, 24) + '…' : (p.label || '');
        var w = ctx.measureText(text).width + 4;
        return { px:px, py:py, text:text, color: p.borderColor || CHARCOAL, w:w, h:H };
      });

      // Ordenar por X para mejorar la coherencia visual
      items.sort(function(a,b){ return a.px - b.px; });

      function overlaps(lx, ly, w, placed){
        var x1=lx-2, y1=ly-H/2, x2=lx+w, y2=ly+H/2;
        for(var j=0;j<placed.length;j++){
          var b=placed[j];
          if(!(x2<b.x1||b.x2<x1||y2<b.y1||b.y2<y1)) return true;
        }
        return false;
      }

      var placed = [];
      items.forEach(function(item){
        var bestLx = item.px + 12, bestLy = item.py, found = false;
        outer:
        for(var di=0; di<DISTS.length; di++){
          for(var ai=0; ai<ANGLES.length; ai++){
            var r = DISTS[di] + POINT_R;
            var lx = item.px + Math.cos(ANGLES[ai]) * r;
            var ly = item.py + Math.sin(ANGLES[ai]) * r;
            if(!overlaps(lx, ly, item.w, placed)){
              bestLx = lx; bestLy = ly; found = true; break outer;
            }
          }
        }
        if(!found){ bestLx = item.px + 12; bestLy = item.py; }
        item.lx = bestLx; item.ly = bestLy;
        placed.push({ x1:bestLx-2, y1:bestLy-H/2, x2:bestLx+item.w, y2:bestLy+H/2 });
      });

      // Dibujar leader lines y texto
      items.forEach(function(l){
        var dx = l.lx - l.px, dy = l.ly - l.py;
        var dist = Math.sqrt(dx*dx + dy*dy);
        if(dist > POINT_R + 3){
          ctx.beginPath();
          ctx.strokeStyle = 'rgba(80,80,80,0.28)';
          ctx.lineWidth = 0.65;
          // Empezar en el borde del punto, no en el centro
          var sx = l.px + dx/dist * POINT_R;
          var sy = l.py + dy/dist * POINT_R;
          ctx.moveTo(sx, sy);
          ctx.lineTo(l.lx - 2, l.ly);
          ctx.stroke();
        }
        ctx.fillStyle = l.color;
        ctx.fillText(l.text, l.lx, l.ly);
      });
      ctx.restore();
    }
  };

  function buildChart5(){
    const allPoints = D.chart5.points.map(function(p){
      const cat = p.categoria || 'Otros';
      const color = CAT_COLORS[cat] || GRAY;
      const dim   = activeCat && cat !== activeCat;
      return {
        x: p.x, y: p.y, label: p.label, categoria: cat,
        backgroundColor: dim ? 'rgba(180,180,180,0.18)' : color,
        borderColor:     dim ? 'rgba(180,180,180,0.18)' : color,
        radius: dim ? 4 : 7
      };
    });
    // Para el plugin de labels: cuando hay filtro activo, mostrar SOLO etiquetas
    // de la categoría seleccionada (más limpio). Sin filtro, mostrar todas.
    const labelPoints = activeCat ? allPoints.filter(function(p){ return p.categoria === activeCat; }) : allPoints;

    if (chart5Instance) chart5Instance.destroy();
    chart5Instance = new Chart(document.getElementById('chart5'), {
      type:'scatter',
      data:{
        datasets:[
          // dataset 0: para el plugin de labels (sólo los visibles con etiqueta)
          { label:'Categorías', data: labelPoints,
            pointRadius: function(c){ return c.raw && c.raw.radius != null ? c.raw.radius : 7; },
            pointHoverRadius: 10,
            backgroundColor: function(ctx){ return ctx.raw ? ctx.raw.backgroundColor : TEAL; },
            borderColor:     function(ctx){ return ctx.raw ? ctx.raw.borderColor    : TEAL; }
          },
          // dataset 1: los puntos atenuados (para que se vean igual aunque no se etiqueten)
          { label:'(fondo)', data: activeCat ? allPoints.filter(function(p){ return p.categoria !== activeCat; }) : [],
            pointRadius: 4,
            backgroundColor: 'rgba(180,180,180,0.18)',
            borderColor:     'rgba(180,180,180,0.18)',
            // No participa en el plugin de leader-labels
          }
        ]
      },
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{
          legend:{ display:false },
          tooltip:{
            callbacks:{
              title: function(ctx){ return ctx[0].raw.label || ''; },
              label: function(ctx){
                const cat = ctx.raw.categoria || '';
                return cat + ' · x: ' + fmtPct(ctx.raw.x, 1) + ' · y: ' + fmtPct(ctx.raw.y, 1);
              }
            }
          }
        },
        scales:{
          x: pctAxis({ type:'linear', position:'bottom',
            title:{ display:true, text: c5XLabel } }),
          y: pctAxis({ type:'linear', position:'center',
            title:{ display:false, text: c5YLabel } })
        }
      },
      plugins:[ leaderLabels, {
        id:'yTitleLeft',
        afterDraw: function(chart){
          var yScale = chart.scales.y;
          if (!yScale) return;
          var ctx = chart.ctx;
          var titleText = c5YLabel;
          ctx.save();
          ctx.font = '11px HK Grotesk';
          ctx.fillStyle = 'rgba(100,100,100,0.85)';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'middle';
          var x = chart.chartArea.left - 10;
          var y = (chart.chartArea.top + chart.chartArea.bottom) / 2;
          ctx.translate(x, y);
          ctx.rotate(-Math.PI / 2);
          ctx.fillText(titleText, 0, 0);
          ctx.restore();
        }
      } ]
    });
  }

  /* ---------- Gráfico 22 ---------- */
  function buildChart22(){
    const d = D.chart22.filter(function(p){ return p.fecha; });
    const labels = d.map(function(p){ return p.fecha; });
    new Chart(document.getElementById('chart22'), {
      data:{
        labels: labels,
        datasets:[
          { type:'line', label:'RPM Eco Go (m/m)', data:d.map(function(p){return p.rpm_mm;}),
            borderColor:TEAL_DARK, backgroundColor:TEAL_DARK, borderWidth:2.5, tension:.3, pointRadius:0, yAxisID:'y' },
          { type:'line', label:'IPC GBA INDEC (m/m)', data:d.map(function(p){return p.ipc_gba;}),
            borderColor:TEAL, backgroundColor:TEAL, borderWidth:2, tension:.3, pointRadius:0, yAxisID:'y' },
          { type:'line', label:'IPC Nacional (m/m)', data:d.map(function(p){return p.ipc_nac;}),
            borderColor:ORANGE, backgroundColor:ORANGE, borderWidth:2, tension:.3, pointRadius:0, yAxisID:'y' },
          { type:'line', label:'RPM Var i.a. (eje der.)', data:d.map(function(p){return p.rpm_ia;}),
            borderColor:RED, backgroundColor:RED, borderWidth:2, borderDash:[5,4], tension:.3, pointRadius:0, yAxisID:'y2' }
        ]
      },
      options:{
        responsive:true, maintainAspectRatio:false,
        interaction:{ mode:'index', intersect:false },
        plugins:{
          legend:{ position:'bottom', labels:{ usePointStyle:true, padding:14 } },
          tooltip:{ callbacks:{ label: function(c){ return c.dataset.label + ': ' + fmtPct(c.parsed.y, 2); } } }
        },
        scales:{
          x: timeAxis(),
          y:  pctAxis({ position:'left',  title:{ display:true, text:'Variación mensual' } }),
          y2: pctAxis({ position:'right', grid:{ drawOnChartArea:false }, title:{ display:true, text:'RPM Var i.a.' } })
        }
      }
    });
  }

  /* ---------- Tabla proyección RPM ---------- */
  function buildTablaProyeccion(){
    const p = D.proyeccion;
    document.getElementById('proyeccionTitulo').textContent =
      p.header_periodo || p.subtitulo;
    const tbody = p.filas.map(function(f){
      const isTotal = (f.capitulo || '').toUpperCase().indexOf('NIVEL GENERAL') >= 0;
      return '<tr class="' + (isTotal ? 'is-total' : '') + '">' +
        '<td>' + f.capitulo + '</td>' +
        '<td class="num">' + fmtPct(f.mensual, 2) + '</td>' +
        '<td class="num">' + fmtPct(f.acumulada, 2) + '</td>' +
        '<td class="num">' + fmtPct(f.anual, 2) + '</td>' +
      '</tr>';
    }).join('');
    document.getElementById('tablaProyeccion').innerHTML =
      '<thead><tr>' +
        '<th>Capítulo</th>' +
        '<th class="num">Mensual</th>' +
        '<th class="num">Acumulada</th>' +
        '<th class="num">Anual (i.a.)</th>' +
      '</tr></thead>' +
      '<tbody>' + tbody + '</tbody>';
  }


  function setupDownloads() {
    var D = window.PRECIOS_DATA;
    if (!D || !window.EcoGo) return;
    var pct = function(v){ return (v !== null && v !== undefined) ? +(v*100).toFixed(2) : ''; };

    EcoGo.dlBtn('#chart21', 'ipc_variacion_mensual.csv', function(){
      return {
        headers: ['Fecha','Var. mensual (%)','Prom. anual (%)','Var. i.a. (%)'],
        rows: (D.chart21||[]).map(function(r){ return [r.fecha, pct(r.mensual), pct(r.promedio_anual), pct(r.var_ia)]; })
      };
    });
    EcoGo.dlBtn('#chart23', 'ipc_componentes.csv', function(){
      return {
        headers: ['Fecha','Var. mensual (%)','Var. i.a. (%)','Nucleo i.a. (%)','Regulados i.a. (%)','Prom. mensual (%)'],
        rows: (D.chart23||[]).map(function(r){
          return [r.fecha, pct(r.var_men), pct(r.var_ia), pct(r.nucleo_ia), pct(r.regulados_ia), pct(r.prom_men)];
        })
      };
    });
    EcoGo.dlBtn('#chart22', 'ipc_rpm_vs_indec.csv', function(){
      return {
        headers: ['Fecha','RPM mensual (%)','IPC GBA (%)','IPC Nacional (%)','RPM i.a. (%)'],
        rows: (D.chart22||[]).map(function(r){
          return [r.fecha, pct(r.rpm_mm), pct(r.ipc_gba), pct(r.ipc_nac), pct(r.rpm_ia)];
        })
      };
    });
    EcoGo.dlBtn('#chart5', 'ipc_serie_completa.csv', function(){
      return {
        headers: ['Fecha','IPC General m/m (%)','IPC General i.a. (%)','Nucleo m/m (%)','Nucleo i.a. (%)','Estacional m/m (%)','Regulados m/m (%)'],
        rows: (D.series_24m||[]).map(function(r){
          return [r.fecha, pct(r.general_mm), pct(r.general_ia), pct(r.nucleo_mm), pct(r.nucleo_ia), pct(r.estacional_mm), pct(r.regulados_mm)];
        })
      };
    });
  }

  document.addEventListener('DOMContentLoaded', function(){
    setupChart();
    setupTabs();
    renderKpis();
    buildChart21();
    buildChart23();
    renderChips();
    buildChart5();
    buildChart22();
    buildTablaProyeccion();
    setupDownloads();
  });
})();
