"""Synthetic CLI trial: persisted questions, subsidence opinion and recovery.

No model calls or live engineering inputs. UI display must be tested separately.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from roadexpert.service import App
from roadexpert.specs import file_hash


def run_checks(store):
    # Validate existing records locally without returning their contents.
    default = App(ROOT)
    doctor = default.dispatch({"op": "doctor"})
    before = {str(p): file_hash(p) for p in default.store.root.rglob("*.json")}
    rows = default.store.list_sessions()
    for row in rows:
        default.store.read(row["id"])
    steps = []

    def call(req, target=store):
        run = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/road.py"),
                              "--store", str(target), "-"], input=json.dumps(req, ensure_ascii=False),
                             capture_output=True, encoding="utf-8", cwd=ROOT, timeout=60)
        payload = json.loads(run.stdout)
        assert run.returncode == 0 and payload["ok"], payload
        steps.append(req["op"])
        return payload["result"]

    s = call({"op": "start", "title": "全合成试用：雨后局部沉陷", "domain": "pavement",
              "text": "全合成开发测试：道路雨后局部沉陷，发现两天，是否扩大不清楚。",
              "privacy": {"level": "synthetic", "external_model_allowed": True, "authorization_basis": "开发合成验证"},
              "facts": [{"field": "facility", "value": "道路"},
                        {"field": "rain", "value": "雨后"},
                        {"field": "progression", "value": "是否扩大不清楚", "state": "unknown"}]})["session"]
    sid, revision = s["id"], s["revision"]
    asked = call({"op": "question-ask", "session_id": sid, "base_revision": revision, "fields": ["traffic"],
                  "decision_impact": {"traffic": "合成影响：若仍通行先管控，若已封闭转核查，不清楚按暴露处理"}})
    revision, q = asked["session_revision"], asked["questions"][0]
    recovered = call({"op": "resume", "session_id": sid})
    assert recovered["resume_summary"]["pending_questions"][0]["id"] == q["id"]
    s = call({"op": "turn", "session_id": sid, "base_revision": revision, "text": "不清楚",
              "question_responses": [{"question_id": q["id"], "text": "不清楚", "state": "unknown", "submitted": True}]})["session"]
    assert s["facts"][-1]["state"] == "unknown"
    assert not call({"op": "resume", "session_id": sid})["resume_summary"]["pending_questions"]
    revision = s["revision"]
    rain_id = next(f["id"] for f in s["facts"] if f["field"] == "rain")
    answer = {
        "analysis_profile": "pavement-subsidence-v1",
        "summary": "合成意见：雨后出现是时间线索，当前不能确认沉陷原因；先补充具体位置与排水资料。",
        "hypotheses": [{"label": "水相关支撑流失待核查", "support_fact_ids": [rain_id], "against_fact_ids": [],
                        "uncertainties": ["缺少水路、隐蔽结构与调查资料"],
                        "reasoning": "雨后是弱时间线索，尚无直接证据支持冲刷；不能用未知的扩大情况作证据。",
                        "discriminator": "异常位置与排水、管线及既有维修资料是否对应，须专业核查。"}],
        "next_checks": [{"action": "整理异常位置与已有排水、维修记录供核查", "purpose": "区分是否存在相应水路或施工历史线索",
                         "different_results": "有对应线索则进一步核对；无对应线索则检查其他候选；资料不足仍保持未知。"}],
        "claims": [], "options": [], "questions": [],
        "handoff": ["交接已知描述、未知通行与发展情况、已有资料及缺口"],
        "limitations": ["全合成流程样例，未经工程专业审核，不是现场诊断或施工意见"]}
    revision = call({"op": "answer", "session_id": sid, "base_revision": revision, "answer": answer})["session_revision"]
    s = call({"op": "turn", "session_id": sid, "base_revision": revision,
              "text": "合成补充：在路肩，邻近旧沟槽。", "facts": [{"field": "location", "value": "在路肩，邻近旧沟槽"}]})["session"]
    revision = s["revision"]
    summary = call({"op": "resume", "session_id": sid})["resume_summary"]
    assert summary["latest_opinion"]["stale"] and len(summary["new_information"]) == 1
    old = s["facts"][-1]["id"]
    s = call({"op": "turn", "session_id": sid, "base_revision": revision,
              "text": "合成更正：在车道内，是否邻近沟槽不清楚。", "user_correction": True,
              "correction_reason": "合成模拟位置纠正", "facts": [{"field": "location", "value": "在车道内", "supersedes": [old]},
              {"field": "other", "value": "是否邻近沟槽不清楚", "state": "unknown"}]})["session"]
    revision = s["revision"]
    summary = call({"op": "resume", "session_id": sid})["resume_summary"]
    assert summary["corrected_facts"][0]["id"] == old and len(summary["new_information"]) == 2
    answer["summary"] = "合成更新：位置已纠正为车道内，不能沿用路肩判断；沟槽关系仍未知，先核对通行措施与实际位置资料。"
    revision = call({"op": "answer", "session_id": sid, "base_revision": revision, "answer": answer})["session_revision"]
    summary = call({"op": "resume", "session_id": sid})["resume_summary"]
    assert summary["opinion_changes"]["summary_changed"] and not summary["latest_opinion"]["stale"]
    asked = call({"op": "question-ask", "session_id": sid, "base_revision": revision, "fields": ["drainage"],
                  "decision_impact": {"drainage": "合成影响：有水路线索则优先核查水相关机理，无线索仍保留隐蔽水路待查"}})
    revision = call({"op": "question-close", "session_id": sid, "base_revision": asked["session_revision"],
                     "question_ids": [asked["questions"][0]["id"]], "reason": "合成模拟用户跳过"})["session_revision"]
    final = call({"op": "resume", "session_id": sid})
    assert final["resume_summary"]["unanswered_questions"]
    assert len(final["session"]["turns"]) == 4
    revision = call({"op": "save", "session_id": sid, "base_revision": revision,
                     "user_requested": True, "basis": "合成模拟明确保存"})["session_revision"]
    final = call({"op": "resume", "session_id": sid})
    exported = call({"op": "export", "session_id": sid, "user_requested": True})
    report = Path(exported["markdown"]).read_text(encoding="utf-8")
    assert answer["next_checks"][0]["different_results"] in report and "续办摘要" in report
    backup = store.parent / (store.name + "-backup")
    call({"op": "backup", "destination": str(backup)})
    assert call({"op": "backup-verify"}, backup)["status"] == "backup_verified"
    restored = call({"op": "resume", "session_id": sid}, backup)
    assert restored["resume_summary"] == final["resume_summary"]
    after = {str(p): file_hash(p) for p in default.store.root.rglob("*.json")}
    assert before == after, "Existing records changed"
    result = {"status": "trial_checks_passed", "steps": steps,
              "default_doctor": "passed", "existing_sessions_readable": len(rows), "existing_json_files_unchanged": True,
              "session_id": sid, "store": str(store), "export": exported, "backup": str(backup),
              "popup_ui": "not_exercised_by_script", "engineering_quality": "not_professionally_validated"}
    (store / "trial-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["artifacts_retained"] = False
    return result


def main():
    base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "RoadMaintenanceExpert"
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="synthetic-trial-", dir=base) as workspace:
        # tempfile owns this exact directory. Resolve before cleanup and verify
        # the ordinary or MSIX physical parent is the same storage location.
        root = Path(workspace).resolve()
        if not root.parent.samefile(base):
            raise RuntimeError("Unexpected synthetic trial directory")
        store = root / "records"
        store.mkdir()
        result = run_checks(store)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
