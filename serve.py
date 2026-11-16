#!/usr/bin/env python3
"""静态服务 + 自动采集。替代 `python3 -m http.server`。

页面每 60 秒拉一次 data.json；这个服务在拉取时检查数据是否过期，
过期就当场跑一遍 collect.py，所以页面始终是最新的，不用手动重采。

    python3 serve.py <Obsidian 库路径>
    python3 serve.py <库路径> --port 8899 --ttl 60
"""
import argparse
import datetime
import os
import sys
import threading
import traceback
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import collect as C

ROOT = Path(__file__).parent
_lock = threading.Lock()
_last = {}       # date_str -> 上次采集完成的时刻
_busy = set()    # 正在采集的 date_str，避免并发重复跑


class Handler(SimpleHTTPRequestHandler):
    vault = None
    ttl = 60

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        name = path.rsplit('/', 1)[-1]
        today = datetime.date.today()
        # data.json 代表"今天"，跟着实时刷新
        if name == 'data.json':
            self._refresh(today)
        elif name.startswith('data-') and name.endswith('.json'):
            try:
                day = datetime.date.fromisoformat(name[5:-5])
            except ValueError:
                day = None
            if day == today:
                self._refresh(day)
            elif day and not (ROOT / name).exists():
                # 历史日期只在缺文件时补采一次，翻日期不卡 4 秒
                self._refresh(day)
        super().do_GET()

    def _refresh(self, day):
        """该日数据超过 ttl 秒就重新采集。失败不阻塞请求。"""
        key = f'{day:%Y-%m-%d}'
        now = datetime.datetime.now()
        with _lock:
            if key in _busy:
                return
            last = _last.get(key)
            if last and (now - last).total_seconds() < self.ttl:
                return
            _busy.add(key)
        try:
            payload = C.collect_all(self.vault, day)
            C.write_payload(payload, update_latest=(day == datetime.date.today()))
            with _lock:
                _last[key] = datetime.datetime.now()
            self.log_message('采集 %s → %d 来源 / %d 段',
                             key, payload['totals']['agents'], payload['totals']['sessions'])
        except Exception:
            traceback.print_exc()
            with _lock:
                # 失败也记时间，避免每次请求都重试拖慢页面
                _last[key] = datetime.datetime.now()
        finally:
            with _lock:
                _busy.discard(key)

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
                    help='数据过期秒数，浏览器每次请求都会检查（默认 60）')
    ap.add_argument('--no-warm', action='store_true',
                    help='启动时不预先采集')
    a = ap.parse_args()

    vault = Path(os.path.expanduser(a.vault)).resolve()
    if not vault.is_dir():
        raise SystemExit(f'✗ 库路径不存在: {vault}')
    Handler.vault = vault
    Handler.ttl = a.ttl

    # 起服务前先采一次，避免首屏空白
    if not a.no_warm:
        try:
            payload = C.collect_all(vault, datetime.date.today())
            C.write_payload(payload)
            print(f"✓ 预热采集 {payload['date']}: "
                  f"{payload['totals']['agents']} 来源 / {payload['totals']['sessions']} 段")
        except Exception:
            traceback.print_exc()

    srv = ThreadingHTTPServer(('127.0.0.1', a.port), Handler)
    print(f'→ http://127.0.0.1:{a.port}/index.html   '
          f'(库 {vault} · 过期 {a.ttl}s 自动重采)')
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\n停止')


if __name__ == '__main__':
    main()
