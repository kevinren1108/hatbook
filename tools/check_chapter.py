#!/usr/bin/env python3
"""主agent审查工具:核对章节与 OUTLINE.md 的单元完整度、每单元字数、章级固定件。
用法: python3 tools/check_chapter.py ch05 [--min 1000]
"""
import re, sys, argparse

ap = argparse.ArgumentParser()
ap.add_argument('ch')                      # 如 ch05 / ch00
ap.add_argument('--min', type=int, default=1000)
args = ap.parse_args()
chnum = int(args.ch.replace('ch', ''))

outline = open('OUTLINE.md', encoding='utf-8').read()
# 抽取本章目录块
m = re.search(rf'^###? 第{chnum}章 .*?$(.*?)(?=^### 第|^## 第|\Z)', outline, re.M | re.S)
if not m:
    sys.exit(f'OUTLINE.md 找不到第{chnum}章')
block = m.group(1)

# 目录单元 = 最深层条目:有三级取三级,无三级的二级为叶子
units = []           # [(编号, 标题)]
lines = block.splitlines()
for i, ln in enumerate(lines):
    m2 = re.match(r'^- (\d+\.\d+) (.+)', ln)
    m3 = re.match(r'^  - (\d+\.\d+\.\d+) (.+)', ln)
    if m3:
        units.append((m3.group(1), m3.group(2)))
    elif m2:
        # 若下一非空行不是三级子目,则该二级为叶子单元
        has_child = i + 1 < len(lines) and re.match(r'^  - \d+\.\d+\.\d+', lines[i + 1])
        if not has_child:
            units.append((m2.group(1), m2.group(2)))

path = f'chapters/{args.ch}.md'
text = open(path, encoding='utf-8').read()

# 正文单元:## x.x 或 ### x.x.x 标题;叶子二级的正文在 ## x.x 下(排除其子三级)
def cn_count(s):
    return len(re.findall(r'[一-鿿,。;:""''?!、()《》—…·]', s))

heads = [(mm.start(), mm.group(1) or mm.group(2))
         for mm in re.finditer(r'^#{2,3} (?:(\d+\.\d+\.\d+)|(\d+\.\d+))[  ::]', text, re.M)]
heads.sort()
seg = {}
for idx, (pos, num) in enumerate(heads):
    end = heads[idx + 1][0] if idx + 1 < len(heads) else len(text)
    seg[num] = text[pos:end]
# 叶子二级若含三级子段,截到第一个三级标题前(不应发生,但防御)
problems, ok = [], []
for num, title in units:
    if num not in seg:
        problems.append(f'缺单元 {num} {title}')
        continue
    body = seg[num]
    body_wo_head = body.split('\n', 1)[1] if '\n' in body else ''
    n = cn_count(body_wo_head)
    (ok if n >= args.min else problems).append(f'{num} {n}字' + ('' if n >= args.min else f' <{args.min} ✗ ({title})'))
unit_nums = {u[0] for u in units}
group_l2 = {u[0].rsplit('.', 1)[0] for u in units if u[0].count('.') == 2}
extra = [num for num in seg if num not in unit_nums and num not in group_l2]
if extra:
    problems.append('目录外多出单元: ' + ', '.join(sorted(extra)))

fixtures = []
if chnum != 0:
    for k in ('主线推进', '本章工具', '本章作业'):
        if k not in text:
            fixtures.append(f'缺章级固定件: {k}')

print(f'== {args.ch}: 目录单元 {len(units)} 个 ==')
for line in ok:
    print('  ✓', line)
for line in problems + fixtures:
    print('  ✗', line)
total = cn_count(text)
print(f'全章中文字数: {total}')
sys.exit(1 if (problems or fixtures) else 0)
