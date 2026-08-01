-- hatbook 用户数据库 (Cloudflare D1 / SQLite)
-- 执行方式见 worker/README.md

-- ─── 账号 ───
CREATE TABLE IF NOT EXISTS users (
  id           TEXT PRIMARY KEY,          -- 登录名,如 kevin
  display_name TEXT NOT NULL,             -- 显示名,如 老任
  pw_hash      TEXT NOT NULL,             -- PBKDF2-SHA256 十六进制
  pw_salt      TEXT NOT NULL,
  created_at   INTEGER NOT NULL
);

-- ─── 会话令牌 ───
CREATE TABLE IF NOT EXISTS sessions (
  token      TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

-- ─── 登录失败计数(简易速率限制) ───
CREATE TABLE IF NOT EXISTS login_fails (
  user_id     TEXT PRIMARY KEY,
  fails       INTEGER NOT NULL DEFAULT 0,
  locked_until INTEGER NOT NULL DEFAULT 0
);

-- ─── 阅读位置:每人一行 ───
CREATE TABLE IF NOT EXISTS reading_pos (
  user_id     TEXT PRIMARY KEY,
  chapter     TEXT NOT NULL,
  block_index INTEGER NOT NULL DEFAULT 0,
  ratio       REAL NOT NULL DEFAULT 0,
  snippet     TEXT,                       -- 定位失败时的兜底文本
  updated_at  INTEGER NOT NULL
);

-- ─── 每章阅读进度 ───
CREATE TABLE IF NOT EXISTS chapter_progress (
  user_id    TEXT NOT NULL,
  chapter    TEXT NOT NULL,
  max_ratio  REAL NOT NULL DEFAULT 0,     -- 本章读到的最深处 0~1
  seconds    INTEGER NOT NULL DEFAULT 0,  -- 累计停留秒数
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, chapter)
);

-- ─── 划线标注(note 非空即为带笔记的划线) ───
CREATE TABLE IF NOT EXISTS annotations (
  id           TEXT PRIMARY KEY,          -- 前端生成的 uuid
  user_id      TEXT NOT NULL,
  chapter      TEXT NOT NULL,
  block_index  INTEGER NOT NULL,
  start_offset INTEGER NOT NULL,
  end_offset   INTEGER NOT NULL,
  quote        TEXT NOT NULL,             -- 划中的原文
  prefix       TEXT,                      -- 前文 30 字,锚点失效时重定位用
  suffix       TEXT,                      -- 后文 30 字
  color        TEXT NOT NULL DEFAULT 'yellow',
  note         TEXT,                      -- 附笔记,空 = 纯划线
  private      INTEGER NOT NULL DEFAULT 0,
  deleted      INTEGER NOT NULL DEFAULT 0,
  created_at   INTEGER NOT NULL,
  updated_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_anno_sync ON annotations(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_anno_chapter ON annotations(chapter);

-- ─── 章节级自由笔记(不锚定段落) ───
CREATE TABLE IF NOT EXISTS chapter_notes (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL,
  chapter    TEXT NOT NULL,
  body       TEXT NOT NULL,
  private    INTEGER NOT NULL DEFAULT 0,
  deleted    INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_note_sync ON chapter_notes(user_id, updated_at);

-- ─── 对标注的回话(共读讨论) ───
CREATE TABLE IF NOT EXISTS replies (
  id            TEXT PRIMARY KEY,
  annotation_id TEXT NOT NULL,
  user_id       TEXT NOT NULL,
  body          TEXT NOT NULL,
  deleted       INTEGER NOT NULL DEFAULT 0,
  created_at    INTEGER NOT NULL,
  updated_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reply_anno ON replies(annotation_id);
CREATE INDEX IF NOT EXISTS idx_reply_sync ON replies(updated_at);

-- ─── 本章作业完成状态 ───
CREATE TABLE IF NOT EXISTS homework (
  user_id    TEXT NOT NULL,
  chapter    TEXT NOT NULL,
  done       INTEGER NOT NULL DEFAULT 0,
  log        TEXT,                        -- 我的完成记录
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (user_id, chapter)
);
