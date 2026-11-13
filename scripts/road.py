"""One JSON request per invocation; shell-free, no network, no model API."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from roadexpert.service import App
from roadexpert.storage import RoadError, load_json


def resolve_config(explicit=None):
    """配置优先级：--config > 环境变量 ROAD_EXPERT_CONFIG > 仓库 config.example.json。"""
    return explicit or os.environ.get("ROAD_EXPERT_CONFIG") or None


def main():
    parser = argparse.ArgumentParser(description="道路养护个人咨询工具；请求格式见项目 Skill")
    parser.add_argument("request", nargs="?", help="UTF-8 JSON 文件，或 - 从 stdin 读取")
    parser.add_argument("--store", help="仓库外受控记录目录")
    parser.add_argument("--config", help="本机配置 JSON；默认取 ROAD_EXPERT_CONFIG，其次 config.example.json")
    parser.add_argument("--doctor", action="store_true")
    args = parser.parse_args()
    try:
        if args.doctor:
            request = {"op": "doctor"}
        elif args.request == "-":
            request = json.load(sys.stdin)
        elif args.request:
            request = load_json(args.request)
        else:
            parser.error("请提供请求文件、- 或 --doctor")
        result = App(ROOT, args.store, resolve_config(args.config)).dispatch(request)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    except (RoadError, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), "error_type": type(exc).__name__}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
