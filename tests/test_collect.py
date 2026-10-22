import sys
from pathlib import Path
import unittest
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect import categories, item, merge, parse_cips, parse_rss, SOURCES

NOW = datetime.fromisoformat('2026-10-22T22:00:00+08:00')

class CollectorTests(unittest.TestCase):
    def row(self, **kwargs):
        args = dict(title='宠物洗护行业新进展', url='https://www.chongwu365.com/news/1.html', date='2026-10-22T10:00:00+08:00', source='宠物365', source_id='365-wash', default='宠物洗美', now=NOW)
        args.update(kwargs)
        return item(**args)

    def test_relevance(self):
        self.assertEqual(categories('宠物鲜食营养标准'), ['营养鲜食'])
        self.assertEqual(categories('人类美容护肤趋势'), [])
        self.assertEqual(categories('2026龙鱼锦标赛', '行业动态'), [])

    def test_invalid_and_future_metadata_is_not_published(self):
        for change in [dict(date='2026-10-24T10:00:00+08:00'), dict(date='2020-01-01T00:00:00+08:00'), dict(url='javascript:alert(1)'), dict(url='https://evil.example/a'), dict(date='bad')]:
            self.assertIsNone(self.row(**change))

    def test_merge_retains_previous_when_source_has_no_new_items(self):
        row = self.row()
        self.assertEqual(merge([row], [], NOW), [row])
        duplicate = self.row(url='https://www.chongwu365.com/news/2.html')
        self.assertEqual(len(merge([row], [row, duplicate], NOW)), 1)

    def test_cips_uses_publication_date_not_future_event_date(self):
        html='<li><h3>10.19<span>2026</span></h3><a href="https://www.cipscom.com/ShowNews/1.htm">11月宠物美容大会</a></li>'
        rows=parse_cips(html, SOURCES[3], NOW)
        self.assertEqual(rows[0]['publishedAt'], '2026-10-19T00:00:00+08:00')
        self.assertIn('宠物洗美', rows[0]['categories'])

    def test_rss_filters_unrelated_news_and_ignores_description_html(self):
        xml='<rss><channel><item><title>宠物食品行业</title><link>https://www.chinanews.com.cn/cj/1.shtml</link><pubDate>Thu, 22 Oct 2026 10:00:00 +0800</pubDate><description>&lt;script&gt;bad&lt;/script&gt;</description></item><item><title>海洋经济大会</title><link>https://www.chinanews.com.cn/cj/2.shtml</link><pubDate>Thu, 22 Oct 2026 10:00:00 +0800</pubDate></item></channel></rss>'
        rows=parse_rss(xml,SOURCES[4],NOW)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['summary'],'')

if __name__ == '__main__':
    unittest.main()
