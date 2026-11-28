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
      // Who's out leaves Available players off; one cleared since the build
      // is hidden until the next refresh rebuilds the list.
      if (node.classList.contains('out-chip')) node.hidden = status === 'Available';
    });
  }

  /* ---------------- who's out, rebuilt from the live data ----------------
     The same list pages.common.out_block() and the hub's Out detail render
     at build time, from the same rules: today's game only, Available left
     off, "Injury report not available yet" when nobody on today's teams is
     listed after 3 pm ET and the feed has not reached today. A part is only
     replaced when what it would show differs from what is there, so an
     unchanged page never moves. tests/test_live_out.py renders both ways and
     compares them. */

  var GUARD_START_HOUR = 15;   // config.INJURY_GUARD_START_HOUR

  function mk(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Tag, class, the attributes that carry meaning and leaf text, ignoring
  // whitespace, so a server-rendered part and a rebuilt one compare equal.
  function shape(node) {
    if (node.nodeType === 3) return node.nodeValue.replace(/\s+/g, ' ').trim();
    if (node.nodeType !== 1) return '';
    var keep = ['class', 'data-player', 'data-status-slot', 'data-out-message', 'hidden', 'open'];
    var attrs = keep.filter(function (a) { return node.hasAttribute(a); })
      .map(function (a) { return a + '=' + node.getAttribute(a); }).join(',');
    var kids = Array.prototype.map.call(node.childNodes, shape).filter(Boolean).join('');
    return '<' + node.tagName + ' ' + attrs + '>' + kids + '</>';
  }

  function etHour(iso) {
    var when = new Date(iso);
    if (isNaN(when.getTime())) return null;
    try {
      var h = parseInt(part(fmt('en-US', { timeZone: EASTERN, hour: 'numeric', hour12: false }, 'et-hour')
        .formatToParts(when), 'hour'), 10);
      return isNaN(h) ? null : h % 24;
    } catch (e) { return null; }
  }

  // context.injury_report_missing(), on the data the page fetched.
  function reportMissing(data, anyListed) {
    if (!data.has_games_today || anyListed) return false;
    var hour = etHour(data.updated_at);
    if (hour === null || hour < GUARD_START_HOUR) return false;
    return (data.as_of || '').slice(0, 10) !== data.date_et;
  }

  function availability(data) {
    var byTeam = {}, any = false;
    function add(p) {
      if (!p || !p.team) return;
      (byTeam[p.team] = byTeam[p.team] || []).push(p);
      any = true;
    }
    (data.players || []).forEach(add);
    (data.games || []).forEach(function (g) { (g.players || []).forEach(add); });
    var hasData = data.has_injury_data === undefined ? any : !!data.has_injury_data;
    return { byTeam: byTeam, any: any, hasData: hasData, missing: reportMissing(data, any) };
  }

  // Swaps a part's content for `nodes` only when it would read differently.
  // With keepFirst the first element (the heading) stays where it is.
  function replaceIfDifferent(holder, keepFirst, nodes) {
    var first = keepFirst ? holder.firstElementChild : null;
    var current = Array.prototype.slice.call(holder.childNodes, 0).filter(function (n) { return n !== first; });
    var before = current.map(shape).filter(Boolean).join('');
    var after = nodes.map(shape).join('');
    if (before === after) return;
    var tail = document.createDocumentFragment();
    nodes.forEach(function (n) { tail.appendChild(n); });
    if (first) {
      while (first.nextSibling) holder.removeChild(first.nextSibling);
      holder.appendChild(tail);
    } else {
      holder.replaceChildren(tail);
    }
  }

  function renderOut(data, av) {
    $$('[data-live-out]').forEach(function (box) {
      if (box.getAttribute('data-date') !== data.date_et) return;
      var teams = (box.getAttribute('data-teams') || '').split(' ');
      var names = (box.getAttribute('data-names') || '').split('|');
      var nodes;
      if (av.missing) {
        var msg = mk('p', 'small muted', box.getAttribute('data-l-missing') || '');
        msg.setAttribute('data-out-message', '');
        nodes = [msg];
      } else {
        var sides = mk('div', 'game-sides');
        teams.forEach(function (t, i) {
          var side = mk('div', 'game-side');
          side.appendChild(mk('h5', '', names[i] || t));
          var players = (av.byTeam[t] || []).filter(function (p) { return p.status !== 'Available'; });
          if (players.length) {
            var ul = mk('ul', 'out-chips');
            players.forEach(function (p) {
              var li = mk('li', 'out-chip');
              li.setAttribute('data-player', p.player);
              li.appendChild(mk('span', '', p.player));
              li.appendChild(document.createTextNode(' '));
              var badge = mk('span', 'badge badge-' + String(p.status).toLowerCase(), p.status);
              badge.setAttribute('data-status-slot', '');
              li.appendChild(badge);
              ul.appendChild(li);
            });
            side.appendChild(ul);
          } else {
            side.appendChild(mk('p', 'small muted',
              box.getAttribute(av.hasData ? 'data-l-listed' : 'data-l-none') || ''));
          }
          sides.appendChild(side);
        });
        nodes = [sides];
      }
      replaceIfDifferent(box, true, nodes);   // the heading stays
    });
  }

  function renderHubOut(data, av) {
    $$('[data-hub-out]').forEach(function (box) {
      if (box.getAttribute('data-date') !== data.date_et) return;
      var teams = (box.getAttribute('data-teams') || '').split(' ');
      var names = (box.getAttribute('data-names') || '').split('|');
      var nodes = [];
      if (av.missing) {
        var msg = mk('p', 'hg-out-msg small muted', box.getAttribute('data-l-missing') || '');
        msg.setAttribute('data-volatile', '');
        nodes.push(msg);
      } else {
        var lines = [], count = 0;
        teams.forEach(function (t, i) {
          var out = (av.byTeam[t] || []).filter(function (p) { return p.status === 'Out'; })
            .map(function (p) { return p.player; });
          count += out.length;
          if (out.length) lines.push((names[i] || t) + ': ' + out.join(', '));
        });
        if (lines.length) {
          var det = mk('details', 'hg-out small');
          det.setAttribute('data-volatile', '');
          var old = box.querySelector('details');
          if (old && old.open) det.open = true;
          det.appendChild(mk('summary', '', (box.getAttribute('data-l-summary') || '').replace('{count}', String(count))));
          var ul = mk('ul');
          lines.forEach(function (line) { ul.appendChild(mk('li', '', line)); });
          det.appendChild(ul);
          nodes.push(det);
        }
      }
      replaceIfDifferent(box, false, nodes);
    });
  }

  // The live Worker first (same domain, /how-to-watch/live/), then the file
  // the last build published. The Worker answers 404 when it has nothing
  // for today, which is what sends a page to the published file.
  function load(file) {
    function get(url) {
      return fetch(url, { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; });
    }
    return get(PREFIX + '/live/' + file)
      .catch(function () { return null; })
      .then(function (data) { return data || get(PREFIX + '/data/' + file); });
  }

  function refresh() {
    var wantsTonight = !!$('[data-tonight]');
    load(wantsTonight ? 'tonight.json' : 'injuries.json').then(function (data) {
      if (!data) return;
      var byPlayer = {};
      (data.players || []).forEach(function (p) { byPlayer[p.player] = p.status; });
      (data.games || []).forEach(function (g) {
        (g.players || []).forEach(function (p) { byPlayer[p.player] = p.status; });
      });
      var av = availability(data);
      renderOut(data, av);
      renderHubOut(data, av);
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
    if ($('[data-player]') || $('[data-updated]') || $('[data-live-out]') || $('[data-hub-out]')) refresh();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
