# CLAUDE.md — hatbook 仓库工作说明

这是《一顶帽子的全球旅行:小白入行帽子厂贸实战》的写作与发布仓库。

## 必读文件(按顺序)

1. `skills/hatbook-writer/SKILL.md` — **写作规范,任何正文写作前必须完整阅读并遵守**:从业者级深度、五件套结构、每个三级小节≥1000字、逐节自审检查表、主线订单规则。
2. `OUTLINE.md` — 全书三级目录与完成状态(✅/⬜)。目录定"写什么",skill 定"怎么写"。**全书目录已细化到最深层写作单元(2026-07-29 经作者确认):有三级小节(X.X.X)的以三级为单元,未细分三级的二级小节本身即一个单元,第0章按二级小节为单元。**
3. `chapters/ch01.md` — 已完成的 1.1+1.2 九个小节,是深度和口吻的**校准样板**;新写内容与它对齐。

## 写作工作流

- **写作严格跟随 OUTLINE.md 的一/二/三级标题**:章 → 二级 → 三级逐级对应,正文标题与目录条目一致(成文时可微调措辞,结构与编号不得变);不得自行增删、合并、拆分小节,要改先提案获作者确认。
- **流水线模式(2026-07-29 作者确认)**:按 skill 第五条执行"辅助agent执笔整章 → 主agent四项审查(内容质量/标题符合度/内容完整度/前后连贯性)→ 通过即入库构建上站",**跳过人工审查**,按目录顺序连续推进直至全书完成。
- `CANON.md` 是全书一致性登记簿(主线时间线/人物设定/数字口径/术语首次定义索引):辅助agent开工前必读,主agent每章入库时更新。
- 主线订单(Ridge & Barrel / Mike / 500顶)时间线必须与已写章节连续,人物设定不可漂移。
- 旧版内容处理:ch01 的 1.3-1.5、ch02/ch03/ch08/ch09、ch04 的 4.3-4.7 存在旧版底稿(词典条目式),重写时可参考其知识点覆盖面,但**文字全部重起,不做缝补**。ch04 的 4.1+4.2 已有新版(见 git 历史或作者提供),直接沿用。

## 构建与发布

- 全部章节 markdown 在 `chapters/chXX.md`,目录页为 `toc.md`。
- 阅读器模板 `reader_web_template.html`,构建脚本 `build.py`:读取模板 + 注入各章 markdown + 写入 Worker 地址,产出根目录 `index.html`。
- 每章审查通过后运行 `python3 build.py`,确认构建校验通过,再 `git add -A && git commit && git push`,GitHub Pages 自动更新。
- 新完成的章节要同步三处:`chapters/` 的 md 文件、`build.py` 的 files 列表、模板中 CHAPTERS 数组的 done 状态与 toc.md 的 ✅ 标记。
- 构建硬校验(build.py 内已含断言):不得出现 `api.anthropic.com` 直连;WORKER_URL 必须是 `https://shy-brook-76ea.kevinren1108.workers.dev`;不得出现 pingBtn;`isComposing` 修复必须在;术语表须解析出 400 条以上;`sendBeacon` 与术语字典须已注入。

## 阅读器功能层(2026-07-31 加)

- 账号登录、阅读位置云同步、划线标注、笔记、共读批注、全书搜索、术语释义、作业打勾。**手机优先**:弹层在窄屏为底部抽屉,底栏五键为 目录/搜索/笔记/助教/我。
- 后端在 `worker/`(独立的第二个 Worker + Cloudflare D1),与助教代理 Worker 互不影响。部署步骤见 `worker/README.md`;地址填进 `build.py` 的 `DATA_WORKER_URL`,留空则阅读器自动降级为纯本机存储。
- 阅读位置采用「本机瞬时 + 云端兜底」双层:滚动落定写 localStorage,`visibilitychange:hidden` / `pagehide` 用 `navigator.sendBeacon` 上报(令牌走 body 的 `_t`,因为 beacon 带不了请求头)。这是手机切后台被系统杀掉后仍能回到原处的关键,改动此处务必回归验证。
- 划线锚点 = 块序号 + 块内纯文本偏移 + 前后文,三级容错(原坐标 → 前后文重定位 → 全章找原文)。**若日后修订已发布章节的正文,划线会自动重定位,但仍应抽查一次。**
- 术语字典由 `build.py` 从附录 A1 的十四张表解析生成(447 条),不要手工维护第二份;改动 A1 表格式会影响解析。
- **PWA**:`manifest.webmanifest` + `icons/` + `sw_template.js`。`build.py` 把页面内容的 sha1 前12位注入模板产出根目录 `sw.js`,所以**书稿一改、重新构建,读者就会收到「有更新」提示**,点了才换新版,不打断阅读。改 `sw.js` 要改 `sw_template.js`(sw.js 是产物)。Service Worker 显式放行 `*.workers.dev`(接口永不进缓存),其余走缓存优先,因此离线可读全书。
- 账号:`kevin`(Kevin)、`iris`(Iris)。主屏 PWA 与 Safari 是两套独立存储,首次从主屏打开需重新登录一次,登录后笔记自动同步回来。

## 拍照估价与每日练习(2026-08-30 加)

- **价格库** `data/prices.json`:帽子部件市场价(带出处/置信度),拍照估价与每日练习共用;结构(各节条目的 id 集合)不能随意变动——`scripts/update_prices.py` 有结构守卫,前端按条目字段渲染。`.github/workflows/update-prices.yml` 可让 Claude 联网校准(**定时已停用**,2026-08-31 作者要求,仅手动触发)。
- **拍照估价**:助教输入行的 📷(`photoBtn`),canvas 压到长边 1568px 后以 image block 随请求发助教 Worker(已验证该 Worker 对 messages 是透传的,图片能过);图片不进 history。报价员模式的 system 内嵌价格库摘要(`pricesDigest()`)。
- **每日练习**:`.github/workflows/daily-quiz.yml` 跑 `scripts/daily_quiz.py`(**定时已停用**,2026-08-31 作者要求省费用,仅手动 `gh workflow run daily-quiz.yml` 触发;往期题永久保留),四通道降级:RapidAPI Otapi 1688(secret:`RAPIDAPI_KEY`,免费档20次/天)→ OneBound(secret:`ONEBOUND_KEY`/`ONEBOUND_SECRET`,可选)→ Claude 联网搜索 → 纸面题兜底。出题模型默认 `claude-sonnet-5`,可用仓库 variable `QUIZ_MODEL` 覆盖(设 haiku 时脚本自动换基础版联网工具)。产出 `daily/YYYY-MM-DD.json` + `daily/img/`(留90天) + `daily/index.json`,Action 直接 commit,不需要跑 build.py。前端入口:目录抽屉顶部 + 「我」面板;答题记录只存 localStorage。
- SW 对 `daily/`、`data/` 走网络优先(见 `sw_template.js` 的 `isDaily`),否则读者拿不到当天新题。
- **密钥位置**:助教 Worker(shy-brook-76ea)的 `ANTHROPIC_API_KEY` 在 wrangler secret(换法:`printf 'sk-...' | npx wrangler secret put ANTHROPIC_API_KEY --name shy-brook-76ea`);GitHub Actions 用仓库 secret `ANTHROPIC_API_KEY`(没配时 workflow 自动跳过不报错)。

## 边界

- 不改动助教代理 Worker 的部署架构;不在前端引入任何密钥(数据 Worker 的 ADMIN_KEY 只存在 wrangler secret 里)。
- 目录小节的合并/拆分、主线剧情的重大转折,先提案获作者确认。
