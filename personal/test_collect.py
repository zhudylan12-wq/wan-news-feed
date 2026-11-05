import contextlib
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import collect

NOW = datetime(2026, 11, 5, 12, tzinfo=collect.TZ)
SOURCES = json.loads((Path(__file__).parent / 'sources.json').read_text())


class CollectorTests(unittest.TestCase):
    def test_youtube_fixed_identity_and_v2_layout(self):
        source = SOURCES[0]
        data = {'metadata': {'channelMetadataRenderer': {'externalId': source['channelId']}}, 'contents': {'twoColumnBrowseResultsRenderer': {'tabs': [{'tabRenderer': {'selected': True, 'content': {'richGridRenderer': {'contents': [{'richItemRenderer': {'content': {'lockupViewModel': {'contentId': 'WoeDaIg7Xf4', 'contentType': 'LOCKUP_CONTENT_TYPE_VIDEO', 'metadata': {'lockupMetadataViewModel': {'title': {'content': 'Concert Behind'}}}}}}}]}}}}]}}}
        page = '<script>var ytInitialData = ' + json.dumps(data) + ';</script>'
        self.assertEqual(collect.youtube_index(page, source)[0]['remoteId'], 'WoeDaIg7Xf4')
        with self.assertRaises(collect.SourceError):
            collect.youtube_index(page.replace(source['channelId'], 'wrong-channel'), source)

    def test_collaboration_requires_explicit_verified_staff_identity(self):
        source = SOURCES[2]
        data = {'videoData': {'owner': {'mid': 670061998, 'name': 'A2O_WORLD'}, 'bvid': 'BV19jnG6kEWV', 'pubdate': NOW.timestamp(), 'title': 'A2O MAY MV'}, 'staffData': [{'mid': source['mid'], 'name': source['account']}]}
        page = lambda: '<script>window.__INITIAL_STATE__=' + json.dumps(data) + ';</script>'
        self.assertTrue(collect.bilibili_detail(page(), source, 'BV19jnG6kEWV')['collaboration'])
        data['staffData'] = []
        with self.assertRaises(collect.SourceError):
            collect.bilibili_detail(page(), source, 'BV19jnG6kEWV')

    def test_filter_girls_and_travel_not_everything_by_creator(self):
        self.assertTrue(collect.relevant('A2O LITE NEON', SOURCES[1]))
        self.assertFalse(collect.relevant('A2O SOUL SUPERSTAR', SOURCES[1]))
        self.assertFalse(collect.relevant('A2O SOUL and A2O LITE', SOURCES[1]))
        self.assertFalse(collect.relevant('旅行博主的人生巅峰在NBA球场', SOURCES[5]))
        self.assertFalse(collect.relevant('带着相机评测去法国旅行', SOURCES[3]))
        self.assertTrue(collect.relevant('探秘法国南部小岛', SOURCES[4]))

    def test_exact_dates_future_rejection_dedup_and_failed_source_retention(self):
        detail = {'title': 'aespa Concert Behind', 'publishedAt': (NOW-timedelta(days=1)).isoformat()}
        row = collect.make_item(SOURCES[0], 'WoeDaIg7Xf4', detail, NOW)
        self.assertIsNone(collect.make_item(SOURCES[0], 'WoeDaIg7Xf4', {**detail, 'publishedAt': (NOW+timedelta(days=1)).isoformat()}, NOW))
        self.assertEqual(len(collect.merge([row], [dict(row, title='Corrected title')], NOW)), 1)
        self.assertEqual(collect.merge([row], [], NOW)[0]['id'], row['id'])
        with self.assertRaises(ValueError):
            collect.stamp('2026-11-04')

    def test_all_failed_never_replaces_last_successful_feed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            existing = {'items': [{'id': 'keep'}], 'sources': []}
            collect.atomic_json(root/'feed.json', existing)
            before = (root/'feed.json').read_bytes()
            def fail(_):
                raise collect.SourceError('Source unavailable')
            with contextlib.redirect_stdout(io.StringIO()):
                health, code = collect.run(root, SOURCES, NOW, getter=fail)
            self.assertEqual(code, 2)
            self.assertEqual(health['status'], 'error')
            self.assertEqual((root/'feed.json').read_bytes(), before)
            self.assertTrue(health['retainedPrevious'])

    def test_same_day_run_is_idempotent_next_day_checks_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            collect.atomic_json(root/'health.json', {'checkedAt': NOW.isoformat(), 'status': 'ok'})
            with patch.object(collect, 'collect_source', side_effect=collect.SourceError('offline')) as fn, contextlib.redirect_stdout(io.StringIO()):
                result, code = collect.run(root, SOURCES, NOW, if_due=True)
                self.assertEqual(result['status'], 'already-updated-today')
                self.assertEqual(code, 0)
                fn.assert_not_called()
                result, code = collect.run(root, SOURCES, NOW+timedelta(days=1), if_due=True)
                self.assertEqual(fn.call_count, len(SOURCES))
                self.assertEqual(code, 2)


if __name__ == '__main__':
    unittest.main()
