"""Daily public news metadata collector. No accounts, personal data or full articles."""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import json
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=8))
SOURCES = [
    ('365-wash', '宠物365', 'https://www.chongwu365.com/news/xihu/', '宠物洗美'),
    ('365-food', '宠物365', 'https://www.chongwu365.com/news/chongliang/', '营养鲜食'),
    ('365-industry', '宠物365', 'https://www.chongwu365.com/news/gnxw/', '行业动态'),
    ('cips', 'CIPS 官网', 'https://www.cipscom.com/ShowNews/index.htm', '行业动态'),
    ('cns-finance', '中国新闻网', 'https://www.chinanews.com.cn/rss/finance.xml', None),
    ('cns-society', '中国新闻网', 'https://www.chinanews.com.cn/rss/society.xml', None),
]
HOSTS = {'www.chongwu365.com', 'www.cipscom.com', 'www.chinanews.com.cn', 'www.chinanews.com'}


def clean(value):
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', '', value or ''))).strip()


def categories(title, default=None):
    if re.search(r'水族|龙鱼|魟鱼|虎鱼|蝴蝶鲤|小丑鱼|造景|鹦鹉', title):
        return []
    if not default and not re.search(r'宠物|宠业|猫粮|狗粮|犬猫', title):
        return []
    result = []
    if re.search(r'洗护|洗美|美容|护理|洗澡|美毛|梳毛', title):
        result.append('宠物洗美')
    if re.search(r'鲜食|营养|食品|宠粮|猫粮|狗粮|犬粮|主粮|零食|饲料', title):
        result.append('营养鲜食')
    if default and default not in result:
        result.append(default)
    return result or ['行业动态']


def item(title, url, date, source, source_id, default, now):
    title = clean(title)
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password:
        return None
    try:
        stamp = datetime.fromisoformat(date)
    except ValueError:
        return None
    if stamp.tzinfo is None or not now - timedelta(days=180) <= stamp <= now + timedelta(minutes=5):
        return None
    cats = categories(title, default)
    if not cats or not 5 <= len(title) <= 180:
        return None
    return dict(id=sha256(url.encode()).hexdigest()[:20], title=title, url=url,
                publishedAt=stamp.astimezone(TZ).isoformat(), source=source,
                sourceId=source_id, categories=cats,
                kind='展会动态' if source_id == 'cips' else '媒体资讯', summary='')


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = None
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.active = [dict(attrs).get('href', ''), '']

    def handle_data(self, data):
        if self.active is not None:
            self.active[1] += data

    def handle_endtag(self, tag):
        if tag == 'a' and self.active is not None:
            self.rows.append(self.active)
            self.active = None


def fetch(url):
    request = Request(url, headers={'User-Agent': 'WanNews/1.0 (+https://github.com/zhudylan12-wq/wan-news-feed)'})
    with urlopen(request, timeout=18) as response:
        if urlparse(response.url).hostname not in HOSTS:
            raise ValueError('Unexpected redirect host')
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError('Source response too large')
        return data.decode(response.headers.get_content_charset() or 'utf-8')


def parse_cips(body, source, now):
    sid, publisher, _, default = source
    rows = []
    for block in re.findall(r'<li\b[^>]*>(.*?)</li>', body, re.S):
        date = re.search(r'<h3>\s*(\d{2})\.(\d{2})\s*<span>(\d{4})</span>', block)
        link = re.search(r'href="(https://www\.cipscom\.com/ShowNews/\d+\.htm)">(.*?)</a>', block, re.S)
        if date and link:
            month, day, year = date.groups()
            row = item(link[2], link[1], f'{year}-{month}-{day}T00:00:00+08:00', publisher, sid, default, now)
            if row:
                row['datePrecision'] = 'day'
                rows.append(row)
    if not re.search(r'/ShowNews/\d+\.htm', body):
        raise ValueError('CIPS page format changed')
    return rows


def parse_rss(body, source, now):
    sid, publisher, _, default = source
    root = ET.fromstring(body)
    if root.tag != 'rss' or root.find('channel') is None:
        raise ValueError('Invalid RSS')
    rows = []
    for entry in root.findall('./channel/item'):
        try:
            date = parsedate_to_datetime(entry.findtext('pubDate', '')).isoformat()
        except (ValueError, TypeError):
            continue
        row = item(entry.findtext('title'), entry.findtext('link', ''), date, publisher, sid, default, now)
        if row:
            rows.append(row)
    return rows


def collect_source(source, existing, now):
    sid, publisher, url, default = source
    body = fetch(url)
    if sid == 'cips':
        return parse_cips(body, source, now), 0
    if sid.startswith('cns-'):
        return parse_rss(body, source, now), 0
    links = Links()
    links.feed(body)
    urls = list(dict.fromkeys(u for u, _ in links.rows if re.fullmatch(r'https://www\.chongwu365\.com/news/\d+\.html', u)))[:15]
    if not urls:
        raise ValueError('News index format changed')
    rows, failed, parsed_count = [], 0, 0
    for link in urls:
        if link in existing:
            row = dict(existing[link])
            row['categories'] = sorted(set(row['categories'] + [default]))
            rows.append(row)
            parsed_count += 1
            continue
        try:
            article = fetch(link)
            title = re.search(r'<h1\b[^>]*>(.*?)</h1>', article, re.S)
            date = re.search(r'时间[：:]\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})', article)
            if not title or not date:
                raise ValueError('Missing article metadata')
            parsed_count += 1
            row = item(title[1], link, f'{date[1]}T{date[2]}:00+08:00', publisher, sid, default, now)
            if row:
                rows.append(row)
        except Exception:
            failed += 1
    if not parsed_count:
        raise ValueError('No readable article metadata')
    return rows, failed


def merge(previous, incoming, now):
    result, titles = {}, set()
    for row in previous + incoming:
        if row['url'] in result:
            row = dict(row, categories=sorted(set(row['categories'] + result[row['url']]['categories'])))
        result[row['url']] = row
    output = []
    for row in sorted(result.values(), key=lambda r: r['publishedAt'], reverse=True):
        stamp = datetime.fromisoformat(row['publishedAt'])
        title_key = re.sub(r'\W', '', row['title']).lower()
        if now - timedelta(days=180) <= stamp <= now + timedelta(minutes=5) and title_key not in titles:
            titles.add(title_key)
            output.append(row)
    return output[:180]


def main():
    now = datetime.now(TZ)
    target = ROOT / 'public/feed.json'
    previous = json.loads(target.read_text()) if target.exists() else {'items': []}
    existing = {row['url']: row for row in previous['items']}
    incoming, status = [], []
    def run(source):
        try:
            rows, failed = collect_source(source, existing, now)
            return rows, dict(id=source[0], status='partial' if failed else 'ok', count=len(rows), failedArticles=failed)
        except Exception as error:
            return [], dict(id=source[0], status='error', detail=type(error).__name__)
    # Each publisher is fetched sequentially to avoid a burst of article requests.
    for source in SOURCES:
        rows, health = run(source)
        incoming.extend(rows)
        status.append(health)
        print(json.dumps(health, ensure_ascii=False))
    available = sum(row['status'] != 'error' for row in status)
    if available == 0:
        raise RuntimeError('All sources failed; retaining last successful feed')
    items = merge(previous['items'], incoming, now)
    if not items:
        raise RuntimeError('No valid news; retaining last successful feed')
    feed = dict(schemaVersion=1, checkedAt=now.isoformat(), newestPublishedAt=items[0]['publishedAt'],
                status='ok' if all(s['status'] == 'ok' for s in status) else 'partial',
                sources=status, items=items)
    target.parent.mkdir(exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(target)
    print(f'Published {len(items)} items; {available}/{len(SOURCES)} sources available')


if __name__ == '__main__':
    main()
