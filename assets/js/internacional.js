/* ============================================================
   ECO GO — Internacional · Monitor mundial
   ============================================================ */
(function(){
  const D = window.INTERNACIONAL_DATA;
  if (!D) { console.error("INTERNACIONAL_DATA no disponible"); return; }

  const TEAL_DARK='#1B5F5E', TEAL='#3C9794', TEAL_LITE='#8FCCCA';
  const RED='#DA4531', ORANGE='#FE8B5F', CHARCOAL='#333333', GRAY='#A8B0B1';

  // Mapping ISO3 → emoji bandera (subset común)
  const FLAGS = {
    ARG:'🇦🇷', AUS:'🇦🇺', BRA:'🇧🇷', CAN:'🇨🇦', CHN:'🇨🇳', DEU:'🇩🇪', FRA:'🇫🇷',
    GBR:'🇬🇧', IND:'🇮🇳', IDN:'🇮🇩', ITA:'🇮🇹', JPN:'🇯🇵', KOR:'🇰🇷', MEX:'🇲🇽',
    RUS:'🇷🇺', SAU:'🇸🇦', ZAF:'🇿🇦', TUR:'🇹🇷', USA:'🇺🇸'
  };

  function fmt(v, dec){
    dec = (dec===undefined) ? 1 : dec;
    if (v === null || v === undefined || isNaN(v)) return '—';
    return Number(v).toLocaleString('es-AR', {minimumFractionDigits:dec, maximumFractionDigits:dec});
  }
  function fmtChange(v, dec){
    dec = (dec===undefined) ? 1 : dec;
    if (v === null || v === undefined || isNaN(v)) return '—';
    const s = Number(v).toLocaleString('es-AR', {minimumFractionDigits:dec, maximumFractionDigits:dec});
    return (v > 0 ? '+' : '') + s;
  }
  function fmtPeriod(p){
    if (!p) return '—';
    // "2026-03" → "mar-2026"
    const MESES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
    const m = String(p).match(/^(\d{4})-(\d{2})/);
    if (m) return MESES[+m[2]-1] + '-' + m[1];
    if (String(p).match(/^(\d{4})-Q(\d)/)) return 'T'+RegExp.$2+'-'+RegExp.$1;
    return String(p);
  }
  function norm(s){
    return (s||'').toString().toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9 ]/g, '');
  }

  // Setup global
  function setupTabs(){
    const nav = document.getElementById('intlTabsNav');
    nav.addEventListener('click', function(e){
      const btn = e.target.closest('.eg-tabs__btn'); if (!btn) return;
      const tab = btn.dataset.tab;
      nav.querySelectorAll('.eg-tabs__btn').forEach(function(b){ b.classList.toggle('is-active', b === btn); });
      document.querySelectorAll('.eg-tab-panel').forEach(function(p){ p.hidden = (p.id !== 'panel-' + tab); });
    });
  }

  function setupLastUpdate(){
    const dt = new Date(D.metadata.generatedAt);
    document.getElementById('intlLastUpdate').textContent = 'Actualizado: ' + dt.toLocaleDateString('es-AR', {day:'2-digit', month:'long', year:'numeric'});
  }

  function getIndicator(id){ return D.indicators.find(function(i){ return i.id === id; }); }
  function getCountry(iso){  return D.countries.find(function(c){ return c.iso3 === iso; }); }

  /* ============================================================
     TAB 1 · HERO CHART + SIDE FILTER
     ============================================================ */
  let heroChartInstance = null;
  const heroState = { country:'ARG', indicator:'inflationYoy' };

  function populateHeroFilters(){
    const selC = document.getElementById('heroCountry');
    const selI = document.getElementById('heroIndicator');
    selC.innerHTML = D.countries.slice().sort(function(a,b){ return a.name.localeCompare(b.name); })
      .map(function(c){
        const flag = FLAGS[c.iso3] || '';
        return '<option value="' + c.iso3 + '"' + (c.iso3===heroState.country?' selected':'') + '>' + flag + ' ' + c.name + '</option>';
      }).join('');
    selI.innerHTML = D.indicators.map(function(i){
      return '<option value="' + i.id + '"' + (i.id===heroState.indicator?' selected':'') + '>' + i.label + '</option>';
    }).join('');
    selC.addEventListener('change', function(e){ heroState.country = e.target.value; renderHero(); });
    selI.addEventListener('change', function(e){ heroState.indicator = e.target.value; renderHero(); });
  }

  function getSeries(iso, indId){
    return (D.series[iso] && D.series[iso][indId]) ? D.series[iso][indId] : null;
  }

  function renderHero(){
    const c = getCountry(heroState.country);
    const ind = getIndicator(heroState.indicator);
    const s = getSeries(heroState.country, heroState.indicator);

    document.getElementById('heroChartTitle').textContent = (FLAGS[c.iso3]||'') + ' ' + c.name + ' · ' + ind.label;
    const subt = (s && s.latest) ?
      fmt(s.latest.value, ind.precision) + ind.unit + ' en ' + fmtPeriod(s.latest.period) +
      (s.latest.change !== null && s.latest.change !== undefined ? '; ' + fmtChange(s.latest.change, 1) + ' p.p. vs previo' : '')
      : 'Sin datos';
    document.getElementById('heroChartSub').textContent = subt;
    document.getElementById('heroSource').textContent = s ? (s.sourceName || s.source || '—') : '—';

    // KPI lateral
    const kpiHtml = (s && s.latest) ?
      '<div class="intl-filter-card__kpi-label">Último dato</div>' +
      '<div class="intl-filter-card__kpi-value">' + fmt(s.latest.value, ind.precision) + ind.unit + '</div>' +
      '<div class="intl-filter-card__kpi-sub">' + fmtPeriod(s.latest.period) + ' · ' +
        (s.latest.change!=null ? (fmtChange(s.latest.change, 1) + ' p.p. vs previo') : 's/d') +
      '</div>' +
      (s.sourceUrl ? '<a href="' + s.sourceUrl + '" target="_blank" rel="noopener" class="intl-source-link">Ver fuente ↗</a>' : '')
      : '<div class="intl-filter-card__kpi-label">Sin datos disponibles</div>';
    document.getElementById('heroKpi').innerHTML = kpiHtml;

    // Chart
    Chart.defaults.font.family = "'HK Grotesk', system-ui, sans-serif";
    Chart.defaults.color = CHARCOAL;
    if (heroChartInstance) heroChartInstance.destroy();

    const values = (s && s.values) ? s.values.slice() : [];
    // Limitar a últimos 36 puntos para que se vea bien
    const last = values.slice(-36);
    const color = ind.color || TEAL;

    heroChartInstance = new Chart(document.getElementById('heroChart'), {
      type:'line',
      data:{
        labels: last.map(function(p){ return p.date; }),
        datasets:[{
          label: ind.label,
          data: last.map(function(p){ return p.value; }),
          borderColor: color, backgroundColor: color + '22',
          borderWidth: 2.5, tension:.25, pointRadius:0,
          fill: 'origin', spanGaps: true
        }]
      },
      options:{
        responsive:true, maintainAspectRatio:false,
        interaction:{ mode:'index', intersect:false },
        plugins:{
          legend:{ display:false },
          tooltip:{ callbacks:{
            title: function(items){ if(!items.length) return ''; return fmtPeriod(items[0].label && items[0].label.slice(0,7) || ''); },
            label: function(c){ return fmt(c.parsed.y, ind.precision) + ind.unit; }
          }}
        },
        scales:{
          x:{ type:'time', time:{ unit:'month', displayFormats:{month:'yyyy-MM'} },
              ticks:{ color:'#6E7679', maxTicksLimit:8, autoSkip:true }, grid:{ color:'rgba(0,0,0,0.04)' } },
          y:{ ticks:{ color:'#6E7679', callback:function(v){return fmt(v, ind.precision) + ind.unit;} },
              grid:{ color:'rgba(0,0,0,0.06)' } }
        }
      }
    });
  }

  /* ============================================================
     COMPARATIVO DINÁMICO
     ============================================================ */
  const compState = {
    countries: new Set(['ARG','BRA','MEX','USA','DEU']),
    indicator: 'inflationYoy',
    search: ''
  };

  function populateCompFilters(){
    const selI = document.getElementById('compIndicator');
    selI.innerHTML = D.indicators.map(function(i){
      return '<option value="' + i.id + '"' + (i.id===compState.indicator?' selected':'') + '>' + i.label + '</option>';
    }).join('');
    selI.addEventListener('change', function(e){ compState.indicator = e.target.value; renderComp(); });
    document.getElementById('compSearch').addEventListener('input', function(e){
      compState.search = e.target.value;
      renderCompChips();
    });
    document.getElementById('btnVerTodo').addEventListener('click', function(){
      D.countries.forEach(function(c){ compState.countries.add(c.iso3); });
      renderCompChips();
      renderComp();
    });
    document.getElementById('btnLimpiar').addEventListener('click', function(){
      compState.countries.clear();
      // Default: arg solo
      compState.countries.add('ARG');
      renderCompChips();
      renderComp();
    });
  }

  function renderCompChips(){
    const wrap = document.getElementById('compCountriesPick');
    const query = norm(compState.search);
    const list = D.countries.slice().sort(function(a,b){ return a.name.localeCompare(b.name); })
      .filter(function(c){
        if (!query) return true;
        return norm(c.name).indexOf(query) >= 0;
      });
    wrap.innerHTML = list.map(function(c){
      const active = compState.countries.has(c.iso3);
      const flag = FLAGS[c.iso3] || '';
      return '<button class="intl-chip' + (active ? ' is-active' : '') + '" data-iso="' + c.iso3 + '">' +
        '<span class="intl-chip__flag">' + flag + '</span>' + c.name + '</button>';
    }).join('');
    wrap.querySelectorAll('.intl-chip').forEach(function(btn){
      btn.addEventListener('click', function(){
        const iso = btn.dataset.iso;
        if (compState.countries.has(iso)) compState.countries.delete(iso);
        else compState.countries.add(iso);
        renderCompChips();
        renderComp();
      });
    });
    document.getElementById('compCount').textContent =
      compState.countries.size + ' país' + (compState.countries.size===1?'':'es') + ' seleccionado' + (compState.countries.size===1?'':'s');
  }

  function renderComp(){
    const ind = getIndicator(compState.indicator);
    const rank = ind.rank || 'descending';

    // Construir filas
    const rows = [];
    compState.countries.forEach(function(iso){
      const c = getCountry(iso);
      const s = getSeries(iso, compState.indicator);
      const latest = s ? s.latest : null;
      rows.push({
        iso: iso, name: c.name, highlight: !!c.highlight,
        value: latest ? latest.value : null,
        period: latest ? latest.period : null,
        change: latest ? latest.change : null,
        prevValue: latest ? latest.previousValue : null,
        prevPeriod: latest ? latest.previousPeriod : null,
        source: s ? (s.sourceName || s.source) : '—'
      });
    });
    // Ordenar
    rows.sort(function(a, b){
      const av = a.value, bv = b.value;
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      return (rank === 'ascending') ? (av - bv) : (bv - av);
    });

    const tbl = document.getElementById('compTable');
    if (!rows.length) {
      tbl.innerHTML = '<tbody><tr><td class="intl-cuadro__empty">Seleccioná al menos un país.</td></tr></tbody>';
      return;
    }
    let html = '<thead><tr><th>#</th><th>País</th><th class="num">Valor</th><th>Período</th><th class="num">vs previo</th><th>Fuente</th></tr></thead><tbody>';
    rows.forEach(function(r, i){
      const cls = r.highlight ? ' class="is-highlight"' : '';
      const flag = FLAGS[r.iso] || '';
      const chCls = r.change > 0 ? ' pos' : (r.change < 0 ? ' neg' : '');
      html += '<tr' + cls + '>' +
        '<td class="num">' + (i+1) + '</td>' +
        '<td><span class="flag">' + flag + '</span>' + r.name + '</td>' +
        '<td class="num">' + fmt(r.value, ind.precision) + ind.unit + '</td>' +
        '<td>' + fmtPeriod(r.period) + '</td>' +
        '<td class="num' + chCls + '">' + (r.change !== null ? fmtChange(r.change, 1) + ' p.p.' : '—') + '</td>' +
        '<td style="font-size:.72rem; color:var(--color-text-muted)">' + (r.source || '—') + '</td>' +
        '</tr>';
    });
    html += '</tbody>';
    tbl.innerHTML = html;
  }

  /* ============================================================
     TAB 2 · RANKING
     ============================================================ */
  function renderRanking(){
    const grid = document.getElementById('rankingGrid');
    let html = '';
    D.indicators.forEach(function(ind){
      const rows = [];
      D.countries.forEach(function(c){
        const s = getSeries(c.iso3, ind.id);
        if (s && s.latest && s.latest.value !== null) {
          rows.push({
            iso:c.iso3, name:c.name, highlight: !!c.highlight,
            value: s.latest.value, period: s.latest.period, change: s.latest.change
          });
        }
      });
      const desc = ind.rank !== 'ascending';
      rows.sort(function(a,b){ return desc ? (b.value - a.value) : (a.value - b.value); });

      html += '<div class="ranking-card">' +
        '<div class="ranking-card__head">' +
          '<h3 class="ranking-card__title">' + ind.label + '</h3>' +
          '<span class="ranking-card__meta">' + (desc ? 'Mayor → menor' : 'Menor → mayor') + ' · ' + ind.unit + '</span>' +
        '</div>' +
        '<ul class="ranking-card__list">';
      rows.forEach(function(r, i){
        const flag = FLAGS[r.iso] || '';
        html += '<li' + (r.highlight ? ' class="is-highlight"' : '') + '>' +
          '<span class="ranking-card__pos">#' + String(i+1).padStart(2,'0') + '</span>' +
          '<div>' +
            '<div class="ranking-card__name">' + flag + ' ' + r.name + '</div>' +
            '<div class="ranking-card__sub">' + fmtPeriod(r.period) +
              (r.change!=null ? ' · ' + fmtChange(r.change, 1) + ' p.p. vs previo' : '') +
            '</div>' +
          '</div>' +
          '<span class="ranking-card__val">' + fmt(r.value, ind.precision) + ind.unit + '</span>' +
          '</li>';
      });
      html += '</ul></div>';
    });
    grid.innerHTML = html;
  }

  /* ============================================================
     TAB 3 · CALENDARIO
     ============================================================ */
  function renderCalendar(){
    const list = document.getElementById('calList');
    const items = (D.calendar || []).slice().sort(function(a,b){ return (a.date||'').localeCompare(b.date||''); });
    if (!items.length) {
      list.innerHTML = '<div class="intl-cuadro__empty">No hay eventos próximos.</div>';
      return;
    }
    list.innerHTML = items.map(function(ev){
      const flag = FLAGS[ev.countryIso3] || '';
      const imp = (ev.importance || 'media').toLowerCase();
      const dt = ev.date ? new Date(ev.date + 'T00:00:00') : null;
      const day = dt ? dt.toLocaleDateString('es-AR', {day:'2-digit', month:'short'}) : '—';
      const year = dt ? dt.getFullYear() : '';
      const ind = getIndicator(ev.indicator);
      return '<div class="cal-item is-imp-' + imp + '">' +
        '<div>' +
          '<div class="cal-item__date">' + day + '</div>' +
          '<div class="cal-item__sub">' + year + '</div>' +
        '</div>' +
        '<div>' +
          '<div class="cal-item__title">' + (ev.title || '—') + '</div>' +
          '<div class="cal-item__country">' + flag + ' ' + (ev.countryName || ev.countryIso3 || '—') +
            (ev.sourceName ? ' · ' + ev.sourceName : '') + '</div>' +
        '</div>' +
        '<span class="cal-item__indicator">' + (ind ? ind.label : (ev.indicator || '')) + '</span>' +
        '</div>';
    }).join('');
  }


  function setupDownloads() {
    var D = window.INTERNACIONAL_DATA;
    if (!D || !window.EcoGo) return;
    EcoGo.dlBtn('#heroChart', 'internacional_ranking.csv', function(){
      var countries = D.countries || [];
      var indicators = D.indicators || [];
      var headers = ['Pais', 'ISO3'].concat(indicators.map(function(i){ return i.label || i.id; }));
      var rows = countries.map(function(c){
        var row = [c.name, c.iso3];
        indicators.forEach(function(ind){
          var ser = D.series[c.iso3] && D.series[c.iso3][ind.id];
          if (ser && ser.length) {
            var last = ser[ser.length - 1];
            row.push(last.value !== undefined ? last.value : (last.y || ''));
          } else { row.push(''); }
        });
        return row;
      });
      return { headers: headers, rows: rows };
    });
  }

  /* ============================================================
     Boot
     ============================================================ */
  document.addEventListener('DOMContentLoaded', function(){
    setupTabs();
    setupLastUpdate();
    populateHeroFilters();
    renderHero();
    populateCompFilters();
    renderCompChips();
    renderComp();
    renderRanking();
    renderCalendar();
    setupDownloads();
  });
})();
