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

## Girl groups and travel creators

`personal/` collects public video-upload metadata from the fixed aespa, A2O WORLD / A2O MAY, Linksphotograph, 杰克小兔 and 小鹿Lawrence accounts. A2O MAY/LITE only; A2O SOUL and non-travel creator uploads are excluded. No Shorts, text/image posts, video downloads, cookies, account logins, API keys or personal records are used.

`Refresh Wan personal news` runs on GitHub-hosted Ubuntu daily at **08:30 UTC+8**. It restores the latest committed `public/personal-feed.json`, verifies original publication times and identities, merges and deduplicates, retains up to 180 days / 200 items, then commits public metadata and deploys Pages. Both workflows share the existing publishing concurrency lock and check out the latest main branch.

A failed source retains its last verified items; total failure never replaces the published content. `public/personal-feed-health.json`, the workflow summary and seven-day diagnostics expose failures. A partial failure publishes successful sources but marks the run failed. Scheduled starts can be delayed by GitHub.

App endpoints remain `https://zhudylan12-wq.github.io/wan-news-feed/personal-feed.json` and `https://raw.githubusercontent.com/zhudylan12-wq/wan-news-feed/main/public/personal-feed.json`. No Mac, Codex session or App rebuild is needed for daily refreshes. Run tests with `python3 -m unittest discover -s personal -p "test_*.py" -v`, then `python3 personal/cloud_refresh.py`.
