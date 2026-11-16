// how-to-watch-live: the 30-minute "Who's out" refresh for
// hoopsmatic.com/how-to-watch, moved off GitHub Actions.
//
// A separate Worker from the one that serves hoopsmatic.com
// (nba-trade-calculator in hoopsmatic-worker): it owns only the route
// hoopsmatic.com/how-to-watch/live/*, which is more specific than that
// Worker's hoopsmatic.com/* zone route, so nothing there changes.
//
// Every 30 minutes on game evenings (crons in wrangler.toml, UTC) it
//   1. reads data/live-base.json, which every full build publishes (player
//      index, aliases, the next few days of games with their channels);
//   2. fetches the public availability feed (no key, no token);
//   3. applies the build's guards: future-dated rows are dropped, and a feed
//      that shrank by more than half is not trusted, the last good copy is
//      used instead with its own fetch time, so the pages' "Status may be out
//      of date" notice behaves exactly as it does after a GitHub refresh;
//   4. stores injuries.json and tonight.json, shaped like the build's, in KV.
//
// Readers' pages fetch /how-to-watch/live/<file> (same domain, so no
// third-party request) and fall back to /how-to-watch/data/<file> when this
// answers 404, which it does whenever it has nothing for today.
//
// Upstreams (build-time style fetches from Cloudflare, never from a reader):
//   LIVE_BASE_URL  the gh-pages copy of data/live-base.json
//   FEED_URL       the availability feed the build reads (injuries.py)

import { checkShrink, easternIso, latestValidDate, normalize, payloads, todayEastern } from './availability.js';

const PREFIX = '/how-to-watch/live';
const FILES = new Set(['injuries.json', 'tonight.json']);
const RUN_FLOOR_MS = 5 * 60 * 1000;   // /run never refreshes more often than this

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(runRefresh(env, new Date(controller.scheduledTime || Date.now())));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return json({ error: 'method not allowed' }, 405);
    }
    const rel = url.pathname.startsWith(PREFIX) ? url.pathname.slice(PREFIX.length).replace(/^\/+/, '') : null;
    if (rel === null) return json({ error: 'not found' }, 404);

    if (rel === '') return json(await statusView(env), 200);

    if (rel === 'run') {
      // The deploy script's first run, so a fresh deploy can be checked at
      // once. Public but harmless: it only re-reads two public files, and
      // never more often than every five minutes.
      const status = (await env.LIVE_KV.get('status', 'json')) || {};
      const last = Date.parse(status.last_run_utc || '') || 0;
      if (Date.now() - last >= RUN_FLOOR_MS) await runRefresh(env, new Date());
      return json(await statusView(env), 200);
    }

    if (FILES.has(rel)) {
      const body = await env.LIVE_KV.get('file:' + rel, { type: 'text', cacheTtl: 30 });
      const today = todayEastern();
      if (!body) return json({ error: 'nothing for today' }, 404);
      let date;
      try { date = JSON.parse(body).date_et; } catch (e) { date = ''; }
      if (date !== today) return json({ error: 'nothing for today' }, 404);
      return new Response(request.method === 'HEAD' ? null : body, { status: 200, headers: headers(30) });
    }

    return json({ error: 'not found' }, 404);
  },
};

function headers(maxAge) {
  return {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': maxAge ? `public, max-age=${maxAge}` : 'no-store',
    'X-Robots-Tag': 'noindex',
  };
}

function json(payload, status) {
  return new Response(JSON.stringify(payload, null, 1), { status, headers: headers(0) });
}

async function getJson(url) {
  const sep = url.includes('?') ? '&' : '?';
  const r = await fetch(url + sep + 't=' + Date.now(), {
    headers: { 'User-Agent': 'Mozilla/5.0 (how-to-watch-live)', Accept: 'application/json' },
    cf: { cacheTtl: 0 },
  });
  if (!r.ok) throw new Error(`${r.status} from ${new URL(url).hostname}`);
  return r.json();
}

async function statusView(env) {
  const status = (await env.LIVE_KV.get('status', 'json')) || { state: 'never run' };
  const today = todayEastern();
  const view = { ...status, today_et: today, serving: {} };
  for (const file of FILES) {
    const body = await env.LIVE_KV.get('file:' + file, 'text');
    let date = '';
    try { date = body ? JSON.parse(body).date_et : ''; } catch (e) { /* ignore */ }
    view.serving[file] = date === today;
  }
  return view;
}

// One refresh. Never throws: what happened goes into the "status" key.
export async function runRefresh(env, now) {
  const today = todayEastern(now);
  const status = { last_run_utc: now.toISOString(), last_run_et: easternIso(now), today_et: today };
  try {
    // 1. The build's inputs; the last copy that loaded when this one doesn't.
    let base;
    try {
      base = await getJson(env.LIVE_BASE_URL);
      await env.LIVE_KV.put('base', JSON.stringify(base));
    } catch (e) {
      base = await env.LIVE_KV.get('base', 'json');
      if (!base) throw new Error(`live-base.json did not load (${e.message}) and there is no earlier copy`);
      status.base_note = `live-base.json did not load (${e.message}); used the copy from ${base.built_for}`;
    }
    status.base_built_for = base.built_for;
    const games = (base.games || []).filter((g) => g.date_et === today);
    status.games_today = games.length;
    if (!games.length) {
      status.state = 'no games today';
      return status;
    }

    // 2-3. The feed, with the build's guards (build.load_injuries).
    const until = latestValidDate(today);
    const previous = await env.LIVE_KV.get('raw', 'json');   // {fetched_at, rows}
    const previousCount = previous ? previous.rows.length : (base.raw_count || 0);
    let rows = null, complaint = '';
    try {
      rows = await getJson(env.FEED_URL);
      if (!Array.isArray(rows)) throw new Error('injury feed was not a list of players');
      complaint = checkShrink(rows.length, previousCount, base.max_shrink ?? 0.5);
    } catch (e) {
      complaint = `availability feed did not load: ${e.message}`;
    }

    let result, updatedAt;
    if (!complaint) {
      result = normalize(rows, base.player_teams || {}, base.since || '', until, base.aliases || {});
      updatedAt = easternIso(now);
      await env.LIVE_KV.put('raw', JSON.stringify({ fetched_at: updatedAt, rows }));
      status.rows = rows.length;
    } else if (previous && previous.rows.length) {
      result = normalize(previous.rows, base.player_teams || {}, base.since || '', until, base.aliases || {});
      updatedAt = previous.fetched_at;
      status.rows = previous.rows.length;
      status.kept_last_good = true;
    } else {
      // Nothing trustworthy here yet: leave the files as they are (or absent),
      // so the pages read the build's own copy.
      status.state = 'feed not trusted, no earlier copy';
      status.error = complaint;
      return status;
    }
    if (complaint) status.error = complaint;

    // 4. The two files.
    const files = payloads(base, result.by_team, updatedAt, result.as_of, today);
    await env.LIVE_KV.put('file:injuries.json', JSON.stringify(files.injuries, null, 1));
    await env.LIVE_KV.put('file:tonight.json', JSON.stringify(files.tonight, null, 1));
    status.state = complaint ? 'serving the last good copy' : 'ok';
    status.updated_at = updatedAt;
    status.as_of = result.as_of;
    status.players_listed = files.injuries.players.length;
    status.unmatched = result.unmatched.length;
    if (result.dropped_future.length) status.dropped_future = result.dropped_future.length;
    return status;
  } catch (e) {
    status.state = 'failed';
    status.error = String(e && e.message || e);
    return status;
  } finally {
    await env.LIVE_KV.put('status', JSON.stringify(status));
  }
}
