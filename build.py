#!/usr/bin/env python3
"""hatbook 构建脚本:模板 + 各章markdown → index.html"""
import sys, re

WORKER_URL = 'https://shy-brook-76ea.kevinren1108.workers.dev'
FILES = ['toc', 'ch00', 'ch01', 'ch02', 'ch03', 'ch04', 'ch05', 'ch07', 'ch08', 'ch09']  # 新章完成后加进来

html = open('reader_web_template.html', encoding='utf-8').read()
html = html.replace("const CONFIG = { WORKER_URL: 'https://REPLACE-ME.workers.dev' };",
                    f"const CONFIG = {{ WORKER_URL: '{WORKER_URL}' }};")

blocks = []
for f in FILES:
    path = f'{f}.md' if f == 'toc' else f'chapters/{f}.md'
    content = open(path, encoding='utf-8').read().replace('</script>', '<\\/script>')
    blocks.append(f'<script type="text/x-markdown" id="md-{f}">\n{content}\n</script>')
out = html.replace('<!--BOOK_CONTENT-->', '\n\n'.join(blocks))

# 硬校验
assert 'api.anthropic.com' not in out, '禁止直连API'
assert WORKER_URL in out, 'Worker地址缺失'
assert 'pingBtn' not in out, '测试按钮应已移除'
assert 'isComposing' in out, 'IME修复缺失'
assert out.count('id="md-') == len(FILES), '章节块数量不符'

open('index.html', 'w', encoding='utf-8').write(out)
print(f'✅ build OK: {len(FILES)} chapters, {len(out.encode("utf-8"))} bytes → index.html')
