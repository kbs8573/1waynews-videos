"""
Fetches 1waynews YouTube channel videos + shorts and saves to data.json.
Uses only Python stdlib — no pip install needed.
"""
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import Request, urlopen

CHANNEL_HANDLE = '@1waynews-jhg'
BASE_URL = f'https://www.youtube.com/{CHANNEL_HANDLE}'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


def fetch(url, timeout=15):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


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


def get_short_ids(html):
    """Extract video IDs from the /shorts page."""
    ids = set()
    for pat in [
        r'"reelItemRenderer".*?"videoId"\s*:\s*"([^"]+)"',
        r'"videoId"\s*:\s*"([^"]+)".*?"reelItemRenderer"',
    ]:
        for m in re.finditer(r'"videoId"\s*:\s*"([^"]{5,})"', html):
            ids.add(m.group(1))
    # Also search ytInitialData for reelItemRenderer
    reel_pattern = re.compile(r'"reelItemRenderer"\s*:\s*\{[^}]*?"videoId"\s*:\s*"([^"]+)"')
    for m in reel_pattern.finditer(html):
        ids.add(m.group(1))
    return ids


def fetch_rss(channel_id):
    rss_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    xml_text = fetch(rss_url)

    NS = {
        'atom':  'http://www.w3.org/2005/Atom',
        'yt':    'http://www.youtube.com/xml/schemas/2015',
        'media': 'http://search.yahoo.com/mrss/',
    }

    root = ET.fromstring(xml_text)
    videos = []

    for entry in root.findall('atom:entry', NS):
        vid_id = entry.findtext('yt:videoId', namespaces=NS)
        title  = entry.findtext('atom:title', namespaces=NS)
        pub    = entry.findtext('atom:published', namespaces=NS)

        views = None
        stats = entry.find('media:group/media:community/media:statistics', NS)
        if stats is not None:
            try:
                views = int(stats.get('views', 0))
            except ValueError:
                pass

        if vid_id:
            videos.append({
                'id':          vid_id,
                'title':       title or '',
                'publishedAt': pub or '',
                'views':       views,
                'thumb':       f'https://i.ytimg.com/vi/{vid_id}/mqdefault.jpg',
                'url':         f'https://www.youtube.com/watch?v={vid_id}',
                'type':        'video',  # will be updated below
            })

    return videos


def main():
    print('📡 Fetching channel page…')
    channel_html = fetch(BASE_URL + '/videos')
    channel_id = get_channel_id(channel_html)
    if not channel_id:
        raise RuntimeError('Could not find channel ID')
    print(f'✅ Channel ID: {channel_id}')

    print('📋 Fetching RSS feed…')
    videos = fetch_rss(channel_id)
    print(f'✅ Found {len(videos)} items in RSS')

    print('🩳 Fetching Shorts page…')
    try:
        shorts_html = fetch(BASE_URL + '/shorts')
        # Extract all videoIds from the shorts page
        short_ids = set(re.findall(
            r'"videoId"\s*:\s*"([A-Za-z0-9_-]{10,12})"', shorts_html
        ))
        # Cross-reference: mark videos that appear on /shorts page
        marked = 0
        for v in videos:
            if v['id'] in short_ids:
                v['type'] = 'short'
                v['url']  = f'https://www.youtube.com/shorts/{v["id"]}'
                marked += 1
        print(f'✅ Marked {marked} shorts (out of {len(short_ids)} IDs found)')
    except Exception as e:
        print(f'⚠️  Shorts page fetch failed: {e}')

    data = {
        'updated':   datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'channelId': channel_id,
        'videos':    videos,
    }

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    video_cnt = sum(1 for v in videos if v['type'] == 'video')
    short_cnt = sum(1 for v in videos if v['type'] == 'short')
    print(f'💾 Saved data.json — 동영상 {video_cnt}개, Shorts {short_cnt}개')


if __name__ == '__main__':
    main()
