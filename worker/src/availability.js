// Player availability for the how-to-watch-live Worker.
//
// A line-for-line port of watchguide/sources/injuries.py (normalize_name,
// normalize_status, latest_per_player, future_rows, normalize),
// watchguide/guard.py (check_shrink) and watchguide/build.py
// (injuries_payload, tonight_payload). Python stays the reference:
// tests/test_live_worker.py runs these under Node against the Python on the
// same input, including the real raw feed, so the two cannot drift.
// Pure functions only: no fetch, no KV, no clock unless one is passed in.

export const ALLOWED_STATUSES = ['Out', 'Doubtful', 'Questionable', 'Probable', 'Available'];
const STATUS_ORDER = Object.fromEntries(ALLOWED_STATUSES.map((s, i) => [s, i]));
const SUFFIXES = new Set(['jr', 'sr', 'ii', 'iii', 'iv', 'v']);
export const EASTERN = 'America/New_York';

// injuries._fold: NFKD, combining marks dropped, anything but a-z and space
// becomes a space, lower case, split on spaces.
function fold(name) {
  const text = String(name || '').normalize('NFKD').replace(/\p{Mn}/gu, '');
  return text.replace(/[^a-zA-Z ]/g, ' ').toLowerCase().split(' ').filter(Boolean);
}

// `aliases` is live-base.json's map, already folded on both sides.
export function normalizeName(name, aliases = {}) {
  const parts = fold(name);
  while (parts.length > 1 && SUFFIXES.has(parts[parts.length - 1])) parts.pop();
  const key = parts.join(' ');
  return Object.prototype.hasOwnProperty.call(aliases, key) ? aliases[key] : key;
}

// str.strip().title(): upper case after any non-letter, lower case elsewhere.
function title(text) {
  return text.toLowerCase().replace(/(^|[^a-z])([a-z])/g, (m, before, c) => before + c.toUpperCase());
}

export function normalizeStatus(raw) {
  const value = title(String(raw || '').trim());
  return ALLOWED_STATUSES.includes(value) ? value : null;
}

const isRow = (row) => row !== null && typeof row === 'object' && !Array.isArray(row);
const day = (row) => String(row.date || '').slice(0, 10);
const playerName = (row) => String(row.player || '').trim();
const byCodePoint = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

export function latestValidDate(buildDate) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(buildDate || '');
  if (!m) return '';
  const next = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3] + 1));
  return next.toISOString().slice(0, 10);
}

export function futureRows(raw, until) {
  if (!until) return [];
  return raw.filter((row) => isRow(row) && playerName(row) && day(row) > until).map(day).sort(byCodePoint);
}

export function latestPerPlayer(raw, since = '', until = '', aliases = {}) {
  const latest = new Map();          // insertion order, like a Python dict
  for (const row of raw) {
    if (!isRow(row)) continue;
    const name = playerName(row);
    if (!name) continue;
    const when = day(row);
    if (since && when < since) continue;
    if (until && when > until) continue;
    const key = normalizeName(name, aliases);
    if (!key) continue;
    const current = latest.get(key);
    if (current === undefined || when >= day(current)) latest.set(key, row);
  }
  return latest;
}

export function normalize(raw, playerTeams, since = '', until = '', aliases = {}) {
  const byTeam = {};
  const unmatched = new Set();
  let skippedStatus = 0;
  let asOf = '';
  for (const [key, row] of latestPerPlayer(raw, since, until, aliases)) {
    const name = playerName(row);
    const status = normalizeStatus(row.status || '');
    if (status === null) { skippedStatus += 1; continue; }
    const tricode = playerTeams[key];
    if (!tricode) { unmatched.add(name); continue; }
    const when = day(row);
    if (when > asOf) asOf = when;
    (byTeam[tricode] = byTeam[tricode] || []).push({
      player: name, status, injury: String(row.injury || '').trim(), date: when,
    });
  }
  for (const players of Object.values(byTeam)) {
    players.sort((a, b) => ((STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99))
      || byCodePoint(a.player, b.player));
  }
  return {
    by_team: byTeam,
    as_of: asOf,
    unmatched: [...unmatched].sort(byCodePoint),
    skipped_status: skippedStatus,
    dropped_future: futureRows(raw, until),
    until,
  };
}

// Python's f"{x:.0f}": an exact half goes to the even neighbour (50.5 -> 50).
function roundHalfEven(x) {
  return Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : Math.round(x);
}

// guard.check_shrink: '' when fine, else why the last good copy is kept.
export function checkShrink(newCount, previousCount, maxShrink = 0.5) {
  if (!previousCount) return '';
  if (newCount >= previousCount * (1 - maxShrink)) return '';
  const drop = (100 * (previousCount - newCount)) / previousCount;
  return `availability feed returned ${newCount} rows against ${previousCount} last time, ` +
    `a drop of ${roundHalfEven(drop)}%. Anything over ${roundHalfEven(maxShrink * 100)}% is treated as ` +
    'the feed breaking, so the last good copy has been kept.';
}

// --- Eastern time, the way the build writes it ---------------------------

function easternParts(when) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: EASTERN, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).formatToParts(when);
  const get = (t) => parts.find((p) => p.type === t).value;
  return { y: get('year'), mo: get('month'), d: get('day'), h: get('hour'), mi: get('minute'), s: get('second') };
}

export function todayEastern(now = new Date()) {
  const p = easternParts(now);
  return `${p.y}-${p.mo}-${p.d}`;
}

// datetime.now(ET).isoformat(timespec="seconds"): 2026-11-16T19:30:05-05:00
export function easternIso(now = new Date()) {
  const whole = new Date(Math.floor(now.getTime() / 1000) * 1000);
  const p = easternParts(whole);
  const asUtc = Date.UTC(+p.y, +p.mo - 1, +p.d, +p.h, +p.mi, +p.s);
  const offset = Math.round((asUtc - whole.getTime()) / 60000);
  const sign = offset < 0 ? '-' : '+';
  const abs = Math.abs(offset);
  const hh = String(Math.floor(abs / 60)).padStart(2, '0');
  const mm = String(abs % 60).padStart(2, '0');
  return `${p.y}-${p.mo}-${p.d}T${p.h}:${p.mi}:${p.s}${sign}${hh}:${mm}`;
}

// --- the two files the pages read ----------------------------------------

function playerRows(byTeam, tricodes) {
  const rows = [];
  for (const t of tricodes) {
    for (const p of byTeam[t] || []) {
      rows.push({ player: p.player, status: p.status, injury: p.injury || '', date: p.date || '', team: t });
    }
  }
  return rows;
}

// build.injuries_payload and build.tonight_payload, same keys, same order.
export function payloads(base, byTeam, updatedAt, asOf, today) {
  const games = (base.games || []).filter((g) => g.date_et === today);
  const playing = [...new Set(games.flatMap((g) => [g.home, g.away]))].sort(byCodePoint);
  const head = {
    updated_at: updatedAt,
    as_of: asOf,
    source_id: base.source_id,
    date_et: today,
  };
  const hasData = Object.keys(byTeam).length > 0;
  return {
    injuries: {
      ...head,
      has_games_today: games.length > 0,
      has_injury_data: hasData,
      players: playerRows(byTeam, playing),
    },
    tonight: {
      ...head,
      has_games_today: games.length > 0,
      has_injury_data: hasData,
      games: games.map((g) => ({
        game_id: g.game_id,
        home: g.home,
        away: g.away,
        tipoff_utc: g.tipoff_utc,
        tipoff_et: g.tipoff_et,
        channels: g.channels,
        players: playerRows(byTeam, [g.away, g.home]),
      })),
    },
  };
}
