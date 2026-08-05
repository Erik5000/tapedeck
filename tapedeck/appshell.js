/* TAPEDECK app shell — injected into the dashboard by tapedeck/server.py.
 *
 * Adds Refresh / Rescan-VWAP buttons to the page's existing .controls row so
 * they inherit its styling and theme, and drives them off /api/status. The
 * dashboard itself is untouched: this file only ever appends.
 */
(function () {
  'use strict';

  var SPINNER = ['◐', '◓', '◑', '◒'];
  var POLL_MS = 1000;

  // Everything here is expressed in the page's own CSS variables, so the modal
  // follows the theme toggle without being told which theme is on.
  var EDITOR_CSS =
    '.tded-wrap{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:999;' +
      'display:none;align-items:center;justify-content:center;padding:24px}' +
    '.tded-box{background:var(--page);color:var(--ink);border:1px solid var(--border);' +
      'border-radius:10px;width:min(1200px,100%);max-height:100%;display:flex;' +
      'flex-direction:column;font:13px/1.45 ui-monospace,"SF Mono",Menlo,Consolas,monospace}' +
    '.tded-head{display:flex;gap:10px;align-items:center;padding:10px 12px;' +
      'border-bottom:1px solid var(--border)}' +
    '.tded-note{font-size:11px;color:var(--muted)}' +
    '.tded-note.bad{color:#e53e3e}' +
    '.tded-body{display:flex;gap:0;min-height:0;flex:1}' +
    '.tded-side{width:220px;flex:none;border-right:1px solid var(--border);' +
      'overflow-y:auto;padding:8px;display:flex;flex-direction:column;gap:4px}' +
    '.tded-list{display:flex;flex-direction:column;align-items:flex-start;gap:1px;' +
      'text-align:left;font:inherit;color:var(--ink);background:transparent;' +
      'border:1px solid transparent;border-radius:6px;padding:5px 8px;cursor:pointer}' +
    '.tded-list:hover{border-color:var(--border)}' +
    '.tded-list.on{border-color:var(--ink2);background:var(--surface)}' +
    '.tded-sub{font-size:11px;color:var(--muted)}' +
    '.tded-sub.bad{color:#e53e3e}' +
    '.tded-new{margin-top:6px}' +
    '.tded-pane{flex:1;min-width:0;overflow:auto;padding:12px}' +
    '.tded-settings{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));' +
      'gap:8px;margin-bottom:14px}' +
    '.tded-field{display:flex;flex-direction:column;gap:2px}' +
    '.tded-lab{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.6px}' +
    '.tded-in{font:inherit;font-size:12px;color:var(--ink);background:var(--surface);' +
      'border:1px solid var(--border);border-radius:5px;padding:3px 6px;width:100%;min-width:0}' +
    '.tded-tbl{border-collapse:collapse;width:100%}' +
    '.tded-tbl th{font-size:10px;color:var(--muted);text-transform:uppercase;' +
      'letter-spacing:.6px;text-align:left;padding:2px 4px;font-weight:400}' +
    '.tded-tbl td{padding:2px 4px}' +
    '.tded-foot{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}' +
    '.tded-danger{margin-left:auto;color:#e53e3e}';

  var els = {};
  var timer = null;
  var frame = 0;
  // Whether we're following a run to its end. The server reports the last job
  // forever, so without this a page load would see state "ok" and reload, and
  // reload, and reload.
  var watching = false;

  function build() {
    var controls = document.querySelector('.controls');
    if (!controls) return false;                 // not a dashboard page

    els.refresh = button('⟳ Refresh', 'refresh');
    els.vwap = button('◇ Rescan VWAP', 'vwap');
    els.lists = document.createElement('button');
    els.lists.className = 'tbtn';
    els.lists.textContent = '✎ Lists';
    els.lists.addEventListener('click', openEditor);
    els.status = document.createElement('span');
    els.status.className = 'tdapp-status';

    // Before .hint, which carries margin-left:auto and would push us to the
    // far edge if we landed after it.
    var hint = controls.querySelector('.hint');
    [els.refresh, els.vwap, els.lists, els.status].forEach(function (el) {
      controls.insertBefore(el, hint);
    });

    var style = document.createElement('style');
    style.textContent =
      '.tdapp-status{color:var(--muted);font-size:11px;margin-left:4px;' +
      'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:46ch}' +
      '.tdapp-status.bad{color:#e53e3e}' +
      '.tbtn[disabled]{opacity:.5;cursor:default}' +
      EDITOR_CSS;
    document.head.appendChild(style);
    return true;
  }

  function button(label, kind) {
    var b = document.createElement('button');
    b.className = 'tbtn';
    b.textContent = label;
    b.dataset.kind = kind;
    b.addEventListener('click', function () { start(kind); });
    return b;
  }

  function say(text, bad) {
    els.status.textContent = text || '';
    els.status.classList.toggle('bad', !!bad);
  }

  function busy(on) {
    els.refresh.disabled = on;
    els.vwap.disabled = on;
  }

  function start(kind) {
    busy(true);
    watching = true;
    say('starting…');
    fetch(kind === 'vwap' ? '/api/vwap' : '/api/refresh', { method: 'POST' })
      .then(function (r) {
        if (r.status === 409) { say('already running', true); return poll(); }
        if (!r.ok) {
          return r.json().catch(function () { return {}; }).then(function (body) {
            busy(false);
            say(body.error || ('could not start (' + r.status + ')'), true);
          });
        }
        poll();
      })
      .catch(function (e) { busy(false); say('server unreachable: ' + e.message, true); });
  }

  function poll() {
    clearTimeout(timer);
    timer = setTimeout(tick, POLL_MS);
  }

  function tick() {
    fetch('/api/status')
      .then(function (r) { return r.json(); })
      .then(render)
      .catch(function () {
        // The refresh restarts nothing server-side, so a blip is not fatal.
        say('waiting for the server…');
        poll();
      });
  }

  function render(s) {
    if (!s.vwap_available) els.vwap.style.display = 'none';

    var job = s.job;
    if (job && job.state === 'running') {
      busy(true);
      watching = true;              // a run started elsewhere, or before a reload
      frame = (frame + 1) % SPINNER.length;
      say(SPINNER[frame] + ' ' + (job.kind === 'vwap' ? 'rescanning' : 'refreshing') +
          ' · ' + (job.last_line || 'starting…'));
      return poll();
    }

    busy(false);
    if (!job || !watching) return say(levels(s));

    watching = false;
    if (job.state === 'ok') {
      say('done — reloading…');
      return window.location.reload();
    }
    if (job.state === 'timeout') return say(job.kind + ' timed out', true);
    if (job.state === 'failed') {
      return say(job.kind + ' failed (exit ' + job.returncode + ') — see the server log', true);
    }
  }

  function levels(s) {
    if (!s.vwap || !s.vwap.generated) return '';
    var age = s.vwap.age_days;
    var when = age === 0 ? 'today' : age === 1 ? '1 day old' : age + ' days old';
    return 'levels: ' + s.vwap.generated + ' (' + when + ')' + (s.vwap.stale ? ' — stale' : '');
  }

  /* ---------------- watchlist editor ----------------
   *
   * A modal over the dashboard: pick a list on the left, edit it on the right,
   * save. Everything reuses the page's own .tbtn / .panel / CSS variables so it
   * follows the theme without knowing which theme is on.
   *
   * The server is the authority on what's valid — it parses every candidate
   * through config.load_config before writing — so this side validates nothing
   * beyond "you must give a ticker", and surfaces whatever the server says.
   */

  var HOLDING_COLS = [
    {key: 'ticker', label: 'Ticker', size: 9},
    {key: 'name', label: 'Name', size: 18},
    {key: 'group', label: 'Group', size: 12},
    {key: 'equity', label: 'Equity', size: 9},
    {key: 'shares', label: 'Shares', size: 7},
    {key: 'cost_basis', label: 'Cost', size: 7},
    {key: 'tv_symbol', label: 'TV symbol', size: 12}
  ];
  var NUMERIC = {shares: 1, cost_basis: 1, order: 1, vwap_alert_pct: 1};
  var SETTINGS = [
    {key: 'title', label: 'Title'},
    {key: 'order', label: 'Tab order'},
    {key: 'benchmark', label: 'Benchmark'},
    {key: 'source', label: 'Source', options: ['yahoo', 'hyperliquid']},
    {key: 'cockpit', label: 'Cockpit file'},
    {key: 'anti_basket', label: 'Anti-basket'},
    {key: 'vwap', label: 'VWAP feed'},
    {key: 'vwap_alert_pct', label: 'VWAP band %'}
  ];

  var ed = {};              // modal element refs
  var model = null;         // the list being edited
  var dirty = false;

  function openEditor() {
    if (!ed.wrap) buildEditor();
    ed.wrap.style.display = 'flex';
    loadLists();
  }

  function closeEditor() {
    if (dirty && !window.confirm('Discard unsaved changes?')) return;
    ed.wrap.style.display = 'none';
    model = null;
    setDirty(false);
  }

  function buildEditor() {
    ed.wrap = el('div', 'tded-wrap');
    var box = el('div', 'tded-box');
    var head = el('div', 'tded-head');
    head.appendChild(el('span', 'ptitle', 'Watchlists'));
    ed.note = el('span', 'tded-note');
    head.appendChild(ed.note);
    var close = el('button', 'tbtn', '✕');
    close.style.marginLeft = 'auto';
    close.addEventListener('click', closeEditor);
    head.appendChild(close);

    var body = el('div', 'tded-body');
    ed.side = el('div', 'tded-side');
    ed.pane = el('div', 'tded-pane');
    body.appendChild(ed.side);
    body.appendChild(ed.pane);

    box.appendChild(head);
    box.appendChild(body);
    ed.wrap.appendChild(box);
    document.body.appendChild(ed.wrap);

    // Click the backdrop to dismiss, but not a click that started inside.
    ed.wrap.addEventListener('mousedown', function (e) {
      if (e.target === ed.wrap) closeEditor();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && ed.wrap.style.display === 'flex') closeEditor();
    });
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function setDirty(on) {
    dirty = on;
    if (ed.save) ed.save.disabled = !on;
    if (ed.saveRun) ed.saveRun.disabled = !on;
  }

  function note(text, bad) {
    ed.note.textContent = text || '';
    ed.note.classList.toggle('bad', !!bad);
  }

  function api(method, path, body) {
    var opts = {method: method, headers: {'Content-Type': 'application/json'}};
    if (body !== undefined) opts.body = JSON.stringify(body);
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) throw new Error(data.error || (method + ' ' + path + ' → ' + r.status));
        return data;
      });
    });
  }

  // loadLists and openList return their promise so a caller can report an
  // outcome *after* the reload settles. Without that, note('saved') is written
  // and then immediately overwritten by openList's own note — the save looked
  // like it had silently done nothing.
  function loadLists(select) {
    return api('GET', '/api/watchlists').then(function (data) {
      ed.side.innerHTML = '';
      data.lists.forEach(function (item) {
        var row = el('button', 'tded-list');
        row.appendChild(el('b', null, item.title));
        var sub = item.error ? 'unreadable' :
          item.count + (item.count === 1 ? ' name' : ' names') +
          (item.source === 'hyperliquid' ? ' · trade.xyz' : '');
        var meta = el('span', item.error ? 'tded-sub bad' : 'tded-sub', sub);
        row.appendChild(meta);
        row.addEventListener('click', function () { openList(item.name); });
        row.dataset.name = item.name;
        ed.side.appendChild(row);
      });
      var add = el('button', 'tbtn tded-new', '+ New list');
      add.addEventListener('click', createList);
      ed.side.appendChild(add);
      var want = select || (model && model.name) ||
        (data.lists[0] && data.lists[0].name);
      if (want) return openList(want);
      ed.pane.innerHTML = '';
    }).catch(function (e) { note(e.message, true); });
  }

  function createList() {
    var name = window.prompt('Name for the new watchlist (letters, digits, dashes):');
    if (!name) return;
    api('POST', '/api/watchlists', {name: name}).then(function (data) {
      setDirty(false);
      return loadLists(data.name).then(function () { note('created ' + data.name); });
    }).catch(function (e) { note(e.message, true); });
  }

  function openList(name) {
    if (dirty && !window.confirm('Discard unsaved changes?')) return Promise.resolve();
    return api('GET', '/api/watchlists/' + encodeURIComponent(name)).then(function (data) {
      model = data;
      setDirty(false);
      note(data.has_comments
        ? 'note: this file has comments — saving rewrites it without them (a backup is kept)'
        : '');
      markActive(name);
      renderPane();
      if (data.source === 'hyperliquid') loadMarkets(data.dex);
    }).catch(function (e) { note(e.message, true); });
  }

  function markActive(name) {
    Array.prototype.forEach.call(ed.side.querySelectorAll('.tded-list'), function (row) {
      row.classList.toggle('on', row.dataset.name === name);
    });
  }

  var markets = [];
  function loadMarkets(dex) {
    api('GET', '/api/markets?dex=' + encodeURIComponent(dex || 'xyz'))
      .then(function (data) {
        markets = data.markets || [];
        var list = document.getElementById('tded-markets');
        if (!list) return;
        list.innerHTML = '';
        markets.forEach(function (m) {
          var o = document.createElement('option');
          o.value = m;
          list.appendChild(o);
        });
      }).catch(function () { /* a picker without autocomplete still types fine */ });
  }

  function renderPane() {
    ed.pane.innerHTML = '';

    var grid = el('div', 'tded-settings');
    SETTINGS.forEach(function (field) {
      var lab = el('label', 'tded-field');
      lab.appendChild(el('span', 'tded-lab', field.label));
      var input;
      if (field.options) {
        input = document.createElement('select');
        field.options.forEach(function (opt) {
          var o = document.createElement('option');
          o.value = o.textContent = opt;
          input.appendChild(o);
        });
        input.value = model[field.key] || field.options[0];
        input.addEventListener('change', function () {
          model[field.key] = input.value;
          setDirty(true);
          if (field.key === 'source' && input.value === 'hyperliquid') loadMarkets(model.dex);
        });
      } else {
        input = document.createElement('input');
        input.value = model[field.key] === null || model[field.key] === undefined
          ? '' : model[field.key];
        input.addEventListener('input', function () {
          model[field.key] = coerce(field.key, input.value);
          setDirty(true);
        });
      }
      input.className = 'tded-in';
      lab.appendChild(input);
      grid.appendChild(lab);
    });
    ed.pane.appendChild(grid);

    var list = document.createElement('datalist');
    list.id = 'tded-markets';
    ed.pane.appendChild(list);

    var table = el('table', 'tded-tbl');
    var thead = document.createElement('thead');
    var hrow = document.createElement('tr');
    HOLDING_COLS.forEach(function (c) { hrow.appendChild(el('th', null, c.label)); });
    hrow.appendChild(el('th', null, ''));
    thead.appendChild(hrow);
    table.appendChild(thead);
    ed.rows = document.createElement('tbody');
    table.appendChild(ed.rows);
    ed.pane.appendChild(table);
    (model.holdings || []).forEach(addRow);

    var foot = el('div', 'tded-foot');
    var add = el('button', 'tbtn', '+ Add ticker');
    add.addEventListener('click', function () {
      var blank = {};
      model.holdings.push(blank);
      addRow(blank);
      setDirty(true);
      var inputs = ed.rows.querySelectorAll('tr:last-child input');
      if (inputs.length) inputs[0].focus();
    });
    ed.save = el('button', 'tbtn', 'Save');
    ed.save.addEventListener('click', function () { save(false); });
    ed.saveRun = el('button', 'tbtn', 'Save & Refresh');
    ed.saveRun.addEventListener('click', function () { save(true); });
    var del = el('button', 'tbtn tded-danger', 'Delete list');
    del.addEventListener('click', removeList);
    foot.appendChild(add);
    foot.appendChild(ed.save);
    foot.appendChild(ed.saveRun);
    foot.appendChild(del);
    ed.pane.appendChild(foot);
    setDirty(false);
  }

  function addRow(holding) {
    var tr = document.createElement('tr');
    HOLDING_COLS.forEach(function (col) {
      var td = document.createElement('td');
      var input = document.createElement('input');
      input.className = 'tded-in';
      input.size = col.size;
      input.value = holding[col.key] === null || holding[col.key] === undefined
        ? '' : holding[col.key];
      if (col.key === 'ticker') input.setAttribute('list', 'tded-markets');
      input.addEventListener('input', function () {
        holding[col.key] = coerce(col.key, input.value);
        setDirty(true);
      });
      td.appendChild(input);
      tr.appendChild(td);
    });
    var td = document.createElement('td');
    var x = el('button', 'tbtn', '✕');
    x.addEventListener('click', function () {
      var at = model.holdings.indexOf(holding);
      if (at >= 0) model.holdings.splice(at, 1);
      tr.remove();
      setDirty(true);
    });
    td.appendChild(x);
    tr.appendChild(td);
    ed.rows.appendChild(tr);
  }

  function coerce(key, raw) {
    var value = String(raw).trim();
    if (!value) return null;                  // empty means "omit the key"
    if (NUMERIC[key]) {
      var n = Number(value);
      return isNaN(n) ? value : n;            // let the server reject the junk
    }
    return value;
  }

  function save(thenRefresh) {
    if (!model) return;
    note('saving…');
    api('PUT', '/api/watchlists/' + encodeURIComponent(model.name), model)
      .then(function (data) {
        model = data;
        setDirty(false);
        if (thenRefresh) {
          closeEditorSilently();
          return start('refresh');
        }
        return loadLists(data.name).then(function () { note('saved'); });
      })
      .catch(function (e) { note(e.message, true); });
  }

  function closeEditorSilently() {
    ed.wrap.style.display = 'none';
    setDirty(false);
  }

  function removeList() {
    if (!model) return;
    if (!window.confirm('Delete "' + model.name + '"? A backup is kept in output/watchlist-backups/.')) return;
    api('DELETE', '/api/watchlists/' + encodeURIComponent(model.name))
      .then(function () {
        model = null;
        setDirty(false);
        return loadLists().then(function () { note('deleted'); });
      })
      .catch(function (e) { note(e.message, true); });
  }

  if (build()) tick();   // an initial read, which also resumes a run in progress
})();
