#!/usr/bin/env python3
"""Check content parity, portable local URLs and publishable file sizes."""
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
DATA = json.loads((ROOT / 'data/content.json').read_text())
ERRORS = []


class Page(HTMLParser):
    def __init__(self, path=None):
        super().__init__(convert_charrefs=True)
        self.path = path
        self.text = []
        self.images = []
        self.embeds = []
        self.featured = []

    def handle_data(self, value): self.text.append(value)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'figure' and attrs.get('data-featured-id'): self.featured.append(attrs['data-featured-id'])
        if tag == 'img' and attrs.get('src') and 'data-decorative' not in attrs: self.images.append(attrs['src'])
        if tag == 'iframe': self.embeds.append(attrs.get('src'))
        if not self.path: return
        for key in ('href', 'src', 'data-full-url', 'data-download-url'):
            value = attrs.get(key)
            if not value: continue
            parts = urlsplit(value)
            if parts.scheme or parts.netloc or value.startswith('#'): continue
            target = (self.path.parent / unquote(parts.path)).resolve()
            if not target.is_relative_to(DIST.resolve()): ERRORS.append(f'URL leaves site: {self.path}: {value}')
            elif not target.exists(): ERRORS.append(f'Missing target: {self.path}: {value}')
        if tag == 'audio' and 'autoplay' in attrs: ERRORS.append('Audio must not autoplay')


def text(content):
    content = re.sub(r'<span\b[^>]*aria-hidden="true"[^>]*>.*?</span>', '', content, flags=re.S)
    parser = Page(); parser.feed(content)
    return re.sub(r'\s+', '', html.unescape(''.join(parser.text)))


pages = list(DIST.rglob('*.html'))
for path in pages:
    data = path.read_text()
    parser = Page(path); parser.feed(data)
    if 'https://6c2021msc.ddns.net' in data or 'http://localhost:8086' in data:
        ERRORS.append(f'Production WordPress dependency in {path}')
    for secret in ('DB_PASSWORD', 'MYSQL_ROOT_PASSWORD', 'comment_author_email', 'user_pass', 'SUPABASE_SERVICE_ROLE_KEY'):
        if secret in data: ERRORS.append(f'Private field in {path}: {secret}')
for post in DATA['posts']:
    kind = post['post_type']
    if kind not in ('page', 'post'): continue
    route = ('posts/' if kind == 'post' else '') + post['post_name'] + '/index.html'
    generated = (DIST / route).read_text()
    before = Page(); before.feed(post['post_content'])
    after = Page(); after.feed(generated)
    featured=(post.get('meta') or {}).get('_thumbnail_id') if kind=='post' else None
    expected_images=len(before.images)+(1 if featured else 0)
    if len(after.images) != expected_images: ERRORS.append(f'Image count changed in {route}: expected {expected_images}, got {len(after.images)}')
    if after.featured != ([str(featured)] if featured else []): ERRORS.append(f'WordPress featured image missing in {route}')
    if post['post_name'] == 'say-something': continue
    if post['post_name'] == 'video-gallery':
        expected = re.findall(r'watch\?v=([A-Za-z0-9_-]{11})', post['post_content'])
        actual = re.findall(r'data-video-id="([A-Za-z0-9_-]{11})"', generated)
        if actual != list(dict.fromkeys(expected)): ERRORS.append('YouTube IDs or order changed')
        continue
    # Rewrite links before comparing visible words; URLs are not prose.
    raw = re.sub(r'<!--.*?-->', '', post['post_content'], flags=re.S)
    if text(raw) not in text(generated): ERRORS.append(f'Visible content changed in {route}')
homepage = Page(); homepage.feed((DIST / 'index.html').read_text())
articles = sorted([p for p in DATA['posts'] if p['post_type']=='post'], key=lambda p:p['post_date'], reverse=True)
expected_home_features = [str(p['meta']['_thumbnail_id']) for p in articles if (p.get('meta') or {}).get('_thumbnail_id')]
if homepage.featured != expected_home_features: ERRORS.append('Homepage featured images do not match the WordPress metadata')
files = [p for p in DIST.rglob('*') if p.is_file()]
for path in files:
    if path.stat().st_size >= 100 * 1024 * 1024: ERRORS.append(f'File exceeds GitHub limit: {path}')
    if path.suffix.lower() in ('.php', '.sql', '.gz', '.env', '.sqlite', '.wpress'): ERRORS.append(f'Private or executable asset published: {path}')
total = sum(p.stat().st_size for p in files)
if total >= 1024**3: ERRORS.append('Site exceeds GitHub Pages 1 GiB limit')
if ERRORS:
    print('\n'.join(ERRORS)); raise SystemExit(1)
print(json.dumps({'validated_html_pages':len(pages),'files':len(files),'bytes':total,'content_parity':True,'local_links_valid':True,'largest_file_bytes':max(p.stat().st_size for p in files)}))
