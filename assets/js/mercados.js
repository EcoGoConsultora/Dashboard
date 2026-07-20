/* ============================================================
   ECO GO — Mercados · Tasa fija / RV / CER / DL / HD  v4
   ============================================================ */
(function(){
  var TEAL_DARK='#1B5F5E', TEAL='#3C9794';
  var GREEN='#89C442', RED='#DA4531', ORANGE='#FE8B5F', PURPLE='#7E5CCB';
  var CHARCOAL='#333333';

  var FAMILY_COLORS = {
    lecap:'#8FCCCA', boncap:'#2890A4', lede:'#89C442',
    boncer:'#7E5CCB', lecer:'#3A82C4', tzx:'#FE8B5F', tv:'#DA4531'
  };
  var DL_COLORS = ['#8FCCCA','#2890A4','#DA4531','#FE8B5F','#7E5CCB'];

  /* Paleta fija por índice de botón (1D→0, 2D→1, 3D→2, 1S→3) */
  var HIST_PALETTE = [
    { border:'#1B5F5E', bg:'rgba(27,95,94,0.32)'  },
    { border:'#3C9794', bg:'rgba(60,151,148,0.28)' },
    { border:'#89C442', bg:'rgba(137,196,66,0.28)' },
    { border:'#FE8B5F', bg:'rgba(254,139,95,0.32)' }
  ];

  /* ================================================================
     Plugin nativo: labels de instrumentos sobre cada punto
     ================================================================ */
  var symLabelPlugin = {
    id: 'symLabels',
    afterDatasetsDraw: function(chart){
      var ctx = chart.ctx;
      chart.data.datasets.forEach(function(ds, di){
        if (!ds.data || !ds.data.length || !ds.data[0] || !ds.data[0].sym) return;
        var meta = chart.getDatasetMeta(di);
        ds.data.forEach(function(pt, pi){
          if (!pt.sym) return;
          var el = meta.data[pi];
          if (!el || el.hidden) return;
          var radius = (el.options && el.options.radius) ? el.options.radius : 9;
          var x = el.x, y = el.y - radius - 4;
          ctx.save();
          ctx.font = '700 8.5px "HK Grotesk", system-ui, sans-serif';
          ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
          ctx.strokeStyle = 'rgba(255,255,255,0.9)'; ctx.lineWidth = 3; ctx.lineJoin = 'round';
          ctx.strokeText(pt.sym, x, y);
          ctx.fillStyle = ds._symColor || TEAL_DARK;
          ctx.fillText(pt.sym, x, y);
          ctx.restore();
        });
      });
    }
  };

  /* ==============================================================
     Regresión polinomial en espacio log(duration)
     ============================================================== */
  function solveLinearSystem(mat, vec){
    var n = mat.length;
    var aug = mat.map(function(row, ri){ return row.slice().concat([vec[ri]]); });
    for (var pi = 0; pi < n; pi++){
      var pr = pi;
      for (var ri = pi+1; ri < n; ri++){
        if (Math.abs(aug[ri][pi]) > Math.abs(aug[pr][pi])) pr = ri;
      }
      if (Math.abs(aug[pr][pi]) < 1e-12) return null;
      if (pr !== pi){ var t = aug[pi]; aug[pi] = aug[pr]; aug[pr] = t; }
      var pv = aug[pi][pi];
      for (var ci = pi; ci <= n; ci++) aug[pi][ci] /= pv;
      for (var ri2 = 0; ri2 < n; ri2++){
        if (ri2 === pi) continue;
        var fc = aug[ri2][pi];
        for (var ci2 = pi; ci2 <= n; ci2++) aug[ri2][ci2] -= fc * aug[pi][ci2];
      }
    }
    return aug.map(function(row){ return row[n]; });
  }

  function buildTrendCurve(rows, valueKey, nSamples){
    valueKey = valueKey || 'tir_pct'; nSamples = nSamples || 64;
    var clean = (rows||[]).map(function(r){
      return { d: Number(r.duration), v: Number(r[valueKey]) };
    }).filter(function(p){ return isFinite(p.d) && p.d > 0 && isFinite(p.v); })
      .sort(function(a,b){ return a.d - b.d; });
    if (clean.length < 2) return null;
    var deg = clean.length >= 4 ? 2 : 1;
    var lx = clean.map(function(p){ return Math.log(p.d); });
    var ly = clean.map(function(p){ return p.v; });
    var sz = deg + 1, mat = [], vec = [];
    for (var ri = 0; ri < sz; ri++){
      var row = [], vv = 0;
      for (var ci = 0; ci < sz; ci++){
        var s = 0;
        for (var k = 0; k < lx.length; k++) s += Math.pow(lx[k], ri+ci);
        row.push(s);
      }
      for (var k2 = 0; k2 < lx.length; k2++) vv += ly[k2] * Math.pow(lx[k2], ri);
      mat.push(row); vec.push(vv);
    }
    var coefs = solveLinearSystem(mat, vec);
    if (!coefs) return null;
    var minD = clean[0].d, maxD = clean[clean.length-1].d;
    if (Math.abs(maxD - minD) < 1e-9) return null;
    var curve = [];
    for (var i = 0; i < nSamples; i++){
      var w = i/(nSamples-1), d = minD+(maxD-minD)*w, ld = Math.log(d);
      var val = coefs.reduce(function(sum,c,idx){ return sum+c*Math.pow(ld,idx); }, 0);
      if (isFinite(val)) curve.push({x:d, y:val});
    }
    return curve.length >= 2 ? curve : null;
  }

  /* Build a trend curve directly from {x,y} scatter points */
  function buildTrendFromXY(pts){
    var fakeRows = (pts||[]).filter(function(p){ return p && p.x>0 && isFinite(p.x) && isFinite(p.y); })
                            .map(function(p){ return {duration: p.x, _v: p.y}; });
    return buildTrendCurve(fakeRows, '_v');
  }

  function makeTrendToggle(btnId, getChart, rows, valueKey, color){
    var TREND_LBL = '__trend__';
    var btn = document.getElementById(btnId); if (!btn) return;
    btn.addEventListener('click', function(){
      var ch = getChart(); if (!ch) return;
      var exists = ch.data.datasets.some(function(ds){ return ds.label===TREND_LBL; });
      if (exists){
        /* Remove main trend + all hist trends */
        ch.data.datasets = ch.data.datasets.filter(function(ds){
          return ds.label !== TREND_LBL && !ds._isHistTrend;
        });
        ch.update(); btn.classList.remove('is-active');
      } else {
        var curve = buildTrendCurve(rows, valueKey);
        if (!curve){ btn.disabled=true; btn.title='Sin suficientes puntos'; return; }
        ch.data.datasets.unshift({
          type:'line', label:TREND_LBL, data:curve,
          borderColor:color, borderWidth:2.5, borderDash:[6,4],
          pointRadius:0, fill:false, tension:0, order:0
        });
        /* Also add trend for every active hist overlay */
        ch.data.datasets.filter(function(ds){ return ds._isHistOverlay; }).forEach(function(ods){
          var c = buildTrendFromXY(ods.data);
          if (!c) return;
          ch.data.datasets.push({
            type:'line', label:'__trend_hist_'+ods.label, _isHistTrend:true,
            data:c, borderColor:ods.borderColor, borderWidth:2, borderDash:[4,3],
            pointRadius:0, fill:false, tension:0, order:0
          });
        });
        ch.update(); btn.classList.add('is-active');
      }
    });
  }

  /* ── Formatters ── */
  function fmtN(v,dec){
    if(v===null||v===undefined) return '—';
    dec=(dec===undefined)?2:dec;
    return Number(v).toLocaleString('es-AR',{minimumFractionDigits:dec,maximumFractionDigits:dec});
  }
  function fmtPct(v){
    if(v===null||v===undefined) return {html:'—',cls:'neu'};
    var sign=v>=0?'+':'';
    return {html:sign+Number(v).toFixed(2)+'%', cls:v>0?'pos':(v<0?'neg':'neu')};
  }
  function fmtTir(v){ return (v===null||v===undefined)?'—':Number(v).toFixed(2)+'%'; }
  function fmtDur(v){ return (v===null||v===undefined)?'—':Number(v).toFixed(2)+'y'; }
  function fmtVol(v){
    if(v===null||v===undefined) return '—';
    if(v===0) return '0';
    var m=v/1e6;
    if(m>=1000) return fmtN(m/1000,1)+' B';
    if(m>=1)    return fmtN(m,1)+' M';
    return fmtN(v,0);
  }
  function familyLabel(f){
    var m={lecap:'LECAP',lede:'LEDE',boncap:'BONCAP',boncer:'BONCER',lecer:'LECER',tzx:'TZX',tv:'TV',al:'AL',gd:'GD'};
    return m[f]||(f||'—').toUpperCase();
  }
  function bubbleR(vol,items){
    if(!vol) return 8;
    var vols=(items||[]).filter(function(i){return i.volume;}).map(function(i){return i.volume;});
    if(!vols.length) return 8;
    var mx=Math.max.apply(null,vols);
    return Math.min(18, 6+Math.round(12*(vol/mx)));
  }

  Chart.defaults.font.family = "'HK Grotesk', system-ui, sans-serif";
  Chart.defaults.color = CHARCOAL;
  var scaleX = { ticks:{color:'#6E7679'}, grid:{color:'rgba(0,0,0,0.04)'} };
  var scaleY = { ticks:{color:'#6E7679'}, grid:{color:'rgba(0,0,0,0.06)'} };
  var charts = {};

  /* ================================================================
     HIST NAV helpers
     ================================================================ */
  function getSortedDates(dl){
    var hist=(dl&&dl.history)||[], set={};
    hist.forEach(function(h){ set[h.date]=true; });
    return Object.keys(set).sort();
  }

  var HIST_DEFS = [
    { label:'Hoy', offset:0 },
    { label:'-1D', offset:1 },
    { label:'-2D', offset:2 },
    { label:'-3D', offset:3 },
    { label:'-1S', offset:5 }
  ];

  /* ================================================================
     CURVE HISTORY NAV
     Activa los botones estáticos del HTML para TF / CER / HD.
     Multi-select: cada botón agrega/quita su propia capa superpuesta.
     ================================================================ */
  function activateCurveHistNav(canvasId, chartKey, historyData, familyFilter, trendBtnId){
    var canvas = document.getElementById(canvasId); if (!canvas) return;
    var cardEl = canvas.closest('.mk-chart-card'); if (!cardEl) return;
    var navEl  = cardEl.querySelector('.mk-hist-nav'); if (!navEl) return;

    var dates  = (historyData && historyData.dates)  || [];
    var curves = (historyData && historyData.curves) || {};
    if (dates.length < 2) return;

    var btns = navEl.querySelectorAll('.mk-hist-btn');

    function dsKey(date){ return '__hist_' + date; }
    function trendKey(date){ return '__trend_hist___hist_' + date; }

    function getChart(){ return charts[chartKey]; }
    function isTrendActive(){
      var tb = trendBtnId ? document.getElementById(trendBtnId) : null;
      return tb && tb.classList.contains('is-active');
    }

    function addOverlay(ch, targetDate, paletteIdx){
      var items = curves[targetDate]; if (!items || !items.length) return;
      var filtered = familyFilter
        ? items.filter(function(r){ return (r.family||'').toUpperCase()===familyFilter.toUpperCase(); })
        : items;
      if (!filtered.length) return;
      var pal = HIST_PALETTE[Math.min(paletteIdx, HIST_PALETTE.length-1)];
      var chartType = ch.config.type;
      var pts = filtered.map(function(r){
        var pt = { x: r.duration, y: (r.tir_pct != null ? r.tir_pct : r.tir) };
        if (chartType === 'bubble') pt.r = bubbleR(r.volume, filtered);
        return pt;
      });
      ch.data.datasets.push({
        label: dsKey(targetDate),
        type: chartType,
        _isHistOverlay: true,
        data: pts,
        backgroundColor: pal.bg,
        borderColor: pal.border,
        borderWidth: 1.5,
        pointRadius: chartType === 'scatter' ? 7 : undefined,
        order: 0
      });
      /* If trend is currently active, add matching trend line for this overlay */
      if (isTrendActive()){
        var tc = buildTrendFromXY(pts);
        if (tc) ch.data.datasets.push({
          type:'line', label: trendKey(targetDate), _isHistTrend: true,
          data: tc, borderColor: pal.border, borderWidth: 2, borderDash:[4,3],
          pointRadius:0, fill:false, tension:0, order:0
        });
      }
      ch.update();
    }

    function removeOverlay(ch, targetDate){
      var keep = function(ds){ return ds.label !== dsKey(targetDate) && ds.label !== trendKey(targetDate); };
      ch.data.datasets = ch.data.datasets.filter(keep);
      ch.update();
    }

    function clearAllOverlays(ch){
      ch.data.datasets = ch.data.datasets.filter(function(ds){ return !ds._isHistOverlay && !ds._isHistTrend; });
      ch.update();
    }

    HIST_DEFS.forEach(function(def, btnIdx){
      if (btnIdx >= btns.length) return;
      var btn = btns[btnIdx];

      if (def.offset === 0){
        /* "Hoy": limpia todos los overlays al hacer click */
        btn.disabled = false;
        btn.addEventListener('click', function(){
          var ch = getChart(); if (!ch) return;
          clearAllOverlays(ch);
          /* desmarcar todos los otros botones */
          btns.forEach(function(b,i){ if(i>0) b.classList.remove('is-active'); });
        });
      } else {
        var dateIdx = dates.length - 1 - def.offset;
        if (dateIdx < 0) return; /* permanece disabled */
        var targetDate = dates[dateIdx];
        var paletteIdx = btnIdx - 1; /* 0-based para la paleta */
        btn.disabled = false;
        btn.title = targetDate;
        (function(td, pi, b){
          b.addEventListener('click', function(){
            var ch = getChart(); if (!ch) return;
            if (b.classList.contains('is-active')){
              b.classList.remove('is-active');
              removeOverlay(ch, td);
            } else {
              b.classList.add('is-active');
              addOverlay(ch, td, pi);
            }
          });
        })(targetDate, paletteIdx, btn);
      }
    });
  }

  /* ================================================================
     DL HIST NAV — construido dinámicamente con fechas reales
     Multi-select: cada botón togglea su overlay. "Hoy" limpia todo.
     ================================================================ */
  function buildHistNav(cardEl, dates, dl, symbols, chart){
    var nav = document.createElement('div');
    nav.className = 'mk-hist-nav';

    function dsKey(date){ return '__hist_dl_' + date; }

    function getVolsForDate(date){
      var hist = (dl&&dl.history)||[];
      var bySymbol = {};
      hist.filter(function(h){ return h.date===date; })
          .forEach(function(h){ bySymbol[h.symbol]=h; });
      return symbols.map(function(sym){
        var h=bySymbol[sym]; return (h&&h.volume!=null)?h.volume:0;
      });
    }

    function addDLOverlay(targetDate, paletteIdx){
      var pal = HIST_PALETTE[Math.min(paletteIdx, HIST_PALETTE.length-1)];
      var datesAll = getSortedDates(dl);
      var daysBack = datesAll.length - 1 - datesAll.indexOf(targetDate);
      void daysBack; /* info disponible si se quiere usar en tooltip */
      chart.data.datasets.push({
        label: dsKey(targetDate),
        _isDLOverlay: true,
        data: getVolsForDate(targetDate),
        backgroundColor: pal.bg,
        borderColor: pal.border,
        borderWidth: 1.5, borderRadius: 3,
        barPercentage: 0.4, categoryPercentage: 0.85
      });
      /* Reducir barra principal para que quepan las superpuestas */
      chart.data.datasets[0].barPercentage = 0.4;
      chart.data.datasets[0].categoryPercentage = 0.85;
      chart.update();
    }

    function removeDLOverlay(targetDate){
      var idx = -1;
      chart.data.datasets.forEach(function(ds,i){ if(ds.label===dsKey(targetDate)) idx=i; });
      if (idx !== -1){ chart.data.datasets.splice(idx,1); }
      /* Si no quedan overlays, restaurar ancho normal */
      var hasOverlays = chart.data.datasets.some(function(ds){ return ds._isDLOverlay; });
      if (!hasOverlays && chart.data.datasets[0]){
        chart.data.datasets[0].barPercentage = 0.6;
        chart.data.datasets[0].categoryPercentage = 0.9;
      }
      chart.update();
    }

    HIST_DEFS.forEach(function(def, btnIdx){
      var btn = document.createElement('button');
      btn.className = 'mk-hist-btn' + (def.offset===0 ? ' is-active' : '');
      btn.textContent = def.label;

      if (def.offset === 0){
        btn.addEventListener('click', function(){
          /* Limpiar todos los overlays */
          chart.data.datasets = chart.data.datasets.filter(function(ds){ return !ds._isDLOverlay; });
          if (chart.data.datasets[0]){
            chart.data.datasets[0].barPercentage = 0.6;
            chart.data.datasets[0].categoryPercentage = 0.9;
          }
          chart.update();
          nav.querySelectorAll('.mk-hist-btn').forEach(function(b,i){ if(i>0) b.classList.remove('is-active'); });
        });
      } else {
        var dateIdx = dates ? (dates.length - 1 - def.offset) : -1;
        if (!dates || dateIdx < 0){
          btn.disabled = true; btn.title = 'Sin datos para este período';
        } else {
          var targetDate = dates[dateIdx];
          var paletteIdx = btnIdx - 1;
          btn.title = targetDate;
          (function(td, pi, b){
            b.addEventListener('click', function(){
              if (b.classList.contains('is-active')){
                b.classList.remove('is-active');
                removeDLOverlay(td);
              } else {
                b.classList.add('is-active');
                addDLOverlay(td, pi);
              }
            });
          })(targetDate, paletteIdx, btn);
        }
      }
      nav.appendChild(btn);
    });

    var boxEl = cardEl.querySelector('.mk-chart-box');
    if (boxEl) boxEl.insertAdjacentElement('beforebegin', nav);
    else cardEl.appendChild(nav);
    return nav;
  }

  /* ================================================================
     TABS
     ================================================================ */
  var chartBuilt = {};
  function setupTabs(D){
    var nav = document.getElementById('mkTabsNav');
    nav.addEventListener('click', function(e){
      var btn = e.target.closest('.eg-tabs__btn'); if (!btn) return;
      var tab = btn.dataset.tab;
      nav.querySelectorAll('.eg-tabs__btn').forEach(function(b){ b.classList.toggle('is-active',b===btn); });
      document.querySelectorAll('.eg-tab-panel').forEach(function(p){ p.hidden = p.id!=='panel-'+tab; });
      if (!chartBuilt[tab]){
        chartBuilt[tab] = true;
        if (tab==='renta-variable') buildChartEquities(D.overview&&D.overview.categories);
        if (tab==='cer'){
          buildChartCer(D.cer_curve);
          activateCurveHistNav('chartCer', 'chartCer', D.cer_curve_history, null, 'trendBtnCer');
          makeTrendToggle('trendBtnCer', function(){return charts['chartCer'];}, D.cer_curve||[], 'tir_pct', PURPLE);
        }
        if (tab==='dolar-linked') buildChartDolarLinked(D.dollar_linked);
        if (tab==='hard-dollar')  buildChartsHD(D.hard_dollar, D.hard_dollar_curve_history);
      }
    });
  }

  /* ================================================================
     HERO KPIs
     ================================================================ */
  function renderHero(hm){
    var el=document.getElementById('mkHero'); if (!el) return;
    var html='';
    (hm||[]).forEach(function(m){
      var c1=fmtPct(m.ret_1d_pct), cy=fmtPct(m.ret_ytd_pct);
      html+=
        '<div class="mk-hero-card">'+
        '<div class="mk-hero-card__label">'+(m.label||m.asset)+'</div>'+
        '<div class="mk-hero-card__value">'+fmtN(m.value,0)+'</div>'+
        '<div class="mk-hero-card__chgs">'+
          '<span class="mk-hero-card__chg"><span class="mk-hero-card__chg-lbl">1D</span><span class="'+c1.cls+'">'+c1.html+'</span></span>'+
          '<span class="mk-hero-card__chg"><span class="mk-hero-card__chg-lbl">YTD</span><span class="'+cy.cls+'">'+cy.html+'</span></span>'+
        '</div>'+
        '<div style="font-size:.65rem;color:var(--color-text-muted);margin-top:4px">'+(m.unit||'')+'</div>'+
        '</div>';
    });
    el.innerHTML=html;
  }

  /* ================================================================
     TASA FIJA
     ================================================================ */
  function renderTasaFija(fc){
    var rows=(fc||[]).slice().sort(function(a,b){return a.duration-b.duration;});
    var tb='';
    rows.forEach(function(it){
      tb+='<tr><td><strong>'+it.symbol+'</strong></td><td class="badge">'+familyLabel(it.family)+'</td>'+
          '<td class="num">'+fmtTir(it.tir_pct)+'</td><td class="num">'+fmtDur(it.duration)+'</td>'+
          '<td>'+(it.maturity_date||'—')+'</td><td class="num">'+fmtVol(it.volume)+'</td></tr>';
    });
    document.getElementById('bodyTasaFija').innerHTML=tb;
  }

  function buildChartTasaFija(fc, historyData){
    var rows=(fc||[]).slice().sort(function(a,b){return a.duration-b.duration;});
    if (!rows.length) return;
    var fams=[];
    rows.forEach(function(r){ if(r.family&&fams.indexOf(r.family)===-1) fams.push(r.family); });
    var datasets=fams.map(function(fam){
      var pts=rows.filter(function(r){return r.family===fam;});
      var ds={
        label:familyLabel(fam),
        data:pts.map(function(r){ return {x:r.duration,y:r.tir_pct,r:bubbleR(r.volume,rows),sym:r.symbol}; }),
        backgroundColor:(FAMILY_COLORS[fam]||TEAL)+'BB',
        borderColor:FAMILY_COLORS[fam]||TEAL, borderWidth:1.5
      };
      ds._symColor = FAMILY_COLORS[fam]||TEAL_DARK;
      return ds;
    });
    /* KEY: guardado con el mismo ID del canvas para que activateCurveHistNav lo encuentre */
    charts['chartTasaFija'] = new Chart(document.getElementById('chartTasaFija'),{
      type:'bubble', data:{datasets:datasets},
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{
          legend:{position:'bottom',labels:{usePointStyle:true,padding:12,boxWidth:8,boxHeight:8}},
          tooltip:{callbacks:{label:function(c){
            var r=rows.find(function(i){return Math.abs(i.duration-c.raw.x)<0.001&&Math.abs(i.tir_pct-c.raw.y)<0.001;});
            return r?(r.symbol+' | TIR: '+fmtTir(r.tir_pct)+' | Dur: '+fmtDur(r.duration)+' | Vol: '+fmtVol(r.volume)):'';
          }}}
        },
        scales:{
          x:Object.assign({title:{display:true,text:'Duration (años)',color:'#6E7679'}},scaleX),
          y:Object.assign({title:{display:true,text:'TIR (%)',color:'#6E7679'},ticks:{color:'#6E7679',callback:function(v){return v.toFixed(1)+'%';}}},scaleY)
        }
      },
      plugins:[symLabelPlugin]
    });
    activateCurveHistNav('chartTasaFija', 'chartTasaFija', historyData, null, 'trendBtnTasaFija');
  }

  /* ================================================================
     RENTA VARIABLE
     ================================================================ */
  function getEquities(cats){
    var eq=null;
    (cats||[]).forEach(function(c){ if(c.category==='Equities') eq=c.assets; });
    return eq||[];
  }
  function renderRentaVariable(cats){
    var rows=getEquities(cats).slice().sort(function(a,b){return(b.ret_1d_pct||0)-(a.ret_1d_pct||0);});
    var tb='';
    rows.forEach(function(it){
      var c1=fmtPct(it.ret_1d_pct), c1m=fmtPct(it.ret_1m_pct), cy=fmtPct(it.ret_ytd_pct);
      tb+='<tr><td><strong>'+it.label+'</strong></td><td class="num">'+fmtN(it.value,2)+'</td>'+
          '<td style="font-size:.75rem;color:var(--color-text-muted)">'+(it.unit||'')+'</td>'+
          '<td class="num '+c1.cls+'">'+c1.html+'</td><td class="num '+c1m.cls+'">'+c1m.html+'</td>'+
          '<td class="num '+cy.cls+'">'+cy.html+'</td><td style="font-size:.75rem">'+(it.date||'—')+'</td></tr>';
    });
    document.getElementById('bodyRentaVariable').innerHTML=tb;
  }
  function buildChartEquities(cats){
    var rows=getEquities(cats)
      .filter(function(r){return r.ret_1d_pct!==null&&r.ret_1d_pct!==undefined;})
      .slice().sort(function(a,b){return(a.ret_1d_pct||0)-(b.ret_1d_pct||0);});
    if (!rows.length) return;
    new Chart(document.getElementById('chartEquities'),{
      type:'bar',
      data:{
        labels:rows.map(function(r){return r.label;}),
        datasets:[{label:'Var. 1D %',
          data:rows.map(function(r){return r.ret_1d_pct;}),
          backgroundColor:rows.map(function(r){return r.ret_1d_pct>=0?GREEN+'CC':RED+'CC';}),
          borderColor:rows.map(function(r){return r.ret_1d_pct>=0?GREEN:RED;}),
          borderWidth:1.5, borderRadius:4}]
      },
      options:{
        indexAxis:'y', responsive:true, maintainAspectRatio:false,
        plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){return ' '+(c.raw>=0?'+':'')+Number(c.raw).toFixed(2)+'%';}}}}},
        scales:{
          x:{ticks:{color:'#6E7679',callback:function(v){return v.toFixed(1)+'%';}},grid:{color:'rgba(0,0,0,0.05)'},border:{dash:[4,4]}},
          y:{ticks:{color:'#333',font:{size:11}},grid:{display:false}}
        }
    });
  }

  /* ================================================================
     CER
     ================================================================ */
  function renderCer(cc){
    var rows=(cc||[]).slice().sort(function(a,b){return a.duration-b.duration;});
    var tb='';
    rows.forEach(function(it){
      tb+='<tr><td><strong>'+it.symbol+'</strong></td><td class="num">'+fmtTir(it.tir_pct)+'</td>'+
          '<td class="num">'+fmtDur(it.duration)+'</td><td>'+(it.payment_date||'—')+'</td>'+
          '<td class="num">'+fmtN(it.price,2)+'</td><td class="num">'+fmtN(it.technical_price,2)+'</td>'+
          '<td class="num">'+fmtN(it.parity,2)+'%</td><td class="num">'+fmtVol(it.volume)+'</td></tr>';
    });
    document.getElementById('bodyCer').innerHTML=tb;
  }
  function buildChartCer(cc){
    var rows=(cc||[]).slice().sort(function(a,b){return a.duration-b.duration;});
    if (!rows.length) return;
    charts['chartCer'] = new Chart(document.getElementById('chartCer'),{
      type:'bubble',
      data:{datasets:[{label:'CER', _symColor:PURPLE,
        data:rows.map(function(r){return {x:r.duration,y:r.tir_pct,r:bubbleR(r.volume,rows),sym:r.symbol};}),
        backgroundColor:PURPLE+'BB', borderColor:PURPLE, borderWidth:1.5}]},
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){
          var r=rows.find(function(i){return Math.abs(i.duration-c.raw.x)<0.001;});
          return r?(r.symbol+' | TIR real: '+fmtTir(r.tir_pct)+' | Dur: '+fmtDur(r.duration)+' | Vol: '+fmtVol(r.volume)):'';
        }}}},
        scales:{
          x:Object.assign({title:{display:true,text:'Duration (años)',color:'#6E7679'}},scaleX),
          y:Object.assign({title:{display:true,text:'TIR real (%)',color:'#6E7679'},ticks:{color:'#6E7679',callback:function(v){return v.toFixed(1)+'%';}}},scaleY)
        }
      },
      plugins:[symLabelPlugin]
    });
  }

  /* ================================================================
     DÓLAR LINKED — volumen + multi-select histórico + 20 ruedas
     ================================================================ */
  function renderDolarLinked(dl){
    var items=(dl&&dl.latest)?dl.latest:[];
    var tb='';
    items.forEach(function(it){
      tb+='<tr><td><strong>'+it.symbol+'</strong></td><td class="num">'+fmtN(it.price,2)+'</td>'+
          '<td class="num">'+(it.volume!=null?fmtN(it.volume,0):'—')+'</td>'+
          '<td class="num">'+(it.amount!=null?fmtVol(it.amount):'—')+'</td>'+
          '<td style="font-size:.75rem">'+(it.date||'—')+'</td></tr>';
    });
    document.getElementById('bodyDolarLinked').innerHTML=tb;
  }

  function buildChartDolarLinked(dl){
    var hist    = (dl&&dl.history)||[];
    var symbols = (dl&&dl.symbols)?dl.symbols.slice():[];
    if (!symbols.length && hist.length){
      var symSet={}; hist.forEach(function(h){symSet[h.symbol]=true;}); symbols=Object.keys(symSet).sort();
    }
    var dates      = getSortedDates(dl);
    var latestDate = dates[dates.length-1];
    var byDate     = {};
    dates.forEach(function(d){byDate[d]={};});
    hist.forEach(function(h){ if(byDate[h.date]) byDate[h.date][h.symbol]=h; });

    function getVolumes(date){
      var row=byDate[date]||{};
      return symbols.map(function(sym){ var h=row[sym]; return (h&&h.volume!=null)?h.volume:0; });
    }
    var currentVols = getVolumes(latestDate);
    var canvas = document.getElementById('chartDolarLinked'); if (!canvas) return;

    var dlChart = new Chart(canvas,{
      type:'bar',
      data:{
        labels:symbols,
        datasets:[{
          label:'Volumen '+latestDate, data:currentVols,
          backgroundColor:symbols.map(function(_,j){return DL_COLORS[j%DL_COLORS.length]+'BB';}),
          borderColor:symbols.map(function(_,j){return DL_COLORS[j%DL_COLORS.length];}),
          borderWidth:1.5, borderRadius:5, barPercentage:0.6, categoryPercentage:0.9, order:1
        }]
      },
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{
          legend:{display:false},
          tooltip:{callbacks:{
            title:function(items){return items[0].label;},
            label:function(c){
              if(c.dataset._isDLOverlay) return ' '+c.dataset.label.replace('__hist_dl_','')+': '+fmtVol(c.raw);
              return ' Hoy: '+fmtVol(c.raw);
            }
          }}
        },
        scales:{
          x:{ticks:{color:'#333'},grid:{display:false},stacked:false},
          y:{title:{display:true,text:'Volumen operado',color:'#6E7679'},
             ticks:{color:'#6E7679',callback:function(v){return fmtVol(v);}},
             grid:{color:'rgba(0,0,0,0.06)'},stacked:false}
        }
      }
    });
    charts['dolarLinked'] = dlChart;

    var dlMode = 'normal';

    /* ── Vista 20 Ruedas ── */
    function switchTo20Ruedas(){
      dlMode='20ruedas';
      var last20=dates.slice(-20);
      var ds20=symbols.map(function(sym,j){
        return {
          label:sym,
          data:last20.map(function(date){ var row=byDate[date]||{}; var h=row[sym]; return (h&&h.volume!=null)?h.volume:0; }),
          backgroundColor:DL_COLORS[j%DL_COLORS.length]+'CC',
          borderColor:DL_COLORS[j%DL_COLORS.length],
          borderWidth:1, borderRadius:3, stack:'vol'
        };
      });
      dlChart.data.labels=last20.map(function(d){var p=d.split('-');return p[2]+'/'+p[1];});
      dlChart.data.datasets=ds20;
      dlChart.options.scales.x.stacked=true; dlChart.options.scales.y.stacked=true;
      dlChart.options.plugins.legend.display=true;
      dlChart.options.plugins.tooltip.callbacks.title=function(items){return last20[items[0].dataIndex];};
      dlChart.options.plugins.tooltip.callbacks.label=function(c){return ' '+c.dataset.label+': '+fmtVol(c.raw);};
      dlChart.update();
    }
    function switchToNormal(){
      dlMode='normal';
      dlChart.data.labels=symbols;
      dlChart.data.datasets=[{
        label:'Volumen '+latestDate, data:currentVols,
        backgroundColor:symbols.map(function(_,j){return DL_COLORS[j%DL_COLORS.length]+'BB';}),
        borderColor:symbols.map(function(_,j){return DL_COLORS[j%DL_COLORS.length];}),
        borderWidth:1.5, borderRadius:5, barPercentage:0.6, categoryPercentage:0.9, order:1
      }];
      dlChart.options.scales.x.stacked=false; dlChart.options.scales.y.stacked=false;
      dlChart.options.plugins.legend.display=false;
      dlChart.options.plugins.tooltip.callbacks.title=function(items){return items[0].label;};
      dlChart.options.plugins.tooltip.callbacks.label=function(c){
        if(c.dataset._isDLOverlay) return ' '+c.dataset.label.replace('__hist_dl_','')+': '+fmtVol(c.raw);
        return ' Hoy: '+fmtVol(c.raw);
      };
      dlChart.update();
    }

    var cardEl = canvas.closest('.mk-chart-card');
    if (cardEl){
      /* Botón 20 Ruedas en el encabezado */
      var cardHead = cardEl.querySelector('.mk-chart-card__head');
      if (cardHead){
        var btn20r = document.createElement('button');
        btn20r.className='mk-trend-btn'; btn20r.style.flexShrink='0';
        btn20r.innerHTML='<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="4" height="18"/><rect x="10" y="8" width="4" height="13"/><rect x="18" y="5" width="4" height="16"/></svg> 20 Ruedas';
        btn20r.addEventListener('click', function(){
          if (dlMode==='20ruedas'){
            btn20r.classList.remove('is-active');
            switchToNormal();
          } else {
            btn20r.classList.add('is-active');
            switchTo20Ruedas();
          }
        });
        cardHead.appendChild(btn20r);
      }

      /* Nav histórico multi-select */
      buildHistNav(cardEl, dates, dl, symbols, dlChart);
    }
  }

  /* ================================================================
     HARD DOLLAR
     ================================================================ */
  function renderHdCurve(items, tbodyId){
    var tb='';
    (items||[]).forEach(function(it){
      var c1=fmtPct(it.ret_1d_pct);
      tb+='<tr><td><strong>'+it.symbol+'</strong></td><td class="num">'+fmtTir(it.tir_pct)+'</td>'+
          '<td class="num">'+fmtDur(it.duration)+'</td><td>'+(it.payment_date||'—')+'</td>'+
          '<td class="num">'+fmtN(it.price,2)+'</td><td class="num">'+fmtN(it.technical_price,2)+'</td>'+
          '<td class="num">'+fmtN(it.parity,2)+'%</td><td class="num '+c1.cls+'">'+c1.html+'</td></tr>';
    });
    document.getElementById(tbodyId).innerHTML=tb;
  }

  function buildHdChart(canvasId, items, lineColor){
    var rows=(items||[]).slice().sort(function(a,b){return a.duration-b.duration;});
    if (!rows.length) return;
    charts[canvasId] = new Chart(document.getElementById(canvasId),{
      type:'scatter',
      data:{datasets:[{
        label:'TIR vs Duration', _symColor:CHARCOAL,
        data:rows.map(function(r){return {x:r.duration,y:r.tir_pct,sym:r.symbol,d1:r.ret_1d_pct};}),
        backgroundColor:rows.map(function(r){return (r.ret_1d_pct>=0?GREEN:RED)+'CC';}),
        borderColor:rows.map(function(r){return r.ret_1d_pct>=0?GREEN:RED;}),
        pointRadius:9, pointHoverRadius:11, borderWidth:1.5, order:1
      }]},
      options:{
        responsive:true, maintainAspectRatio:false,
        plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){
          if(!c.raw||!c.raw.sym) return '';
          var d1Str=(c.raw.d1!=null?(c.raw.d1>=0?'+':'')+Number(c.raw.d1).toFixed(2)+'%':'—');
          return c.raw.sym+' | TIR: '+Number(c.raw.y).toFixed(2)+'% | Dur: '+Number(c.raw.x).toFixed(2)+'y | 1D: '+d1Str;
        }}}},
        scales:{
          x:Object.assign({title:{display:true,text:'Duration (años)',color:'#6E7679'}},scaleX),
          y:Object.assign({title:{display:true,text:'TIR (%)',color:'#6E7679'},ticks:{color:'#6E7679',callback:function(v){return v.toFixed(2)+'%';}}},scaleY)
        }
      },
      plugins:[symLabelPlugin]
    });
  }

  function buildChartsHD(hd, hdHistory){
    var hdA=(hd&&hd.a_curve)||[], hdG=(hd&&hd.g_curve)||[];
    buildHdChart('chartHdA', hdA, TEAL);
    buildHdChart('chartHdG', hdG, ORANGE);
    activateCurveHistNav('chartHdA', 'chartHdA', hdHistory, 'A', 'trendBtnHdA');
    activateCurveHistNav('chartHdG', 'chartHdG', hdHistory, 'G', 'trendBtnHdG');
    makeTrendToggle('trendBtnHdA', function(){return charts['chartHdA'];}, hdA, 'tir_pct', TEAL_DARK);
    makeTrendToggle('trendBtnHdG', function(){return charts['chartHdG'];}, hdG, 'tir_pct', ORANGE);
  }

  /* ================================================================
     BOOT
     ================================================================ */

  function setupDownloads(D) {
    if (!window.EcoGo) return;
    EcoGo.dlBtn('#chartTasaFija', 'tasa_fija_curva.csv', function(){
      var fc = D.fixed_curve || [];
      return {
        headers: ['Simbolo','Familia','TIR (%)','Duration (anos)','Vencimiento','Volumen'],
        rows: fc.map(function(r){ return [r.symbol, r.family, r.tir_pct, r.duration, r.maturity_date, r.volume]; })
      };
    });
    EcoGo.dlBtn('#chartCer', 'cer_curva.csv', function(){
      var cc = D.cer_curve || [];
      return {
        headers: ['Simbolo','TIR real (%)','Duration (anos)','Pago','Precio','Paridad (%)','Volumen'],
        rows: cc.map(function(r){ return [r.symbol, r.tir_pct, r.duration, r.payment_date, r.price, r.parity, r.volume]; })
      };
    });
    EcoGo.dlBtn('#chartDolarLinked', 'dolar_linked.csv', function(){
      var dl = D.dollar_linked || {};
      var syms = dl.symbols || [];
      var hist = dl.history || {};
      var dates = Object.keys(hist).sort();
      if (!dates.length) {
        var lat = dl.latest || [];
        return {
          headers: ['Simbolo','TIR (%)','Duration'],
          rows: lat.map(function(r){ return [r.symbol, r.tir_pct, r.duration]; })
        };
      }
      return {
        headers: ['Fecha'].concat(syms),
        rows: dates.map(function(d){
          return [d].concat(syms.map(function(s){ return (hist[d] && hist[d][s] !== undefined) ? hist[d][s] : ''; }));
        })
      };
    });
    EcoGo.dlBtn('#chartHdA', 'hard_dollar_ars.csv', function(){
      var hd = (D.hard_dollar && D.hard_dollar.a_curve) || [];
      return {
        headers: ['Simbolo','TIR (%)','Duration (anos)','Paridad (%)','Precio','Volumen'],
        rows: hd.map(function(r){ return [r.symbol, r.tir_pct, r.duration, r.parity, r.price, r.volume]; })
      };
    });
    EcoGo.dlBtn('#chartHdG', 'hard_dollar_gd.csv', function(){
      var hd = (D.hard_dollar && D.hard_dollar.g_curve) || [];
      return {
        headers: ['Simbolo','TIR (%)','Duration (anos)','Paridad (%)','Precio','Volumen'],
        rows: hd.map(function(r){ return [r.symbol, r.tir_pct, r.duration, r.parity, r.price, r.volume]; })
      };
    });
  }

  document.addEventListener('DOMContentLoaded', function(){
    var D = window.MERCADOS_DATA;
    if (!D){
      document.getElementById('mkError').style.display='';
      document.getElementById('mkError').textContent='No se encontro window.MERCADOS_DATA. Corra actualizar_mercados.py para generar los datos.';
      document.getElementById('mkLoading').style.display='none';
      return;
    }
    var latestDate=(D.external_context&&D.external_context.latest_date)
                  ||(D.meta&&D.meta.generated_at&&D.meta.generated_at.slice(0,10))||'--';
    document.getElementById('mkDate').textContent='Datos al: '+latestDate;

    renderHero(D.hero_metrics);
    renderTasaFija(D.fixed_curve);
    renderRentaVariable(D.overview&&D.overview.categories);
    renderCer(D.cer_curve);
    renderDolarLinked(D.dollar_linked);
    renderHdCurve((D.hard_dollar&&D.hard_dollar.a_curve)||[], 'bodyHdA');
    renderHdCurve((D.hard_dollar&&D.hard_dollar.g_curve)||[], 'bodyHdG');

    chartBuilt['tasa-fija'] = true;
    buildChartTasaFija(D.fixed_curve, D.fixed_curve_history);
    makeTrendToggle('trendBtnTasaFija', function(){return charts['chartTasaFija'];}, D.fixed_curve||[], 'tir_pct', TEAL_DARK);

    setupTabs(D);
    setupDownloads(D);

    document.getElementById('mkLoading').style.display='none';
    document.getElementById('mkContent').style.display='';
  });
})();
