#!/usr/bin/env python3
"""带 no-store 的静态服务器，用于本地调试这个站点。

python -m http.server 不发 Cache-Control，Chromium 会对它做启发式缓存
（按 Last-Modified 推算），于是改完 CSS/JS 刷新页面依然加载旧文件 ——
调试窄屏适配时每次都要换端口绕开缓存，很烦。这里补上 no-store 头。

用法：python3 devserver.py [port] [directory]
"""
import functools
import http.server
import os
import sys


class NoStoreHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 静音，避免刷屏


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5180
    directory = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'dist')
    handler = functools.partial(NoStoreHandler, directory=directory)
    with http.server.ThreadingHTTPServer(('127.0.0.1', port), handler) as httpd:
        print('serving %s at http://127.0.0.1:%d  (Cache-Control: no-store)' % (directory, port))
        httpd.serve_forever()


if __name__ == '__main__':
    main()
