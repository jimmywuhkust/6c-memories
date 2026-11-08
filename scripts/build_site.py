#!/usr/bin/env python3
"""Build portable static HTML from the original, public WordPress content."""
import argparse
from datetime import datetime
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import posixpath
import re
import shutil
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'
DATA = json.loads((ROOT / 'data/content.json').read_text())
ASSET_VERSIONS = {name: hashlib.sha256((ROOT / 'web' / name).read_bytes()).hexdigest()[:12] for name in ('style.css','site.js')}
CONFIG_VERSION = hashlib.sha256((ROOT / 'site.config.json').read_bytes()).hexdigest()[:12]
POSTS = {int(p['ID']): p for p in DATA['posts']}
PAGES = [p for p in DATA['posts'] if p['post_type'] == 'page']
ARTICLES = sorted([p for p in DATA['posts'] if p['post_type'] == 'post'], key=lambda p: p['post_date'], reverse=True)
ATTACHMENTS = [p for p in DATA['posts'] if p['post_type'] == 'attachment']
VIDEO_DATA = json.loads((ROOT / 'data/videos.json').read_text())
MEDIA_DIMS = {}
for attachment in ATTACHMENTS:
    meta = attachment['meta'].get('_wp_attachment_metadata')
    if not isinstance(meta, dict): continue
    file = attachment['meta']['_wp_attached_file']
    MEDIA_DIMS[file] = (meta.get('width'), meta.get('height'))
    for size in meta.get('sizes', {}).values():
        MEDIA_DIMS[str(Path(file).parent / size['file'])] = (size.get('width'), size.get('height'))
ORIGIN = urlsplit(DATA['site']['home']).netloc
ROUTES = {int(p['ID']): p['post_name'] + '/' for p in PAGES}
ROUTES.update({int(p['ID']): f"posts/{p['post_name']}/" for p in ARTICLES})
MENUS = sorted([p for p in DATA['posts'] if p['post_type'] == 'nav_menu_item'], key=lambda p: int(p['menu_order']))
LEGACY = {'/': ''}
for p in PAGES:
    for prefix in ('/', '/index.php/'):
        LEGACY[prefix + p['post_name'] + '/'] = ROUTES[int(p['ID'])]
for p in ARTICLES:
    day = p['post_date'][:10].replace('-', '/')
    LEGACY[f"/index.php/{day}/{p['post_name']}/"] = ROUTES[int(p['ID'])]


def rel(route, current):
    return posixpath.relpath(route or '.', current or '.') + ('/' if route.endswith('/') or not route else '')


def media(file, current):
    return rel('media/' + unquote(file), current)


def rewrite_url(value, current):
    url = urlsplit(html.unescape(value))
    if url.netloc and url.netloc not in (ORIGIN, 'localhost:8086'):
        return value
    if '/wp-content/uploads/' in url.path:
        return media(url.path.split('/wp-content/uploads/', 1)[1], current)
    if url.netloc in (ORIGIN, 'localhost:8086') or value.startswith('/'):
        path = unquote(url.path)
        target = LEGACY.get(path)
        if target is not None:
            return rel(target, current) + (('#' + url.fragment) if url.fragment else '')
        attachment = next((p for p in ATTACHMENTS if path.rstrip('/').split('/')[-1] == unquote(p['post_name'])), None)
        if attachment:
            return media(attachment['meta']['_wp_attached_file'], current)
    return value


class Rewriter(HTMLParser):
    def __init__(self, current):
        super().__init__(convert_charrefs=False)
        self.current = current
        self.result = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img':
            attrs.update(loading='lazy', decoding='async')
            original = attrs.get('src', '').split('/wp-content/uploads/')[-1]
            dimensions = MEDIA_DIMS.get(unquote(original))
            if dimensions and all(dimensions):
                attrs['width'], attrs['height'] = map(str, dimensions)
            identifier=re.search(r'wp-image-(\d+)',attrs.get('class',''))
            if identifier and int(identifier[1]) in POSTS:
                attachment=POSTS[int(identifier[1])]
                attached=attachment['meta'].get('_wp_attached_file')
                if attached:
                    attrs.setdefault('data-full-url', '/wp-content/uploads/'+attached)
                    metadata=attachment['meta'].get('_wp_attachment_metadata')
                    original=str(Path(attached).parent/metadata['original_image']) if isinstance(metadata,dict) and metadata.get('original_image') else attached
                    attrs['data-download-url']='/wp-content/uploads/'+original
        for key in ('src', 'href', 'data-full-url', 'data-download-url', 'data-link', 'poster'):
            if attrs.get(key): attrs[key] = rewrite_url(attrs[key], self.current)
        if attrs.get('srcset'):
            attrs['srcset'] = ', '.join(rewrite_url(item.strip().split()[0], self.current) + ' ' + ' '.join(item.strip().split()[1:]) for item in attrs['srcset'].split(','))
        self.result.append('<' + tag + ''.join(' ' + k + (('="' + html.escape(v, quote=True) + '"') if v is not None else '') for k, v in attrs.items()) + '>')

    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag, attrs)
    def handle_endtag(self, tag): self.result.append(f'</{tag}>')
    def handle_data(self, value): self.result.append(value)
    def handle_entityref(self, name): self.result.append(f'&{name};')
    def handle_charref(self, name): self.result.append(f'&#{name};')
    # Gutenberg comments are editor metadata, not visible content.


def render_content(post, current):
    value = post['post_content'].strip()
    def embed(match):
        video = re.search(r'(?:watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})', match.group())
        if not video: return match.group()
        vid = video.group(1)
        return f'<figure class="video"><iframe loading="lazy" src="https://www.youtube-nocookie.com/embed/{vid}" title="YouTube video" allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe><a class="video-link" href="https://www.youtube.com/watch?v={vid}" target="_blank" rel="noopener">YouTube ↗</a></figure>'
    value = re.sub(r'<figure\b[^>]*class="[^"]*wp-block-embed[^"]*"[^>]*>.*?</figure>', embed, value, flags=re.S)
    if not value.startswith('<'):
        value = ''.join('<p>' + part.replace('\n', '<br>') + '</p>' for part in re.split(r'\n\s*\n', value))
    parser = Rewriter(current)
    parser.feed(value)
    return ''.join(parser.result)


def collect_media():
    destination = ROOT / 'assets/media'
    source = ROOT / 'local-wordpress/html/wp-content/uploads'
    destination.mkdir(parents=True, exist_ok=True)
    wanted = set()
    for p in ATTACHMENTS:
        file = p['meta']['_wp_attached_file']
        wanted.add(file)
        meta = p['meta'].get('_wp_attachment_metadata')
        if isinstance(meta, dict):
            parent = str(Path(file).parent)
            for size in meta.get('sizes', {}).values():
                wanted.add(parent + '/' + size['file'])
            if meta.get('original_image'): wanted.add(parent + '/' + meta['original_image'])
    for p in PAGES + ARTICLES:
        for match in re.findall(r'(?:https?://[^/]+)?/wp-content/uploads/([^"\s<>]+)', p['post_content']):
            wanted.add(unquote(html.unescape(match)))
    for file in sorted(wanted):
        target = destination / file
        if target.exists(): continue
        original = source / file
        if not original.is_file(): raise FileNotFoundError(f'Original media missing: {file}')
        if not original.resolve().is_relative_to(source.resolve()): raise ValueError('Invalid media path')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
    return len(wanted)


def nav(current, active):
    links = []
    for item in MENUS:
        if item['meta']['_menu_item_type'] == 'custom':
            label, route = item['post_title'], ''
        else:
            target = POSTS[int(item['meta']['_menu_item_object_id'])]
            label, route = item['post_title'] or target['post_title'], ROUTES[int(target['ID'])]
        links.append(f'<a href="{rel(route, current)}"' + (' aria-current="page"' if route == active else '') + f'>{html.escape(label)}</a>')
    return ''.join(links)


def form(thread, guestbook=False):
    title = '<label>A title you like~<input name="title" maxlength="160" required></label>' if guestbook else ''
    return f'''<section class="comments" data-thread="{thread}">
<h2>{'Say something' if guestbook else '發佈留言'}</h2>
<div class="guest-entries" aria-live="polite"></div>
<form class="guest-form">
{title}
<label>Anything to say to the class?<textarea name="message" rows="6" maxlength="12000" required></textarea></label>
<div class="form-bottom"><label>Photo to share? (Optional)<input type="file" name="photo" accept="image/jpeg,image/png,image/webp"></label>
<label>Your name? (Optional)<input name="name" maxlength="80" autocomplete="nickname"></label></div>
<label class="honeypot" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label>
<button class="submit" type="submit">Post! <span aria-hidden="true">↗</span></button>
<p class="form-status" role="status"></p>
</form></section>'''


def gallery(post, current):
    body = render_content(post, current)
    pattern = re.compile(r'<figure\b[^>]*class="[^"]*wp-block-pullquote[^"]*"[^>]*>.*?</figure>', re.S)
    quotes = list(pattern.finditer(body))
    sections, tabs, pool = [], [], []
    class Photos(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.photos=[]; self.paragraph=None; self.event=''; self.caption=''
        def handle_starttag(self, tag, attrs):
            if tag=='p': self.paragraph=[]
            if tag=='img':
                self.photos.append((dict(attrs),self.event,self.caption))
                self.caption=''
        def handle_data(self, value):
            if self.paragraph is not None: self.paragraph.append(value)
        def handle_endtag(self, tag):
            if tag=='p' and self.paragraph is not None:
                value=''.join(self.paragraph).strip(); self.paragraph=None
                if value: self.event=value; self.caption=value
    for index, quote in enumerate(quotes):
        heading = re.search(r'<p>(.*?)</p>', quote.group(), re.S).group(1)
        period = re.search(r'<cite>(.*?)</cite>', quote.group(), re.S).group(1)
        number = re.sub(r'\D', '', heading)
        section = 'form-' + number
        end = quotes[index+1].start() if index+1 < len(quotes) else len(body)
        collector=Photos(); collector.feed(body[quote.end():end])
        tiles=[]
        for attrs,event,caption in collector.photos:
            attrs['data-event']=event or heading
            try: ratio=float(attrs['width'])/float(attrs['height'])
            except (KeyError,ValueError,ZeroDivisionError): ratio=1.5
            image='<img'+''.join(' '+key+'="'+html.escape(value or '',quote=True)+'"' for key,value in attrs.items())+'>'
            label='<figcaption>'+html.escape(caption)+'</figcaption>' if caption else ''
            tiles.append(f'<figure class="photo-tile" data-aspect="{ratio:.6f}">{image}{label}</figure>')
            # Reuse the source's smaller image variants for the randomized cover.
            thumb=attrs['src']
            identifier=re.search(r'wp-image-(\d+)',attrs.get('class',''))
            if identifier and int(identifier[1]) in POSTS:
                item=POSTS[int(identifier[1])]; metadata=item['meta'].get('_wp_attachment_metadata')
                if isinstance(metadata,dict):
                    size=metadata.get('sizes',{}).get('medium_large') or metadata.get('sizes',{}).get('large')
                    if size: thumb=media(str(Path(item['meta']['_wp_attached_file']).parent/size['file']),current)
            pool.append({'src':thumb,'aspect':ratio})
        tabs.append(f'<a href="#{section}" data-album-link="{section}"><span>{heading}</span><small>{period}</small></a>')
        sections.append(f'<section class="album" id="{section}"><header class="album-heading"><h2><span class="form-word">Form</span> <span class="form-number">{number}</span></h2><p>{period}</p></header><div class="album-photos photo-grid">'+''.join(tiles)+'</div></section>')
    cover=''.join(f'<img src="{html.escape(item["src"])}" alt="" data-decorative="true" decoding="async">' for item in pool[:6])
    intro='<header class="page-heading gallery-intro"><h1 data-title="Image Gallery"><span>Image</span><em>Gallery</em></h1><div class="mosaic-cover" aria-hidden="true">'+cover+'</div></header>'
    pool_json=json.dumps(pool,ensure_ascii=False).replace('<','\\u003c')
    return intro+'<script type="application/json" id="gallery-cover-pool">'+pool_json+'</script><nav class="album-nav" aria-label="年份">'+''.join(tabs)+'</nav><div class="page-content">'+''.join(sections)+'</div>'


def videos(current):
    cards = []
    play = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M8 4.8v14.4L19 12Z" fill="currentColor"/></svg>'
    for index, video in enumerate(VIDEO_DATA, 1):
        identifier, title = video['id'], html.escape(video['title'])
        cards.append(f'''<article class="video-card">
<button class="video-poster" type="button" data-video-id="{identifier}" data-video-title="{title}" aria-label="播放影片：{title}">
<img src="{html.escape(video['thumbnail'])}" alt="" loading="{'eager' if index==1 else 'lazy'}" data-decorative="true"><span class="play-disc">{play}</span><span class="video-ordinal">0{index}</span></button>
<div class="video-caption"><h2>{title}</h2><a href="https://www.youtube.com/watch?v={identifier}" target="_blank" rel="noopener" aria-label="在 YouTube 觀看 {title}">YouTube <span aria-hidden="true">↗</span></a></div></article>''')
    return '<header class="page-heading video-heading"><h1 data-title="Video Gallery"><span>Video</span><em>Gallery</em></h1><span class="video-total" aria-hidden="true">01 — 05</span></header><div class="page-content video-grid">' + ''.join(cards) + '</div>'


def featured_image(post, current):
    identifier=(post.get('meta') or {}).get('_thumbnail_id')
    if not identifier: return ''
    attachment=POSTS[int(identifier)]
    file=attachment['meta']['_wp_attached_file']
    metadata=attachment['meta'].get('_wp_attachment_metadata')
    if isinstance(metadata,dict):
        size=metadata.get('sizes',{}).get('1536x1536') or metadata.get('sizes',{}).get('large')
        if size: file=str(Path(file).parent/size['file'])
    markup=f'<figure class="post-featured" data-featured-id="{identifier}"><img src="/wp-content/uploads/{html.escape(file)}" alt="" class="wp-image-{identifier}"></figure>'
    parser=Rewriter(current); parser.feed(markup)
    return ''.join(parser.result)


def article(post, current, detail=False):
    link = rel(ROUTES[int(post['ID'])], current)
    date = datetime.fromisoformat(post['post_date']).strftime('%d %b %Y')
    body = featured_image(post, current) + render_content(post, current)
    heading = 'h1' if detail else 'h2'
    return f'''<article class="journal-entry" id="post-{post['ID']}">
<header class="entry-heading"><time datetime="{post['post_date'][:10]}">{date}</time>
<{heading}><a href="{link}">{html.escape(post['post_title'])}</a></{heading}></header>
<div class="entry-content">{body}{form('post-' + str(post['ID'])) if detail else ''}</div></article>'''


def document(title, content, current='', home=False):
    e = html.escape
    header = next(p for p in ATTACHMENTS if int(p['ID']) == DATA['theme']['header_attachment_id'])
    photo = media(header['meta']['_wp_attached_file'], current)
    music = next(p for p in ATTACHMENTS if p['post_mime_type'] == 'audio/mpeg')
    song = media(music['meta']['_wp_attached_file'], current)
    masthead = f'''<header class="hero"><img class="hero-image" src="{photo}" alt="" fetchpriority="high">
<div class="hero-shade"></div><div class="hero-title"><h1>{e(DATA['site']['blogname'])}</h1><p>{e(DATA['site']['blogdescription'])}</p></div>
<a class="scroll-cue" href="#content" aria-label="跳至內容">↓</a></header>''' if home else f'<header class="small-masthead"><a href="{rel("", current)}">{e(DATA["site"]["blogname"])}</a><p>{e(DATA["site"]["blogdescription"])}</p></header>'
    mobile_label = 'Main Menu' if home else title
    return f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}{' — ' + e(DATA['site']['blogname']) if title != DATA['site']['blogname'] else ''}</title>
<meta name="description" content="{e(DATA['site']['blogdescription'])}">
<link rel="icon" href="data:,"><link rel="stylesheet" href="{rel('assets/style.css', current)}?v={ASSET_VERSIONS['style.css']}">
<script src="{rel('assets/config.js', current)}?v={CONFIG_VERSION}" defer></script><script src="{rel('assets/site.js', current)}?v={ASSET_VERSIONS['site.js']}" defer></script></head>
<body class="{'home' if home else 'inner-page'}"><a class="skip-link" href="#content">跳至內容</a>
{masthead}<div class="nav-wrap"><button class="menu-toggle" type="button" aria-label="開啟選單" aria-expanded="false" aria-controls="primary-nav"><span>{e(mobile_label)}</span><i aria-hidden="true"></i></button><nav id="primary-nav" aria-label="頂部選單">{nav(current, current)}</nav>
<button class="music-toggle" type="button" aria-label="播放 {e(music['post_title'])}" aria-pressed="false" title="{e(music['post_title'])}"><span aria-hidden="true">♫</span></button><audio id="class-song" preload="none" src="{song}"></audio></div>
<main id="content">{content}</main>
<footer><a class="footer-name" href="{rel('', current)}">{e(DATA['site']['blogname'])}</a><p>{e(DATA['site']['blogdescription'])}</p><a class="back-top" href="#" aria-label="回到頂部">↑</a></footer>
<dialog id="lightbox" aria-label="照片"><a class="lightbox-download" download><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M5 17v4h14v-4"/></svg>下載原圖</a><button type="button" class="lightbox-close" aria-label="關閉">×</button><button type="button" class="lightbox-prev" aria-label="上一張">←</button><figure><img alt=""><figcaption><span class="lightbox-caption"></span><span class="lightbox-count"></span></figcaption></figure><button type="button" class="lightbox-next" aria-label="下一張">→</button></dialog>
<dialog id="video-modal" aria-label="影片"><button type="button" class="video-close" aria-label="關閉影片">×</button><div class="video-screen"></div><div class="video-modal-caption"><span></span><a target="_blank" rel="noopener">YouTube ↗</a></div></dialog>
</body></html>'''


def write(route, content):
    path = DIST / route / 'index.html'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def build(production=False):
    config = json.loads((ROOT / 'site.config.json').read_text())
    if production and config.get('commentsEnabled', True) and (not (config.get('commentsEndpoint') or '').startswith('https://') or not config.get('publishableKey')):
        raise RuntimeError('Configure the hosted anonymous guestbook in site.config.json before publishing.')
    count = collect_media()
    DIST.mkdir(exist_ok=True)
    # Keep the directory inode stable for the running Docker preview's bind mount.
    for child in DIST.iterdir():
        if child.name == 'media': continue
        if child.is_dir(): shutil.rmtree(child)
        else: child.unlink()
    def copy_media(source, target):
        if Path(target).exists():
            before, after = Path(source).stat(), Path(target).stat()
            if before.st_size == after.st_size and before.st_mtime_ns == after.st_mtime_ns: return target
        return shutil.copy2(source, target)
    shutil.copytree(ROOT / 'assets/media', DIST / 'media', dirs_exist_ok=True, copy_function=copy_media)
    for path in (DIST / 'media').rglob('*'):
        if path.is_file() and not (ROOT / 'assets/media' / path.relative_to(DIST / 'media')).exists(): path.unlink()
    (DIST / 'assets').mkdir()
    for name in ('style.css', 'site.js'):
        shutil.copyfile(ROOT / 'web' / name, DIST / 'assets' / name)
    shutil.copytree(ROOT / 'web/fonts', DIST / 'assets/fonts')
    (DIST / 'assets/config.js').write_text('window.SIXC_CONFIG=' + json.dumps(config) + ';\n')
    (DIST / '.nojekyll').touch()
    write('', document(DATA['site']['blogname'], '<section class="journal">' + ''.join(article(p, '') for p in ARTICLES) + '</section>', home=True))
    for p in PAGES:
        route = ROUTES[int(p['ID'])]
        title = p['post_title'] or 'Prologue'
        kind = 'gallery' if p['post_name'] == 'image-gallery' else ('videos' if p['post_name'] == 'video-gallery' else 'prose')
        if p['post_name'] == 'image-gallery':
            content = '<section class="page gallery">' + gallery(p,route) + '</section>'
        elif p['post_name'] == 'video-gallery':
            content = '<section class="page videos">' + videos(route) + '</section>'
        else:
            body = form('guestbook', True) if p['post_name'] == 'say-something' else render_content(p, route)
            content = f'<section class="page {kind}"><header class="page-heading"><h1>{html.escape(title)}</h1></header><div class="page-content">{body}</div></section>'
        write(route, document(title, content, route))
    for p in ARTICLES:
        route = ROUTES[int(p['ID'])]
        write(route, document(p['post_title'], '<section class="journal">' + article(p, route, True) + '</section>', route))
    for legacy, route in LEGACY.items():
        old = legacy.lstrip('/')
        if not old or old == route: continue
        target = rel(route, old)
        write(old, f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={html.escape(target)}"><link rel="canonical" href="{html.escape(target)}"><a href="{html.escape(target)}">{html.escape(DATA["site"]["blogname"])}</a>')
    (DIST / '404.html').write_text(document('404', '<section class="page"><h1>404</h1><a href="./">6C 回憶錄</a></section>'))
    print(json.dumps({'pages': len(list(DIST.rglob('*.html'))), 'media_files': count, 'articles': len(ARTICLES), 'content_pages': len(PAGES), 'bytes': sum(p.stat().st_size for p in DIST.rglob('*') if p.is_file())}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--production', action='store_true')
    build(parser.parse_args().production)
