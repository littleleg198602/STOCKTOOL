(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let result = null, history = [], view = 'signals', visible = [];
  const columns = {
    signals: [['ticker','Akcie'],['final_total_score','Skóre'],['action','Akce'],['forecast','Výhled'],['final_confidence','Důvěra'],['current_price','Cena'],['tech_score','Technika'],['yahoo_score','Yahoo'],['news_score','Zprávy'],['data_quality_score','Kvalita dat']],
    buy: [['ticker','Akcie'],['buy_score','BUY skóre'],['buy_alpha','Alpha'],['buy_status','Stav'],['data_coverage','Pokrytí'],['confidence','Důvěra'],['statement_status','Výkazy']],
    articles: [['ticker','Akcie'],['title','Titulek'],['published_at','Zveřejněno'],['source','Zdroj']],
    history: [['generated_at','Dokončeno'],['count','Akcií'],['learning_status','Učení'],['run_id','Běh']]
  };
  const format = value => value === null || value === undefined ? '—' : typeof value === 'number' ? new Intl.NumberFormat('cs-CZ',{maximumFractionDigits:2}).format(value) : String(value);
  const date = value => { const d = new Date(value); return Number.isNaN(d.valueOf()) ? '—' : d.toLocaleString('cs-CZ'); };
  function cell(tag, value) { const el = document.createElement(tag); el.textContent = value; return el; }
  async function api(path, options = {}) {
    const response = await fetch(path, {credentials:'same-origin', cache:'no-store', ...options});
    if (response.status === 401) { $('login-form').hidden = false; throw new Error('Pro zobrazení výsledků se přihlas.'); }
    if (!response.ok) throw new Error(`Server odpověděl chybou ${response.status}. Zkus obnovit výsledky.`);
    const data = await response.json();
    if (!data.ok) throw new Error('Data nejsou dostupná.');
    return data;
  }
  function values(target, entries) {
    $(target).replaceChildren();
    for (const [label,value] of entries) $(target).append(cell('dt', label), cell('dd', format(value)));
  }
  function detail(row) {
    if (view === 'history') { load(row.revision); return; }
    const signal = (result.signals || []).find(item => item.ticker === row.ticker);
    if (!signal) return;
    $('detail').hidden = false;
    $('detail-title').textContent = row.ticker;
    $('detail-summary').textContent = signal.overall_summary || '';
    values('detail-values', [['Zdroj cen',signal.tech_source_used],['Zdroj aktuální ceny',signal.current_price_source],['Stav učení',signal.learning_status],['Váha učení',signal.learning_weight],['Fundamenty',signal.fundamental_score],['Síla signálu',signal.signal_strength]]);
    $('detail-reasons').replaceChildren();
    for (const field of ['reasons','warnings','action_reasons','blocked_reasons']) {
      let items = signal[field] || [];
      if (typeof items === 'string') { try { items = JSON.parse(items); } catch { items = [items]; } }
      if (Array.isArray(items)) for (const item of items) $('detail-reasons').append(cell('li',format(item)));
    }
  }
  function render() {
    if (!result) return;
    const learning = view === 'learning';
    $('learning').hidden = !learning;
    $('filters').hidden = learning || view === 'history';
    document.querySelector('.score-table').hidden = learning;
    $('detail').hidden = true;
    document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.view === view)));
    if (learning) { $('table-caption').textContent = ''; return; }
    const query = $('search').value.trim().toUpperCase();
    const action = $('action').value;
    const rows = view === 'history' ? history : result[view] || [];
    visible = rows.filter(row => (view === 'history' || !query || String(row.ticker || row.title || '').toUpperCase().includes(query)) && (view !== 'signals' || !action || row.action === action));
    if (view === 'signals') visible.sort((a,b) => (b.final_total_score ?? -1) - (a.final_total_score ?? -1));
    $('table-caption').textContent = `${visible.length} záznamů${view === 'history' ? ' · vyber běh pro zobrazení' : ''}`;
    const header = document.createElement('tr');
    for (const [,label] of columns[view]) { const th = cell('th',label); th.scope = 'col'; header.append(th); }
    $('table-head').replaceChildren(header); $('table-body').replaceChildren();
    for (const row of visible) {
      const tr = document.createElement('tr');
      for (const [key] of columns[view]) {
        const td = document.createElement('td');
        if (key === 'ticker' || (view === 'history' && key === 'generated_at')) {
          const button = cell('button', key === 'generated_at' ? date(row[key]) : format(row[key]));
          button.type = 'button'; button.addEventListener('click', () => detail(row)); td.append(button);
        } else td.textContent = key.endsWith('_at') ? date(row[key]) : format(row[key]);
        tr.append(td);
      }
      $('table-body').append(tr);
    }
  }
  async function load(revision) {
    $('reload').disabled = true;
    try {
      const data = await api(`./api/state.php?kind=results${revision ? '&revision=' + encodeURIComponent(revision) : ''}`);
      $('login-form').hidden = true;
      if (data.empty) { $('results').hidden = true; $('status').textContent = 'Zatím nejsou uložené výsledky. Spusť první výpočet na GitHubu.'; return; }
      result = data;
      history = (await api('./api/state.php?kind=history')).runs;
      $('results').hidden = false;
      const ageDays = (Date.now() - new Date(data.generated_at).valueOf()) / 86400000;
      $('status').textContent = `${revision ? 'Vybraný běh' : 'Poslední dokončený běh'}: ${date(data.generated_at)}${ageDays > 7 ? ' · výsledky jsou starší než 7 dní' : ''}`;
      $('metrics').replaceChildren();
      const counts = (data.signals || []).reduce((acc,row) => { acc[row.action] = (acc[row.action] || 0) + 1; return acc; },{});
      for (const [label,value] of [['Analyzovaných akcií',data.signals.length],['BUY',counts.BUY || 0],['SELL',counts.SELL || 0],['Bez obchodu',counts.NO_TRADE || 0]]) {
        const item = document.createElement('div'); item.className = 'metric'; item.append(cell('span',label),cell('strong',format(value))); $('metrics').append(item);
      }
      const warnings = [...(data.errors || []), ...(data.warnings || [])];
      $('warnings').hidden = warnings.length === 0; $('warning-list').replaceChildren();
      for (const warning of warnings) $('warning-list').append(cell('li',warning));
      $('learning-status').textContent = `Stav tréninku: ${data.learning?.status || 'Neznámý'}`;
      values('learning-values', [['Vzorků',data.learning?.samples ?? data.learning?.total_examples],['Požadováno',data.learning?.required_samples],['Zdroj cen',data.source],['Verze analýzy',data.scoring_version]]);
      if (revision) view = 'signals';
      render();
    } catch (error) { $('status').textContent = error.message; }
    finally { $('reload').disabled = false; }
  }
  $('login-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const key = $('api-key').value;
      await api('../data-manager/api/login.php',{method:'POST',headers:{'X-StockTool-Key':key}});
      $('api-key').value = ''; await load();
    } catch (error) { $('api-key').value = ''; $('status').textContent = error.message; }
  });
  $('reload').addEventListener('click',() => load());
  $('search').addEventListener('input',render); $('action').addEventListener('change',render);
  document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click',() => { view = button.dataset.view; render(); }));
  $('export').addEventListener('click',() => {
    const escape = value => { let text = value === null || value === undefined ? '' : String(value); if (typeof value === 'string' && /^[=+\-@\t\r\n]/.test(text)) text = "'" + text; return '"' + text.replaceAll('"','""') + '"'; };
    const csv = [columns[view].map(([,label]) => escape(label)).join(';'), ...visible.map(row => columns[view].map(([key]) => escape(row[key])).join(';'))].join('\r\n');
    const url = URL.createObjectURL(new Blob(['\uFEFF',csv],{type:'text/csv;charset=utf-8'}));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `johny-${view}.csv`; anchor.click(); URL.revokeObjectURL(url);
  });
  load();
})();
