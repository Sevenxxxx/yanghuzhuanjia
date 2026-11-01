"""Real subprocess functional check against the local library; synthetic consultation only.

This script never declares a rendered page visually reviewed. Codex/human must actually
view the returned image and submit an evidence-review separately.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from roadexpert.storage import load_json


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_checks(store):
    config = load_json(ROOT / "config.example.json")
    upstream = Path(config["spec_skill"])
    upstream_config = load_json(upstream / "config.json")
    tracked = [upstream / "SKILL.md", upstream / "config.json", upstream / "scripts/spec.py",
               Path(upstream_config["data_dir"]) / "bookshelf.json"]
    fingerprints = {str(p): sha(p) for p in tracked}
    steps = []

    def call(req):
        process = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/road.py"),
                                  "--store", str(store), "-"], input=json.dumps(req, ensure_ascii=False),
                                 capture_output=True, encoding="utf-8", cwd=ROOT, timeout=120, shell=False)
        response = json.loads(process.stdout)
        if process.returncode or not response["ok"]:
            raise RuntimeError(f"{req['op']}: {response}")
        steps.append(req["op"])
        return response["result"]

    doctor = call({"op": "doctor"})
    assert doctor["shelf_books"] > 0
    session = call({"op": "start", "title": "合成流程验证：桥梁异常待核查", "domain": "bridge",
                    "text": "这是一条合成的流程验证输入：桥梁有裂缝，具体构件不清楚，是否继续扩大不知道。",
                    "privacy": {"level": "synthetic", "external_model_allowed": True, "authorization_basis": "开发合成流程测试"},
                    "facts": [{"field": "component", "value": "具体构件不清楚", "basis": "具体构件不清楚", "state": "unknown"},
                              {"field": "progression", "value": "是否继续扩大不知道", "basis": "是否继续扩大不知道", "state": "unknown"}]})["session"]
    sid, revision = session["id"], session["revision"]
    books = call({"op": "spec-list", "query": "JTG5120", "session_id": sid, "base_revision": revision})
    revision = books["session_revision"]
    book_id = books["receipt"]["payload"]["books"][0]["id"]
    toc = call({"op": "spec-toc", "book_id": book_id, "session_id": sid, "base_revision": revision})
    revision = toc["session_revision"]
    search = call({"op": "spec-search", "book_id": book_id, "query": "明显缺损",
                   "session_id": sid, "base_revision": revision, "limit": 20})
    revision = search["session_revision"]
    payload = search["receipt"]["payload"]
    assert payload["status"] in {"matched", "search_incomplete"}, payload
    page_no = payload["data"]["matches"][0]["page"]
    read = call({"op": "spec-read", "book_id": book_id, "page": page_no,
                 "session_id": sid, "base_revision": revision})
    revision = read["session_revision"]
    assert read["receipt"]["payload"]["status"] == "page_read"
    assert read["receipt"]["payload"]["index_source_matches"], "Source fingerprint mismatch"
    render = call({"op": "spec-render", "read_receipt_id": read["receipt"]["id"],
                   "session_id": sid, "base_revision": revision})
    revision = render["session_revision"]
    assert Path(render["receipt"]["payload"]["path"]).is_file()
    no_cases = call({"op": "case-search", "domain": "bridge", "tags": ["裂缝"],
                     "session_id": sid, "base_revision": revision})
    revision = no_cases["session_revision"]
    assert no_cases["receipt"]["payload"]["status"] == "no_qualified_cases"
    session = call({"op": "turn", "session_id": sid, "base_revision": revision,
                    "text": "补充合成信息：桥梁有异常变形，现场已向责任人员报告。",
                    "facts": [{"field": "other", "value": "现场已向责任人员报告", "basis": "现场已向责任人员报告"}]})["session"]
    revision = session["revision"]
    assert session["risk"]["status"] == "attention"
    answer = {"summary": "合成流程：新报告的异常变形应优先关注，当前不能确认病因或安全状态。",
              "hypotheses": [], "next_checks": [{"action": "整理构件位置、变化时间及既有检查资料供专业核查",
                                                "purpose": "先确定对象与发展情况，不要求进入危险部位补拍"}],
              "claims": [], "options": [], "handoff": ["已有描述、已报告情况、构件与发展信息缺口"],
              "limitations": ["完全合成流程测试，不是实际工程诊断", "规范页面已渲染但尚未由查看者核对，未作为已核实判断引用"]}
    saved = call({"op": "answer", "session_id": sid, "base_revision": revision, "answer": answer})
    revision = saved["session_revision"]
    restored = call({"op": "resume", "session_id": sid})
    assert restored["session"]["revision"] == revision
    assert restored["session"]["risk"]["status"] == "attention"
    revision = call({"op": "save", "session_id": sid, "base_revision": revision,
                     "user_requested": True, "basis": "合成模拟明确保存"})["session_revision"]
    exported = call({"op": "export", "session_id": sid, "user_requested": True})
    assert Path(exported["json"]).is_file() and Path(exported["markdown"]).is_file()
    backup = store.parent / (store.name + "-backup")
    call({"op": "backup", "destination": str(backup)})
    restored_process = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/road.py"),
                                       "--store", str(backup), "-"],
                                      input=json.dumps({"op": "resume", "session_id": sid}),
                                      capture_output=True, encoding="utf-8", cwd=ROOT, timeout=60)
    recovered = json.loads(restored_process.stdout)
    assert recovered["ok"] and recovered["result"]["session"]["revision"] == revision
    verified_process = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/road.py"),
                                      "--store", str(backup), "-"], input=json.dumps({"op": "backup-verify"}),
                                     capture_output=True, encoding="utf-8", cwd=ROOT, timeout=60)
    verified = json.loads(verified_process.stdout)
    assert verified["ok"] and verified["result"]["status"] == "backup_verified"
    restored_image = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/road.py"),
                                     "--store", str(backup), "-"], input=json.dumps({
                                         "op": "receipt", "session_id": sid, "receipt_id": render["receipt"]["id"]}),
                                    capture_output=True, encoding="utf-8", cwd=ROOT, timeout=60)
    restored_path = json.loads(restored_image.stdout)["result"]["resolved_path"]
    assert Path(restored_path).is_relative_to(backup) and Path(restored_path).is_file()
    assert all(sha(path) == value for path, value in fingerprints.items()), "Upstream files changed"
    result = {"status": "functional_checks_passed", "steps": steps, "store": str(store),
              "session_id": sid, "session_revision": revision, "read_receipt_id": read["receipt"]["id"],
              "render_receipt_id": render["receipt"]["id"], "image": render["receipt"]["payload"]["path"],
              "book_id": book_id, "page": page_no, "export": exported, "backup": str(backup),
              "upstream_fingerprints_unchanged": True,
              "visual_review": "pending_actual_view", "professional_review": "not_done",
              "boundary": "This verifies local tools and state, not engineering accuracy or independent model quality."}
    result_path = store / "functional-result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["artifacts_retained"] = False
    return result


def main():
    # One owned temporary root contains both records and backup; no test archive
    # remains after success or failure. Originals in guifanchaxun are read-only.
    with tempfile.TemporaryDirectory(prefix="roadexpert-functional-") as workspace:
        root = Path(workspace).resolve()
        if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise RuntimeError("Unexpected temporary directory")
        store = root / "records"
        store.mkdir()
        result = run_checks(store)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
