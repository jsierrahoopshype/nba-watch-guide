/* Progressive enhancement only. Every fact on the page is already in the HTML.
   This file switches the market toggle, shows kick-off times in the reader's
   own zone, and refreshes availability badges from the published JSON. */
(function () {
  'use strict';

  var PREFIX = '/how-to-watch';
  var STALE_MINUTES = 90;
  var STORE_KEY = 'hm-watch-market';

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  /* ---------------- market toggle ---------------- */

  function setMarket(state) {
    $$('[data-state-panel]').forEach(function (panel) {
      panel.hidden = panel.getAttribute('data-state-panel') !== state;
    });
    $$('[data-state-btn]').forEach(function (btn) {
      btn.setAttribute('aria-selected', String(btn.getAttribute('data-state-btn') === state));
    });
    try { localStorage.setItem(STORE_KEY, state); } catch (e) { /* private mode */ }
  }

  function initToggle() {
    var buttons = $$('[data-state-btn]');
    if (!buttons.length) return;
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () { setMarket(btn.getAttribute('data-state-btn')); });
    });
    var saved = null;
    try { saved = localStorage.getItem(STORE_KEY); } catch (e) { /* ignore */ }
    if (saved && $('[data-state-panel="' + saved + '"]')) setMarket(saved);
  }

  /* ---------------- local kick-off times ---------------- */

  function initLocalTimes() {
    var nodes = $$('[data-utc]');
    if (!nodes.length) return;
    nodes.forEach(function (node) {
      var when = new Date(node.getAttribute('data-utc'));
      if (isNaN(when.getTime())) return;
      var opts = { hour: 'numeric', minute: '2-digit' };
      if (node.hasAttribute('data-with-date')) { opts.weekday = 'short'; opts.month = 'short'; opts.day = 'numeric'; }
      var local = when.toLocaleString([], opts);
      var zone = '';
      try { zone = new Intl.DateTimeFormat([], { timeZoneName: 'short' })
        .formatToParts(when).filter(function (p) { return p.type === 'timeZoneName'; })[0].value; } catch (e) { /* ignore */ }
      var slot = node.querySelector('[data-local-slot]');
      if (slot) slot.textContent = local + (zone ? ' ' + zone : '');
    });
  }

  /* ---------------- freshness ---------------- */

  function minutesSince(iso) {
    var then = new Date(iso);
    if (isNaN(then.getTime())) return null;
    return Math.max(0, Math.round((Date.now() - then.getTime()) / 60000));
  }

  function inEveningWindow() {
    // 12:00 to 01:00 Eastern, worked out from the reader's clock via the
    // Intl API so it does not matter where they are.
    var parts;
    try {
      parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York', hour: 'numeric', hour12: false
      }).formatToParts(new Date());
    } catch (e) { return true; }
    var hour = parseInt((parts.filter(function (p) { return p.type === 'hour'; })[0] || {}).value, 10);
    if (isNaN(hour)) return true;
    return hour >= 12 || hour < 1;
  }

  function showUpdated(updatedAt, hasGamesToday) {
    var mins = minutesSince(updatedAt);
    if (mins === null) return;
    $$('[data-updated]').forEach(function (node) {
      node.textContent = node.getAttribute('data-updated-prefix') || 'Updated';
      node.textContent += ' ' + (mins < 1 ? 'just now' : mins + ' min ago');
    });
    var stale = $('[data-stale-notice]');
    if (stale && hasGamesToday && mins > STALE_MINUTES && inEveningWindow()) {
      stale.classList.remove('is-hidden');
    }
  }

  /* ---------------- availability badges ---------------- */

  var BADGE_CLASS = {
    'Out': 'badge-out',
    'Doubtful': 'badge-doubtful',
    'Questionable': 'badge-questionable',
    'Probable': 'badge-probable',
    'Available': 'badge-available'
  };

  function applyStatuses(byPlayer) {
    $$('[data-player]').forEach(function (node) {
      var status = byPlayer[node.getAttribute('data-player')];
      if (!status) return;
      var slot = node.querySelector('[data-status-slot]');
      if (!slot || slot.textContent.trim() === status) return;
      slot.textContent = status;
      slot.className = 'badge ' + (BADGE_CLASS[status] || 'badge-tba');
    });
  }

  function refresh() {
    var wantsTonight = !!$('[data-tonight]');
    var url = PREFIX + '/data/' + (wantsTonight ? 'tonight.json' : 'injuries.json');
    fetch(url, { cache: 'no-store' }).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (data) {
      if (!data) return;
      var byPlayer = {};
      (data.players || []).forEach(function (p) { byPlayer[p.player] = p.status; });
      (data.games || []).forEach(function (g) {
        (g.players || []).forEach(function (p) { byPlayer[p.player] = p.status; });
      });
      applyStatuses(byPlayer);
      showUpdated(data.updated_at, data.has_games_today !== false);
    }).catch(function () { /* keep the prerendered values */ });
  }

  function init() {
    initToggle();
    initLocalTimes();
    if ($('[data-player]') || $('[data-updated]')) refresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
