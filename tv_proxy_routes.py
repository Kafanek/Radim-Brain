# ============================================
# 📺 TV STREAM PROXY + YOUTUBE SEARCH
# ============================================
# 1. HLS proxy: bypass CORS for Czech TV streams
# 2. YouTube search: scrape youtube.com/results (no API key needed)
# and re-serves them to the frontend.
# ============================================

import logging
import re
from urllib.parse import urljoin, quote
from flask import Blueprint, request, Response

logger = logging.getLogger(__name__)

tv_proxy_bp = Blueprint('tv_proxy', __name__, url_prefix='/api/tv')

# Allowed stream domains (whitelist — prevent open proxy abuse)
ALLOWED_DOMAINS = [
    'prima-ott-live.ssl.cdn.cra.cz',
    'ceskatelevize.cz',
    'www.ceskatelevize.cz',
    'ct24.ceskatelevize.cz',
    'cdn.ceskatelevize.cz',
]


def _is_allowed(url):
    """Check if URL domain is in whitelist."""
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ''
        return any(host == d or host.endswith('.' + d) for d in ALLOWED_DOMAINS)
    except Exception:
        return False


@tv_proxy_bp.route('/proxy', methods=['GET'])
def proxy_stream():
    """Proxy HLS manifest or segment.

    Usage:
        GET /api/tv/proxy?url=https://prima-ott-live.ssl.cdn.cra.cz/.../live_hd.m3u8

    For .m3u8 manifests: rewrites segment URLs to also go through proxy.
    For .ts segments: passes through raw binary.
    """
    url = request.args.get('url', '')
    if not url:
        return Response('Missing url parameter', status=400)

    if not _is_allowed(url):
        return Response('Domain not allowed', status=403)

    try:
        import requests as req_lib
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Referer': 'https://www.ceskatelevize.cz/',
        }
        resp = req_lib.get(url, headers=headers, timeout=10, stream=True)

        if resp.status_code != 200:
            return Response(f'Upstream error: {resp.status_code}', status=502)

        content_type = resp.headers.get('Content-Type', 'application/octet-stream')

        # If m3u8 manifest — rewrite segment URLs to go through proxy
        if url.endswith('.m3u8') or 'mpegurl' in content_type.lower():
            body = resp.text
            rewritten = _rewrite_manifest(body, url)
            return Response(rewritten, content_type='application/vnd.apple.mpegurl',
                            headers={'Access-Control-Allow-Origin': '*',
                                     'Cache-Control': 'no-cache'})

        # Binary segment (.ts, .aac, etc.) — stream through
        return Response(
            resp.iter_content(chunk_size=65536),
            content_type=content_type,
            headers={
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=5',
            }
        )

    except Exception as e:
        logger.warning(f'📺 TV proxy error: {e}')
        return Response(f'Proxy error: {str(e)}', status=502)


def _rewrite_manifest(body, manifest_url):
    """Rewrite relative URLs in HLS manifest to go through our proxy."""
    lines = body.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            # This is a URL (segment or sub-manifest)
            if stripped.startswith('http'):
                abs_url = stripped
            else:
                abs_url = urljoin(manifest_url, stripped)
            proxy_url = f'/api/tv/proxy?url={quote(abs_url, safe="")}'
            result.append(proxy_url)
        else:
            result.append(line)
    return '\n'.join(result)


# ============================================
# 🔍 YOUTUBE SEARCH — no API key needed
# ============================================

@tv_proxy_bp.route('/youtube/search', methods=['GET'])
def youtube_search():
    """Search YouTube videos by scraping youtube.com/results.

    Usage:
        GET /api/tv/youtube/search?q=czech+news&limit=6

    Returns JSON array of video results with videoId, title, author, thumbnail, duration.
    """
    query = request.args.get('q', '')
    limit = min(int(request.args.get('limit', '6')), 12)

    if not query:
        return jsonify({'results': [], 'error': 'Missing q parameter'}), 400

    try:
        import requests as req_lib
        import json as json_lib

        resp = req_lib.get(
            f'https://www.youtube.com/results',
            params={'search_query': query, 'sp': 'EgIQAQ=='},  # sp = Videos filter
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'cs,en;q=0.9',
            },
            timeout=10,
        )

        if resp.status_code != 200:
            return jsonify({'results': [], 'error': f'YouTube returned {resp.status_code}'}), 502

        # Extract ytInitialData JSON from HTML
        match = re.search(r'var ytInitialData = ({.*?});', resp.text)
        if not match:
            return jsonify({'results': [], 'error': 'Could not parse YouTube response'}), 502

        data = json_lib.loads(match.group(1))

        # Navigate to video results
        contents = (data.get('contents', {})
                    .get('twoColumnSearchResultsRenderer', {})
                    .get('primaryContents', {})
                    .get('sectionListRenderer', {})
                    .get('contents', []))

        results = []
        for section in contents:
            items = section.get('itemSectionRenderer', {}).get('contents', [])
            for item in items:
                vid = item.get('videoRenderer', {})
                video_id = vid.get('videoId')
                if not video_id:
                    continue

                title_runs = vid.get('title', {}).get('runs', [])
                title = title_runs[0].get('text', '') if title_runs else ''

                author_runs = vid.get('ownerText', {}).get('runs', [])
                author = author_runs[0].get('text', '') if author_runs else ''

                length_text = vid.get('lengthText', {}).get('simpleText', 'LIVE')

                thumbnail = f'https://i.ytimg.com/vi/{video_id}/mqdefault.jpg'

                results.append({
                    'videoId': video_id,
                    'title': title,
                    'author': author,
                    'duration': length_text,
                    'thumbnail': thumbnail,
                })

                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

        return jsonify({
            'results': results,
            'query': query,
        }), 200, {'Access-Control-Allow-Origin': '*'}

    except Exception as e:
        logger.warning(f'📺 YouTube search error: {e}')
        return jsonify({'results': [], 'error': str(e)}), 502
