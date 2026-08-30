#!/usr/bin/env python3
"""价格库周度校准:让 Claude 联网核对 data/prices.json 里的市场价,更新区间与出处。

只更新数字、出处、置信度和 note,不增删条目、不改 id/name/unit/book 字段——
前端和出题脚本都按现有条目结构工作,结构变更需要人工改。

由 .github/workflows/update-prices.yml 每周一调用;本地调试:
  ANTHROPIC_API_KEY=sk-... python3 scripts/update_prices.py
"""
import datetime
import json
import os
import sys
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent.parent
PRICES_PATH = ROOT / 'data/prices.json'
MODEL = (os.environ.get('QUIZ_MODEL') or 'claude-sonnet-5')  # 出题模型,想更省可设为 claude-haiku-4-5
TODAY = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)).strftime('%Y-%m-%d')


def extract_json(text):
    import re
    text = re.sub(r'^```(json)?|```$', '', text.strip(), flags=re.M).strip()
    start = text.find('{')
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError('JSON 未闭合')


def main():
    old = json.loads(PRICES_PATH.read_text(encoding='utf-8'))
    client = anthropic.Anthropic()

    with client.messages.stream(
        model=MODEL, max_tokens=64000,
        tools=([{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 20},
                {'type': 'web_fetch_20250910', 'name': 'web_fetch', 'max_uses': 10}]
               if 'haiku' in MODEL else
               [{'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 20},
                {'type': 'web_fetch_20260209', 'name': 'web_fetch', 'max_uses': 10}]),
        messages=[{'role': 'user', 'content': f"""下面是一份帽子外贸成本价格库(中国产业带、500-1000顶量级、人民币)。
请联网抽查核对:优先核对 confidence 为 low 的条目和大宗原料类条目(面料、纱线、纸箱),
每类至少搜 1-2 次;有新证据就更新 low/high/typical/sources/confidence/note,没有新证据的条目**原样保留**。

规则:
1. 结构不许动:不增删条目,不改 id/name/unit/book/width_m/usage_per_cap_sqm 字段。
2. sources 只放你本次实际看到的链接,并保留原有仍然有效的来源;date 用 "{TODAY[:7]}"。
3. meta.updated 改为 "{TODAY}";若查到新汇率,更新 meta.usd_cny。
4. 数字变动超过 30% 的,note 里必须写明变动依据。
5. 输出完整的更新后 JSON,不要 markdown 代码块,不要解释文字。

{json.dumps(old, ensure_ascii=False)}"""}],
    ) as stream:
        msg = stream.get_final_message()

    text = ''.join(b.text for b in msg.content if b.type == 'text')
    new = extract_json(text)

    # 结构守卫:节名、条目数、id 集合必须一致
    for sec in ('fabrics', 'trims', 'crafts', 'labor', 'overhead', 'reference_caps'):
        old_ids = [x['id'] for x in old[sec]]
        new_ids = [x['id'] for x in new.get(sec, [])]
        assert old_ids == new_ids, f'{sec} 结构被改动: {old_ids} -> {new_ids}'
        for o, n in zip(old[sec], new[sec]):
            for k in ('name', 'unit'):
                n[k] = o[k]
            if 'book' in o:
                n['book'] = o['book']
            for k in ('low', 'high', 'typical'):
                n[k] = round(float(n[k]), 3)
    new['meta']['updated'] = TODAY

    PRICES_PATH.write_text(json.dumps(new, ensure_ascii=False, indent=2), encoding='utf-8')
    changed = sum(1 for sec in ('fabrics', 'trims', 'crafts', 'labor', 'overhead', 'reference_caps')
                  for o, n in zip(old[sec], new[sec])
                  if (o['low'], o['high'], o['typical']) != (n['low'], n['high'], n['typical']))
    print(f'价格库校准完成: {changed} 个条目的数字有更新')


if __name__ == '__main__':
    main()
