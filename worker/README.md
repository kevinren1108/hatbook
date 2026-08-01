# hatbook 数据 Worker 部署说明

这个 Worker 只负责用户数据（账号、阅读位置、划线、笔记、共读回话、作业进度），
和现有的助教代理 Worker（`shy-brook-76ea`）**完全独立**，部署它不会影响助教功能。

数据存在 Cloudflare D1（托管 SQLite），在你自己的 Cloudflare 账号里，不经过任何第三方。

---

## 当前部署状态（2026-07-31 已完成）

| 项目 | 值 |
|---|---|
| Worker 地址 | `https://hatbook-data.kevinren1108.workers.dev` |
| D1 数据库 | `hatbook`（region WNAM），id 见 `wrangler.toml` |
| 账号 | `kevin`（老任）、`taitai`（太太） |
| 管理密钥 | 存在 `wrangler secret` 里，不在仓库中 |

**下面的部署步骤只在需要重建或迁移时才用。**日常改动只需在 `worker/` 里
`npx wrangler deploy` 重新发布；改前端则在仓库根目录 `python3 build.py` 后提交推送。

### 改密码

```bash
cd worker
npx wrangler secret list                 # 确认 ADMIN_KEY 还在
curl -X POST https://hatbook-data.kevinren1108.workers.dev/api/admin/user \
  -H "X-Admin-Key: <你的ADMIN_KEY>" -H "Content-Type: application/json" \
  -d '{"id":"kevin","name":"老任","pass":"新密码"}'
```

忘了 ADMIN_KEY 就重设一个：`printf '新密钥' | npx wrangler secret put ADMIN_KEY`。

---

## 一次性部署（约 5 分钟）

以下命令都在 `worker/` 目录里执行。本机已有 node，直接用 `npx`，不必全局装 wrangler。

### 1. 登录并建数据库

```bash
cd worker
npx wrangler login          # 浏览器里授权一次
npx wrangler d1 create hatbook
```

命令会打印一段配置，把其中的 `database_id` 复制到 `wrangler.toml` 里替换掉
`REPLACE_WITH_YOUR_DATABASE_ID`。

### 2. 建表

```bash
npx wrangler d1 execute hatbook --remote --file=./schema.sql
```

（把 `--remote` 换成 `--local` 就是在本地开发库里建表。）

### 3. 设置管理密钥

这个密钥只用于创建账号和改密码，不会出现在前端。

```bash
npx wrangler secret put ADMIN_KEY
# 提示输入时,粘贴一段你自己想的长随机字符串,回车
```

### 4. 部署

```bash
npx wrangler deploy
```

记下输出里的 Worker 地址，形如 `https://hatbook-data.<你的子域>.workers.dev`，
把它填进仓库根目录 `build.py` 的 `DATA_WORKER_URL`，然后 `python3 build.py` 重新构建。

### 5. 创建两个账号

把下面的 `<ADMIN_KEY>`、`<WORKER_URL>` 换成实际值，密码自己定（至少 6 位）：

```bash
curl -X POST "<WORKER_URL>/api/admin/user" \
  -H "X-Admin-Key: <ADMIN_KEY>" -H "Content-Type: application/json" \
  -d '{"id":"kevin","name":"老任","pass":"你的密码"}'

curl -X POST "<WORKER_URL>/api/admin/user" \
  -H "X-Admin-Key: <ADMIN_KEY>" -H "Content-Type: application/json" \
  -d '{"id":"taitai","name":"太太","pass":"她的密码"}'
```

同一条命令重复执行就是改密码（改密后该账号的旧登录会话全部失效，需要重新登录）。

---

## 本地开发

```bash
cd worker
npx wrangler d1 execute hatbook --local --file=./schema.sql   # 建本地表(仅首次)
npx wrangler dev                                              # 起在 http://localhost:8787
```

前端把 `CONFIG.DATA_URL` 指到 `http://localhost:8787` 即可联调，
CORS 已放行任意 `localhost` / `127.0.0.1` 端口。

本地建账号（本地开发不校验 ADMIN_KEY 以外的东西，先 `npx wrangler secret put ADMIN_KEY`
或在 `.dev.vars` 里写 `ADMIN_KEY=dev`）：

```bash
curl -X POST http://localhost:8787/api/admin/user \
  -H "X-Admin-Key: dev" -H "Content-Type: application/json" \
  -d '{"id":"kevin","name":"老任","pass":"123456"}'
```

---

## 接口一览

除 `/api/login` 与 `/api/admin/user` 外，都需要 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/login` | `{user, pass}` → `{token, user}`，令牌 180 天 |
| POST | `/api/logout` | 注销当前令牌 |
| GET | `/api/sync?since=<ms>` | 增量拉取；`since=0` 为全量。返回自己的全部数据 + 对方非私密的划线/笔记 |
| POST | `/api/pos` | `{chapter, bi, ratio, snippet, chapterRatio, seconds}` 上报阅读位置 |
| POST | `/api/annotations` | `{upsert:[...], delete:[id...]}` 批量，单次上限 200 条 |
| POST | `/api/notes` | 同上，章节级笔记 |
| POST | `/api/replies` | `{id, annotation_id, body}` 或 `{delete:id}` |
| POST | `/api/homework` | `{chapter, done, log}` |
| POST | `/api/admin/user` | 需 `X-Admin-Key`，建号或改密 |
| GET | `/api/health` | 存活检查 |

### 关于 sendBeacon

手机切后台时页面随时会被系统回收，那一刻只有 `navigator.sendBeacon` 还能把数据发出去，
但它带不了 `Authorization` 头。所以 `/api/pos` 额外支持把令牌放在请求体的 `_t` 字段里：

```js
navigator.sendBeacon(DATA_URL + '/api/pos',
  new Blob([JSON.stringify({ _t: token, chapter, bi, ratio })], { type: 'text/plain' }));
```

这是"手机后台被杀后还能回到原位置"这件事的关键。

---

## 安全说明

- 密码用 PBKDF2-SHA256、10 万次迭代、每人独立随机盐，数据库里不存明文。
- 同一账号连续登录失败 10 次锁定 15 分钟。
- 所有写操作都带 `WHERE user_id = 当前用户`，改不了别人的数据。
- CORS 只放行 `https://kevinren1108.github.io` 和本地开发地址。
- 划线/笔记可逐条标记「私密」，标记后对方拉不到。

## 备份

D1 免费版有时间点恢复，但没有异地备份。阅读器「我的笔记本」里有**导出 Markdown**
按钮，导出的文件可以直接放进本仓库提交，笔记就有了 git 版本历史。建议偶尔导一次。
