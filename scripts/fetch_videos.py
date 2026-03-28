"""
Fetches 1waynews YouTube channel videos + shorts and saves to data.json.
- RSS  : 최근 15개 (정확한 날짜)
- ytInitialData : 최근 30개 이상 (상대 날짜 파싱)
→ 두 소스를 병합해 더 넓은 기간의 영상을 커버합니다.
"""
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen

CHANNEL_HANDLE = '@1waynews-jhg'
BASE_URL = f'https://www.youtube.com/{CHANNEL_HANDLE}'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}
NOW = datetime.now(timezone.utc)


def fetch(url, timeout=15):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


# ── Channel ID ───────────────────────────────────────────
def get_channel_id(html):
    for pat in [
        r'"channelId"\s*:\s*"(UC[^"]{20,})"',
        r'"externalChannelId"\s*:\s*"(UC[^"]{20,})"',
        r'channel/(UC[A-Za-z0-9_-]{22})',
    ]:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


# ── RSS (정확한 날짜, 최근 15개) ─────────────────────────
def fetch_rss(channel_id):
    xml_text = fetch(f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}')
    NS = {
        'atom':  'http://www.w3.org/2005/Atom',
        'yt':    'http://www.youtube.com/xml/schemas/2015',
        'media': 'http://search.yahoo.com/mrss/',
    }
    root = ET.fromstring(xml_text)
    videos = {}
    for entry in root.findall('atom:entry', NS):
        vid = entry.findtext('yt:videoId', namespaces=NS)
        if not vid:
            continue
        views = None
        stats = entry.find('media:group/media:community/media:statistics', NS)
        if stats is not None:
            try:
                views = int(stats.get('views', 0))
            except ValueError:
                pass
        pub_str = entry.findtext('atom:published', namespaces=NS) or ''
        upd_str = entry.findtext('atom:updated',   namespaces=NS) or ''
        try:
            pub_dt = datetime.fromisoformat(pub_str.replace('Z', '+00:00'))
        except Exception:
            pub_dt = NOW
        title_rss = entry.findtext('atom:title', namespaces=NS) or ''
        is_live_rss = bool(re.search(r'\[?LIVE\]?|라이브', title_rss, re.IGNORECASE))
        # For live videos use updated (stream-end time) when it's more recent than published
        if is_live_rss and upd_str:
            try:
                upd_dt = datetime.fromisoformat(upd_str.replace('Z', '+00:00'))
                if upd_dt > pub_dt:
                    pub_dt = upd_dt
            except Exception:
                pass
        videos[vid] = {
            'id':          vid,
            'title':       title_rss,
            'publishedAt': pub_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'views':       views,
            'thumb':       f'https://i.ytimg.com/vi/{vid}/mqdefault.jpg',
            'url':         f'https://www.youtube.com/watch?v={vid}',
            'type':        'live' if is_live_rss else 'video',
        }
    return videos


# ── ytInitialData (상대 날짜, 30개+) ─────────────────────
def parse_relative_time(text):
    """'3 days ago', '2주 전', '1 month ago', '어제', 'yesterday' → datetime"""
    if not text:
        return NOW - timedelta(days=30)
    t = text.lower().strip()
    if t.startswith('오늘') or t.startswith('today'):
        return NOW - timedelta(hours=12)
    if t.startswith('어제') or t.startswith('yesterday'):
        return NOW - timedelta(days=1)
    m = re.search(r'(\d+)', t)
    n = int(m.group(1)) if m else 1
    if   re.search(r'second|초',  t): return NOW - timedelta(seconds=n)
    elif re.search(r'minute|분',  t): return NOW - timedelta(minutes=n)
    elif re.search(r'hour|시간',  t): return NOW - timedelta(hours=n)
    elif re.search(r'day|일',     t): return NOW - timedelta(days=n)
    elif re.search(r'week|주',    t): return NOW - timedelta(weeks=n)
    elif re.search(r'month|개월', t): return NOW - timedelta(days=n * 30)
    elif re.search(r'year|년',    t): return NOW - timedelta(days=n * 365)
    return NOW - timedelta(days=30)


def extract_yt_initial_data(html):
    """ytInitialData JSON 추출"""
    idx = html.find('var ytInitialData = ')
    if idx == -1:
        return None
    start = html.index('{', idx)
    depth, i = 0, start
    for i in range(start, min(start + 3_000_000, len(html))):
        if html[i] == '{':
            depth += 1
        elif html[i] == '}':
            depth -= 1
            if depth == 0:
                break
    try:
        return json.loads(html[start:i + 1])
    except Exception:
        return None


def parse_video_items(data):
    """ytInitialData에서 videoRenderer 목록 추출"""
    tabs = (data or {}).get('contents', {}).get('twoColumnBrowseResultsRenderer', {}).get('tabs', [])
    for tab in tabs:
        content = tab.get('tabRenderer', {}).get('content', {})
        grid = (
            content.get('richGridRenderer', {}).get('contents')
            or content.get('sectionListRenderer', {}).get('contents', [{}])[0]
                       .get('itemSectionRenderer', {}).get('contents', [{}])[0]
                       .get('gridRenderer', {}).get('items')
        )
        if grid:
            return grid
    return []


def scrape_videos_page(url):
    html = fetch(url)
    data = extract_yt_initial_data(html)
    if not data:
        return {}

    items = parse_video_items(data)
    result = {}
    for item in items:
        vr = (
            item.get('richItemRenderer', {}).get('content', {}).get('videoRenderer')
            or item.get('gridVideoRenderer')
            or item.get('reelItemRenderer')
            or item.get('videoRenderer')
        )
        if not vr:
            continue
        vid = vr.get('videoId')
        if not vid:
            continue
        time_text = (vr.get('publishedTimeText') or {}).get('simpleText', '')
        pub_dt = parse_relative_time(time_text)
        views_raw = (vr.get('viewCountText') or {}).get('simpleText', '')
        views = None
        vm = re.search(r'[\d,]+', views_raw.replace(',', ''))
        if vm:
            try:
                views = int(vm.group().replace(',', ''))
            except ValueError:
                pass
        title = ''
        t = vr.get('title', {})
        if 'runs' in t:
            title = ''.join(r.get('text', '') for r in t['runs'])
        elif 'simpleText' in t:
            title = t['simpleText']

        # Detect LIVE via thumbnailOverlays or badges
        is_live = False
        for overlay in vr.get('thumbnailOverlays', []):
            if overlay.get('thumbnailOverlayTimeStatusRenderer', {}).get('style') == 'LIVE':
                is_live = True
                break
        if not is_live:
            for badge in vr.get('badges', []):
                if badge.get('metadataBadgeRenderer', {}).get('style') == 'BADGE_STYLE_TYPE_LIVE_NOW':
                    is_live = True
                    break
        if not is_live and re.search(r'\[?LIVE\]?|라이브', title, re.IGNORECASE):
            is_live = True

        result[vid] = {
            'id':          vid,
            'title':       title,
            'publishedAt': pub_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'views':       views,
            'thumb':       f'https://i.ytimg.com/vi/{vid}/mqdefault.jpg',
            'url':         f'https://www.youtube.com/watch?v={vid}',
            'type':        'live' if is_live else 'video',
        }
    return result


# ── Shorts 감지 ──────────────────────────────────────────
def get_short_ids(html):
    return set(re.findall(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{10,12})"', html))


# ── Main ─────────────────────────────────────────────────
def main():
    print('📡 Fetching channel /videos page…')
    videos_html = fetch(BASE_URL + '/videos')
    channel_id  = get_channel_id(videos_html)
    if not channel_id:
        raise RuntimeError('Could not find channel ID')
    print(f'✅ Channel ID: {channel_id}')

    # 1. RSS (정확한 날짜)
    print('📋 Fetching RSS (accurate dates)…')
    rss_items = fetch_rss(channel_id)
    print(f'   RSS: {len(rss_items)} items')

    # 2. ytInitialData /videos (상대 날짜, 30개+)
    print('🔍 Parsing ytInitialData /videos…')
    yt_items = scrape_videos_page(BASE_URL + '/videos')
    print(f'   ytInitialData /videos: {len(yt_items)} items')

    # 3. 병합: RSS 날짜 우선, ytInitialData로 보완
    merged = {}
    for vid, v in yt_items.items():
        merged[vid] = v
    for vid, v in rss_items.items():
        # RSS has accurate date — override ytInitialData entry
        if vid in merged:
            merged[vid]['publishedAt'] = v['publishedAt']
            if v['views'] is not None:
                merged[vid]['views'] = v['views']
            # Preserve 'live' type if either source detected it
            if v['type'] == 'live':
                merged[vid]['type'] = 'live'
        else:
            merged[vid] = v

    # 3-b. 구독자 전용(멤버십) 콘텐츠 제외
    # RSS에만 있고(ytInitialData 공개 목록에 없음) views == 0 인 경우
    yt_ids = set(yt_items.keys())
    excluded = [vid for vid, v in merged.items()
                if v.get('views') == 0 and vid not in yt_ids]
    for vid in excluded:
        print(f'   ⛔ 구독자 전용 제외: {merged[vid]["title"][:40]}')
        del merged[vid]

    print(f'   Merged total: {len(merged)} unique items')

    # 4. Shorts 감지
    print('🩳 Fetching /shorts page…')
    try:
        shorts_html = fetch(BASE_URL + '/shorts')
        short_ids = get_short_ids(shorts_html)
        marked = 0
        for vid, v in merged.items():
            if vid in short_ids:
                v['type'] = 'short'
                v['url']  = f'https://www.youtube.com/shorts/{vid}'
                marked += 1
        print(f'   Marked {marked} shorts')
    except Exception as e:
        print(f'⚠️  Shorts page failed: {e}')

    # 5. 날짜순 정렬 (최신순)
    videos = sorted(merged.values(), key=lambda v: v['publishedAt'], reverse=True)

    data = {
        'updated':   NOW.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'channelId': channel_id,
        'videos':    videos,
    }

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    v_cnt = sum(1 for v in videos if v['type'] == 'video')
    s_cnt = sum(1 for v in videos if v['type'] == 'short')
    print(f'💾 Saved data.json — 동영상 {v_cnt}개, Shorts {s_cnt}개 (총 {len(videos)}개)')


if __name__ == '__main__':
    main()
