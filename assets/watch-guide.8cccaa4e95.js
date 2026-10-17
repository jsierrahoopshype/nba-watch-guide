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

  /* ---------------- local tip-off times ----------------
     One format everywhere: "9:00 pm" plus a zone abbreviation, the same
     shape as the "7:00 pm ET" in the HTML. A time on another calendar day
     than the game's Eastern date gets the local weekday in front. */

  var EASTERN = 'America/New_York';

  function readerIsEastern() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone === EASTERN; }
    catch (e) { return false; }
  }

  function part(parts, type) {
    for (var i = 0; i < parts.length; i++) if (parts[i].type === type) return parts[i].value;
    return '';
  }

  // Intl formatters are slow to build, so each one is made once and reused.
  var FORMATS = {};
  function fmt(locale, opts, key) {
    if (!FORMATS[key]) FORMATS[key] = new Intl.DateTimeFormat(locale, opts);
    return FORMATS[key];
  }

  function clock(when) {
    var parts = fmt('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }, 'clock').formatToParts(when);
    return part(parts, 'hour') + ':' + part(parts, 'minute') + ' ' + part(parts, 'dayPeriod').toLowerCase();
  }

  // "EDT", "PDT", "CEST", "BST", "IST", "AEDT": the first locale that has a
  // real abbreviation for the reader's zone, else the GMT offset.
  function zoneName(when) {
    if (readerIsEastern()) return 'ET';
    var locales = ['en-US', 'en-GB', 'en-AU', 'en-IN'], fallback = '';
    for (var i = 0; i < locales.length; i++) {
      var name = '';
      try {
        name = part(fmt(locales[i], { timeZoneName: 'short' }, 'zone-' + locales[i]).formatToParts(when), 'timeZoneName');
      } catch (e) { /* ignore */ }
      if (!fallback) fallback = name;
      if (name && name.indexOf('GMT') !== 0 && name.indexOf('UTC') !== 0) return name;
    }
    return fallback;
  }

  function dayKey(when, zone) {
    var opts = { year: 'numeric', month: '2-digit', day: '2-digit' };
    if (zone) opts.timeZone = zone;
    var parts = fmt('en-US', opts, 'day-' + (zone || 'local')).formatToParts(when);
    return part(parts, 'year') + '-' + part(parts, 'month') + '-' + part(parts, 'day');
  }

  function weekday(when) {
    return fmt('en-US', { weekday: 'short' }, 'weekday').format(when);
  }

  function dateLabel(when) {
    var parts = fmt('en-US', { weekday: 'short', month: 'short', day: 'numeric' }, 'date').formatToParts(when);
    return part(parts, 'weekday') + ' ' + part(parts, 'month') + ' ' + part(parts, 'day');
  }

  function initLocalTimes(root) {
    $$('[data-utc]', root).forEach(function (node) {
      var when = new Date(node.getAttribute('data-utc'));
      if (isNaN(when.getTime())) return;
      var time, zone;
      try { time = clock(when); zone = zoneName(when); } catch (e) { return; }
      var otherDay = dayKey(when) !== dayKey(when, EASTERN);
      var prefix = '';
      if (node.hasAttribute('data-with-date')) prefix = dateLabel(when) + ', ';
      else if (otherDay) prefix = weekday(when) + ' ';
      var clockSlot = node.querySelector('[data-local-clock]');
      var zoneSlot = node.querySelector('[data-local-zone]');
      var daySlot = node.querySelector('[data-local-day]');
      var slot = node.querySelector('[data-local-slot]');
      if (clockSlot) {
        // The big number: the weekday, when it differs, goes in its own
        // smaller slot in front, followed by a real space so the text reads
        // "Thu 2:00 am" when copied, read aloud or shown without the CSS.
        clockSlot.textContent = time;
        if (daySlot) daySlot.textContent = otherDay ? weekday(when) + ' ' : '';
        if (zoneSlot) zoneSlot.textContent = zone;
      } else if (slot) {
        slot.textContent = prefix + time + (zone ? ' ' + zone : '');
      }
      // The small ET time beside the big one: only worth showing when the
      // reader is not on Eastern time already. It always holds its space.
      var et = node.querySelector('[data-et-extra]');
      if (et && !readerIsEastern()) et.classList.add('is-shown');
    });
  }

  /* ---------------- my team ----------------
     The reader's team, kept on this device only (localStorage
     hm-watch-team; nothing is sent anywhere). On the hub my-team.js has
     already put the saved team's card in place before first paint; this
     wires the picker and Clear, and the team pages' "Make this my team". */

  var TEAM_KEY = 'hm-watch-team';

  function readTeam() {
    try { return localStorage.getItem(TEAM_KEY) || ''; } catch (e) { return ''; }
  }

  function writeTeam(slug) {
    try {
      if (slug) localStorage.setItem(TEAM_KEY, slug); else localStorage.removeItem(TEAM_KEY);
    } catch (e) { /* private mode */ }
  }

  function showHubTeam(slug) {
    var root = $('[data-my-team-root]'), slot = $('[data-my-team-slot]'), tpl = $('#my-team-cards');
    if (!root || !slot || !tpl || !tpl.content) return;
    while (slot.firstChild) slot.removeChild(slot.firstChild);
    var card = /^[a-z0-9-]{2,40}$/.test(slug) ? tpl.content.querySelector('[data-team="' + slug + '"]') : null;
    if (card) {
      slot.appendChild(card.cloneNode(true));
      root.setAttribute('data-saved', slug);
      initLocalTimes(slot);
    } else {
      root.removeAttribute('data-saved');
    }
    var select = $('[data-my-team-select]');
    if (select) select.value = card ? slug : '';
  }

  function initMyTeam() {
    var select = $('[data-my-team-select]');
    if (select) {
      select.addEventListener('change', function () {
        writeTeam(select.value);
        showHubTeam(select.value);
      });
      var clear = $('[data-my-team-clear]');
      if (clear) clear.addEventListener('click', function () {
        writeTeam('');
        showHubTeam('');
        select.focus();
      });
    }
    $$('[data-my-team-btn]').forEach(function (btn) {
      var slug = btn.getAttribute('data-my-team-btn');
      var make = btn.querySelector('.myt-l-make'), mine = btn.querySelector('.myt-l-mine');
      function sync() {
        var on = readTeam() === slug;
        btn.setAttribute('aria-pressed', String(on));
        // Both labels stay in the button (it never resizes); only the one
        // shown is read out.
        if (make) make.setAttribute('aria-hidden', String(on));
        if (mine) mine.setAttribute('aria-hidden', String(!on));
      }
      btn.addEventListener('click', function () {
        writeTeam(readTeam() === slug ? '' : slug);
        sync();
      });
      sync();
    });
  }

  /* ---------------- date chip countdown ----------------
     The build writes "Tonight", "Tomorrow" or "In 21 days" for its own day;
     this redoes the count from today's Eastern date, so a page cached from
     yesterday does not say Tonight a day late. */

  function initCountdowns() {
    var nodes = $$('[data-countdown]');
    if (!nodes.length) return;
    var today;
    try { today = dayKey(new Date(), EASTERN); } catch (e) { return; }
    var t = Date.UTC(+today.slice(0, 4), +today.slice(5, 7) - 1, +today.slice(8, 10));
    nodes.forEach(function (node) {
      var d = node.getAttribute('data-date') || '';
      var g = Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10));
      if (isNaN(g)) return;
      var days = Math.round((g - t) / 86400000);
      var label;
      if (days < 0) { node.hidden = true; return; }
      if (days === 0) label = node.getAttribute(node.hasAttribute('data-evening') ? 'data-l-tonight' : 'data-l-today');
      else if (days === 1) label = node.getAttribute('data-l-tomorrow');
      else label = (node.getAttribute('data-l-days') || '').replace('{n}', String(days));
      if (label && node.textContent !== label) node.textContent = label;
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

  function showUpdated(data) {
    var mins = minutesSince(data.updated_at);
    if (mins !== null) {
      $$('[data-updated]').forEach(function (node) {
        node.textContent = node.getAttribute('data-updated-prefix') || 'Updated';
        node.textContent += ' ' + (mins < 1 ? 'just now' : mins + ' min ago');
      });
    }
    var notice = $('[data-stale-notice]');
    if (!notice || data.has_games_today === false) return;
    // Two ways to be out of date: our own refresh has not run for a while, or
    // the feed itself has not moved on to today.
    var lateRefresh = mins !== null && mins > STALE_MINUTES && inEveningWindow();
    var oldFeed = !data.as_of || (data.date_et && data.as_of < data.date_et);
    if (lateRefresh || oldFeed) notice.classList.remove('is-hidden');
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
      showUpdated(data);
    }).catch(function () { /* keep the prerendered values */ });
  }

  /* ---------------- what am I missing? ----------------
     answer() and cheapest() are a line-for-line port of watchguide/missing.py
     answer() and coverage._cheapest(). tests/test_missing.py runs this file
     under Node against the Python on the same inputs, so they cannot drift.
     The data is embedded in the page; nothing is fetched or sent anywhere. */

  var OWNED_KEY = 'hm-watch-owned';
  // BigInt() rather than 0n/1n literals, so an old browser without BigInt
  // still parses the file and keeps the market toggle and times working.
  var HAS_BIGINT = typeof BigInt !== 'undefined';
  var ZERO = HAS_BIGINT ? BigInt(0) : 0;
  var ONE = HAS_BIGINT ? BigInt(1) : 1;

  function pop(mask) {
    var n = 0;
    while (mask > ZERO) { n += Number(mask & ONE); mask >>= ONE; }
    return n;
  }

  function round2(x) { return Math.round(x * 100) / 100; }

  function effectivePrice(opt, byId, owned) {
    if (opt.price === null) return null;
    var price = opt.price;
    for (var i = 0; i < opt.req.length; i++) {
      var rid = opt.req[i];
      if (owned[rid]) continue;
      var req = byId[rid];
      if (!req || req.price === null) return null;
      price += req.price;
    }
    return round2(price);
  }

  function combinations(items, size, visit) {
    var idx = [];
    for (var i = 0; i < size; i++) idx.push(i);
    while (true) {
      visit(idx.map(function (k) { return items[k]; }));
      var j = size - 1;
      while (j >= 0 && idx[j] === items.length - size + j) j--;
      if (j < 0) return;
      idx[j]++;
      for (var k = j + 1; k < size; k++) idx[k] = idx[k - 1] + 1;
    }
  }

  function keyLess(a, b) {
    for (var i = 0; i < a.length; i++) {
      if (a[i] < b[i]) return true;
      if (a[i] > b[i]) return false;
    }
    return false;
  }

  // coverage._cheapest: cheapest subset covering at least `target` games.
  function cheapest(priced, masks, total, target) {
    if (!total || !target || !priced.length) return null;
    var sorted = priced.slice().sort(function (a, b) {
      return (a.price - b.price) || (pop(masks[b.id]) - pop(masks[a.id]));
    });
    var kept = [];
    sorted.forEach(function (svc) {
      var m = masks[svc.id];
      var dominated = kept.some(function (k) { return (m | masks[k.id]) === masks[k.id] && k.price <= svc.price; });
      if (!dominated) kept.push(svc);
    });
    var best = null, bestCombo = null, bestMask = ZERO;
    var prices = kept.map(function (s) { return s.price; }).sort(function (a, b) { return a - b; });
    for (var size = 1; size <= kept.length; size++) {
      if (best !== null && size > bestCombo.length) {
        var possible = 0;
        for (var p = 0; p < size; p++) possible += prices[p];
        if (possible > best[0]) break;
      }
      combinations(kept, size, function (combo) {
        var mask = ZERO, sum = 0;
        combo.forEach(function (s) { mask |= masks[s.id]; sum += s.price; });
        var covered = pop(mask);
        if (covered < target) return;
        var key = [round2(sum), combo.length, -covered];
        if (best === null || keyLess(key, best)) { best = key; bestCombo = combo; bestMask = mask; }
      });
    }
    if (bestCombo === null) return null;
    var services = bestCombo.slice().sort(function (a, b) {
      return (b.price - a.price) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
    var sum = 0;
    bestCombo.forEach(function (s) { sum += s.price; });
    return { services: services, total_price: round2(sum), covered: pop(bestMask) };
  }

  function answer(data, state, ownedList) {
    var total = data.games.length;
    var byId = {}, maskOf = {}, owned = {};
    data.options.forEach(function (o) { byId[o.id] = o; maskOf[o.id] = BigInt('0x' + o.m[state]); });
    ownedList.forEach(function (id) { if (byId[id]) owned[id] = true; });

    var have = ZERO;
    Object.keys(owned).forEach(function (id) { have |= maskOf[id]; });
    var covered = pop(have);
    var missing = [];
    for (var i = 0; i < total; i++) if (!((have >> BigInt(i)) & ONE)) missing.push(i);

    var candidates = [];
    data.options.forEach(function (opt) {
      if (owned[opt.id]) return;
      var price = effectivePrice(opt, byId, owned);
      var added = pop(maskOf[opt.id] & ~have);
      if (price === null || !added) return;
      candidates.push({ id: opt.id, name: opt.name, price: price, added: added });
    });

    var single = null;
    if (candidates.length) {
      var ranked = candidates.slice().sort(function (a, b) {
        return (b.added - a.added) || (a.price - b.price) || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
      });
      single = { id: ranked[0].id, added: ranked[0].added, price: ranked[0].price };
    }

    var bestSet = null;
    if (missing.length && candidates.length) {
      var reach = have, masks = {};
      candidates.forEach(function (c) { reach |= maskOf[c.id]; masks[c.id] = maskOf[c.id] | have; });
      var combo = cheapest(candidates, masks, total, pop(reach));
      if (combo) {
        bestSet = { ids: combo.services.map(function (s) { return s.id; }), price: combo.total_price,
                    covered: combo.covered, complete: combo.covered === total };
      }
    }
    return { covered: covered, total: total, missing: missing, single: single, set: bestSet };
  }

  function fill(template, fields) {
    return String(template || '').replace(/\{(\w+)\}/g, function (all, key) {
      return fields.hasOwnProperty(key) ? fields[key] : all;
    });
  }

  function money(price, text) {
    if (price === 0) return text.free;
    var fixed = price === Math.round(price) ? String(price) : price.toFixed(2);
    return '$' + fixed + ' ' + text.per_month;
  }

  function readOwned() {
    try { return JSON.parse(localStorage.getItem(OWNED_KEY) || '[]') || []; } catch (e) { return []; }
  }

  function writeOwned(list) {
    try { localStorage.setItem(OWNED_KEY, JSON.stringify(list)); } catch (e) { /* private mode */ }
  }

  function currentState() {
    var on = $('[data-state-btn][aria-selected="true"]');
    return on ? on.getAttribute('data-state-btn') : 'out_of_market';
  }

  function el(tag, text, cls) {
    var node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }

  function initMissing() {
    var root = $('[data-missing-root]');
    var source = $('#missing-data');
    if (!root || !source || !HAS_BIGINT) return;
    var payload;
    try { payload = JSON.parse(source.textContent); } catch (e) { return; }
    var data = payload.data, text = payload.text || {};
    var names = {};
    data.options.forEach(function (o) { names[o.id] = o.name; });

    root.appendChild(el('h2', text.heading));
    root.appendChild(el('p', text.intro, 'small muted'));
    var form = el('div', null, 'missing-options');
    var result = el('div', null, 'missing-result');
    root.appendChild(form);
    root.appendChild(result);

    // Ids from other team pages (their local options) are kept in storage
    // but ignored here, so one saved list works across the whole site.
    var saved = readOwned();

    function ownedHere() {
      return $$('input[type=checkbox]', form).filter(function (b) { return b.checked; })
        .map(function (b) { return b.value; });
    }

    function render() {
      result.textContent = '';
      var owned = ownedHere();
      if (!owned.length) return;                 // nothing ticked: nothing added to the page
      var r = answer(data, currentState(), owned);
      if (!r.missing.length) {
        result.appendChild(el('p', text.all_covered));
        return;
      }
      result.appendChild(el('p', fill(text.can_watch, { covered: r.covered, total: r.total })));
      var details = el('details');
      details.appendChild(el('summary', fill(text.miss_list, { count: r.missing.length })));
      var list = el('ul');
      r.missing.forEach(function (i) { list.appendChild(el('li', data.games[i].d + ', ' + data.games[i].o)); });
      details.appendChild(list);
      result.appendChild(details);
      if (r.single) {
        result.appendChild(el('p', fill(text.best_single, {
          name: names[r.single.id], price: money(r.single.price, text), added: r.single.added })));
      } else {
        result.appendChild(el('p', text.best_single_none));
      }
      if (r.set) {
        var fields = { names: r.set.ids.map(function (id) { return names[id]; }).join(' + '),
                       price: money(r.set.price, text), covered: r.set.covered, total: r.total };
        result.appendChild(el('p', fill(r.set.complete ? text.full_set : text.best_possible, fields)));
      } else {
        result.appendChild(el('p', text.nothing_more));
      }
    }

    data.options.forEach(function (o) {
      var label = el('label', null, 'missing-option');
      var box = el('input');
      box.type = 'checkbox';
      box.value = o.id;
      box.checked = saved.indexOf(o.id) !== -1;
      box.addEventListener('change', function () {
        var keep = readOwned().filter(function (id) { return !names[id]; });
        writeOwned(keep.concat(ownedHere()));
        render();
      });
      label.appendChild(box);
      label.appendChild(document.createTextNode(' ' + o.name));
      form.appendChild(label);
    });

    $$('[data-state-btn]').forEach(function (btn) { btn.addEventListener('click', render); });
    root.hidden = false;
    render();
  }

  // Exposed for the parity test only; the page never calls it.
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { answer: answer };
    return;
  }

  function init() {
    initToggle();
    initLocalTimes();
    initCountdowns();
    initMissing();
    initMyTeam();
    if ($('[data-player]') || $('[data-updated]')) refresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
