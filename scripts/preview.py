#!/usr/bin/env python3
"""Local static preview with a private, persistent anonymous guestbook sandbox."""
import argparse
import base64
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / 'private'
DB = PRIVATE / 'guestbook.sqlite'
MAX_BODY = 12 * 1024 * 1024
LIMITS = {}
LOCK = threading.Lock()
THREADS = {'guestbook', 'post-249', 'post-251', 'post-256', 'post-258'}


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def init():
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY, thread TEXT NOT NULL, title TEXT NOT NULL,
            message TEXT NOT NULL, name TEXT NOT NULL, created_at TEXT NOT NULL,
            approved INTEGER NOT NULL DEFAULT 0, photo_path TEXT
        )''')
    DB.chmod(0o600)


class Handler(SimpleHTTPRequestHandler):
    def json_response(self, status, data):
        payload = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == '/api/guestbook':
            thread = parse_qs(parsed.query).get('thread', ['guestbook'])[0]
            if thread not in THREADS:
                return self.json_response(400, {'error': '留言位置不正確。'})
            with connect() as db:
                entries = [dict(row) for row in db.execute('SELECT id,title,message,name,created_at,photo_path FROM entries WHERE thread=? AND approved=1 ORDER BY created_at DESC LIMIT 100', (thread,))]
            for entry in entries:
                entry['photo_url'] = '/api/photos/' + entry['id'] if entry.pop('photo_path') else None
            return self.json_response(200, {'entries': entries})
        if parsed.path.startswith('/api/photos/'):
            identifier = parsed.path.rsplit('/', 1)[-1]
            with connect() as db:
                row = db.execute('SELECT photo_path FROM entries WHERE id=? AND approved=1', (identifier,)).fetchone()
            if not row or not row['photo_path']: return self.send_error(404)
            photo = PRIVATE / 'guest-photos' / row['photo_path']
            data = photo.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', self.guess_type(str(photo)))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers(); self.wfile.write(data)
            return
        return super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != '/api/guestbook': return self.send_error(404)
        host = self.headers.get('Host', '')
        if self.headers.get('Origin') not in (None, 'http://' + host):
            return self.json_response(403, {'error': '無法送出。'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY: return self.json_response(413, {'error': '照片請小於 8 MB。'})
            if self.headers.get_content_type() != 'application/json':
                return self.json_response(415, {'error': '資料格式不正確。'})
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict): raise ValueError('資料格式不正確。')
            if body.get('website'): raise ValueError('無法送出。')
            thread = str(body.get('thread', ''))
            title = str(body.get('title', '')).strip()
            message = str(body.get('message', '')).strip()
            name = str(body.get('name', '')).strip()
            if thread not in THREADS or not 1 <= len(message) <= 12000 or len(title) > 160 or len(name) > 80:
                raise ValueError('請檢查留言內容。')
            if thread == 'guestbook' and not title: raise ValueError('請填寫標題。')
            identifier = str(uuid.uuid4())
            photo_path = None; photo_data = None
            if body.get('photo'):
                match = re.fullmatch(r'data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)', body['photo'])
                if not match: raise ValueError('請選擇 JPG、PNG 或 WebP 照片。')
                photo_data = base64.b64decode(match[2], validate=True)
                if len(photo_data) > 8 * 1024 * 1024: raise ValueError('照片請小於 8 MB。')
                valid = (match[1] == 'jpeg' and photo_data[:3] == b'\xff\xd8\xff') or (match[1] == 'png' and photo_data[:8] == b'\x89PNG\r\n\x1a\n') or (match[1] == 'webp' and photo_data[:4] == b'RIFF' and photo_data[8:12] == b'WEBP')
                if not valid: raise ValueError('照片格式不正確。')
                photo_path = identifier + '.' + match[1]
            now = time.time()
            with LOCK:
                times = [t for t in LIMITS.get(self.client_address[0], []) if now - t < 900]
                if len(times) >= 6: return self.json_response(429, {'error': '請稍後再送出留言。'})
                LIMITS[self.client_address[0]] = times + [now]
            if photo_path:
                folder = PRIVATE / 'guest-photos'; folder.mkdir(mode=0o700, exist_ok=True)
                (folder / photo_path).write_bytes(photo_data)
            with connect() as db:
                db.execute('INSERT INTO entries(id,thread,title,message,name,created_at,photo_path) VALUES (?,?,?,?,?,?,?)', (identifier, thread, title, message, name, datetime.now(timezone.utc).isoformat(), photo_path))
            return self.json_response(201, {'id': identifier, 'status': 'pending'})
        except (ValueError, TypeError) as error:
            return self.json_response(400, {'error': str(error)})
        except Exception:
            return self.json_response(500, {'error': '暫時無法送出，請稍後再試。'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8087)
    parser.add_argument('--bind', default='127.0.0.1')
    args = parser.parse_args()
    init()
    server = ThreadingHTTPServer((args.bind, args.port), partial(Handler, directory=str(ROOT / 'dist')))
    print(f'Local: http://localhost:{args.port}/', flush=True)
    server.serve_forever()
