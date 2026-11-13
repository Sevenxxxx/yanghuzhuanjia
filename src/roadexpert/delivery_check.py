"""Deterministic delivery checks plus explicit items for host semantic review.

No search, model calls, engineering approval or automatic correction.
"""
import re
from pathlib import Path

from .advice import DELIVERIES, validate_deliveries
from .comparison import validate_comparison
from .photos import checked_photo, validate_photo_fact
from .specs import file_hash
from .storage import RoadError, canonical, digest, load_json

MEASUREMENT = re.compile(r"(?<![0-9A-Za-z.])\d+(?:\.\d+)?\s*(?:毫米|厘米|千米|米|小时|分钟|天|摄氏度|mm|cm|km|m|MPa|kPa|kN|%|％|℃|度)(?![A-Za-z])", re.I)
STANDARD = re.compile(r"(?:JTG(?:/T)?|CJJ(?:/T)?|GB(?:/T)?|JT/T)\s*[A-Z]?\s*\d+(?:\.\d+)?\s*[-—–－]\s*\d{4}", re.I)
CLAUSE = re.compile(r"(?:第\s*)?\d+\.\d+(?:\.\d+)?\s*条")
CITATION_NAME = re.compile(r"《[^》]{2,60}》")


def citation_name_missing(text):
    """每个标准号**首次**出现时是否带了《规范名称》。

    只查首次出现：写清一次之后，后文用「同规范」或只写编号是正常的写法。
    """
    missing, seen = [], set()
    for token in STANDARD.finditer(text):
        key = normalized(token.group())
        if key in seen:
            continue
        seen.add(key)
        start = max(text.rfind("。", 0, token.start()),
                    text.rfind("；", 0, token.start()),
                    text.rfind("\n", 0, token.start())) + 1
        if not CITATION_NAME.search(text[max(0, start):token.start()]):
            missing.append(token.group())
    return missing
SKIP_KEYS = {"at", "based_on_turn", "photo_context", "risk_snapshot", "technical_review", "stale_after_turn", "analysis_profile", "status"}


def normalized(value):
    return re.sub(r"\s+", "", value).replace("—", "-").replace("–", "-").replace("－", "-").casefold()


def strings(value, path):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from strings(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in SKIP_KEYS and not key.endswith(("_ids", "_id")):
                yield from strings(item, f"{path}.{key}")


def check_delivery(app, data, kind="consultation", file_format="markdown", include_photos=False):
    if not isinstance(kind, str) or kind not in {"consultation", *DELIVERIES}:
        raise RoadError("交付类型无效")
    if not isinstance(file_format, str) or file_format not in {"markdown", "docx"} or type(include_photos) is not bool:
        raise RoadError("交付格式或附图参数无效")
    if include_photos and file_format != "docx":
        raise RoadError("嵌图仅支持Word")
    errors, warnings, dependencies = [], [], []
    def finding(target, code, location, message, excerpt=None):
        item = {"code": code, "location": location, "message": message}
        if excerpt:
            item["excerpt"] = excerpt[:180]
        target.append(item)
    def error(code, location, message):
        finding(errors, code, location, message)
    latest = data["answers"][-1] if data["answers"] else None
    facts = {f["id"]: f for f in app.active_facts(data)}
    if not latest:
        error("no_opinion", "answer", "尚未形成咨询意见，不能作为当前意见交付")
    elif (latest.get("stale_after_turn") or latest.get("based_on_turn") != data["turns"][-1]["id"] or
          latest.get("photo_context", 0) != data.get("photo_context", 0)):
        error("stale_opinion", "answer", "用户补充或照片资料变化后，旧意见尚未更新")
    answer = latest or {}
    if kind != "consultation" and kind not in answer.get("deliverables", {}):
        error("missing_delivery", "deliverables." + kind, "尚未形成所选交付内容")
    if latest:
        for key in ("summary", "limitations", "next_checks"):
            if not answer.get(key):
                error("missing_content", "answer." + key, "意见缺少摘要、判断边界或具体下一步")
        try:
            validate_deliveries(answer, app.validate_text)
            validate_comparison(answer, facts, app.validate_text)
        except (RoadError, TypeError, KeyError):
            error("invalid_structure", "answer", "交付内容或比较方向的字段与当前事实引用需修正")
    for i, hyp in enumerate(answer.get("hypotheses", [])):
        for key in ("support_fact_ids", "against_fact_ids"):
            for fid in hyp.get(key, []):
                fact = facts.get(fid)
                if not fact or fact["state"] != "known" or fact["kind"] == "system_hypothesis":
                    error("invalid_fact_reference", f"hypotheses[{i}].{key}", "引用了缺失、已纠正、未知或系统假设事实")
    for photo in data.get("photos", []):
        try:
            checked_photo(app.store, data, photo["id"])
            dependencies.append([photo["id"], photo["sha256"]])
        except (RoadError, OSError, KeyError):
            error("photo_changed", "photos", "照片副本缺失、变化或归属不符，需重新登记查看")
        if photo.get("status") == "registered_not_viewed":
            finding(warnings, "photo_not_viewed", "photos." + photo["id"], "照片尚无实际查看记录，不得据此声称已经看图分析")
    for fact in facts.values():
        if fact["kind"] == "photo_observation":
            try:
                validate_photo_fact(app.store, data, fact)
            except (RoadError, OSError, KeyError):
                error("photo_fact_unbound", "facts." + fact["id"], "图片观察无法对应已登记照片中的实际观察和状态")
    if include_photos and not data.get("photos"):
        error("no_photos", "include_photos", "要求附图但本次尚未登记照片")
    reviews = {r["id"]: r for r in data["reviews"]}
    source_quotes, standard_sources = [], []
    for i, claim in enumerate(answer.get("claims", [])):
        refs = claim.get("review_ids", [])
        if not refs:
            error("claim_without_review", f"claims[{i}]", "规范判断未绑定有效审阅")
        for rid in refs:
            review = reviews.get(rid)
            try:
                if (not review or not review["eligible"] or review["read_receipt_id"] not in data["evidence_ids"] or
                    review.get("based_on_turn") != data["turns"][-1]["id"] or
                    review.get("photo_context", 0) != data.get("photo_context", 0)):
                    raise RoadError("审阅不再适用")
                receipt = app.store.get_receipt(review["read_receipt_id"])
                page = receipt["payload"]
                if receipt["kind"] != "spec-read" or page.get("status") != "page_read" or not page.get("index_source_matches"):
                    raise RoadError("未完成可信回源")
                current_hash = file_hash(page["source_path"])
                dependencies.append([rid, current_hash])
                if current_hash != page["source_sha256"] or normalized(review["quote"]) not in normalized(page["raw_text"]):
                    raise RoadError("来源已变或摘录无法定位")
                if page.get("needs_visual"):
                    image = app.store.get_receipt(review.get("visual_receipt_id"))
                    payload = image["payload"]
                    if image["kind"] != "spec-render" or payload.get("read_receipt_id") != receipt["id"]:
                        raise RoadError("图片与原页不对应")
                    path = app.store.path(payload["relative_path"]) if payload.get("relative_path") else Path(payload["path"])
                    if file_hash(path) != payload["sha256"]:
                        raise RoadError("回源图片已变化")
                    dependencies.append([image["id"], payload["sha256"]])
                source_quotes.append(review["quote"])
                standard_sources.append(str(page.get("std_no", "")))
            except (RoadError, OSError, KeyError, TypeError):
                error("invalid_norm_source", f"claims[{i}].review_ids", "规范来源、原页图片或适用性审阅已失效，需重新核验")
    for i, ref in enumerate(answer.get("case_refs", [])):
        try:
            rid = ref["query_receipt_id"]
            if rid not in data["evidence_ids"]:
                raise RoadError("案例查询不属于本咨询")
            query = app.store.get_receipt(rid)
            if query["kind"] != "case-search":
                raise RoadError("无实际案例查询")
            matched = next(m for m in query["payload"]["matches"] if m["case_id"] == ref["case_id"])
            if matched.get("evidence_status") == "unverified_candidate":
                raise RoadError("候选案例未经人工审核，不能作为 case_refs 依据")
            case = matched["case"]
            current = app.cases.validate(load_json(app.cases._path("verified", ref["case_id"])), published=True)
            if digest(canonical(current)) != digest(canonical(case)):
                raise RoadError("案例已变化")
            dependencies.append([ref["case_id"], digest(canonical(current))])
        except (RoadError, OSError, KeyError, StopIteration):
            error("invalid_case", f"case_refs[{i}]", "引用案例已变化、撤回或不属于本次实际查询")
    selected = {"summary": answer.get("summary", ""), "claims": answer.get("claims", []),
                "comparison": answer.get("comparison"), "limitations": answer.get("limitations", [])}
    if kind == "consultation":
        selected = {**answer, "deliverables": answer.get("deliverables", {})}
    else:
        selected["deliverables"] = {kind: answer.get("deliverables", {}).get(kind, {})}
    segments = list(strings(selected, "answer"))
    factual_text = "\n".join(f["value"] for f in facts.values()
                             if f["state"] == "known" and f["kind"] in {"user_report", "report_record"})
    numeric_basis = {normalized(x.group()) for x in MEASUREMENT.finditer(factual_text + "\n" + "\n".join(source_quotes))}
    standards = {normalized(x.group()) for x in STANDARD.finditer("\n".join(standard_sources + source_quotes))}
    clauses = {normalized(x.group()).removeprefix("第") for x in CLAUSE.finditer("\n".join(source_quotes))}
    for location, value in segments:
        for token in MEASUREMENT.finditer(value):
            if normalized(token.group()) not in numeric_basis:
                finding(warnings, "quantity_source_unmatched", location, "该数值与单位未在当前已知文字事实或已审阅摘录中直接匹配，需核对来源和含义", token.group())
        for token in STANDARD.finditer(value):
            if normalized(token.group()) not in standards:
                finding(warnings, "standard_source_unmatched", location, "标准号未匹配本次有效规范审阅；不能仅凭正文声称已核实", token.group())
        for token in citation_name_missing(value):
            finding(warnings, "standard_citation_name_missing", location,
                    "该标准号首次出现时没有写规范名称，读者无法定位；应写成《规范全名》（编号）", token)
        for token in CLAUSE.finditer(value):
            if normalized(token.group()).removeprefix("第") not in clauses:
                finding(warnings, "clause_source_unmatched", location, "条号未在本次有效审阅摘录中直接匹配，需核对标准、版本和原页", token.group())
    # Only flag explicit selections of a named constrained option. Other
    # cross-section semantic contradictions are intentionally left to the host.
    for option in (answer.get("comparison") or {}).get("alternatives", []):
        if option.get("status") not in {"insufficient_evidence", "not_supported"}:
            continue
        for location, value in segments:
            if location.startswith("answer.comparison"):
                continue
            for sentence in re.split(r"[。；\n]", value):
                if option["label"] in sentence and re.search(r"直接采用|确定采用|建议采用|优先实施|最终选用|立即施工", sentence) and not re.search(r"不得|不能|不应|不宜|暂不|尚不能|并非", sentence):
                    finding(warnings, "comparison_selection_conflict", location, "正文选用了比较表中证据不足或当前不支持的方向，需核对是否矛盾", sentence)
    unique = {(x["code"], x["location"], x.get("excerpt")): x for x in warnings}
    warnings = list(unique.values())
    stamp = digest(canonical({"session_revision": data["revision"], "scope": [kind, file_format, include_photos], "answer": answer,
                              "facts": list(facts.values()), "photos": data.get("photos", []),
                              "dependencies": dependencies, "errors": errors, "warnings": warnings}))
    return {"status": "blocked" if errors else "automatic_checks_passed_manual_review_required",
            "session_revision": data["revision"], "content_sha256": stamp,
            "scope": {"kind": kind, "format": file_format, "include_photos": include_photos},
            "exportable": not errors, "errors": errors, "warnings": warnings,
            "manual_checks": ["核对摘要、所选正文、处理方向与比较表是否表达同一判断，特别是条件、否定和例外",
                              "逐项核对数值、单位、标准号及条文的对象、来源和适用条件；文字匹配不证明工程正确",
                              "核对图片观察、图注、拍摄信息及未知项；Word仍需渲染核对中文、图片和分页"],
            "notice": "程序只检查可确定的完整性、引用和文字线索；未发现问题不等于语义一致、排版合格或专业审核通过"}
