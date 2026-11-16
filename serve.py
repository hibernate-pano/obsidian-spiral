#!/usr/bin/env python3
"""静态服务 + 自动采集。替代 `python3 -m http.server`。

后台线程按 `ttl` 周期重采今天的数据；页面每 60 秒轮询读文件。
请求永远只读磁盘，不会因为采集而变慢。浏览历史日期时若文件缺失，会补采一次。

    python3 serve.py <Obsidian 库路径>
    python3 serve.py <库路径> --port 8899 --ttl 60
"""
import argparse
import datetime
import os
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import collect as C

ROOT = Path(__file__).parent
_today = datetime.date.today


def collect_once(vault, day, update_latest=True):
    payload = C.collect_all(vault, day)
    C.write_payload(payload, update_latest=update_latest)
    return payload


def watcher(vault, ttl, stop):
    """按周期采今天；采完睡 ttl 秒。"""
    while not stop.is_set():
        day = _today()
        try:
            p = collect_once(vault, day)
            print(f"[{datetime.datetime.now():%H:%M:%S}] 采集 {p['date']} → "
                  f"{p['totals']['agents']} 来源 / {p['totals']['sessions']} 段",
                  flush=True)
        except Exception:
            traceback.print_exc()
        stop.wait(ttl)


class Handler(SimpleHTTPRequestHandler):
    vault = None

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def do_GET(self):
        name = urllib.parse.urlparse(self.path).path.rsplit('/', 1)[-1]
        # 历史日期缺文件时补采一次（今天由 watcher 负责）
        if (name.startswith('data-') and name.endswith('.json')
                and not (ROOT / name).exists()):
            try:
                day = datetime.date.fromisoformat(name[5:-5])
            except ValueError:
                day = None
            if day and day != _today():
                try:
                    collect_once(self.vault, day, update_latest=False)
                    self.log_message('补采历史 %s', name)
                except Exception:
                    traceback.print_exc()
        super().do_GET()

    def end_headers(self):
        # 页面轮询要拿新数据，别让浏览器缓存
        if self.path.split('?')[0].endswith('.json'):
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write('[%s] %s\n' % (datetime.datetime.now().strftime('%H:%M:%S'),
                                        fmt % args))


def main():
    ap = argparse.ArgumentParser(description='螺旋盘服务：静态文件 + 自动采集')
    ap.add_argument('vault', help='Obsidian 库路径（日记来源）')
    ap.add_argument('--port', type=int, default=8899)
    ap.add_argument('--ttl', type=int, default=60,
                    help='后台重采间隔秒数（默认 60）')
    ap.add_argument('--no-warm', action='store_true',
                    help='启动时不预先采集')
    a = ap.parse_args()

    vault = Path(os.path.expanduser(a.vault)).resolve()
    if not vault.is_dir():
        raise SystemExit(f'✗ 库路径不存在: {vault}')
    Handler.vault = vault

    # 先同步采一次，避免首屏空白
    if not a.no_warm:
        try:
            p = collect_once(vault, _today())
            print(f"✓ 预热采集 {p['date']}: "
                  f"{p['totals']['agents']} 来源 / {p['totals']['sessions']} 段")
        except Exception:
            traceback.print_exc()

    stop = threading.Event()
    threading.Thread(target=watcher, args=(vault, a.ttl, stop), daemon=True).start()

    srv = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    print(f'→ http://127.0.0.1:{a.port}/index.html   '
          f'(库 {vault} · 每 {a.ttl}s 后台重采)', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        stop.set()
        print('\n停止')


if __name__ == '__main__':
    main()
