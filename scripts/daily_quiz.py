#!/usr/bin/env python3
"""每日练习出题脚本:每天从网上找一顶真实帽子,按部件拆出参考报价,生成一道估价题。

四条通道,依次降级:
  1. RapidAPI Otapi 1688(配了 RAPIDAPI_KEY 时,免费档20次/天够用):真图 + 真实批发价
  2. OneBound 1688 API(配了 ONEBOUND_KEY/ONEBOUND_SECRET 时):同上,备选
  3. Claude 联网搜索(web_search/web_fetch 服务端工具):找真实商品页
  4. 纸面题:从价格库随机组合规格,无图纯文字——保证每天必有一题

产出:
  daily/YYYY-MM-DD.json   题目(部件参考答案 + 解析 + 出处)
  daily/img/YYYY-MM-DD-N.jpg  商品图(本地化,保证显示与离线)
  daily/index.json        索引(新的在前)

由 .github/workflows/daily-quiz.yml 每天调用;本地调试:
  ANTHROPIC_API_KEY=sk-... python3 scripts/daily_quiz.py
"""
import base64
import datetime
import json
import os
import random
import re
import sys
from pathlib import Path

import requests
import anthropic

ROOT = Path(__file__).resolve().parent.parent
DAILY = ROOT / 'daily'
IMG_DIR = DAILY / 'img'
MODEL = (os.environ.get('QUIZ_MODEL') or 'claude-sonnet-5')  # 出题模型,想更省可设为 claude-haiku-4-5
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
      'Referer': 'https://www.1688.com/'}

# 北京时间的"今天"
TODAY = os.environ.get('QUIZ_DATE') or (
    datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
).strftime('%Y-%m-%d')

KEYWORD_POOL = [
    ('六片棒球帽', '纯棉斜纹 刺绣 棒球帽'),
    ('五片平沿帽', '五片 平沿帽 嘻哈帽'),
    ('网帽trucker', '网帽 卡车帽 五片 拼接'),
    ('渔夫帽', '渔夫帽 双面 纯棉'),
    ('3D绣花棒球帽', '3D立体绣 棒球帽'),
    ('灯芯绒帽', '灯芯绒 棒球帽 复古'),
    ('麂皮帽', '麂皮 绒面 棒球帽'),
    ('儿童棒球帽', '儿童 棒球帽 卡通刺绣'),
    ('运动速干帽', '速干 运动帽 涤纶'),
]


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default


def prices_digest(prices):
    """价格库压成给模型看的摘要文字"""
    out = []
    for sec, title in [('fabrics', '面料'), ('trims', '辅料'), ('crafts', '工艺'),
                       ('labor', '工缴'), ('overhead', '比例项'), ('reference_caps', '整帽参考')]:
        items = prices.get(sec) or []
        lines = []
        for it in items:
            rng = f"{it.get('low')}-{it.get('high')}" if it.get('low') is not None else str(it.get('typical'))
            s = f"{it.get('name')}:{rng}{it.get('unit', '')}"
            if it.get('usage_per_cap_sqm'):
                s += f"(单顶约{it['usage_per_cap_sqm']}㎡)"
            if it.get('note'):
                s += f"[{it['note'][:40]}]"
            lines.append(s)
        if lines:
            out.append(f"【{title}】" + ';'.join(lines))
    meta = prices.get('meta') or {}
    out.append(f"(价格库更新于{meta.get('updated')},美元汇率{meta.get('usd_cny')})")
    return '\n'.join(out)


QUIZ_SCHEMA_HINT = """输出且只输出一个 JSON 对象(不要 markdown 代码块、不要任何解释文字),结构:
{
  "title": "十字内的题目名,如: 灯芯绒六片棒球帽",
  "desc": "两三句题干:这是什么帽子、什么面料工艺、假设的客户场景",
  "order": {"qty": 500, "note": "FOB青岛,含单塑袋与外箱"},
  "components": [
    {"label": "面料", "hint": "提示用量或规格,不给答案", "low": 1.2, "high": 1.7, "typical": 1.4,
     "explain": "一两句:这个数怎么算出来的(用量×单价),引用价格库口径"},
    ... 共7-9项,必须覆盖: 面料、辅料合计(或拆开2-3项)、绣花/印花等可见工艺(逐项)、裁剪车缝工缴、损耗、管理摊销、毛利
  ],
  "fob": {"low": 16, "high": 19, "typical": 17.5, "explain": "合计口径说明"},
  "market_price": {"cny": 9.9, "note": "商品页实际标价与我们拆算FOB的差异解释(档口现货价vs定制FOB的区别)", "url": "商品页链接"} 或 null,
  "analysis": "150-300字完整解析,markdown,像老业务复盘:哪几项最容易估错、为什么",
  "sources": [{"title": "出处名", "url": "链接"}]
}
所有价格用人民币元/顶。components 的 low/high 是"行情合理区间",typical 是你的参考答案;
区间要实事求是,别把区间放宽到怎么填都对。数字都用 number 不用字符串。"""


def extract_json(text):
    """从模型输出里抠出第一个完整 JSON 对象"""
    text = re.sub(r'^```(json)?|```$', '', text.strip(), flags=re.M).strip()
    start = text.find('{')
    if start < 0:
        raise ValueError('输出里没有 JSON')
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError('JSON 未闭合')


def validate_quiz(q):
    assert isinstance(q.get('components'), list) and 5 <= len(q['components']) <= 12, 'components 数量异常'
    for c in q['components'] + [q['fob']]:
        for k in ('low', 'high', 'typical'):
            c[k] = round(float(c[k]), 2)
        assert c['low'] <= c['typical'] <= c['high'], f"区间不合法: {c}"
    assert q.get('title') and q.get('fob'), '缺 title/fob'
    return q


def download_images(urls, date):
    """下载商品图到 daily/img/,返回相对路径列表"""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for i, u in enumerate(urls[:4]):
        if u.startswith('//'):
            u = 'https:' + u
        try:
            r = requests.get(u, headers=UA, timeout=30)
            r.raise_for_status()
            if len(r.content) < 3000:  # 占位图/防盗链小图
                continue
            p = IMG_DIR / f'{date}-{len(saved) + 1}.jpg'
            p.write_bytes(r.content)
            saved.append(f'daily/img/{p.name}')
        except Exception as e:
            print(f'图片下载失败 {u}: {e}', file=sys.stderr)
    return saved


def image_blocks(paths):
    blocks = []
    for p in paths:
        data = base64.standard_b64encode((ROOT / p).read_bytes()).decode()
        blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': data}})
    return blocks


def gen_quiz(client, digest, listing_text, img_paths, extra_rule=''):
    """看图(可选)+商品信息 → 出题 JSON"""
    system = f"""你是帽子外贸教学书《一顶帽子的全球旅行》的出题老师,给学员出「看帽拆价」每日一题。
学员要练的是:看到一顶帽子,按报价单八层拆法(面料/辅料/工艺/工缴/损耗/管理/毛利)逐项估出元/顶,再合成FOB价。
计价必须基于下面的价格库区间,结合这顶帽子的具体工艺增减,不许凭空编价:
{digest}
{extra_rule}
{QUIZ_SCHEMA_HINT}"""
    content = image_blocks(img_paths) + [{'type': 'text', 'text': listing_text}]
    messages = [{'role': 'user', 'content': content}]
    last_err = None
    for attempt in range(3):  # 模型偶发输出不合法 JSON,带着报错重试
        with client.messages.stream(
            model=MODEL, max_tokens=16000,
            system=system,
            messages=messages,
        ) as stream:
            msg = stream.get_final_message()
        text = ''.join(b.text for b in msg.content if b.type == 'text')
        try:
            return validate_quiz(extract_json(text))
        except Exception as e:
            last_err = e
            print(f'出题第{attempt + 1}次输出无效({e}),重试', file=sys.stderr)
            messages = messages[:1] + [
                {'role': 'assistant', 'content': text[:3000]},
                {'role': 'user', 'content': f'你上面的输出解析失败:{e}。重新输出完整、合法的 JSON,注意字符串里的引号要转义,只输出 JSON 本身。'},
            ]
    raise last_err


# ───────── 通道一:RapidAPI Otapi 1688(免费档20次/天) ─────────

def _pic_urls(obj):
    """从 OTAPI 返回的任意 JSON 里抠出所有图片直链(结构防御:不依赖具体字段路径)"""
    blob = json.dumps(obj, ensure_ascii=False)
    urls = re.findall(r'https?:[^"\\\s]+?\.(?:jpg|jpeg|png|webp)[^"\\\s]*', blob)
    seen, out = set(), []
    for u in urls:
        base = u.split('?')[0]
        if base not in seen and 'video' not in u:
            seen.add(base)
            out.append(u)
    return out


def _find_items(obj):
    """在嵌套 JSON 里找第一组带 Id+Title 的商品列表"""
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and 'Id' in obj[0] and 'Title' in obj[0]:
            return obj
        for x in obj:
            r = _find_items(x)
            if r:
                return r
    elif isinstance(obj, dict):
        for v in obj.values():
            r = _find_items(v)
            if r:
                return r
    return None


def try_otapi(client, digest, recent_ids):
    rk = os.environ.get('RAPIDAPI_KEY')
    if not rk:
        print('未配置 RAPIDAPI_KEY,跳过通道一')
        return None
    headers = {'x-rapidapi-key': rk, 'x-rapidapi-host': 'otapi-1688.p.rapidapi.com'}
    name, kw = random.choice(KEYWORD_POOL)
    try:
        r = requests.get('https://otapi-1688.p.rapidapi.com/BatchSearchItemsFrame',
                         params={'language': 'en', 'ItemTitle': kw,
                                 'framePosition': random.choice([0, 20, 40]), 'frameSize': 20,
                                 'OrderBy': 'Popularity:Desc', 'MinVolume': 30},
                         headers=headers, timeout=90)
        items = _find_items(r.json()) or []
    except Exception as e:
        print(f'Otapi 搜索失败: {e}', file=sys.stderr)
        return None
    random.shuffle(items)
    for it in items:
        iid = str(it.get('Id') or '')
        if not iid or iid in recent_ids:
            continue
        try:
            r2 = requests.get('https://otapi-1688.p.rapidapi.com/BatchGetItemFullInfo',
                              params={'language': 'en', 'itemId': iid}, headers=headers, timeout=90)
            detail = r2.json()
        except Exception as e:
            print(f'Otapi 详情失败: {e}', file=sys.stderr)
            continue
        img_paths = download_images(_pic_urls(detail), TODAY)
        if not img_paths:
            continue
        raw = json.dumps(detail, ensure_ascii=False)
        raw = re.sub(r'https?:[^"\\\s]{80,}', '', raw)[:7000]  # 去长URL省token
        listing = (f"下面是 1688 上一个真实商品(OTAPI 返回数据节选,价格多为人民币,若带汇率字段注意换算):\n{raw}\n\n"
                   f"配图是它的商品图。请围绕这顶帽子出今天的题。market_price 用它的真实标价(阶梯价取批发档),"
                   f"url 用 1688 商品页链接(ExternalItemUrl 或按 id 拼 https://detail.1688.com/offer/<纯数字id>.html)。"
                   f"注意:1688标价是档口现货价,和我们拆算的定制FOB口径不同,要在 note 里讲清差异。")
        try:
            quiz = gen_quiz(client, digest, listing, img_paths)
            quiz['images'] = img_paths
            quiz['source'] = 'otapi'
            quiz['source_id'] = iid
            return quiz
        except Exception as e:
            print(f'通道一出题失败: {e}', file=sys.stderr)
            return None
    return None


# ───────── 通道二:OneBound 1688 API ─────────

def try_onebound(client, digest, recent_ids):
    key, secret = os.environ.get('ONEBOUND_KEY'), os.environ.get('ONEBOUND_SECRET')
    if not (key and secret):
        print('未配置 OneBound,跳过通道一')
        return None
    name, kw = random.choice(KEYWORD_POOL)
    try:
        r = requests.get('https://api-gw.onebound.cn/1688/item_search/',
                         params={'key': key, 'secret': secret, 'q': kw,
                                 'page': random.randint(1, 3), 'page_size': 20, 'sort': 'sales'},
                         timeout=60)
        items = (r.json().get('items') or {}).get('item') or []
    except Exception as e:
        print(f'OneBound 搜索失败: {e}', file=sys.stderr)
        return None
    random.shuffle(items)
    for it in items:
        iid = str(it.get('num_iid') or '')
        if not iid or iid in recent_ids:
            continue
        try:
            r2 = requests.get('https://api-gw.onebound.cn/1688/item_get/',
                              params={'key': key, 'secret': secret, 'num_iid': iid}, timeout=60)
            detail = (r2.json() or {}).get('item') or {}
        except Exception as e:
            print(f'OneBound 详情失败: {e}', file=sys.stderr)
            continue
        img_urls = [x.get('url') for x in (detail.get('item_imgs') or []) if x.get('url')]
        if detail.get('pic_url'):
            img_urls.insert(0, detail['pic_url'])
        img_paths = download_images(list(dict.fromkeys(img_urls)), TODAY)
        if not img_paths:
            continue
        raw = json.dumps({k: detail.get(k) for k in
                          ('title', 'price', 'orginal_price', 'priceRange', 'props_list', 'props',
                           'num', 'detail_url', 'location', 'sales')},
                         ensure_ascii=False)[:6000]
        listing = (f"下面是 1688 上一个真实商品(原始数据节选):\n{raw}\n\n"
                   f"配图是它的商品图。请围绕这顶帽子出今天的题。market_price 用它的真实标价,"
                   f"url 用 detail_url(补全 https:)。注意:1688标价是档口现货价,"
                   f"和我们拆算的定制FOB口径不同,要在 note 里讲清差异。")
        try:
            quiz = gen_quiz(client, digest, listing, img_paths)
            quiz['images'] = img_paths
            quiz['source'] = 'onebound'
            quiz['source_id'] = iid
            return quiz
        except Exception as e:
            print(f'通道一出题失败: {e}', file=sys.stderr)
            return None
    return None


# ───────── 通道二:Claude 联网搜索 ─────────

def try_websearch(client, digest, recent_urls):
    name, kw = random.choice(KEYWORD_POOL)
    avoid = '\n'.join(recent_urls[:30])
    try:
        with client.messages.stream(
            model=MODEL, max_tokens=16000,
            # haiku 只支持基础版联网工具,新版 20260209 需要 sonnet 4.6+/sonnet 5/opus
            tools=([{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 8},
                    {'type': 'web_fetch_20250910', 'name': 'web_fetch', 'max_uses': 6}]
                   if 'haiku' in MODEL else
                   [{'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 8},
                    {'type': 'web_fetch_20260209', 'name': 'web_fetch', 'max_uses': 6}]),
            messages=[{'role': 'user', 'content': f"""帮我找一个真实在售的帽子商品页,用于外贸估价教学。
要求:类型是「{name}」(搜索方向:{kw}),商品页要有多角度大图(最好含内里/细节图),页面上有标价。
优先 1688 / 阿里巴巴国际站 / made-in-china / 亚马逊。避开这些用过的链接:\n{avoid or '(无)'}
找到后,只输出一个 JSON(不要代码块):
{{"title":"商品名","url":"商品页链接","price_note":"页面标价与阶梯价原文","image_urls":["图片直链",...最多6个],"desc":"一句话描述帽子的款式面料工艺"}}
图片直链要是 .jpg/.png/.webp 的完整 URL。"""}],
        ) as stream:
            msg = stream.get_final_message()
        raw_text = ''.join(b.text for b in msg.content if b.type == 'text')
        try:
            found = extract_json(raw_text)
        except Exception:
            # 偶发 JSON 格式错:让模型自己修一遍,不重新联网搜
            with client.messages.stream(
                model=MODEL, max_tokens=4000,
                messages=[{'role': 'user', 'content':
                           f'把下面内容修成一个合法 JSON 对象原样输出(修引号转义/缺逗号,不改内容,只输出JSON):\n{raw_text[:4000]}'}],
            ) as s2:
                found = extract_json(''.join(b.text for b in s2.get_final_message().content if b.type == 'text'))
    except Exception as e:
        print(f'联网搜索失败: {e}', file=sys.stderr)
        return None
    img_paths = download_images(found.get('image_urls') or [], TODAY)
    listing = (f"商品信息:{json.dumps(found, ensure_ascii=False)[:3000]}\n"
               + (f"配图是它的商品图。" if img_paths else "图片下载失败,按文字描述出题,desc 里把帽子外观写详细些。")
               + "market_price 依据 price_note,url 用商品页链接。")
    try:
        quiz = gen_quiz(client, digest, listing, img_paths)
        quiz['images'] = img_paths
        quiz['source'] = 'websearch'
        quiz['source_id'] = found.get('url', '')
        return quiz
    except Exception as e:
        print(f'通道二出题失败: {e}', file=sys.stderr)
        return None


# ───────── 通道三:纸面题兜底 ─────────

def synthetic(client, digest):
    name, kw = random.choice(KEYWORD_POOL)
    listing = (f"今天没有真实商品图,出一道纸面题:虚构一顶规格具体的「{name}」"
               f"(面料规格、克重、工艺、针数都写死在 desc 里,让学员有足够信息估价),market_price 填 null。")
    quiz = gen_quiz(client, digest, listing, [])
    quiz['images'] = []
    quiz['source'] = 'synthetic'
    quiz['source_id'] = ''
    return quiz


def prune_old():
    """图片留 90 天,索引留 120 条"""
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
    for p in IMG_DIR.glob('*.jpg'):
        if p.name[:10] < cutoff:
            p.unlink()
    for p in DAILY.glob('*.json'):
        if p.name != 'index.json' and p.name[:10] < cutoff:
            p.unlink()


def main():
    DAILY.mkdir(exist_ok=True)
    prices = load_json(ROOT / 'data/prices.json', None)
    if not prices:
        sys.exit('data/prices.json 缺失,先跑价格库')
    digest = prices_digest(prices)
    index = load_json(DAILY / 'index.json', {'days': []})
    if any(d.get('date') == TODAY for d in index['days']) and not os.environ.get('FORCE'):
        print(f'{TODAY} 已出过题,跳过(设 FORCE=1 可重出)')
        return

    client = anthropic.Anthropic()
    recent_ids = {str(d.get('source_id')) for d in index['days'][:60] if d.get('source_id')}

    quiz = (try_otapi(client, digest, recent_ids)
            or try_onebound(client, digest, recent_ids)
            or try_websearch(client, digest, list(recent_ids))
            or synthetic(client, digest))
    quiz['date'] = TODAY

    (DAILY / f'{TODAY}.json').write_text(
        json.dumps(quiz, ensure_ascii=False, indent=1), encoding='utf-8')
    index['days'] = ([{'date': TODAY, 'title': quiz['title'],
                       'source': quiz['source'], 'source_id': quiz.get('source_id', '')}]
                     + [d for d in index['days'] if d.get('date') != TODAY])[:120]
    (DAILY / 'index.json').write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
    prune_old()
    print(f"出题完成: {TODAY} 「{quiz['title']}」 通道={quiz['source']} 图={len(quiz['images'])}张")


if __name__ == '__main__':
    main()
