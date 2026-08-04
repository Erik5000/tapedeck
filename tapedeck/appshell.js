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
    els.status = document.createElement('span');
    els.status.className = 'tdapp-status';

    // Before .hint, which carries margin-left:auto and would push us to the
    // far edge if we landed after it.
    var hint = controls.querySelector('.hint');
    [els.refresh, els.vwap, els.status].forEach(function (el) {
      controls.insertBefore(el, hint);
    });

    var style = document.createElement('style');
    style.textContent =
      '.tdapp-status{color:var(--muted);font-size:11px;margin-left:4px;' +
      'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:46ch}' +
      '.tdapp-status.bad{color:#e53e3e}' +
      '.tbtn[disabled]{opacity:.5;cursor:default}';
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

  if (build()) tick();   // an initial read, which also resumes a run in progress
})();
