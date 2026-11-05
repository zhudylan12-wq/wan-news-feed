"""Refresh the existing App feed on a cloud runner without local state or secrets."""
import argparse
from datetime import datetime
import json
from pathlib import Path

import collect
from publish import public_payload, SOURCE_FIELDS


def refresh(public_dir, work_dir, sources, now, getter=collect.fetch):
    public_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    feed_path = public_dir / 'personal-feed.json'
    # A fresh hosted runner starts from the last published snapshot, not a Mac cache.
    if feed_path.exists():
        previous = public_payload(json.loads(feed_path.read_text()))
        collect.atomic_json(work_dir / 'feed.json', previous)
    health, code = collect.run(work_dir, sources, now, getter=getter)
    if health.get('status') in ('ok', 'partial'):
        payload = public_payload(json.loads((work_dir / 'feed.json').read_text()))
        collect.atomic_json(feed_path, payload)
    # Publish a separate operational status even when the content must be retained.
    status = {key: health[key] for key in ('schemaVersion', 'checkedAt', 'status',
              'itemCount', 'addedCount', 'retainedPrevious') if key in health}
    status['sources'] = [{key: row[key] for key in SOURCE_FIELDS if key in row}
                         for row in health.get('sources', [])]
    collect.atomic_json(public_dir / 'personal-feed-health.json', status)
    return health, code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--public-dir', type=Path, default=Path('public'))
    parser.add_argument('--work-dir', type=Path, default=Path('.work/personal-news'))
    args = parser.parse_args()
    sources = json.loads((collect.ROOT / 'sources.json').read_text())
    health, code = refresh(args.public_dir, args.work_dir, sources, datetime.now(collect.TZ))
    print(json.dumps({key: health.get(key) for key in
                     ('status', 'checkedAt', 'itemCount', 'addedCount', 'retainedPrevious')}, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
