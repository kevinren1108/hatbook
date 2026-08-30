#!/usr/bin/env python3
"""hatbook 构建脚本:模板 + 各章markdown + 术语字典 → index.html,并产出 sw.js"""
import hashlib, json, os, re, sys

WORKER_URL = 'https://shy-brook-76ea.kevinren1108.workers.dev'
# 数据 Worker(账号/阅读位置/划线/笔记)。部署后把地址填在这里;
# 留空则阅读器只用本机存储,登录入口自动隐藏。部署步骤见 worker/README.md
DATA_WORKER_URL = 'https://hatbook-data.kevinren1108.workers.dev'

FILES = ['toc', 'ch00', 'ch01', 'ch02', 'ch03', 'ch04', 'ch05', 'ch06', 'ch07', 'ch08', 'ch09', 'ch10', 'ch11', 'ch12', 'ch13', 'ch14', 'ch15', 'ch16', 'ch17', 'ch18', 'ch19', 'ch20', 'ch21', 'ch22', 'ch23', 'ch24', 'ch25', 'ch26', 'ch27', 'ch28', 'ch29', 'ch30']  # 新章完成后加进来


def parse_glossary(path='chapters/ch30.md'):
    """把附录 A1 的十四张对照表解析成术语字典(中文/英文/首见/释义)"""
    txt = open(path, encoding='utf-8').read()
    m = re.search(r'^## A1 .*?$(.*?)^## A2 ', txt, re.S | re.M)
    if not m:
        return []
    terms, seen = [], set()
    for line in m.group(1).split('\n'):
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 4:
            continue
        cn, en, src = cells[0], cells[1], cells[2]
        dfn = '|'.join(cells[3:]).strip()          # 释义里若含竖线,原样拼回
        if not cn or cn == '中文' or set(cn) <= set('-: '):
            continue
        if cn in seen:
            continue
        seen.add(cn)
        terms.append({'cn': cn, 'en': en, 'src': src, 'def': dfn})
    return terms


html = open('reader_web_template.html', encoding='utf-8').read()
html = html.replace("WORKER_URL: 'https://REPLACE-ME.workers.dev',",
                    f"WORKER_URL: '{WORKER_URL}',")
if DATA_WORKER_URL:
    html = html.replace("DATA_URL:   'https://REPLACE-ME-DATA.workers.dev',",
                        f"DATA_URL:   '{DATA_WORKER_URL}',")

blocks = []
for f in FILES:
    path = f'{f}.md' if f == 'toc' else f'chapters/{f}.md'
    content = open(path, encoding='utf-8').read().replace('</script>', '<\\/script>')
    blocks.append(f'<script type="text/x-markdown" id="md-{f}">\n{content}\n</script>')

terms = parse_glossary()
gloss = json.dumps(terms, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
blocks.append(f'<script type="application/json" id="glossary">{gloss}</script>')

out = html.replace('<!--BOOK_CONTENT-->', '\n\n'.join(blocks))

# 硬校验
assert 'api.anthropic.com' not in out, '禁止直连API'
assert WORKER_URL in out, 'Worker地址缺失'
assert 'pingBtn' not in out, '测试按钮应已移除'
assert 'isComposing' in out, 'IME修复缺失'
assert out.count('id="md-') == len(FILES), '章节块数量不符'
assert len(terms) > 400, f'术语表解析异常:只拿到{len(terms)}条'
assert 'sendBeacon' in out, '后台被杀时的位置上报缺失'
assert 'id="glossary"' in out, '术语字典未注入'
if DATA_WORKER_URL:
    assert DATA_WORKER_URL in out, '数据Worker地址替换失败'
    assert 'REPLACE-ME-DATA' not in out, '数据Worker占位符残留'

# 拍照估价 + 每日练习(2026-08-30 加)
assert 'id="photoBtn"' in out, '拍照估价按钮缺失'
assert 'openDaily' in out, '每日练习入口缺失'
assert os.path.exists('data/prices.json'), '价格库缺失: data/prices.json'
assert os.path.exists('daily/index.json'), '每日练习索引缺失: daily/index.json'

# PWA 相关
assert 'rel="manifest"' in out, 'manifest 未挂上'
assert 'apple-touch-icon' in out, 'iOS 主屏图标未挂上'
assert "serviceWorker.register('sw.js')" in out, 'Service Worker 未注册'
assert 'env(safe-area-inset-top)' in out, '主屏全屏模式下的刘海避让缺失'
for f in ('manifest.webmanifest', 'icons/icon-192.png', 'icons/icon-512.png',
          'icons/icon-maskable-512.png', 'icons/apple-touch-icon.png', 'icons/favicon-32.png'):
    assert os.path.exists(f), f'PWA 资源缺失: {f}'

open('index.html', 'w', encoding='utf-8').write(out)

# Service Worker:版本号跟页面内容走,书稿一改就会在页面上提示「有更新」
digest = hashlib.sha1(out.encode('utf-8')).hexdigest()[:12]
sw = open('sw_template.js', encoding='utf-8').read().replace('__BUILD_VERSION__', digest)
assert '__BUILD_VERSION__' not in sw, 'SW 版本号未替换'
assert 'workers.dev' in sw, 'SW 必须显式放行接口请求(不缓存)'
assert 'isDaily' in sw, 'SW 必须对 daily/ 与 data/ 走网络优先'
open('sw.js', 'w', encoding='utf-8').write(sw)

cloud = DATA_WORKER_URL or '未配置(仅本机存储)'
print(f'✅ build OK: {len(FILES)} chapters, {len(terms)} terms, '
      f'{len(out.encode("utf-8"))} bytes → index.html')
print(f'   数据Worker: {cloud}')
print(f'   PWA: sw.js 版本 {digest}')
