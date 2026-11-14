"""纯聊天 Web 前端：自有页面 + 薄服务 + dsh SDK stdio JSON-RPC 后端。

链路：浏览器 → 本进程（HTTP + SSE）→ `dsh --profile road-sdk`（按换行分帧的 JSON-RPC）
→ 项目里的 road.py。页面只有一个聊天区和一个输入框，不显示 dsh 的侧栏与设置。

协议依据：packages/sdk/protocol（方法名、载荷、通知）。
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
P3 = HERE.parent
ROOT = P3.parent.parent
sys.path.insert(0, str(P3))

from local_web import local_addresses, pick_lan_address  # noqa: E402

PROFILE = "road-sdk"
VERSION = "0.4.0"
DEFAULT_PORT = 8091
DEFAULT_ROOT = Path.home() / "dsh-roads"
# 同一访问者累计开这么多新对话且空闲时，重建运行时，避免会话无限堆积。
REBUILD_AFTER = 20
PAGE = HERE / "page.html"
WEB_PATCH = P3 / "road_expert.patch.yml"


class ChatError(RuntimeError):
    pass


# ---------------------------------------------------------------- 协议切片

def split_patch(text):
    """按顶层 `- ` 把 patch 文件切成块（保留每块原文）。"""
    blocks, current = [], []
    for line in text.splitlines():
        if line.startswith("- ") and current:
            blocks.append("\n".join(current).rstrip() + "\n")
            current = [line]
        elif line.startswith("- ") or current:
            current.append(line)
    if current:
        blocks.append("\n".join(current).rstrip() + "\n")
    return [block for block in blocks if block.strip()]


def persona_text(web_patch_text):
    """从 Web preset 的 persona 块取出同一条职责说明，避免两处各写一份。"""
    lines = web_patch_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "prefix: |":
            indent = len(line) - len(line.lstrip())
            body = []
            for follow in lines[index + 1:]:
                if follow.strip() and (len(follow) - len(follow.lstrip())) <= indent:
                    break
                body.append(follow)
            while body and not body[-1].strip():
                body.pop()
            widths = [len(item) - len(item.lstrip()) for item in body if item.strip()]
            cut = min(widths) if widths else 0
            return [item[cut:] if item.strip() else "" for item in body]
    raise ChatError("road_expert.patch.yml 里找不到 persona prefix，无法生成 SDK profile patch")


def sdk_patch_text(web_patch_text):
    """SDK profile 的 patch：部署 persona + 权限，另关掉不该给咨询终端的工具。

    SDK 的根 agent 不走 preset（`preset-road` 会一直 pending 等 Web 端的 agentPresets 服务），
    所以这里不搬 preset，只搬 persona 文案与权限，并从 Web patch 里取 permission 块。
    """
    chosen = [b for b in split_patch(web_patch_text) if "id: permission" in b]
    merged = "".join(line for block in chosen for line in block.splitlines(True)
                     if not line.lstrip().startswith("#"))
    if "defaultPreset: danger-full-access" not in merged:
        raise ChatError("road_expert.patch.yml 里没有 permission 块，无法生成 SDK profile patch")
    persona = "\n".join("      " + line for line in persona_text(web_patch_text))
    disabled = "\n".join(
        f"- id: {row}\n  disabled: true" for row in (
            "tool-plugin-manager", "tool-schedule", "tool-workflow",
            "tool-subagent", "tool-subagent-fork", "tool-subagent-control",
            "tool-goal", "command-goal", "plan-mode",
        )
    )
    return (
        "# 由 scripts/p3/chat/app.py 从 road_expert.patch.yml 生成，勿手改\n"
        "- id: system-prompt\n  name: '@deepseek-ai/dsh-system-prompt'\n"
        "  config:\n    personaPrefix: |\n" + persona + "\n"
        + merged + disabled + "\n"
    )


def assistant_text(event):
    """从 assistant/message 事件里取文本块。"""
    data = event.get("data")
    if not isinstance(data, dict):
        return ""
    message = data.get("message")
    owner = message if isinstance(message, dict) else data
    content = owner.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(str(b.get("text") or "") for b in content
                   if isinstance(b, dict) and b.get("type") == "text")


def assistant_blocks(event):
    """把一条助手消息拆成思考文本与正文，顺序保留。"""
    data = event.get("data")
    if not isinstance(data, dict):
        return [], ""
    message = data.get("message")
    owner = message if isinstance(message, dict) else data
    content = owner.get("content")
    if not isinstance(content, list):
        return [], ""
    thinking, answer = [], []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "reasoning":
            text = str(block.get("text") or "").strip()
            if text:
                thinking.append(text)
        elif block.get("type") == "text":
            answer.append(str(block.get("text") or ""))
    return thinking, "".join(answer)


TRACE_LABELS = {
    "pwsh": "运行命令", "bash": "运行命令", "skill": "加载技能", "read": "读取",
    "write": "写入", "edit": "修改", "glob": "查找文件", "grep": "搜索内容",
    "web_search": "联网查询", "web_fetch": "联网查询", "present": "生成文件",
    "todo_write": "更新计划", "ask_user_question": "提问", "working_directory": "确认工作目录",
}


def trace_label(name, arguments):
    """把一次工具调用压成一行过程说明：动作 + 目标。"""
    args = {}
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            args = {}
    elif isinstance(arguments, dict):
        args = arguments
    label = TRACE_LABELS.get(str(name), str(name or "工具"))
    detail = ""
    if name in {"pwsh", "bash"}:
        detail = str(args.get("command") or "")
    elif name == "skill":
        detail = str(args.get("name") or "")
    elif name in {"read", "write", "edit"}:
        detail = str(args.get("file_path") or "")
    elif name in {"glob", "grep"}:
        detail = str(args.get("pattern") or "")
    elif name in {"web_search", "web_fetch"}:
        detail = str(args.get("query") or args.get("url") or "")
    return label, detail


def context_label(source):
    """上下文注入行的标题；指令注入要写出具体文件名。"""
    kind = str(source.get("kind") or "context")
    if kind != "agent-instructions":
        return f"上下文注入 · {kind}"
    names = []
    for change in source.get("changes") or []:
        if not isinstance(change, dict):
            continue
        path = str(change.get("path") or "")
        scope = str(change.get("scope") or "")
        candidate = path or scope.split("\x00")[-1]
        name = candidate.replace("\\", "/").rstrip("/").split("/")[-1].strip()
        if name and name not in names:
            names.append(name)
    return "上下文注入 · " + ("、".join(names) if names else "workspace")


def read_api_key(home=None):
    """先看环境变量，再从目标 home 或默认 home 的凭据文件读 refs.DEEPSEEK_API_KEY。"""
    value = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if value:
        return value
    candidates = [Path(home or DEFAULT_ROOT) / ".credentials.yaml", Path.home() / ".dsh" / ".credentials.yaml"]
    for path in candidates:
        if not path.is_file():
            continue
        match = re.search(r"^\s*DEEPSEEK_API_KEY:\s*(\S+)\s*$", path.read_text(encoding="utf-8"), re.M)
        if match:
            return match.group(1)
    raise ChatError("找不到 DeepSeek API key：设置 DEEPSEEK_API_KEY，或在 .credentials.yaml 的 refs 里保存它")


# ---------------------------------------------------------------- 运行时

class DshRuntime:
    """一个 `dsh --profile <p>` 子进程上的 JSON-RPC 客户端。"""

    def __init__(self, home, profile, api_key, log_path, extra_env=None):
        self.home = Path(home)
        self.profile = profile
        self.api_key = api_key
        self.log_path = Path(log_path)
        self.extra_env = {str(k): str(v) for k, v in (extra_env or {}).items()}
        self._proc = None
        self._stdout = None
        self._pending = {}
        self._listeners = set()
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._counter = 0
        self.requests = {}  # requestId -> JSON-RPC id，等待客户端回答
        self.request_sessions = {}  # requestId -> sessionId，作废旧对话时用来取消

    # -- 进程
    def start(self):
        self._proc, self._stdout = self._spawn()
        threading.Thread(target=self._read_loop, name="dsh-reader", daemon=True).start()
        return self

    def _spawn(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        found = __import__("shutil").which("dsh")
        if not found:
            raise ChatError("找不到 dsh 命令；确认它在 PATH 上")
        prefix = ["cmd", "/c", found] if os.name == "nt" and found.lower().endswith((".cmd", ".bat")) else [found]
        env = os.environ.copy()
        env["DSH_HOME"] = str(self.home)
        env["DEEPSEEK_API_KEY"] = self.api_key
        env.update(self.extra_env)
        log = open(self.log_path, "a", encoding="utf-8")
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} chat runtime start ===\n")
        log.flush()
        flags = 0
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        args = [*prefix, "--profile", self.profile]
        patch = os.environ.get("ROAD_CHAT_PATCH")
        if patch and Path(patch).is_file():
            # launcher flag，必须排在应用参数之前
            args += ["--patch", patch]
        proc = subprocess.Popen(
            args,
            cwd=str(ROOT), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=flags,
            # Linux：独立进程组，停止时用 killpg 连 node 子进程一起结束
            start_new_session=(os.name != "nt"),
        )
        return proc, proc.stdout

    def _kill_tree(self):
        """运行时是经 cmd 包一层拉起的，只 kill 父进程会留下 node 孤儿并占住会话。"""
        if not self._proc or self._proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(self._proc.pid), "/T", "/F"],
                           capture_output=True, check=False)
        else:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                try:
                    self._proc.kill()
                except OSError:
                    pass
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self.send({"jsonrpc": "2.0", "method": "shutdown"})
            except Exception:
                pass
            try:
                self._proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._kill_tree()

    def kill(self):
        """硬停：用户点停止时用，不等待正在生成的那一轮，并连同子进程一起结束。"""
        self._kill_tree()

    def alive(self):
        return self._proc is not None and self._proc.poll() is None

    # -- 收发
    def send(self, message):
        line = json.dumps(message, ensure_ascii=False) + "\n"
        with self._write_lock:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()

    def call(self, method, params=None, timeout=120):
        with self._lock:
            self._counter += 1
            request_id = self._counter
            waiter = queue.Queue(maxsize=1)
            self._pending[request_id] = waiter
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self.send(payload)
        try:
            reply = waiter.get(timeout=timeout)
        finally:
            with self._lock:
                self._pending.pop(request_id, None)
        if "error" in reply:
            raise ChatError(f"{method} 失败：{reply['error'].get('message') or reply['error']}")
        return reply.get("result")

    def respond(self, jsonrpc_id, result):
        self.send({"jsonrpc": "2.0", "id": jsonrpc_id, "result": result})

    def subscribe(self):
        box = queue.Queue()
        with self._lock:
            self._listeners.add(box)
        return box

    def unsubscribe(self, box):
        with self._lock:
            self._listeners.discard(box)

    def _publish(self, item):
        with self._lock:
            listeners = list(self._listeners)
        for box in listeners:
            box.put(item)

    def _read_loop(self):
        for line in self._stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "method" in message and "id" in message:
                self._on_request(message)
            elif "method" in message:
                self._publish({"kind": "notification", "method": message["method"],
                               "payload": message.get("params") or {}})
            elif "id" in message:
                with self._lock:
                    waiter = self._pending.get(message["id"])
                if waiter is not None:
                    waiter.put(message)
        self._publish({"kind": "closed"})

    def _on_request(self, message):
        method = message["method"]
        payload = message.get("params") or {}
        if method == "user-question/ask":
            request_id = payload.get("requestId") or f"q-{uuid.uuid4().hex[:8]}"
            self.requests[request_id] = message["id"]
            self.request_sessions[request_id] = payload.get("sessionId")
            self._publish({"kind": "question", "requestId": request_id, "payload": payload})
            return
        # 其余服务端请求（审批等）本部署不启用，按 unavailable 拒绝，避免挂住。
        self.respond_error(message["id"], -32601, f"unsupported {method}")

    def respond_error(self, jsonrpc_id, code, message):
        self.send({"jsonrpc": "2.0", "id": jsonrpc_id, "error": {"code": code, "message": message}})


# ---------------------------------------------------------------- profile 与配置

def state_path(home):
    """启动脚本用来拿当前地址的小文件；放在 home 旁边，不进仓库。"""
    return Path(home).parent / "chat-url.txt"


def ensure_profile(home, log=print):
    """创建/更新 SDK profile：缺就按随附 sdk 模板初始化，然后把 patch 写进去。"""
    home = Path(home)
    manifest = home / "profiles" / PROFILE / "package.json"
    if not manifest.is_file():
        found = __import__("shutil").which("dsh")
        if not found:
            raise ChatError("找不到 dsh 命令")
        prefix = ["cmd", "/c", found] if os.name == "nt" and found.lower().endswith((".cmd", ".bat")) else [found]
        env = os.environ.copy()
        env["DSH_HOME"] = str(home)
        result = subprocess.run(
            [*prefix, "--profile", PROFILE, "--from-default-profile", "sdk", "--dump-config"],
            cwd=str(ROOT), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if not manifest.is_file():
            raise ChatError("初始化 SDK profile 失败：" + (result.stderr or result.stdout or "")[-600:])
        log(f"已创建 SDK profile：{manifest.parent}")
    target = home / "profiles" / PROFILE / "cordis.patch.yml"
    text = sdk_patch_text(WEB_PATCH.read_text(encoding="utf-8"))
    if target.is_file() and target.read_text(encoding="utf-8") == text:
        return "unchanged"
    if target.is_file():
        target.with_name(target.name + ".bak").write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return "written"


# ---------------------------------------------------------------- 聊天服务

class Turn:
    """一轮对话的状态：新对话开始时把旧的这一轮作废，不再挡路。"""

    def __init__(self, session_id):
        self.session_id = session_id
        self.abandoned = threading.Event()

    def abandon(self):
        self.abandoned.set()


class Visitor:
    """一个浏览器访问者：自己的运行时、会话、锁与待答提问。

    运行时之间不共享任何东西：独立 DSH_HOME、独立咨询目录（LOCALAPPDATA）、
    独立子进程。因此某人点停止只会重启他自己的运行时。
    """

    def __init__(self, root, visitor_id, api_key):
        self.id = visitor_id
        self.root = Path(root)
        self.dir = self.root / "visitors" / visitor_id
        self.home = self.dir / "home"
        self.store = self.dir / "localappdata"
        self.api_key = api_key
        self.log_path = self.root / "logs" / f"runtime-{visitor_id}.log"
        self.runtime = None
        self.ready = False
        self.error = None
        self.sessions = 0
        self.last_used = time.time()
        self._ready = threading.Event()
        self._lifecycle = threading.Lock()
        self._guard = threading.Lock()
        self._locks = {}    # sessionId -> 该会话的互斥锁
        self._active = {}   # sessionId -> 进行中的 Turn

    # -- 运行时生命周期
    def _initialize(self, runtime):
        runtime.call("initialize", {
            "cwd": str(ROOT),
            "provider": "deepseek-official",
            "model": "deepseek-flash",
            "maxTokens": 16384,
            "capabilities": {"userQuestions": True},
        }, timeout=180)

    def _spawn(self):
        self.home.mkdir(parents=True, exist_ok=True)
        self.store.mkdir(parents=True, exist_ok=True)
        if not (self.home / "profiles" / PROFILE / "package.json").is_file():
            ensure_profile(self.home, log=lambda *_: None)
        runtime = DshRuntime(self.home, PROFILE, self.api_key, self.log_path,
                             extra_env={"LOCALAPPDATA": str(self.store)})
        runtime.start()
        self._initialize(runtime)
        return runtime

    def ensure(self):
        """保证运行时可用；未启动或已被停止时就地拉起。"""
        with self._lifecycle:
            if self.runtime is not None and self.ready and self.runtime.alive():
                return True
            self.ready = False
            self._ready.clear()
            try:
                self.runtime = self._spawn()
                self.error = None
                self.ready = True
            except Exception as error:
                self.error = f"运行时启动失败：{error}"
                raise ChatError(self.error)
            finally:
                self._ready.set()
        return True

    def alive(self):
        return bool(self.runtime and self.runtime.alive())

    def _kill_runtime(self):
        runtime, self.runtime = self.runtime, None
        self.ready = False
        self._ready.clear()
        if runtime is not None:
            runtime.kill()

    def restart(self, resume_session=None):
        """停掉当前运行时再起一个新的；给了会话 id 就恢复它（用于停止后继续）。"""
        if not self._lifecycle.acquire(blocking=False):
            return
        try:
            self._kill_runtime()
            try:
                self.runtime = self._spawn()
                self.error = None
                self.ready = True
                if resume_session:
                    try:
                        self.runtime.call("session/resume", {"sessionId": resume_session}, timeout=180)
                    except ChatError:
                        pass
            except Exception as error:
                self.error = f"运行时重启失败：{error}"
            finally:
                self._ready.set()
        finally:
            self._lifecycle.release()

    # -- 会话与轮次
    def lock_for(self, session_id):
        with self._guard:
            return self._locks.setdefault(session_id, threading.Lock())

    def _cancel_questions(self, sessions):
        """把挂在指定会话上的提问按协议回 {cancelled: true}，让运行时干净结束那一轮。"""
        runtime = self.runtime
        if runtime is None:
            return
        for request_id, session_id in list(runtime.request_sessions.items()):
            if session_id not in sessions:
                continue
            jsonrpc_id = runtime.requests.pop(request_id, None)
            runtime.request_sessions.pop(request_id, None)
            if jsonrpc_id is not None:
                try:
                    runtime.respond(jsonrpc_id, {"cancelled": True})
                except (OSError, ValueError):
                    pass

    def abandon_all(self):
        with self._guard:
            turns = list(self._active.values())
        for turn in turns:
            turn.abandon()
        self._cancel_questions({turn.session_id for turn in turns})
        return len(turns)

    def new_session(self):
        """每次进页面开一个新对话；累计太多且当前空闲时重建运行时，避免会话无限堆积。"""
        self.abandon_all()
        still_running = bool(self._active)
        self.sessions += 1
        if self.sessions > REBUILD_AFTER and not still_running:
            # 重建放在后台：不阻塞这次开新对话，下一条消息会自动拉起新运行时
            threading.Thread(target=self.restart, name=f"rebuild-{self.id}", daemon=True).start()
            self.sessions = 1
        return f"web-{uuid.uuid4().hex[:12]}"

    def stop(self, session_id):
        """停止这一轮：只影响本访问者。SDK 没有 cancel，重启自己的运行时才能真正停住生成。"""
        with self._guard:
            turn = self._active.get(session_id)
        if turn is None:
            return False
        turn.abandon()
        self._cancel_questions({session_id})
        threading.Thread(target=self.restart, args=(session_id,),
                         name=f"stop-{self.id}", daemon=True).start()
        return True

    def _translate_event(self, event, emit):
        """把一条 session.event 翻成 SSE；返回 True 表示这一条带了回答正文。"""
        etype = event.get("type")
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if etype == "user/message":
            source = data.get("source") if isinstance(data.get("source"), dict) else {}
            if source.get("kind") not in (None, "", "user"):
                emit("trace", {"kind": "context", "label": context_label(source)})
        elif etype == "assistant/message":
            thinking, text = assistant_blocks(event)
            for thought in thinking:
                emit("trace", {"kind": "thinking", "text": thought})
            if text:
                emit("assistant", {"text": text})
                return True
        elif etype == "tool/call":
            label, detail = trace_label(data.get("name"), data.get("arguments"))
            emit("trace", {"kind": "tool", "callId": data.get("callId"),
                           "label": label, "detail": detail})
        elif etype == "tool/result":
            message = data.get("message") if isinstance(data.get("message"), dict) else {}
            emit("trace", {"kind": "tool-result",
                           "callId": message.get("toolCallId") or data.get("callId")})
        return False

    def turn(self, session_id, blocks, emit):
        self.last_used = time.time()
        if not session_id:
            raise ChatError("缺少会话标识；刷新页面重开一次")
        self.ensure()
        runtime = self.runtime
        lock = self.lock_for(session_id)
        if not lock.acquire(blocking=False):
            raise ChatError("这个对话还在回答，等它结束再发")
        turn = Turn(session_id)
        with self._guard:
            self._active[session_id] = turn
        box = runtime.subscribe()
        produced = False
        try:
            response = runtime.call("session/query",
                                    {"sessionId": session_id, "contentBlocks": blocks}, timeout=120)
            command_id = None
            if isinstance(response, dict) and response.get("kind") == "command":
                execution = response.get("execution") or {}
                command_id = execution.get("commandId") or execution.get("command_id")
            if turn.abandoned.is_set():
                return
            emit("status", {"status": "running"})
            deadline = time.time() + 1800
            idle_ticks = 0
            while time.time() < deadline:
                if turn.abandoned.is_set():
                    return
                try:
                    item = box.get(timeout=1)
                except queue.Empty:
                    idle_ticks += 1
                    if idle_ticks % 30 == 0:
                        emit("ping", {})
                    continue
                idle_ticks = 0
                kind = item.get("kind")
                if kind == "closed":
                    if turn.abandoned.is_set():
                        return
                    emit("error", {"message": "运行时已退出，看 chat-runtime.log"})
                    return
                if kind == "question":
                    emit("question", item["payload"])
                    continue
                method, payload = item.get("method"), item.get("payload") or {}
                if payload.get("sessionId") not in (None, session_id):
                    continue
                if method == "session.event":
                    if self._translate_event(payload.get("event") or {}, emit):
                        produced = True
                elif method == "session.status":
                    if payload.get("status") == "running":
                        emit("status", {"status": "running"})
                    elif payload.get("status") == "idle":
                        emit("status", {"status": "idle"})
                        if not produced:
                            emit("error", {"message": "模型没有返回内容；检查模型代理与 API key，或看运行时日志"})
                        else:
                            emit("done", {})
                        return
                elif method == "session.query.completed":
                    if command_id is None or payload.get("commandId") == command_id:
                        text = payload.get("finalResponse")
                        if text:
                            emit("assistant", {"text": text})
                        emit("done", {"reason": payload.get("finishReason")})
                        return
                elif method == "user-question.cancelled":
                    runtime.requests.pop(payload.get("requestId"), None)
                    runtime.request_sessions.pop(payload.get("requestId"), None)
                    emit("question-cancelled", payload)
            emit("error", {"message": "这一轮超过 30 分钟，已停止等待"})
        finally:
            runtime.unsubscribe(box)
            with self._guard:
                if self._active.get(session_id) is turn:
                    self._active.pop(session_id, None)
            lock.release()

    def answer(self, request_id, answers):
        runtime = self.runtime
        jsonrpc_id = runtime.requests.pop(request_id, None) if runtime else None
        if runtime is not None:
            runtime.request_sessions.pop(request_id, None)
        if jsonrpc_id is None:
            raise ChatError("这个提问已经不再等待回答")
        runtime.respond(jsonrpc_id, answers)

    def shutdown(self):
        self.abandon_all()
        self._kill_runtime()


class ChatService:
    """按访问者分池：一个访问者一个运行时，互不阻塞。"""

    MAX_VISITORS = 8

    def __init__(self, root, api_key):
        self.root = Path(root)
        self.api_key = api_key
        self._visitors = {}
        self._guard = threading.Lock()

    def visitor(self, visitor_id):
        with self._guard:
            existing = self._visitors.get(visitor_id)
            if existing is not None:
                return existing
            if len(self._visitors) >= self.MAX_VISITORS:
                idle = [v for v in self._visitors.values() if not v._active]
                if not idle:
                    raise ChatError("同时在用的人数已达上限，请稍后再试")
                oldest = min(idle, key=lambda v: v.last_used)
                self._visitors.pop(oldest.id, None)
                oldest.shutdown()
            created = Visitor(self.root, visitor_id, self.api_key)
            self._visitors[visitor_id] = created
            return created

    def health(self):
        with self._guard:
            visitors = list(self._visitors.values())
        return {
            "ok": True,
            "visitors": len(visitors),
            "ready": sum(1 for v in visitors if v.ready),
            "sessions": sum(v.sessions for v in visitors),
            "errors": [v.error for v in visitors if v.error],
        }

    def shutdown(self):
        with self._guard:
            visitors = list(self._visitors.values())
            self._visitors.clear()
        for visitor in visitors:
            visitor.shutdown()


# ---------------------------------------------------------------- HTTP

# ---------------------------------------------------------------- 访问口令

DEFAULT_PASSWORD = "yhg"


def resolve_password(config_path, env_value):
    """口令优先级：环境变量（空值也算）> config.json > 默认值；空字符串表示不设口令。"""
    if env_value is not None:
        return env_value.strip()
    path = Path(config_path)
    if path.is_file():
        try:
            # utf-8-sig：用记事本另存为 UTF-8 会带 BOM，不能因此回落成默认口令
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return DEFAULT_PASSWORD
        return str(data.get("password", DEFAULT_PASSWORD) or "").strip()
    return DEFAULT_PASSWORD


def auth_secret(root):
    """签名密钥落盘复用：服务重启后已登录的浏览器不用重新输口令。"""
    path = Path(root) / "auth.key"
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = uuid.uuid4().hex + uuid.uuid4().hex
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


def _sign(secret, expires):
    return hmac.new(secret.encode(), str(expires).encode(), hashlib.sha256).hexdigest()


def make_auth_cookie(secret, now=None, ttl=7 * 24 * 3600):
    expires = int((time.time() if now is None else now) + ttl)
    return f"{expires}.{_sign(secret, expires)}"


def check_auth_cookie(value, secret, now=None):
    if not value or "." not in value:
        return False
    expires_text, _, signature = value.partition(".")
    try:
        expires = int(expires_text)
    except ValueError:
        return False
    if expires < (time.time() if now is None else now):
        return False
    return hmac.compare_digest(signature, _sign(secret, expires))


LOGIN_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>道路养护咨询助手</title>
<style>
  :root { color-scheme: light dark; --bg:#f2f2f7; --card:#ffffff; --label:#1d1d1f; --label-2:#6e6e73;
          --separator:rgba(60,60,67,0.16); --blue:#007aff; --fill:rgba(118,118,128,0.12); }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#000000; --card:#1c1c1e; --label:#f5f5f7; --label-2:#98989d;
            --separator:rgba(84,84,88,0.6); --blue:#0a84ff; --fill:rgba(118,118,128,0.24); }
  }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body { margin:0; display:flex; align-items:center; justify-content:center; background:var(--bg);
         color:var(--label); font:14px/1.45 -apple-system, BlinkMacSystemFont, "SF Pro Text",
         "PingFang SC", "Microsoft YaHei", system-ui, sans-serif; }
  form { width: min(340px, calc(100vw - 48px)); background:var(--card); border-radius:18px;
         padding:24px; box-shadow:0 1px 2px rgba(0,0,0,0.06); }
  h1 { margin:0 0 6px; font-size:17px; font-weight:600; }
  p { margin:0 0 16px; color:var(--label-2); }
  input { width:100%; height:40px; padding:0 12px; font:inherit; color:var(--label);
          background:var(--fill); border:1px solid transparent; border-radius:10px; outline:none; }
  input:focus { border-color:var(--blue); }
  button { margin-top:12px; width:100%; height:40px; font:inherit; font-weight:500; color:#fff;
           background:var(--blue); border:0; border-radius:10px; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  .error { margin-top:10px; color:#ff3b30; min-height:18px; font-size:13px; }
</style></head>
<body>
<form id="gate" autocomplete="off">
  <h1>道路养护咨询助手</h1>
  <p>请输入访问口令</p>
  <input id="password" type="password" inputmode="text" autocomplete="current-password" required>
  <button id="submit" type="submit">进入</button>
  <div class="error" id="error"></div>
</form>
<script>
  const form = document.getElementById('gate');
  const input = document.getElementById('password');
  const submit = document.getElementById('submit');
  const error = document.getElementById('error');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    submit.disabled = true;
    error.textContent = '';
    try {
      const response = await fetch('api/login', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ password: input.value }),
      });
      if (response.ok) { location.replace('/'); return; }
      error.textContent = response.status === 429 ? '尝试太频繁，稍后再试' : '口令不对';
    } catch (failure) {
      error.textContent = '连不上服务';
    }
    submit.disabled = false;
    input.select();
  });
  input.focus();
</script>
</body></html>"""

COOKIE_NAME = "rc_vid"
COOKIE_MAX_AGE = 30 * 24 * 3600


def _cookie_secure():
    return os.environ.get("ROAD_CHAT_COOKIE_SECURE", "").strip() in {"1", "true", "yes"}


class Handler(BaseHTTPRequestHandler):
    service: ChatService = None  # set in main()
    password = ""                # 空表示不设口令
    secret = ""                  # 口令 cookie 的签名密钥
    server_version = "road-chat/0.4"
    _attempts = {}               # ip -> [次数, 首次时间]
    _attempts_lock = threading.Lock()

    def log_message(self, fmt, *args):  # 安静一点
        return

    def _json(self, status, data, extra_headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        for name, value in (extra_headers or []):
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _cookie_id(self):
        raw = self.headers.get("cookie") or ""
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE_NAME and re.fullmatch(r"[0-9a-f]{32}", value.strip()):
                return value.strip()
        return None

    def _cookie_header(self, name, value, max_age=COOKIE_MAX_AGE):
        """两种 cookie 只差名字与值，统一在这里拼属性。"""
        flags = f"{name}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
        if _cookie_secure():
            flags += "; Secure"
        return ("Set-Cookie", flags)

    def _authorized(self):
        if not self.password:
            return True
        raw = self.headers.get("cookie") or ""
        for part in raw.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "rc_auth" and check_auth_cookie(value.strip(), self.secret):
                return True
        return False

    def _too_many_attempts(self):
        ip = self.client_address[0]
        with Handler._attempts_lock:
            count, first = Handler._attempts.get(ip, (0, time.time()))
            if time.time() - first > 60:
                count, first = 0, time.time()
            return count >= 5

    def _record_attempt(self, success):
        ip = self.client_address[0]
        with Handler._attempts_lock:
            if success:
                Handler._attempts.pop(ip, None)
                return
            count, first = Handler._attempts.get(ip, (0, time.time()))
            if time.time() - first > 60:
                count, first = 0, time.time()
            Handler._attempts[ip] = (count + 1, first)

    def _login(self, payload):
        if self._too_many_attempts():
            self._json(429, {"error": "尝试太频繁，稍后再试"})
            return
        given = str(payload.get("password") or "")
        if not self.password or hmac.compare_digest(given, self.password):
            self._record_attempt(True)
            headers = [self._cookie_header("rc_auth", make_auth_cookie(self.secret))]
            if self._cookie_id() is None:
                headers.append(self._cookie_header(COOKIE_NAME, uuid.uuid4().hex))
            self._json(200, {"ok": True}, headers)
            return
        self._record_attempt(False)
        time.sleep(0.4)
        self._json(401, {"error": "口令不对"})

    def _visitor(self):
        visitor_id = self._cookie_id()
        if not visitor_id:
            return None, None
        return visitor_id, self.service.visitor(visitor_id)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            if not self._authorized():
                body = LOGIN_PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("content-type", "text/html; charset=utf-8")
                self.send_header("content-length", str(len(body)))
                self.send_header("cache-control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            headers = []
            if self._cookie_id() is None:
                visitor_id = uuid.uuid4().hex
                headers.append(self._cookie_header(COOKIE_NAME, visitor_id))
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/health":
            self._json(200, self.service.health())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "请求不是合法 JSON"})
            return
        if self.path == "/api/login":
            self._login(payload)
            return
        if not self._authorized():
            self._json(401, {"error": "需要口令；刷新页面重进"})
            return
        if self.path == "/api/new":
            visitor_id, visitor = self._visitor()
            if visitor is None:
                self._json(401, {"error": "会话标识缺失；刷新页面重开"})
                return
            self._json(200, {"sessionId": visitor.new_session()})
            return
        visitor_id, visitor = self._visitor()
        if visitor is None:
            self._json(401, {"error": "会话标识缺失；刷新页面重开"})
            return
        if self.path == "/api/stop":
            stopped = visitor.stop((payload.get("sessionId") or "").strip())
            self._json(200, {"ok": True, "stopped": stopped})
            return
        if self.path == "/api/send":
            self._send(visitor, payload)
            return
        if self.path == "/api/answer":
            try:
                visitor.answer(payload.get("requestId"), {"answers": payload.get("answers") or []})
            except ChatError as error:
                self._json(409, {"error": str(error)})
                return
            self._json(200, {"ok": True})
            return
        self._json(404, {"error": "not found"})

    def _send(self, visitor, payload):
        blocks = []
        text = (payload.get("text") or "").strip()
        if text:
            blocks.append({"type": "text", "text": text})
        for image in payload.get("images") or []:
            data = image.get("data") or ""
            mime = image.get("mimeType") or "image/png"
            if data:
                blocks.append({"type": "image", "data": data, "mimeType": mime})
        if not blocks:
            self._json(400, {"error": "没有内容可发送"})
            return
        session_id = (payload.get("sessionId") or "").strip()
        if not session_id:
            self._json(400, {"error": "缺少会话标识；刷新页面重开一次"})
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream; charset=utf-8")
        self.send_header("cache-control", "no-store")
        self.send_header("x-accel-buffering", "no")
        self.end_headers()

        def emit(name, data):
            frame = f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()

        try:
            emit("status", {"status": "running"})
            visitor.turn(session_id, blocks, emit)
        except ChatError as error:
            try:
                emit("error", {"message": str(error)})
            except OSError:
                pass
        except (BrokenPipeError, ConnectionResetError):
            return


def main(argv=None):
    parser = argparse.ArgumentParser(description="道路养护专家·纯聊天前端（按访问者隔离运行时）")
    parser.add_argument("--home", default=str(DEFAULT_ROOT), help="访问者数据根目录（默认 dsh-roads）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口，默认 {DEFAULT_PORT}")
    parser.add_argument("--host", help="监听地址，默认本机局域网 IPv4，取不到则 127.0.0.1")
    parser.add_argument("--print-url", action="store_true", help="只打印访问地址后退出")
    parser.add_argument("--version", action="version", version=f"road-chat {VERSION}")
    parser.add_argument("--config", help="配置文件路径（默认 scripts/p3/chat/config.json；可指向仓库根的 deploy.json）")
    args = parser.parse_args(argv)

    host = args.host or pick_lan_address(local_addresses()) or "127.0.0.1"
    url = f"http://{host}:{args.port}/"
    if args.print_url:
        print(url)
        return 0

    root = Path(args.home)
    root.mkdir(parents=True, exist_ok=True)
    config_path = Path(args.config) if args.config else HERE / "config.json"
    password = resolve_password(config_path, os.environ.get("ROAD_CHAT_PASSWORD"))
    Handler.password = password
    Handler.secret = auth_secret(root) if password else ""
    service = ChatService(root, read_api_key(root))
    Handler.service = service
    server = ThreadingHTTPServer((host, args.port), Handler)
    server.daemon_threads = True
    # 启动脚本靠这个文件拿到实际地址；绑定成功后才写，避免留下不可用的旧地址。
    marker = state_path(root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(url, encoding="utf-8")
    print(f"道路养护专家已启动：{url}（按访问者隔离运行时）", flush=True)
    print("口令：已启用（登录页输入）" if password else "口令：未启用（config.json 里 password 为空）", flush=True)
    print("停止：Ctrl+C", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        service.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
