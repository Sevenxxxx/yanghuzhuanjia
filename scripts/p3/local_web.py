"""在仓库外起一个专用的「道路养护专家」Web 实例（P3 本机阶段）。

实例是独立 dsh home + 独立端口，复用本机已有的 dsh 安装、项目仓库与模型账号，
不改动现有个人 profile 与会话。数据都在 %USERPROFILE%\\dsh-roads 下，可整体删除。

用法见同目录 README.md。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATCH = Path(__file__).resolve().parent / "road_expert.patch.yml"
BASE_NAME = "dsh-roads"
DEFAULT_PORT = 8090
DEV_GUI_PORT = 3080
URL_RE = re.compile(r"http://(?P<host>[^\s/]+):(?P<port>\d+)/\?token=(?P<token>[A-Za-z0-9_\-]+)")


class TrialError(RuntimeError):
    pass


def layout(base=None):
    base = Path(base).expanduser() if base else Path.home() / BASE_NAME
    base = base.resolve()
    return {
        "base": base,
        "home": base / "home",
        "logs": base / "logs",
        "state": base / "state.json",
        "log": base / "logs" / "web.log",
        "patch": base / "home" / "profiles" / "web" / "cordis.patch.yml",
    }


def validate_port(port):
    port = int(port)
    if not 1024 <= port <= 65535:
        raise TrialError("端口须在 1024～65535 之间")
    if port == DEV_GUI_PORT:
        raise TrialError("3080 是当前开发 GUI 的端口，请换一个端口")
    return port


def is_lan_address(text):
    parts = text.split(".")
    if len(parts) != 4 or not all(p.isdigit() and int(p) <= 255 for p in parts):
        return False
    a, b = int(parts[0]), int(parts[1])
    if a == 10:
        return True
    if a == 192 and b == 168:
        return True
    return a == 172 and 16 <= b <= 31


def address_rank(text):
    """局域网地址的偏好顺序：192.168 最像办公室/家庭网段，其次 172.16–31，最后 10/8。

    本机常有 VPN、虚拟网卡等在 10/8 里的地址；按顺序选会让书签地址随机漂移。
    """
    if text.startswith("192.168."):
        return 0
    if text.startswith("172."):
        return 1
    return 2


def pick_lan_address(candidates):
    """从候选里挑一个局域网 IPv4；排除回环、APIPA、Tailscale 100.64/10。"""
    usable = [item for item in candidates if item and is_lan_address(item)]
    if not usable:
        return None
    return min(usable, key=address_rank)


def local_addresses():
    try:
        return socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        return []


def parse_urls(text):
    return [m.group(0) for m in URL_RE.finditer(text)]


def latest_url(text, port=None):
    found = None
    for match in URL_RE.finditer(text):
        if port is None or int(match.group("port")) == int(port):
            found = match.group(0)
    return found


def launcher_command():
    found = shutil.which("dsh")
    if not found:
        raise TrialError("找不到 dsh 命令；请确认 dsh 已安装并在 PATH 上")
    if os.name == "nt" and found.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", found]
    return [found]


def run_launcher(args, home, capture=False):
    env = os.environ.copy()
    env["DSH_HOME"] = str(home)
    return subprocess.run(
        [*launcher_command(), *args], cwd=str(ROOT), env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )


def ensure_profile(home):
    """新 home 首次需要初始化 web profile；已有 package.json 时不动它。"""
    manifest = home / "profiles" / "web" / "package.json"
    if manifest.is_file():
        return False
    result = run_launcher(["--profile", "web", "--dump-default-config"], home)
    if result.returncode != 0 or not manifest.is_file():
        raise TrialError("初始化 profile 失败：" + (result.stderr or result.stdout or "")[-800:])
    return True


def install_patch(paths):
    text = PATCH.read_text(encoding="utf-8")
    target = paths["patch"]
    if target.is_file():
        if target.read_text(encoding="utf-8") == text:
            return "unchanged"
        shutil.copy2(target, target.with_name(target.name + ".bak"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return "written"


def port_open(host, port, timeout=1.0):
    try:
        with socket.create_connection((host, int(port)), timeout):
            return True
    except OSError:
        return False


def launch(paths, host, port, trusted):
    args = ["--profile", "web", "--host", host, "--port", str(port), "--no-open"]
    for item in trusted or []:
        args += ["--trusted-host", item]
    env = os.environ.copy()
    env["DSH_HOME"] = str(paths["home"])
    paths["logs"].mkdir(parents=True, exist_ok=True)
    log = paths["log"]
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start {host}:{port} ===\n")
        handle.flush()
        flags = 0
        if os.name == "nt":
            # DETACHED_PROCESS 会丢掉 Node 写到重定向文件里的 console 输出
            # （实测 URL 行不落盘），改用独立隐藏控制台：既能脱离父进程存活，
            # 又能正常写日志。
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            [*launcher_command(), *args], cwd=str(ROOT), env=env,
            stdout=handle, stderr=subprocess.STDOUT, creationflags=flags,
        )
    return proc


def wait_ready(paths, port, timeout=90):
    deadline = time.time() + timeout
    log = paths["log"]
    while time.time() < deadline:
        if log.is_file():
            url = latest_url(log.read_text(encoding="utf-8", errors="replace"), port)
            if url:
                return url
        time.sleep(0.5)
    raise TrialError(f"等待实例就绪超时（{timeout}s）；日志末尾：\n" + tail(log))


def tail(path, lines=20):
    if not Path(path).is_file():
        return "(无日志)"
    return "\n".join(Path(path).read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])


def write_state(paths, data):
    paths["state"].write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_state(paths):
    if not paths["state"].is_file():
        return {}
    try:
        return json.loads(paths["state"].read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def stop(paths):
    state = read_state(paths)
    pid = state.get("pid")
    if not pid:
        return False
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, check=False)
    else:  # pragma: no cover - 本项目当前只在 Windows 验证
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    for _ in range(40):
        if not port_open(state.get("host", "127.0.0.1"), state.get("port", 0)):
            return True
        time.sleep(0.25)
    return False


def command_up(args, paths):
    port = validate_port(args.port)
    probe_host = args.host or pick_lan_address(local_addresses()) or "127.0.0.1"
    if port_open(probe_host, port):
        raise TrialError(f"{probe_host}:{port} 已有进程在监听；用 status 查看或换端口")
    initialized = ensure_profile(paths["home"])
    patch_state = install_patch(paths)
    proc = launch(paths, probe_host, port, args.trusted_host)
    write_state(paths, {
        "pid": proc.pid, "port": port, "host": probe_host,
        "base": str(paths["base"]), "log": str(paths["log"]),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    url = wait_ready(paths, port)
    print(json.dumps({
        "status": "running", "pid": proc.pid, "host": probe_host, "port": port,
        "url": url, "profile_initialized": initialized,
        "patch": patch_state,
        "base": str(paths["base"]),
    }, ensure_ascii=False, indent=2))
    return 0


def command_status(args, paths):
    state = read_state(paths)
    if not state:
        print(json.dumps({"status": "absent", "base": str(paths["base"])}, ensure_ascii=False, indent=2))
        return 1
    running = port_open(state.get("host", "127.0.0.1"), state.get("port", 0))
    url = None
    if paths["log"].is_file():
        url = latest_url(paths["log"].read_text(encoding="utf-8", errors="replace"), state.get("port"))
    print(json.dumps({**state, "running": running, "url": url}, ensure_ascii=False, indent=2))
    return 0 if running else 1


def command_url(args, paths):
    if not paths["log"].is_file():
        raise TrialError("还没有日志；先运行 up")
    state = read_state(paths)
    url = latest_url(paths["log"].read_text(encoding="utf-8", errors="replace"), state.get("port"))
    if not url:
        raise TrialError("日志里没有带 token 的启动地址；实例可能启动失败，见 down 之外的日志尾部")
    print(url)
    return 0


def command_down(args, paths):
    stopped = stop(paths)
    state = read_state(paths)
    write_state(paths, {**state, "stopped_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
    print(json.dumps({"status": "stopped" if stopped else "not-running",
                      "port": state.get("port")}, ensure_ascii=False, indent=2))
    return 0


def command_reset(args, paths):
    base = paths["base"]
    if base.name != BASE_NAME:
        raise TrialError(f"拒绝删除非试用目录：{base}")
    if not base.is_dir():
        print(json.dumps({"status": "absent"}, ensure_ascii=False))
        return 0
    if not args.yes:
        raise TrialError(f"这会删除 {base}（含会话与凭据副本）；确认后加 --yes")
    stop(paths)
    shutil.rmtree(base)
    print(json.dumps({"status": "removed", "base": str(base)}, ensure_ascii=False, indent=2))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="local_web.py",
        description="在仓库外起一个专用的道路养护专家 Web 实例（独立 dsh home 与端口）",
    )
    parser.add_argument("--base", help=f"实例目录，默认 %USERPROFILE%\\{BASE_NAME}")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="安装配置并启动实例")
    up.add_argument("--host", help="监听地址，默认自动取本机局域网 IPv4，取不到则 127.0.0.1")
    up.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口，默认 {DEFAULT_PORT}")
    up.add_argument("--trusted-host", action="append", default=[],
                    help="额外允许的 authority（经主机名访问时用；可重复）")
    up.set_defaults(func=command_up)

    status = sub.add_parser("status", help="查看实例状态")
    status.set_defaults(func=command_status)

    url = sub.add_parser("url", help="打印最近一次带 token 的启动地址")
    url.set_defaults(func=command_url)

    down = sub.add_parser("down", help="停止实例")
    down.set_defaults(func=command_down)

    reset = sub.add_parser("reset", help="停止并删除整个实例目录")
    reset.add_argument("--yes", action="store_true", help="确认删除")
    reset.set_defaults(func=command_reset)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = layout(args.base)
    try:
        return args.func(args, paths)
    except TrialError as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False, indent=2),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
