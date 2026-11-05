"""Publish only validated public metadata to Wan's existing public feed repository."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
REPOSITORY = 'zhudylan12-wq/wan-news-feed'
REMOTE_PATH = 'public/personal-feed.json'
SOURCE_IDS = {s['id']: s for s in json.loads((ROOT/'sources.json').read_text())}
ITEM_FIELDS = ['id','remoteId','title','type','publishedAt','published','collectedAt','sourceId','account','source','url','label','cover','desc','verified','datePrecision','artist','author','region','originalAccount','ownerId','collaboration']
SOURCE_FIELDS = ['id','account','status','checkedAt','count','lastSuccessAt','newestId','newestPublishedAt']


def public_payload(data):
    if data.get('schemaVersion') != 1 or data.get('status') not in ('ok','partial') or not 1 <= len(data.get('items', [])) <= 200:
        raise ValueError('No valid successful public feed')
    items, ids = [], set()
    for row in data['items']:
        source = SOURCE_IDS.get(row.get('sourceId'))
        if not source or row.get('verified') is not True or row.get('id') in ids:
            raise ValueError('Invalid item identity')
        if row.get('artist') != source.get('artist') or row.get('author') != source.get('author'):
            raise ValueError('Account assignment mismatch')
        url = urlparse(row.get('url',''))
        if url.scheme != 'https' or url.hostname not in ('www.youtube.com','www.bilibili.com') or url.username or url.password:
            raise ValueError('Unexpected original URL')
        items.append({key:row[key] for key in ITEM_FIELDS if key in row})
        ids.add(row['id'])
    sources = []
    for source in data['sources']:
        if source.get('id') not in SOURCE_IDS:
            raise ValueError('Unexpected source')
        sources.append({key:source[key] for key in SOURCE_FIELDS if key in source})
    return dict(schemaVersion=1,collectedAt=data['collectedAt'],newestPublishedAt=data['newestPublishedAt'],status=data['status'],sources=sources,items=items)


def gh(args, body=None):
    result = subprocess.run(['gh','api',*args],input=json.dumps(body) if body is not None else None,text=True,capture_output=True,check=False)
    if result.returncode:
        raise RuntimeError('GitHub publication failed: '+result.stderr[:300])
    return json.loads(result.stdout)


def publish(raw):
    endpoint=f'repos/{REPOSITORY}/contents/{REMOTE_PATH}'
    # The target already exists after the initial reviewed release commit.
    old=gh([endpoint])
    if base64.b64decode(old['content']).decode() == raw:
        return {'status':'unchanged','url':old['html_url']}
    result=gh(['--method','PUT',endpoint,'--input','-'],{'message':'Update Wan personal news metadata','content':base64.b64encode(raw.encode()).decode(),'sha':old['sha'],'branch':'main'})
    return {'status':'published','commit':result['commit']['sha'],'url':result['content']['html_url']}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'data/public-feed.json')
    args=parser.parse_args()
    feed=public_payload(json.loads((ROOT/'data/feed.json').read_text()))
    raw=json.dumps(feed,ensure_ascii=False,indent=2)+'\n'
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(raw)
    print(json.dumps(publish(raw) if args.publish else {'status':'prepared','items':len(feed['items']),'output':str(args.output)},ensure_ascii=False))


if __name__=='__main__':
    main()
