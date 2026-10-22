# Wan public news feed

An isolated, public metadata service for Wan. Contains no app source, account credentials, tester details, personal notes, fitness records, or learning progress.

- Collects article titles, publication dates, publisher names and direct original links from public pages at **宠物365**, **CIPS**, and official **中国新闻网 RSS**.
- No article bodies or images are republished. News is not professional medical/nutritional guidance; publisher statements are not independently verified.
- Categories: 宠物洗美 / 营养鲜食 / 行业动态. Filters unrelated aquarium news, future timestamps and items older than 180 days. Retains at most 180 items, newest first, with URL/title deduplication.
- GitHub Actions schedules: **08:17 and 20:17 UTC+8 daily**, with manual dispatch. Scheduling can be delayed by GitHub; this is a daily collector, not a real-time breaking news service.
- Updates `checkedAt` only after a successful collection, separately from each article's `publishedAt`. A partial failure is visible in feed status. Total failure keeps the last successful feed and fails the workflow. Successful data snapshots are committed as the service's data history.
- Index formats can change. Check workflow logs and `sources` in the JSON if a publisher fails. Never turn an HTTP failure into a claim of no new articles.
- Pages endpoint: `https://zhudylan12-wq.github.io/wan-news-feed/feed.json`
- Independent host mirror: `https://raw.githubusercontent.com/zhudylan12-wq/wan-news-feed/main/public/feed.json`

Run `python3 -m unittest discover -s tests -v`, then `python3 collect.py`. Python standard library only, no paid API or secrets required.

Robots directives checked on 2026-10-22: 宠物365 allows the selected query-free public news paths; 中国新闻网 allows the selected RSS paths; CIPS robots.txt returned 404. No account/cookie, access-control bypass or anti-bot circumvention is used.

[GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) · [中国新闻网 RSS](https://www.chinanews.com.cn/rss/) · [CIPS news](https://www.cipscom.com/ShowNews/index.htm)
