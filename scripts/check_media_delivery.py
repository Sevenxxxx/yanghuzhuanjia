"""Synthetic CLI integration. --qa-dir keeps only synthetic DOCX files for visual QA."""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from roadexpert.advice import DELIVERIES
from roadexpert.specs import file_hash


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa-dir", type=Path)
    args = parser.parse_args()
    qa_dir = args.qa_dir.resolve() if args.qa_dir else None
    if qa_dir:
        if qa_dir.is_relative_to(ROOT) or qa_dir.exists():
            raise ValueError("QA目录须为新的仓库外目录，仅保存合成文件")
        qa_dir.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="roadexpert-media-") as workspace:
        base = Path(workspace).resolve()
        store = base / "records"
        def call(req, expected=True):
            run = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/road.py"), "--store", str(store), "-"],
                input=json.dumps(req, ensure_ascii=False), capture_output=True, encoding="utf-8", timeout=100, cwd=ROOT)
            result = json.loads(run.stdout)
            assert result["ok"] == expected and (run.returncode == 0) == expected, result
            return result.get("result")
        s = call({"op": "start", "title": "合成开发测试 道路异常咨询意见", "domain": "pavement",
            "text": "全合成流程测试：道路表面有异常，具体层位、发展与通行情况不清楚。",
            "privacy": {"level": "synthetic", "external_model_allowed": True, "authorization_basis": "开发合成验证"}})["session"]
        sid, revision = s["id"], s["revision"]
        originals = {}
        photo_paths = []
        for index, size in enumerate(((900, 500), (450, 900)), 1):
            source = base / f"synthetic-{index}.png"
            image = Image.new("RGB", size, "#e6e6e6")
            draw = ImageDraw.Draw(image)
            draw.rectangle((40, 70, size[0]-40, size[1]-70), fill="#888888", outline="black", width=3)
            draw.line((90, 110, size[0]-90, size[1]-100), fill="#333333", width=6)
            draw.text((40, 25), "SYNTHETIC QA ONLY - NOT A REAL ROAD", fill="black")
            image.save(source)
            originals[str(source)] = file_hash(source)
            added = call({"op": "photo-add", "session_id": sid, "base_revision": revision, "path": str(source),
                "user_provided": True, "authorization_basis": "全合成开发验证", "label": f"合成图{index}",
                "location": "合成位置，无真实坐标", "capture_time": "不清楚", "direction": "不清楚"})
            revision, photo = added["session_revision"], added["photo"]
            photo_paths.append(store / photo["relative_path"])
            shown = call({"op": "photo-show", "session_id": sid, "photo_id": photo["id"]})
            assert Path(shown["path"]).is_file() and photo["status"] == "registered_not_viewed"
            observed = call({"op": "photo-observe", "session_id": sid, "base_revision": revision,
                "photo_id": photo["id"], "viewed": True, "viewer": "synthetic-test-attestation",
                "observations": [{"field": "other", "state": "known", "value": "合成图中可见灰色矩形和深色斜线",
                    "region": "图片中央", "limitation": "仅为合成图形，不含真实病害，无法判断工程尺寸或隐蔽状态"}]})
            revision = observed["session_revision"]
        alternative = {"label": "先核查表面及既有维修资料", "purpose": "区分外观现象与已有维修位置关系",
            "status": "insufficient_evidence", "conditions": "需有可核实的位置和维修记录，由相应专业确定下一步调查范围",
            "evidence_fact_ids": [], "missing_evidence": ["真实现场资料", "结构及维修记录"],
            "advantages": "先利用已有资料，有助于确定调查重点；效果未经现场验证", "limitations": "外观不能证明病害止于表层，不据此选定施工方案",
            "next_step": "整理已有记录交相应专业核查"}
        answer = {"analysis_profile": "pavement-distress-v1", "analysis_context": {
            "surface_type": "不清楚，仅有合成描述", "distribution": "真实位置与分布未核实", "depth_status": "无检测资料，层位未知"},
            "summary": "本文件为全合成开发样例。当前只能组织调查问题，不能确认真实病因；先整理位置、变化和已有记录，再交相应专业核查。",
            "hypotheses": [], "next_checks": [{"action": "收集已有位置、巡查及维修资料", "purpose": "确定核查对象和信息缺口",
                "different_results": "资料一致则核对对应条件；存在冲突则先定位纠正；无法取得仍保留未知"}],
            "claims": [], "options": [], "handoff": ["携带已知描述、图片来源和未知事项，交管养单位协调专业核查"],
            "limitations": ["仅验证流程及文档排版，全部素材为合成，不作为现场诊断、检测方案或施工依据"],
            "deliverables": {
                "field_advice": {"priority_actions": ["先确认管养单位已知的通行与人员暴露情况，未落实的事项保持待办"],
                    "pause_conditions": ["不能确认作业安全条件时暂停靠近异常区域的作业，报告并安排专业核查"],
                    "handoff": ["向管养单位交接已有描述、照片来源及关键未知项"]},
                "inspection_brief": {"objective": ["请协助明确需要补充的资料及调查范围"], "scope": ["拟核查对象的准确位置、层位和范围尚待确认"],
                    "available_materials": ["已有全合成描述与两张合成图片，无真实检测记录"],
                    "requested_work": ["拟请相应专业核定调查项目，并说明各项目拟解决的疑问；不预设方法或数量"],
                    "constraints": ["通行、进入条件及实施前提均未核实"], "expected_outputs": ["提供定位记录、已核实事实、剩余缺口及后续建议"]},
                "department_reply": {"conditional_conclusion": ["现有合成资料不足以判断实际工程状态，建议先补充调查资料后再研究具体处理方向"],
                    "basis_and_gaps": ["仅有合成描述和图形，未取得适用规范原文核验及真实检测证据"],
                    "verification_checklist": ["核查对象位置、当前变化、既有结构及维修资料，并说明来源"],
                    "coordination": ["建议由管养单位协调相关专业核查，反馈实际结果后更新意见"]}},
            "comparison": {"question": "在证据不足时，下一步可以研究哪些调查方向", "decision_basis": "先解决资料缺口；资料支持某一方向时再核对适用条件，不自动选出施工方案",
                "alternatives": [alternative, {**alternative, "label": "再核查隐蔽状态的调查需求", "purpose": "请专业人员判断是否需要进一步调查",
                    "conditions": "已有资料提示可能涉及其他层位或设施时，由相应专业核定调查范围和实施条件"}]}}
        revision = call({"op": "answer", "session_id": sid, "base_revision": revision, "answer": answer})["session_revision"]
        documents = []
        for kind in ["consultation", *DELIVERIES]:
            result = call({"op": "export", "session_id": sid, "user_requested": True, "format": "docx", "kind": kind, "include_photos": True})
            with ZipFile(result["docx"]) as archive:
                assert len([name for name in archive.namelist() if name.startswith("word/media/")]) == 2
                assert "证据不足" in archive.read("word/document.xml").decode()
            if qa_dir:
                target = qa_dir / f"{kind}.docx"
                shutil.copy2(result["docx"], target)
                documents.append(str(target))
        call({"op": "finish", "session_id": sid, "base_revision": revision})
        assert all(not path.exists() for path in photo_paths)
        assert all(file_hash(Path(path)) == sha for path, sha in originals.items())
        assert call({"op": "sessions"}) == []
    print(json.dumps({"status": "media_delivery_checks_passed", "word_types_verified": 4, "photos_verified": 2,
        "originals_unchanged": True, "temporary_copies_cleaned": True, "artifacts_retained": bool(qa_dir),
        "qa_documents": documents, "visual_review": "requires_actual_render_and_view", "engineering_review": "not_performed"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
