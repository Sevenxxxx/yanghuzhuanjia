"""本地模型代理：真实 API key 只在这里，dsh 只拿到占位 token。

部署时它监听 127.0.0.1，只转发到允许的上游；dsh 侧的 provider base URL 指过来即可。
这样即使访问者让 agent 读环境变量或磁盘，也拿不到真 key。

用法：
    python -X utf8 scripts/p3/proxy/model_proxy.py --port 8096 \
        --upstream https://api.deepseek.com --key sk-xxx

兼容 OpenAI 风格的 /models、/chat/completions；其余路径一律 404，避免被当成通用代理。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 只放行 DeepSeek API 的路径族；其余一律 404，避免被当成通用代理。
DEFAULT_UPSTREAM = "https://api.deepseek.com/anthropic"  # dsh 用 Messages API：<base>/v1/messages
ALLOWED_PREFIXES = ("/v1/", "/beta/", "/files/", "/models", "/chat/completions", "/messages")


def allowed(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in ALLOWED_PREFIXES)


class Handler(BaseHTTPRequestHandler):
    server_version = "road-model-proxy/0.1"
    upstream: str = "https://api.deepseek.com"
    api_key: str = ""
    usage_log = None

    def log_message(self, fmt, *args):  # 不把请求体写进访问日志
        return

    def _proxy(self, method: str):
        path = self.path.split("?")[0]
        if not allowed(path):
            if self.usage_log:
                self.usage_log("DENIED", self.path)
            self.send_error(404, "unsupported path")
            return
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else None
        target = self.upstream.rstrip("/") + self.path
        headers = {"authorization": f"Bearer {self.api_key}", "accept": self.headers.get("accept", "*/*")}
        if body is not None:
            headers["content-type"] = self.headers.get("content-type", "application/json")
        request = urllib.request.Request(target, data=body, headers=headers, method=method)
        if self.usage_log:
            self.usage_log(method, self.path)
        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                self.send_response(response.status)
                for name, value in response.headers.items():
                    if name.lower() in {"transfer-encoding", "connection", "content-length"}:
                        continue
                    self.send_header(name, value)
                self.end_headers()
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except urllib.error.HTTPError as error:
            detail = error.read() or b""
            self.send_response(error.code)
            self.send_header("content-type", error.headers.get("content-type", "application/json"))
            self.send_header("content-length", str(len(detail)))
            self.end_headers()
            self.wfile.write(detail)

    def do_GET(self):
        # 上游是 Anthropic 兼容端点，没有 /models；本地直接答，顺带作为存活探测点
        if self.path.split("?")[0] == "/models":
            payload = json.dumps(
                {"object": "list", "data": [{"id": "deepseek-chat", "object": "model", "owned_by": "deepseek"}]}
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self._proxy("GET")

    def do_POST(self):
        self._proxy("POST")


def main(argv=None):
    parser = argparse.ArgumentParser(description="DeepSeek 模型转发代理（持有真实 key）")
    parser.add_argument("--port", type=int, default=8096)
    parser.add_argument("--host", default="127.0.0.1", help="默认只监听回环")
    parser.add_argument("--upstream", default=os.environ.get("ROAD_MODEL_UPSTREAM", DEFAULT_UPSTREAM))
    parser.add_argument("--key", default=os.environ.get("DEEPSEEK_API_KEY", ""))
    parser.add_argument("--usage-log", help="把每次成功转发记一行到该文件")
    args = parser.parse_args(argv)
    if not args.key:
        print("缺少 API key：用 --key 或环境变量 DEEPSEEK_API_KEY", file=sys.stderr)
        return 2

    Handler.upstream = args.upstream
    Handler.api_key = args.key
    if args.usage_log:
        path = args.usage_log

        def usage(method, target):
            try:
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write(f"{method} {target}\n")
            except OSError:
                pass

        Handler.usage_log = staticmethod(usage)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"model proxy: http://{args.host}:{args.port} -> {args.upstream}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
