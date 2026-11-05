"""Personal feed collector for local checks and cloud jobs; public metadata only."""
import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import gzip
from html import unescape
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=8))
MAX_BYTES = 6_000_000
HOSTS = {'www.youtube.com', 'www.bilibili.com'}
GIRLS = re.compile(r'\bA2O[\s_]*(?:MAY|LITE)\b', re.I)
NOT_TRAVEL = re.compile(r'iPhone|Pocket|相机|镜头|评测|开箱|开麦|工作室|抽奖|篮球|NBA|投篮|补剂|营养品工厂|恰饭对决', re.I)
TRAVEL = re.compile(r'旅行|旅程|旅游|探访|探秘|徒步|登山|雪山|船票|船旅|自驾|列车|酒店|海岛|小岛|雨林|极夜|极昼|city.?walk|北极|南极|冰岛|挪威|西班牙|墨脱|科西嘉|法国|巴黎|意大利|米兰|洛杉矶|旧金山|达拉斯|印尼|印度尼西亚|云南|重庆|新疆|山西|西藏|桂林|阳朔|首尔|京都|日本|非洲|北欧|曼谷|摩洛哥|埃及|异世界|村庄', re.I)


class SourceError(Exception):
    pass


def clean(value):
    return re.sub(r'\s+', ' ', unescape(str(value or ''))).strip()


def stamp(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, TZ)
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None:
        raise ValueError('Missing publication timezone')
    return date.astimezone(TZ)


def fetch(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username or parsed.password:
        raise SourceError('Unexpected URL')
    request = Request(url, headers={'User-Agent': 'WanPersonalFeed/0.2 (public metadata reader)', 'Accept-Language': 'zh-CN,en;q=0.8'})
    with urlopen(request, timeout=20) as response:
        if urlparse(response.url).hostname not in HOSTS:
            raise SourceError('Unexpected redirect')
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise SourceError('Response too large')
    if raw[:2] == b'\x1f\x8b':
        # Limit decompressed input as well as wire size.
        from io import BytesIO
        with gzip.GzipFile(fileobj=BytesIO(raw)) as file:
            raw = file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise SourceError('Decoded response too large')
    return raw.decode('utf-8')


def embedded(body, variable):
    match = re.search(r'(?:var\s+|window\.)?' + re.escape(variable) + r'\s*=\s*', body)
    if not match:
        raise SourceError('Public page structure changed')
    data, _ = json.JSONDecoder().raw_decode(body[match.end():])
    if not isinstance(data, dict):
        raise SourceError('Invalid page data')
    return data


def walk(value, key):
    if isinstance(value, dict):
        if key in value:
            yield value[key]
        for child in value.values():
            yield from walk(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child, key)


def youtube_index(body, source):
    data = embedded(body, 'ytInitialData')
    metadata = data.get('metadata', {}).get('channelMetadataRenderer', {})
    if metadata.get('externalId') != source['channelId']:
        raise SourceError('Channel identity mismatch')
    tabs = data.get('contents', {}).get('twoColumnBrowseResultsRenderer', {}).get('tabs', [])
    selected = next((tab['tabRenderer'] for tab in tabs if tab.get('tabRenderer', {}).get('selected')), {})
    grid = selected.get('content', {})
    rows = []
    for vm in walk(grid, 'lockupViewModel'):
        if vm.get('contentType') != 'LOCKUP_CONTENT_TYPE_VIDEO':
            continue
        title = vm.get('metadata', {}).get('lockupMetadataViewModel', {}).get('title', {}).get('content', '')
        if re.fullmatch(r'[\w-]{11}', vm.get('contentId', '')):
            rows.append({'remoteId': vm['contentId'], 'title': clean(title)})
    for vm in walk(grid, 'videoRenderer'):
        title = ''.join(x.get('text', '') for x in vm.get('title', {}).get('runs', [])) or vm.get('title', {}).get('simpleText', '')
        if re.fullmatch(r'[\w-]{11}', vm.get('videoId', '')):
            rows.append({'remoteId': vm['videoId'], 'title': clean(title)})
    rows = list({r['remoteId']: r for r in rows}.values())
    if not rows:
        raise SourceError('No readable channel uploads')
    return rows[:30]


def youtube_detail(body, source, remote_id):
    data = embedded(body, 'ytInitialPlayerResponse')
    detail = data.get('videoDetails', {})
    if detail.get('channelId') != source['channelId'] or detail.get('videoId') != remote_id:
        playability = data.get('playabilityStatus', {})
        raise SourceError('Video owner mismatch: ' + json.dumps({'id': detail.get('videoId'), 'channel': detail.get('channelId'), 'status': playability.get('status'), 'reason': playability.get('reason')}, ensure_ascii=False))
    micro = data.get('microformat', {}).get('playerMicroformatRenderer', {})
    date = micro.get('publishDate') or micro.get('uploadDate')
    if not date:
        raise SourceError('Missing exact publication date')
    return {'title': clean(detail.get('title')), 'publishedAt': stamp(date).isoformat(), 'description': clean(detail.get('shortDescription', ''))[:2000]}


def youtube_feed(body, source):
    """Read the channel's public Atom metadata, without requesting video playback."""
    if '<!DOCTYPE' in body.upper() or '<!ENTITY' in body.upper():
        raise SourceError('Unexpected XML declarations')
    ns = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
    root = ET.fromstring(body)
    if root.findtext('yt:channelId', namespaces=ns) != source['channelId']:
        raise SourceError('Atom channel identity mismatch')
    rows = {}
    for entry in root.findall('a:entry', ns):
        remote = entry.findtext('yt:videoId', namespaces=ns) or ''
        if not re.fullmatch(r'[\w-]{11}', remote) or entry.findtext('yt:channelId', namespaces=ns) != source['channelId']:
            raise SourceError('Atom video identity mismatch')
        rows[remote] = {'title': clean(entry.findtext('a:title', namespaces=ns)),
                        'publishedAt': stamp(entry.findtext('a:published', namespaces=ns) or '').isoformat()}
    if not rows:
        raise SourceError('No readable Atom entries')
    return rows


def bilibili_index(body, source):
    data = embedded(body, '__INITIAL_STATE__')
    info = data.get('mediaListInfo', {})
    if info.get('upper', {}).get('mid') != source['mid'] or info.get('upper', {}).get('name') != source['account']:
        raise SourceError('Creator identity mismatch')
    if data.get('listError', {}).get('code') not in (None, 200):
        raise SourceError('Creator listing unavailable')
    rows = [{'remoteId': r.get('bvid'), 'title': clean(r.get('title'))} for r in data.get('resourceList', []) if re.fullmatch(r'BV[\w]{10}', r.get('bvid', ''))]
    if not rows:
        raise SourceError('No readable creator uploads')
    return rows[:30]


def bilibili_detail(body, source, remote_id):
    data = embedded(body, '__INITIAL_STATE__')
    video = data.get('videoData', {})
    owner = video.get('owner', {})
    staff = [*data.get('staffData', []), *video.get('staff', [])]
    staff_match = any(p.get('mid') == source['mid'] and p.get('name') == source['account'] for p in staff)
    if (owner.get('mid') != source['mid'] and not staff_match) or video.get('bvid') != remote_id:
        raise SourceError('Video owner mismatch: ' + json.dumps({'id': video.get('bvid'), 'owner': owner.get('mid'), 'staff': [(p.get('mid'),p.get('name')) for p in data.get('staffData', [])]}, ensure_ascii=False))
    if not video.get('pubdate'):
        raise SourceError('Missing exact publication date')
    return {'title': clean(video.get('title')), 'publishedAt': stamp(video['pubdate']).isoformat(), 'description': clean(video.get('desc', ''))[:2000], 'originalAccount': clean(owner.get('name')), 'ownerId': owner.get('mid'), 'collaboration': owner.get('mid') != source['mid']}


def relevant(title, source, description=''):
    if source.get('artist') == 'a2o':
        return bool(GIRLS.search(title)) and not re.search(r'\bA2O[\s_]*SOUL\b', title, re.I)
    if source.get('artist') == 'aespa':
        return True
    return not NOT_TRAVEL.search(title) and bool(TRAVEL.search(title + ' ' + description))


def region_for(text):
    domestic = re.search(r'墨脱|云南|重庆|新疆|山西|西藏|桂林|阳朔|北京|上海|中国|国内|扬州|福建|杭州', text)
    overseas = re.search(r'科西嘉|法国|巴黎|洛杉矶|旧金山|达拉斯|印尼|印度尼西亚|意大利|米兰|首尔|京都|日本|非洲|北欧|北极|南极|冰岛|挪威|西班牙|曼谷|摩洛哥|埃及|格陵兰', text)
    if domestic and not overseas:
        return '国内'
    if overseas and not domestic:
        return '国外'
    return '未分类'


def make_item(source, remote_id, detail, now):
    published = stamp(detail['publishedAt'])
    if not now - timedelta(days=180) <= published <= now + timedelta(minutes=5):
        return None
    if not detail['title'] or len(detail['title']) > 280:
        return None
    platform = source['platform']
    row = dict(id=('youtube-' if platform == 'youtube' else 'bili-') + remote_id,
               remoteId=remote_id, title=detail['title'], type=source['type'],
               publishedAt=published.isoformat(), published=published.date().isoformat(),
               collectedAt=now.isoformat(), sourceId=source['id'], account=source['account'],
               source=('YouTube' if platform == 'youtube' else 'B站') + ' · ' + source['account'],
               url=('https://www.youtube.com/watch?v=' if platform == 'youtube' else 'https://www.bilibili.com/video/') + remote_id,
               label=('A2O MAY' if re.search(r'A2O[\s_]*MAY', detail['title'], re.I) else 'A2O LITE') if source.get('artist') == 'a2o' else source['account'],
               cover='music' if source['type'] == 'K-pop' else 'plane',
               desc='官方频道新投稿' if source['type'] == 'K-pop' else '来自关注 UP 主的旅行新投稿',
               verified=True, datePrecision='second')
    for key in ['artist', 'author']:
        if key in source:
            row[key] = source[key]
    if detail.get('originalAccount'):
        row['source'] = 'B站 · ' + detail['originalAccount']
        row['originalAccount'] = detail['originalAccount']
        row['ownerId'] = detail.get('ownerId')
        row['collaboration'] = bool(detail.get('collaboration'))
        if row['collaboration']:
            row['desc'] = '关注账号参与的合作投稿，原作者为' + detail['originalAccount']
    if source['type'] == '旅行':
        row['region'] = region_for(detail['title'])
    return row


def collect_source(source, previous, now, getter=fetch):
    body = getter(source['url'])
    index = youtube_index(body, source) if source['platform'] == 'youtube' else bilibili_index(body, source)
    old = {r['remoteId']: r for r in previous if r.get('sourceId') == source['id']}
    result, failed, inspected = [], [], 0
    atom, atom_error = None, None
    for candidate in index:
        if not relevant(candidate['title'], source):
            continue
        remote_id = candidate['remoteId']
        url = ('https://www.youtube.com/watch?v=' if source['platform'] == 'youtube' else 'https://www.bilibili.com/video/') + remote_id
        inspected += 1
        try:
            # Always verify the newest qualifying upload directly; reuse exact dates for older known IDs.
            if remote_id in old and inspected > 1:
                detail = {**old[remote_id], 'title': candidate['title'], 'publishedAt': old[remote_id]['publishedAt']}
            else:
                # B站's public list already embeds the current video's full metadata.
                current = embedded(body, '__INITIAL_STATE__').get('videoData', {}) if source['platform'] == 'bilibili' else {}
                if source['platform'] == 'youtube':
                    try:
                        detail = youtube_detail(getter(url), source, remote_id)
                    except Exception as original:
                        # An official metadata feed is an alternative public source, not a
                        # playback login workaround. Only accept IDs listed by /videos.
                        if atom is None and atom_error is None:
                            try:
                                atom = youtube_feed(getter('https://www.youtube.com/feeds/videos.xml?channel_id=' + source['channelId']), source)
                            except Exception as error:
                                atom_error = error
                        if not atom or remote_id not in atom:
                            raise SourceError(str(original) + '; public Atom: ' + str(atom_error or 'video not listed'))
                        detail = atom[remote_id]
                else:
                    page = body if current.get('bvid') == remote_id else getter(url)
                    detail = bilibili_detail(page, source, remote_id)
            if relevant(detail['title'], source, detail.get('description', '')):
                row = make_item(source, remote_id, detail, now)
                if row:
                    result.append(row)
        except Exception as error:
            failed.append({'remoteId': remote_id, 'error': type(error).__name__, 'detail': str(error)[:160]})
        if inspected >= source['take']:
            break
    if not result:
        raise SourceError('No current verified qualifying uploads; keep previous cache')
    result.sort(key=lambda r: stamp(r['publishedAt']), reverse=True)
    health = dict(id=source['id'], account=source['account'], url=source['url'], status='partial' if failed else 'ok', checkedAt=now.isoformat(), count=len(result), listedCount=len(index), inspectedCount=inspected, newestId=result[0]['id'], newestPublishedAt=result[0]['publishedAt'], failures=failed)
    return result, health


def merge(previous, incoming, now):
    by_id = {r['id']: r for r in previous}
    by_id.update({r['id']: r for r in incoming})
    rows = []
    for row in by_id.values():
        try:
            if now - timedelta(days=180) <= stamp(row['publishedAt']) <= now + timedelta(minutes=5):
                rows.append(row)
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(rows, key=lambda r: stamp(r['publishedAt']), reverse=True)[:200]


def read_json(path, fallback):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return fallback


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def run(data_dir, sources, now, getter=fetch, if_due=False):
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / 'collect.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'already-running'}, 0
        health_path, feed_path = data_dir / 'health.json', data_dir / 'feed.json'
        last = read_json(health_path, {})
        if if_due and last.get('checkedAt', '').startswith(now.date().isoformat()) and last.get('status') == 'ok':
            return {'status': 'already-updated-today', 'checkedAt': last['checkedAt']}, 0
        previous = read_json(feed_path, {'items': [], 'sources': []})
        incoming, health = [], []
        old_health = {s['id']: s for s in previous.get('sources', [])}
        for source in sources:
            try:
                rows, status = collect_source(source, previous['items'], now, getter)
                incoming.extend(rows)
                status['lastSuccessAt'] = now.isoformat() if status['status'] == 'ok' else old_health.get(source['id'], {}).get('lastSuccessAt')
            except Exception as error:
                status = dict(id=source['id'], account=source['account'], url=source['url'], status='error', checkedAt=now.isoformat(), count=0, error=type(error).__name__, detail=str(error)[:180], lastSuccessAt=old_health.get(source['id'], {}).get('lastSuccessAt'))
            health.append(status)
            print(json.dumps(status, ensure_ascii=False), flush=True)
        available = sum(s['status'] != 'error' for s in health)
        status = 'ok' if all(s['status'] == 'ok' for s in health) else 'partial' if available else 'error'
        current = dict(schemaVersion=1, checkedAt=now.isoformat(), status=status, sources=health)
        if incoming:
            items = merge(previous['items'], incoming, now)
            old_ids = {r['id'] for r in previous['items']}
            current.update(itemCount=len(items), addedCount=sum(r['id'] not in old_ids for r in items))
            feed = dict(schemaVersion=1, collectedAt=now.isoformat(), newestPublishedAt=items[0]['publishedAt'], status=status, sources=health, items=items)
            atomic_json(feed_path, feed)
            atomic_json(data_dir / 'last-good.json', feed)
        else:
            current.update(itemCount=len(previous['items']), addedCount=0, retainedPrevious=True)
        atomic_json(health_path, current)
        with (data_dir / 'runs.jsonl').open('a') as logs:
            logs.write(json.dumps(current, ensure_ascii=False) + '\n')
        return current, 0 if status == 'ok' else 2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--if-due', action='store_true')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    sources = json.loads((ROOT / 'sources.json').read_text())
    summary, code = run(args.data_dir, sources, datetime.now(TZ), if_due=args.if_due)
    print(json.dumps(summary, ensure_ascii=False))
    return code


if __name__ == '__main__':
    sys.exit(main())
