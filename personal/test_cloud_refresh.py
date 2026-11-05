import contextlib
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import collect
import cloud_refresh

NOW = datetime(2026, 11, 5, 13, tzinfo=collect.TZ)
SOURCES = json.loads((collect.ROOT / 'sources.json').read_text())


class CloudTests(unittest.TestCase):
    def snapshot(self):
        row = collect.make_item(SOURCES[0], 'WoeDaIg7Xf4',
                               {'title': 'aespa Concert Behind',
                                'publishedAt': (NOW - timedelta(days=1)).isoformat()}, NOW - timedelta(hours=1))
        return dict(schemaVersion=1, status='ok', collectedAt=(NOW-timedelta(hours=1)).isoformat(),
                    newestPublishedAt=row['publishedAt'], items=[row], sources=[])

    def setup_dirs(self, folder):
        public, work = Path(folder)/'public', Path(folder)/'ephemeral-runner'
        public.mkdir()
        collect.atomic_json(public/'personal-feed.json', self.snapshot())
        return public, work

    def test_cloud_all_fail_keeps_exact_published_content_and_reports_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            public, work = self.setup_dirs(folder)
            before = (public/'personal-feed.json').read_bytes()
            def offline(_):
                raise collect.SourceError('unavailable')
            with contextlib.redirect_stdout(io.StringIO()):
                health, code = cloud_refresh.refresh(public, work, SOURCES, NOW, getter=offline)
            self.assertEqual(code, 2)
            self.assertEqual((public/'personal-feed.json').read_bytes(), before)
            self.assertTrue(health['retainedPrevious'])
            state = json.loads((public/'personal-feed-health.json').read_text())
            self.assertEqual(state['status'], 'error')
            self.assertEqual(len(state['sources']), 6)
            self.assertNotIn('detail', state['sources'][0])

    def test_cloud_partial_success_merges_source_and_retains_unavailable_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            public, work = self.setup_dirs(folder)
            row = collect.make_item(SOURCES[1], '12345678901',
                                   {'title': 'A2O MAY New MV', 'publishedAt': NOW.isoformat()}, NOW)
            def results(source, previous, now, getter):
                self.assertEqual(previous[0]['id'], 'youtube-WoeDaIg7Xf4')
                if source['id'] != SOURCES[1]['id']:
                    raise collect.SourceError('upstream unavailable')
                return [row], {'id': source['id'], 'status': 'ok', 'checkedAt': now.isoformat(), 'count': 1}
            with patch.object(collect, 'collect_source', side_effect=results), contextlib.redirect_stdout(io.StringIO()):
                health, code = cloud_refresh.refresh(public, work, SOURCES, NOW)
            feed = json.loads((public/'personal-feed.json').read_text())
            self.assertEqual(code, 2)
            self.assertEqual(feed['status'], 'partial')
            self.assertEqual([x['id'] for x in feed['items']], [row['id'], 'youtube-WoeDaIg7Xf4'])
            self.assertEqual(health['addedCount'], 1)

    def test_no_new_upload_keeps_publication_time_on_a_fresh_runner(self):
        with tempfile.TemporaryDirectory() as folder:
            public, work = self.setup_dirs(folder)
            old = self.snapshot()['items'][0]
            def success(source, previous, now, getter):
                return [old], {'id': source['id'], 'status': 'ok', 'checkedAt': now.isoformat(), 'count': 1}
            with patch.object(collect, 'collect_source', side_effect=success), contextlib.redirect_stdout(io.StringIO()):
                health, code = cloud_refresh.refresh(public, work, SOURCES[:1], NOW)
            feed = json.loads((public/'personal-feed.json').read_text())
            self.assertEqual(code, 0)
            self.assertEqual(feed['collectedAt'], NOW.isoformat())
            self.assertEqual(feed['items'][0]['publishedAt'], old['publishedAt'])
            self.assertEqual(health['addedCount'], 0)


if __name__ == '__main__':
    unittest.main()
