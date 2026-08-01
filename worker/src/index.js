/**
 * hatbook 用户数据 Worker
 * 账号登录 / 阅读位置 / 划线标注 / 笔记 / 共读回话 / 作业进度
 *
 * 绑定:  DB = D1 数据库(见 wrangler.toml)
 * 密钥:  ADMIN_KEY = 建号改密用的管理密钥(wrangler secret put ADMIN_KEY)
 *
 * 这个 Worker 与助教代理 Worker 完全独立,互不影响。
 */

const ALLOW_ORIGINS = [
  'https://kevinren1108.github.io',
];
const TOKEN_TTL   = 180 * 24 * 3600 * 1000; // 令牌有效期 180 天
const PBKDF2_ITER = 100000;
const MAX_BATCH   = 200;                    // 单次批量提交上限
const LOCK_FAILS  = 10;                     // 连续失败次数触发锁定
const LOCK_MS     = 15 * 60 * 1000;         // 锁定时长

/* ───────── 基础工具 ───────── */

function corsOrigin(request) {
  const o = request.headers.get('Origin') || '';
  if (ALLOW_ORIGINS.includes(o)) return o;
  // 本地开发:任意 localhost / 127.0.0.1 端口
  if (/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(o)) return o;
  return null;
}

function corsHeaders(request) {
  const o = corsOrigin(request);
  const h = {
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization,X-Admin-Key',
    'Access-Control-Max-Age': '86400',
    'Vary': 'Origin',
  };
  if (o) h['Access-Control-Allow-Origin'] = o;
  return h;
}

function json(request, data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...corsHeaders(request) },
  });
}

const err = (request, msg, status = 400) => json(request, { error: msg }, status);

const now = () => Date.now();

function hex(buf) {
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}
function unhex(s) {
  const a = new Uint8Array(s.length / 2);
  for (let i = 0; i < a.length; i++) a[i] = parseInt(s.substr(i * 2, 2), 16);
  return a;
}
function randomHex(bytes = 32) {
  return hex(crypto.getRandomValues(new Uint8Array(bytes)));
}

/** 常量时间字符串比较,避免时序侧信道 */
function safeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function hashPw(pass, saltHex) {
  const key = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveBits']
  );
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt: unhex(saltHex), iterations: PBKDF2_ITER, hash: 'SHA-256' },
    key, 256
  );
  return hex(bits);
}

/**
 * 读取请求体。
 * sendBeacon 只能发 text/plain 且带不了 Authorization 头,
 * 所以约定:beacon 请求把 token 放进 body 的 _t 字段。
 */
async function readBody(request) {
  const raw = await request.text();
  if (!raw) return {};
  try { return JSON.parse(raw); } catch { return {}; }
}

/* ───────── 鉴权 ───────── */

async function authenticate(request, env, body) {
  const h = request.headers.get('Authorization') || '';
  let token = h.startsWith('Bearer ') ? h.slice(7).trim() : '';
  if (!token && body && typeof body._t === 'string') token = body._t.trim();  // sendBeacon 通道
  if (!token) return null;

  const row = await env.DB
    .prepare('SELECT s.token, s.user_id, s.expires_at, u.display_name FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?')
    .bind(token).first();
  if (!row) return null;
  if (row.expires_at < now()) {
    await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(token).run();
    return null;
  }
  return { id: row.user_id, name: row.display_name, token };
}

/* ───────── 路由处理 ───────── */

async function handleLogin(request, env, body) {
  const user = String(body.user || '').trim().toLowerCase();
  const pass = String(body.pass || '');
  if (!user || !pass) return err(request, '请填写用户名和密码');

  const lock = await env.DB.prepare('SELECT fails, locked_until FROM login_fails WHERE user_id = ?')
    .bind(user).first();
  if (lock && lock.locked_until > now()) {
    const mins = Math.ceil((lock.locked_until - now()) / 60000);
    return err(request, `尝试过于频繁,请 ${mins} 分钟后再试`, 429);
  }

  const u = await env.DB.prepare('SELECT id, display_name, pw_hash, pw_salt FROM users WHERE id = ?')
    .bind(user).first();

  // 用户不存在时也走一次哈希,避免通过响应时间探测账号是否存在
  const salt = u ? u.pw_salt : '00'.repeat(16);
  const got  = await hashPw(pass, salt);

  if (!u || !safeEqual(got, u.pw_hash)) {
    const fails = (lock ? lock.fails : 0) + 1;
    const until = fails >= LOCK_FAILS ? now() + LOCK_MS : 0;
    await env.DB.prepare(
      'INSERT INTO login_fails (user_id, fails, locked_until) VALUES (?,?,?) ' +
      'ON CONFLICT(user_id) DO UPDATE SET fails = excluded.fails, locked_until = excluded.locked_until'
    ).bind(user, fails >= LOCK_FAILS ? 0 : fails, until).run();
    return err(request, '用户名或密码不对', 401);
  }

  await env.DB.prepare('DELETE FROM login_fails WHERE user_id = ?').bind(user).run();

  const token = randomHex(32);
  const t = now();
  await env.DB.prepare('INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)')
    .bind(token, u.id, t, t + TOKEN_TTL).run();
  // 顺手清理该用户已过期的会话
  await env.DB.prepare('DELETE FROM sessions WHERE user_id = ? AND expires_at < ?').bind(u.id, t).run();

  return json(request, { token, user: { id: u.id, name: u.display_name } });
}

async function handleLogout(request, env, me) {
  await env.DB.prepare('DELETE FROM sessions WHERE token = ?').bind(me.token).run();
  return json(request, { ok: true });
}

/**
 * 增量同步。since=0 即全量。
 * 返回:自己的全部数据 + 其他人 private=0 的标注/笔记(共读)。
 */
async function handleSync(request, env, me, url) {
  const since = Math.max(0, parseInt(url.searchParams.get('since') || '0', 10) || 0);
  const t = now();

  const [users, pos, annos, notes, replies, hw, prog] = await env.DB.batch([
    env.DB.prepare('SELECT id, display_name FROM users'),
    env.DB.prepare('SELECT * FROM reading_pos WHERE updated_at > ?').bind(since),
    env.DB.prepare(
      'SELECT * FROM annotations WHERE updated_at > ? AND (user_id = ? OR private = 0) ORDER BY chapter, block_index, start_offset'
    ).bind(since, me.id),
    env.DB.prepare(
      'SELECT * FROM chapter_notes WHERE updated_at > ? AND (user_id = ? OR private = 0) ORDER BY created_at'
    ).bind(since, me.id),
    env.DB.prepare('SELECT * FROM replies WHERE updated_at > ? ORDER BY created_at').bind(since),
    env.DB.prepare('SELECT * FROM homework WHERE updated_at > ?').bind(since),
    env.DB.prepare('SELECT * FROM chapter_progress WHERE updated_at > ?').bind(since),
  ]);

  return json(request, {
    now: t,
    me: { id: me.id, name: me.name },
    users: Object.fromEntries((users.results || []).map(u => [u.id, u.display_name])),
    pos: pos.results || [],
    annotations: annos.results || [],
    notes: notes.results || [],
    replies: replies.results || [],
    homework: hw.results || [],
    progress: prog.results || [],
  });
}

/** 阅读位置上报。高频 + sendBeacon 通道,做得尽量轻。 */
async function handlePos(request, env, me, body) {
  const chapter = String(body.chapter || '').slice(0, 32);
  if (!chapter) return err(request, '缺少 chapter');
  const bi      = Math.max(0, parseInt(body.bi, 10) || 0);
  const ratio   = Math.min(1, Math.max(0, Number(body.ratio) || 0));
  const snippet = String(body.snippet || '').slice(0, 200);
  const t = now();

  const stmts = [
    env.DB.prepare(
      'INSERT INTO reading_pos (user_id, chapter, block_index, ratio, snippet, updated_at) VALUES (?,?,?,?,?,?) ' +
      'ON CONFLICT(user_id) DO UPDATE SET chapter=excluded.chapter, block_index=excluded.block_index, ' +
      'ratio=excluded.ratio, snippet=excluded.snippet, updated_at=excluded.updated_at'
    ).bind(me.id, chapter, bi, ratio, snippet, t),
  ];

  // 顺带记录本章读到的最深处与停留时长
  const chRatio = Math.min(1, Math.max(0, Number(body.chapterRatio) || 0));
  const secs    = Math.min(3600, Math.max(0, parseInt(body.seconds, 10) || 0));
  if (chRatio > 0 || secs > 0) {
    stmts.push(env.DB.prepare(
      'INSERT INTO chapter_progress (user_id, chapter, max_ratio, seconds, updated_at) VALUES (?,?,?,?,?) ' +
      'ON CONFLICT(user_id, chapter) DO UPDATE SET ' +
      'max_ratio = MAX(chapter_progress.max_ratio, excluded.max_ratio), ' +
      'seconds = chapter_progress.seconds + excluded.seconds, updated_at = excluded.updated_at'
    ).bind(me.id, chapter, chRatio, secs, t));
  }

  await env.DB.batch(stmts);
  return json(request, { ok: true, updated_at: t });
}

const str = (v, max) => (v === null || v === undefined) ? null : String(v).slice(0, max);

async function handleAnnotations(request, env, me, body) {
  const upsert = Array.isArray(body.upsert) ? body.upsert.slice(0, MAX_BATCH) : [];
  const del    = Array.isArray(body.delete) ? body.delete.slice(0, MAX_BATCH) : [];
  const t = now();
  const stmts = [];

  for (const a of upsert) {
    const id = str(a.id, 64);
    if (!id || !a.chapter || !a.quote) continue;
    stmts.push(env.DB.prepare(
      'INSERT INTO annotations (id,user_id,chapter,block_index,start_offset,end_offset,quote,prefix,suffix,color,note,private,deleted,created_at,updated_at) ' +
      'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?,?) ' +
      'ON CONFLICT(id) DO UPDATE SET block_index=excluded.block_index, start_offset=excluded.start_offset, ' +
      'end_offset=excluded.end_offset, quote=excluded.quote, prefix=excluded.prefix, suffix=excluded.suffix, ' +
      'color=excluded.color, note=excluded.note, private=excluded.private, updated_at=excluded.updated_at ' +
      'WHERE annotations.user_id = excluded.user_id'   // 只能改自己的
    ).bind(
      id, me.id, str(a.chapter, 32),
      Math.max(0, parseInt(a.block_index, 10) || 0),
      Math.max(0, parseInt(a.start_offset, 10) || 0),
      Math.max(0, parseInt(a.end_offset, 10) || 0),
      str(a.quote, 2000), str(a.prefix, 200), str(a.suffix, 200),
      str(a.color, 16) || 'yellow', str(a.note, 5000),
      a.private ? 1 : 0,
      parseInt(a.created_at, 10) || t, t
    ));
  }
  for (const id of del) {
    stmts.push(env.DB.prepare(
      'UPDATE annotations SET deleted = 1, updated_at = ? WHERE id = ? AND user_id = ?'
    ).bind(t, str(id, 64), me.id));
  }

  if (stmts.length) await env.DB.batch(stmts);
  return json(request, { ok: true, updated_at: t, count: stmts.length });
}

async function handleNotes(request, env, me, body) {
  const upsert = Array.isArray(body.upsert) ? body.upsert.slice(0, MAX_BATCH) : [];
  const del    = Array.isArray(body.delete) ? body.delete.slice(0, MAX_BATCH) : [];
  const t = now();
  const stmts = [];

  for (const n of upsert) {
    const id = str(n.id, 64);
    if (!id || !n.chapter || !n.body) continue;
    stmts.push(env.DB.prepare(
      'INSERT INTO chapter_notes (id,user_id,chapter,body,private,deleted,created_at,updated_at) VALUES (?,?,?,?,?,0,?,?) ' +
      'ON CONFLICT(id) DO UPDATE SET body=excluded.body, private=excluded.private, updated_at=excluded.updated_at ' +
      'WHERE chapter_notes.user_id = excluded.user_id'
    ).bind(id, me.id, str(n.chapter, 32), str(n.body, 20000), n.private ? 1 : 0,
           parseInt(n.created_at, 10) || t, t));
  }
  for (const id of del) {
    stmts.push(env.DB.prepare(
      'UPDATE chapter_notes SET deleted = 1, updated_at = ? WHERE id = ? AND user_id = ?'
    ).bind(t, str(id, 64), me.id));
  }

  if (stmts.length) await env.DB.batch(stmts);
  return json(request, { ok: true, updated_at: t, count: stmts.length });
}

async function handleReplies(request, env, me, body) {
  const t = now();
  if (body.delete) {
    await env.DB.prepare('UPDATE replies SET deleted = 1, updated_at = ? WHERE id = ? AND user_id = ?')
      .bind(t, str(body.delete, 64), me.id).run();
    return json(request, { ok: true, updated_at: t });
  }
  const id  = str(body.id, 64);
  const aid = str(body.annotation_id, 64);
  const txt = str(body.body, 2000);
  if (!id || !aid || !txt) return err(request, '缺少参数');

  await env.DB.prepare(
    'INSERT INTO replies (id, annotation_id, user_id, body, deleted, created_at, updated_at) VALUES (?,?,?,?,0,?,?) ' +
    'ON CONFLICT(id) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at ' +
    'WHERE replies.user_id = excluded.user_id'
  ).bind(id, aid, me.id, txt, parseInt(body.created_at, 10) || t, t).run();
  return json(request, { ok: true, updated_at: t });
}

async function handleHomework(request, env, me, body) {
  const chapter = str(body.chapter, 32);
  if (!chapter) return err(request, '缺少 chapter');
  const t = now();
  await env.DB.prepare(
    'INSERT INTO homework (user_id, chapter, done, log, updated_at) VALUES (?,?,?,?,?) ' +
    'ON CONFLICT(user_id, chapter) DO UPDATE SET done=excluded.done, log=excluded.log, updated_at=excluded.updated_at'
  ).bind(me.id, chapter, body.done ? 1 : 0, str(body.log, 20000), t).run();
  return json(request, { ok: true, updated_at: t });
}

/** 建号 / 改密。需要 X-Admin-Key,只在部署时用。 */
async function handleAdminUser(request, env, body) {
  const key = request.headers.get('X-Admin-Key') || '';
  if (!env.ADMIN_KEY || !safeEqual(key, env.ADMIN_KEY)) return err(request, 'forbidden', 403);

  const id   = String(body.id || '').trim().toLowerCase();
  const name = String(body.name || '').trim() || id;
  const pass = String(body.pass || '');
  if (!/^[a-z0-9_-]{2,32}$/.test(id)) return err(request, 'id 只能是 2-32 位小写字母数字下划线连字符');
  if (pass.length < 6) return err(request, '密码至少 6 位');

  const salt = randomHex(16);
  const h    = await hashPw(pass, salt);
  await env.DB.prepare(
    'INSERT INTO users (id, display_name, pw_hash, pw_salt, created_at) VALUES (?,?,?,?,?) ' +
    'ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, pw_hash=excluded.pw_hash, pw_salt=excluded.pw_salt'
  ).bind(id, name, h, salt, now()).run();
  // 改密后让旧会话失效
  await env.DB.prepare('DELETE FROM sessions WHERE user_id = ?').bind(id).run();
  await env.DB.prepare('DELETE FROM login_fails WHERE user_id = ?').bind(id).run();

  return json(request, { ok: true, user: { id, name } });
}

/* ───────── 入口 ───────── */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(request) });
    }
    if (!corsOrigin(request) && request.headers.get('Origin')) {
      return err(request, 'origin not allowed', 403);
    }
    if (path === '/api/health' || path === '/') {
      return json(request, { ok: true, service: 'hatbook-data' });
    }

    try {
      const body = request.method === 'POST' ? await readBody(request) : {};

      if (path === '/api/login')      return await handleLogin(request, env, body);
      if (path === '/api/admin/user') return await handleAdminUser(request, env, body);

      const me = await authenticate(request, env, body);
      if (!me) return err(request, '未登录或登录已过期', 401);

      switch (path) {
        case '/api/logout':      return await handleLogout(request, env, me);
        case '/api/sync':        return await handleSync(request, env, me, url);
        case '/api/pos':         return await handlePos(request, env, me, body);
        case '/api/annotations': return await handleAnnotations(request, env, me, body);
        case '/api/notes':       return await handleNotes(request, env, me, body);
        case '/api/replies':     return await handleReplies(request, env, me, body);
        case '/api/homework':    return await handleHomework(request, env, me, body);
      }
      return err(request, 'not found', 404);
    } catch (e) {
      return err(request, 'server error: ' + (e && e.message ? e.message : String(e)), 500);
    }
  },
};
