"""Run synthetic domain and delivery workflows through the real stdin CLI."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from roadexpert.advice import PROFILES, DELIVERIES


def main():
    profiles = []
    exports = 0
    with tempfile.TemporaryDirectory(prefix="roadexpert-advice-") as workspace:
        store = Path(workspace).resolve() / "records"

        def call(request, expected=True):
            proc = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/road.py"),
                                   "--store", str(store), "-"], input=json.dumps(request, ensure_ascii=False),
                                  capture_output=True, encoding="utf-8", cwd=ROOT, timeout=60)
            result = json.loads(proc.stdout)
            assert result["ok"] == expected and (proc.returncode == 0) == expected, result
            return result.get("result")

        for profile, (domain, fields) in PROFILES.items():
            if not fields:
                continue  # Subsidence is covered by check_trial.py.
            s = call({"op": "start", "title": "全合成领域与交付验证", "domain": domain,
                "text": "全合成测试：设施有异常，具体部位、变化、通行情况待查。",
                "privacy": {"level": "synthetic", "external_model_allowed": True,
                            "authorization_basis": "开发合成验证"}})["session"]
            assert any(card.get("analysis_profile") == profile for card in
                       call({"op": "resume", "session_id": s["id"]})["briefing"]["knowledge_cards"])
            answer = {"analysis_profile": profile, "analysis_context": {k: "合成未知，待核查" for k in fields},
                "summary": "合成咨询：原因尚不能确认，先整理已有记录交相应专业核查。",
                "hypotheses": [], "claims": [], "limitations": ["全合成流程验证，未经工程专业审核"],
                "next_checks": [{"action": "调取已有同位置记录", "purpose": "核对新旧和变化",
                                 "different_results": "有对应资料继续核对，无资料仍保持未知"}],
                "deliverables": {kind: {key: ["合成沟通草稿：待核查，尚未执行"] for key in sections}
                                 for kind, (_, sections) in DELIVERIES.items()}}
            call({"op": "answer", "session_id": s["id"], "base_revision": s["revision"], "answer": answer})
            for kind in DELIVERIES:
                result = call({"op": "export", "session_id": s["id"], "user_requested": True, "kind": kind})
                content = Path(result["markdown"]).read_text(encoding="utf-8")
                assert DELIVERIES[kind][0] in content and "判断边界" in content and "规范依据与核验范围" in content
                assert "turns" not in json.loads(Path(result["json"]).read_text(encoding="utf-8"))
                exports += 1
            current = call({"op": "resume", "session_id": s["id"]})["session"]
            current = call({"op": "turn", "session_id": s["id"], "base_revision": current["revision"],
                            "text": "合成更正：需要重新确认位置"})["session"]
            call({"op": "export", "session_id": s["id"], "user_requested": True, "kind": "department_reply"}, False)
            assert call({"op": "sessions"}) == []
            call({"op": "finish", "session_id": s["id"], "base_revision": current["revision"]})
            assert Path(result["markdown"]).exists()  # Explicit exports outlive temporary sessions.
            profiles.append(profile)
    print(json.dumps({"status": "advice_checks_passed", "profiles": profiles, "exports_verified": exports,
                      "artifacts_retained": False, "engineering_review": "not_performed",
                      "popup_ui": "not_exercised"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
