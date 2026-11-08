#!/usr/bin/env python3
"""Verify the immutable backup and prepare a separate WordPress working copy."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / 'backups/2026-11-08'
LOCAL = ROOT / 'local-wordpress'


def verify():
    for line in (BACKUP / 'SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        path = BACKUP / name
        digest = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise RuntimeError(f'Checksum mismatch: {name}')
        print(f'Verified {name}', flush=True)


def prepare():
    os.umask(0o077)
    if LOCAL.exists():
        raise RuntimeError('Local working copy already exists; leaving it unchanged.')
    LOCAL.mkdir(mode=0o700)
    html = LOCAL / 'html'
    html.mkdir(mode=0o755)
    with tarfile.open(BACKUP / 'wordpress.tar.gz', 'r:gz') as archive:
        if hasattr(tarfile, 'data_filter'):
            archive.extractall(html, filter='data')
        else:
            for item in archive.getmembers():
                destination = (html / item.name).resolve()
                if not destination.is_relative_to(html.resolve()) or item.issym() or item.islnk():
                    raise RuntimeError(f'Unsafe archive entry: {item.name}')
            archive.extractall(html)
    # The original wp-config stays untouched inside the verified archive.
    password = secrets.token_hex(24)
    root_password = secrets.token_hex(24)
    (LOCAL / '.env').write_text(
        f'MYSQL_DATABASE=wordpress\nMYSQL_USER=wordpress\nMYSQL_PASSWORD={password}\n'
        f'MYSQL_ROOT_PASSWORD={root_password}\nWORDPRESS_DB_HOST=db_456c\n'
        f'WORDPRESS_DB_NAME=wordpress\nWORDPRESS_DB_USER=wordpress\nWORDPRESS_DB_PASSWORD={password}\n'
    )
    config = """<?php
define('DB_NAME', getenv('WORDPRESS_DB_NAME'));
define('DB_USER', getenv('WORDPRESS_DB_USER'));
define('DB_PASSWORD', getenv('WORDPRESS_DB_PASSWORD'));
define('DB_HOST', getenv('WORDPRESS_DB_HOST'));
define('DB_CHARSET', 'utf8mb4');
define('DB_COLLATE', '');
define('WP_HOME', 'http://localhost:8086');
define('WP_SITEURL', 'http://localhost:8086');
define('WP_ENVIRONMENT_TYPE', 'local');
define('DISABLE_WP_CRON', true);
define('AUTOMATIC_UPDATER_DISABLED', true);
define('DISALLOW_FILE_MODS', true);
define('WP_HTTP_BLOCK_EXTERNAL', true);
define('WP_MEMORY_LIMIT', '256M');
define('FORCE_SSL_ADMIN', false);
$table_prefix = 'wp_';
"""
    for key in ('AUTH_KEY', 'SECURE_AUTH_KEY', 'LOGGED_IN_KEY', 'NONCE_KEY', 'AUTH_SALT', 'SECURE_AUTH_SALT', 'LOGGED_IN_SALT', 'NONCE_SALT'):
        config += f"define('{key}', '{secrets.token_hex(48)}');\n"
    config += "if (!defined('ABSPATH')) define('ABSPATH', __DIR__ . '/');\nrequire_once ABSPATH . 'wp-settings.php';\n"
    (html / 'wp-config.php').write_text(config)
    (html / 'wp-config.php').chmod(0o644)
    (html / '.htaccess').write_text('''# Local WordPress working copy
<IfModule mod_rewrite.c>
RewriteEngine On
RewriteBase /
RewriteRule ^index\\.php$ - [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule . /index.php [L]
</IfModule>
''')
    (html / '.htaccess').chmod(0o644)
    if (html / '.user.ini').exists():
        (html / '.user.ini').write_text('; Local working copy\n')
        (html / '.user.ini').chmod(0o644)
    mu = html / 'wp-content/mu-plugins'
    mu.mkdir(mode=0o755, exist_ok=True)
    (mu / 'sixc-local.php').write_text('''<?php
add_filter('pre_wp_mail', '__return_false');
add_filter('option_active_plugins', function ($plugins) {
    return array_values(array_filter($plugins, function ($plugin) {
        return !in_array($plugin, ['jetpack/jetpack.php', 'all-in-one-wp-security-and-firewall/wp-security.php'], true);
    }));
});
''')
    (mu / 'sixc-local.php').chmod(0o644)
    (LOCAL / 'db-init').mkdir(mode=0o755)
    shutil.copyfile(BACKUP / 'database.sql.gz', LOCAL / 'db-init/01-wordpress.sql.gz')
    (LOCAL / 'db-init/01-wordpress.sql.gz').chmod(0o644)
    shutil.copyfile(BACKUP / 'uploads.ini', LOCAL / 'uploads.ini')
    (LOCAL / 'uploads.ini').chmod(0o644)
    images = json.loads((BACKUP / 'original-containers.json').read_text())
    subprocess.run(['docker', 'load', '--input', str(BACKUP / 'docker-images.tar.gz')], check=True)
    for image in images:
        kind = 'wordpress' if 'wordpress' in image['Name'] else 'mysql'
        subprocess.run(['docker', 'tag', image['Image'], f'sixc-archive/{kind}:20261108'], check=True)
    print('Local WordPress copy prepared.', flush=True)


if __name__ == '__main__':
    verify()
    prepare()
