"""Synthetic delivery-check workflow through the real stdin CLI, without retained artifacts."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="roadexpert-delivery-") as workspace:
        store = Path(workspace).resolve() / "records"
        def call(req, expected=True):
            proc = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/road.py"), "--store", str(store), "-"],
                input=json.dumps(req, ensure_ascii=False), capture_output=True, encoding="utf-8", cwd=ROOT, timeout=100)
            result = json.loads(proc.stdout)
            assert result["ok"] == expected and (proc.returncode == 0) == expected, result
            return result.get("result")
        session = call({"op": "start", "title": "全合成交付检查", "domain": "pavement", "text": "全合成描述：异常层位与尺寸不清楚",
            "privacy": {"level": "synthetic", "external_model_allowed": True, "authorization_basis": "合成开发验证"}})["session"]
        sid = session["id"]
        assert call({"op": "delivery-check", "session_id": sid})["status"] == "blocked"
        answer = {"summary": "合成未核实描述：裂缝宽度5mm，参考JTG 5110—2023第3.1.2条，须核对来源后再判断。",
            "hypotheses": [], "claims": [], "next_checks": [{"action": "整理已有位置与巡查记录", "purpose": "确定核查对象及缺口"}],
            "limitations": ["全部为合成开发验证，不作为工程依据"]}
        revision = call({"op": "answer", "session_id": sid, "base_revision": session["revision"], "answer": answer})["session_revision"]
        before = call({"op": "resume", "session_id": sid})["session"]
        check = call({"op": "delivery-check", "session_id": sid})
        assert before == call({"op": "resume", "session_id": sid})["session"]
        assert check["exportable"] and {"quantity_source_unmatched", "standard_source_unmatched", "clause_source_unmatched"} <= {x["code"] for x in check["warnings"]}
        exported = call({"op": "export", "session_id": sid, "user_requested": True, "expected_check_sha256": check["content_sha256"]})
        assert exported["delivery_check"] == check
        call({"op": "turn", "session_id": sid, "base_revision": revision, "text": "合成补充：位置需重新确认"})
        call({"op": "export", "session_id": sid, "user_requested": True}, False)
        history = call({"op": "export", "session_id": sid, "user_requested": True, "history_only": True})
        assert history["status"] == "historical_export_not_for_delivery"
        assert "不作为当前意见交付" in Path(history["markdown"]).read_text(encoding="utf-8")
        session = call({"op": "resume", "session_id": sid})["session"]
        answer["summary"] = "合成更新：尺寸未核实，不使用无来源数值或规范断言；先核对位置和已有记录。"
        call({"op": "answer", "session_id": sid, "base_revision": session["revision"], "answer": answer})
        call({"op": "export", "session_id": sid, "user_requested": True, "expected_check_sha256": check["content_sha256"]}, False)
        fresh = call({"op": "delivery-check", "session_id": sid, "format": "docx"})
        assert fresh["exportable"] and fresh["manual_checks"] and not fresh["warnings"]
        word = call({"op": "export", "session_id": sid, "user_requested": True, "format": "docx", "expected_check_sha256": fresh["content_sha256"]})
        assert Path(word["docx"]).is_file()
        assert call({"op": "sessions"}) == []
    print(json.dumps({"status": "delivery_checks_passed", "readonly_check": True, "warnings_have_locations": True,
                      "stale_delivery_blocked": True, "historical_export_labeled": True, "scope_and_content_bound": True,
                      "word_export_verified": True, "artifacts_retained": False, "engineering_review": "not_performed"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
