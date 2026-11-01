"""Conditional comparisons, without automatic engineering ranking."""
from .storage import RoadError


def validate_comparison(answer, facts, validate_text):
    comparison = answer.get("comparison")
    if comparison is None:
        return
    if not isinstance(comparison, dict):
        raise RoadError("comparison 须为对象")
    for field in ("question", "decision_basis"):
        validate_text(comparison.get(field), "comparison." + field, 4000)
    options = comparison.get("alternatives")
    if not isinstance(options, list) or not 2 <= len(options) <= 5:
        raise RoadError("比较须包含2至5个有实际意义的方向；不足时在意见中说明")
    labels = set()
    for option in options:
        if not isinstance(option, dict):
            raise RoadError("比较方向须为对象")
        for field in ("label", "purpose", "conditions", "advantages", "limitations", "next_step"):
            validate_text(option.get(field), "comparison." + field, 4000)
        if option["label"] in labels:
            raise RoadError("不能重复比较同一方向")
        labels.add(option["label"])
        if option.get("status") not in {"insufficient_evidence", "conditional", "not_supported"}:
            raise RoadError("比较状态须为证据不足、有条件研究或当前不支持")
        refs = option.get("evidence_fact_ids")
        if not isinstance(refs, list) or any(not isinstance(x, str) or x not in facts or
                facts[x]["state"] != "known" or facts[x]["kind"] == "system_hypothesis" for x in refs):
            raise RoadError("比较依据须引用当前有效的已知事实")
        gaps = option.get("missing_evidence")
        if not isinstance(gaps, list) or (option["status"] == "insufficient_evidence" and not gaps):
            raise RoadError("证据不足时须列出具体缺口")
        for gap in gaps:
            validate_text(gap, "comparison.missing_evidence", 2000)
        if any(key in option for key in ("score", "probability", "approved", "recommended")):
            raise RoadError("不以自动评分、概率或批准标签代替条件判断")


def comparison_lines(answer, facts=()):
    comparison = answer.get("comparison")
    if not comparison:
        return []
    labels = {"insufficient_evidence": "证据不足", "conditional": "有条件研究", "not_supported": "当前不支持"}
    fact_values = {f["id"]: f["value"] for f in facts}
    lines = ["## 处理方向比较", comparison["question"], "",
             "| 方向 | 当前状态 | 适用前提 | 证据缺口 |", "| --- | --- | --- | --- |"]
    def cell(value):
        return value.replace("|", "／").replace("\n", " ").replace("\r", " ")
    for option in comparison["alternatives"]:
        lines.append("| " + " | ".join(cell(x) for x in (option["label"], labels[option["status"]],
                     option["conditions"], "；".join(option["missing_evidence"]) or "本项未另列，仍受总体判断边界限制")) + " |")
    for option in comparison["alternatives"]:
        evidence = "；".join(fact_values.get(fid, "依据需重新核对") for fid in option["evidence_fact_ids"]) or "暂无可引用的已知事实"
        lines += [f"### {option['label']}", f"- 目的：{option['purpose']}；当前事实依据：{evidence}。",
                  f"- 可能优势：{option['advantages']}", f"- 限制：{option['limitations']}", f"- 下一步：{option['next_step']}"]
    return lines + ["", "判断如何推进：" + comparison["decision_basis"],
                    "这是条件化比较，不是施工方案批准；具体方案与参数需相应专业核定。"]
