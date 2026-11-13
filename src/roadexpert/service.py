"""Consultation orchestration. Codex supplies reasoning; tools preserve and check evidence."""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from . import __version__
from .cases import Cases, DOMAINS
from .library import Library
from .advice import PROFILES, DELIVERIES, validate_deliveries, render_delivery
from .comparison import validate_comparison, comparison_lines
from .photos import prepare_photo, checked_photo, validate_photo_fact, photo_observation, photo_lines, fact_label, STATE_LABELS
from .word_export import export_word, runtime_path
from .delivery_check import check_delivery
from .risk import SIGNALS, SOURCE_KINDS, STATES, TIMES, assess, extract
from .specs import Specs, file_hash
from .storage import RoadError, Store, atomic_json, canonical, digest, load_json, now, inside, is_saved, TEMPORARY_HOURS

FACT_FIELDS = {"facility", "road_class", "location", "discovery_time", "progression",
               "traffic", "rain", "drainage", "component", "dimensions", "history", "other"}
QUESTIONS = {
    "facility": ("涉及哪类道路、设施或构件？", "确定规范和分析对象"),
    "progression": ("异常目前是否仍在扩大或加重？", "区分当前变化与发展情况未知"),
    "traffic": ("异常位置现在是否仍有车辆通行？", "识别当前通行暴露，停止通行也不代表已安全"),
    "location": ("异常具体位于道路或设施的哪个部位？", "区分成因和选择调查位置"),
    "component": ("异常涉及桥梁或涵洞的哪个构件、部位？", "避免把不同设施和构件问题混作同一机理"),
    "drainage": ("有无渗水、积水、堵塞或排水变化？", "判断是否需要核查水相关线索"),
    "rain": ("近期降雨及现象出现的先后关系如何？", "检验时间相关性，不能仅因雨后就确定原因"),
    "dimensions": ("有哪些可安全获取的范围、方向、尺寸记录？", "为后续专业核查提供定位，不要求冒险测量"),
    "road_class": ("这条道路属于什么类别或等级？", "核对适用标准"),
}
QUESTION_OPTIONS = {
    "traffic": ["仍有车辆通行", "已停止通行", "不清楚"],
    "progression": ["仍在扩大或加重", "根据已有观察未见扩大或加重", "不清楚"],
}
# What different answers would change. These are prompt-level defaults for
# briefing and legacy questions; question-ask requires the host to state a
# case-specific impact. No numeric probability or engineering threshold.
DECISION_IMPACT = {
    "facility": "明确设施类型后才能选择对应规范与检查方法；仍不明确时按最不利的设施类型先提示风险，不套用单一规范。",
    "progression": "若仍在扩大或加重，按发展性异常优先核查并提示现场管控；若明确未扩大，仍保留历史触发与复查要求，不能当作稳定；不清楚时保留未知并按可能发展处理。",
    "traffic": "若仍有车辆通行，先提示现场警示、管控与报告，不等待完整分析；若已停止通行，仍不能视为安全，转为核查异常对结构或路面的影响；不清楚时按仍有暴露处理。",
    "location": "位置决定成因候选、规范适用与调查手段；位置不明时先给条件化方向并列为待核查，不凭空推断。",
    "component": "构件不同，机理与检查方法不同；构件不明时先区分桥梁、涵洞及具体部位，避免把不同构件问题混作同一机理。",
    "drainage": "若有渗水、积水、堵塞或排水变化，优先核查水相关机理和设施；若无，仍不能排除隐蔽水路，保留调查项；不清楚时列为待核查。",
    "rain": "雨后出现只能说明时间关系；若现象与降雨、排水过程在时间或空间上对应，可提高水相关机理的核查优先级，但不能据此确认原因。",
    "dimensions": "可安全获取的范围、方向和尺寸用于定位与比较；没有测量时保留未知，不把目测估计写成实测，也不要求进入危险部位。",
    "road_class": "道路类别与等级影响规范适用和核查要求；不明时按实际管养单位适用规范核对，不默认公路或城市道路。",
}


def text(value, name, maximum=30000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RoadError(f"{name} 须为非空文本且不超过 {maximum} 字符")
    return value


def normalized(value):
    return re.sub(r"\s+", "", value)


class App:
    validate_text = staticmethod(text)

    def __init__(self, project, store=None, config=None):
        self.project = Path(project).resolve()
        cfg = load_json(config or self.project / "config.example.json")
        self.config = cfg
        if store is None:
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share"))
            key = digest(str(self.project).encode())[:12]
            store = base / "RoadMaintenanceExpert" / key
        store = Path(store).resolve()
        if store.is_relative_to(self.project):
            raise RoadError("咨询存储必须位于仓库外；测试也使用临时目录")
        self.store = Store(store)
        self.cases = Cases(self.project / "data/cases")
        self.library = Library(self.project / "data/library", self.store)

    def specs(self):
        return Specs(self.config["spec_skill"], self.store, self.config.get("tool_timeout_seconds", 45))

    def session(self, req):
        return self.store.read(req.get("session_id"))

    def readable(self, session):
        # Revocation applies to historical snapshots too, not just the latest raw turn.
        policy = self.store.read(session["id"])["privacy"] if session.get("id") else session["privacy"]
        return policy["external_model_allowed"] is True

    def public_view(self, session):
        if not self.readable(session):
            return {"id": session["id"], "revision": session["revision"],
                    "privacy": self.store.read(session["id"])["privacy"],
                    "status": "restricted_content_not_returned",
                    "notice": "原文和分析保留本地；未经用户明确许可，不向当前模型返回。请只用获准脱敏信息或本地导出。"}
        return session

    def start(self, req):
        domain = req.get("domain", "general")
        if domain not in DOMAINS:
            raise RoadError("domain 只允许 pavement、slope、bridge、general")
        privacy = req.get("privacy", {})
        if privacy.get("level", "restricted") not in {"restricted", "public", "synthetic"}:
            raise RoadError("资料分级无效")
        allowed = privacy.get("external_model_allowed", False)
        if type(allowed) is not bool or (allowed and not privacy.get("authorization_basis")):
            raise RoadError("允许外发须记录用户授权或公开／合成资料依据")
        if req.get("retention", "temporary") != "temporary":
            raise RoadError("新咨询默认临时；用户明确要求后使用 save 归档")
        data = {"schema_version": 1, "app_version": __version__, "retention": "temporary",
                "title": text(req.get("title", "未命名咨询"), "title", 200),
                "domain": domain, "privacy": {"level": privacy.get("level", "restricted"),
                "external_model_allowed": allowed, "authorization_basis": privacy.get("authorization_basis", "")},
                "host": req.get("host", {"client": "Codex", "model": "unknown", "effort": "unknown"}),
                "turns": [], "facts": [], "observations": [], "queries": [], "reviews": [],
                "answers": [], "question_log": [], "evidence_ids": [], "routine": req.get("routine") is True}
        self.add_turn_data(data, req)
        data = self.store.create(data)
        return {"session": self.public_view(data), "briefing": self.briefing(data) if allowed else None,
                "retention": "temporary", "notice": "仅保留当次工作状态，不进入历史列表；无需向用户展示内部编号。"}

    def save_session(self, req):
        if req.get("user_requested") is not True:
            raise RoadError("长期保存须由用户明确要求")
        basis = text(req.get("basis"), "save.basis", 1000)
        data = self.session(req)
        if req.get("base_revision") != data["revision"]:
            raise RoadError("保存须使用最新修订")
        if not is_saved(data):
            data.update(retention="saved", saved_at=now(), save_basis=basis)
            data = self.store.write(data, req["base_revision"])
        return {"session_id": data["id"], "session_revision": data["revision"], "retention": "saved",
                "notice": "已按用户要求保存；保密权限不因保存而改变。"}

    def add_turn_data(self, data, req):
        req = self.apply_question_responses(data, req)
        raw = text(req.get("text"), "text")
        turn_id = uuid.uuid4().hex
        data["turns"].append({"id": turn_id, "text": raw, "at": now(), "kind": "user_report",
                              "correction_reason": req.get("correction_reason", ""),
                              "question_responses": copy.deepcopy(req.get("question_responses", []))})
        for response in req.get("question_responses", []):
            q = next(q for q in data["question_log"] if q.get("id") == response["question_id"])
            q.update(status="answered", response=response["text"], response_state=response["state"],
                     answered_at=now(), answered_turn=turn_id)
        if "domain" in req:
            if req["domain"] not in DOMAINS:
                raise RoadError("领域无效")
            data["domain"] = req["domain"]
        extracted = extract(raw, turn_id)
        # Automated observations never supersede earlier triggers.
        existing = {o["id"]: o for o in data["observations"]}
        for item in req.get("observations", []):
            key, state, time = item.get("key"), item.get("state"), item.get("time", "current")
            kind = item.get("kind", "user_report")
            if key not in SIGNALS or state not in STATES or time not in TIMES or kind not in SOURCE_KINDS:
                raise RoadError("风险观察字段无效")
            basis = text(item.get("basis"), "observation.basis", 3000)
            if kind == "user_report" and normalized(basis) not in normalized(raw):
                raise RoadError("用户风险观察依据必须能定位到本轮原话")
            if kind == "photo_observation":
                origin = photo_observation(self.store, data, item.get("source_ref", ""))
                if basis != origin["value"] or time != origin["time"] or origin["state"] != "known":
                    raise RoadError("照片风险观察必须对应实际可见内容及时间，未知不能作触发依据")
            supersedes = item.get("supersedes", [])
            if supersedes:
                if req.get("user_correction") is not True or not req.get("correction_reason") or kind != "user_report":
                    raise RoadError("撤销旧触发需要用户纠正及理由，不能仅由模型降级")
                for old_id in supersedes:
                    if old_id not in existing or existing[old_id]["key"] != key:
                        raise RoadError("纠正必须对应已有同类观察")
            extracted.append({"id": uuid.uuid4().hex, "key": key, "state": state, "time": time,
                              "kind": kind, "origin": "host_structured", "text": basis,
                              "turn_id": turn_id, "supersedes": supersedes,
                              "correction_reason": req.get("correction_reason", "")})
        data["observations"].extend(extracted)
        prior_facts = {f["id"]: f for f in data["facts"]}
        for item in req.get("facts", []):
            if item.get("field") not in FACT_FIELDS or item.get("kind", "user_report") not in SOURCE_KINDS:
                raise RoadError("事实 field 或 kind 无效")
            if item.get("state", "known") not in {"known", "unknown", "unavailable", "unsafe", "contradictory"}:
                raise RoadError("事实状态无效")
            value = text(item.get("value"), "fact.value", 4000)
            basis = text(item.get("basis", value), "fact.basis", 4000)
            kind = item.get("kind", "user_report")
            if kind == "user_report" and normalized(basis) not in normalized(raw):
                raise RoadError("用户事实依据必须来自本轮原话；解释使用 system_hypothesis")
            if kind == "user_report" and normalized(value) not in normalized(raw):
                raise RoadError("用户事实 value 也须保留原话可定位内容，不借已有 basis 添加实测或推断")
            if kind in {"report_record", "photo_observation"} and not item.get("source_ref"):
                raise RoadError("照片／报告观察必须有实际来源定位")
            if kind == "photo_observation":
                validate_photo_fact(self.store, data, item)
            supersedes = item.get("supersedes", [])
            if any(x not in prior_facts or prior_facts[x]["field"] != item["field"] for x in supersedes):
                raise RoadError("纠正必须对应已有同类事实")
            if supersedes and (req.get("user_correction") is not True or not req.get("correction_reason")):
                raise RoadError("事实纠正需要用户说明理由")
            data["facts"].append({"id": uuid.uuid4().hex, "field": item["field"], "kind": kind,
                                  "value": value, "basis": basis, "source_ref": item.get("source_ref"),
                                  "state": item.get("state", "known"), "turn_id": turn_id,
                                  "supersedes": supersedes, "at": now()})
        # A direct chat reply can supply a field without a popup response object.
        supplied_now = {f["field"] for f in data["facts"] if f["turn_id"] == turn_id and f["kind"] != "system_hypothesis"}
        for q in data["question_log"]:
            if q.get("status") in {"pending", "unanswered"} and q["field"] in supplied_now:
                q.update(status="answered_in_turn", answered_turn=turn_id, answered_at=now())
        data["risk"] = assess(data["observations"], data["domain"], data.get("routine", False))
        if data["answers"]:
            data["answers"][-1]["stale_after_turn"] = turn_id

    def active_facts(self, data):
        replaced = {x for f in data["facts"] for x in f.get("supersedes", [])}
        return [f for f in data["facts"] if f["id"] not in replaced]

    def photo_op(self, req):
        self.require_allowed(req)
        data = self.session(req)
        op = req["op"]
        if op == "photo-show":
            photo, path = checked_photo(self.store, data, req.get("photo_id"))
            return {"photo": photo, "path": str(path), "notice": "宿主须实际查看此图片；路径返回不代表看图"}
        if req.get("base_revision") != data["revision"]:
            raise RoadError("照片操作需要最新 base_revision")
        if op == "photo-add":
            if len(data.get("photos", [])) >= 20:
                raise RoadError("单次咨询最多登记20张照片，请筛选关键照片")
            photo, raw = prepare_photo(req, text)
            photo["relative_path"] = f"sessions/{data['id']}/photos/{photo['id']}.png"
            path = self.store.path(photo["relative_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            photo["sha256"] = file_hash(path)
            data.setdefault("photos", []).append(photo)
        else:
            photo, path = checked_photo(self.store, data, req.get("photo_id"))
            if req.get("viewed") is not True:
                raise RoadError("实际查看照片后才可记录 viewed=true")
            viewer = text(req.get("viewer"), "photo.viewer", 200)
            notes = req.get("observations")
            if not isinstance(notes, list) or not 1 <= len(notes) <= 20 or not all(isinstance(n, dict) for n in notes):
                raise RoadError("须记录1至20项实际观察；看不清也应明确记录")
            for note in notes:
                if note.get("field") not in FACT_FIELDS or note.get("state") not in {"known", "unknown"}:
                    raise RoadError("照片观察字段或状态无效")
                if note.get("time", "unknown") not in {"current", "historical", "unknown"}:
                    raise RoadError("照片观察时间状态无效")
                if note.get("time", "unknown") != "unknown":
                    text(note.get("time_basis"), "photo.time_basis", 2000)
                obs = {"id": uuid.uuid4().hex, "field": note["field"], "state": note["state"],
                       "viewer": viewer, "at": now(), "time": note.get("time", "unknown"), "time_basis": note.get("time_basis", "未确认拍摄时间")}
                for key in ("value", "region", "limitation"):
                    obs[key] = text(note.get(key), "photo." + key, 3000)
                photo["observations"].append(obs)
                source_ref = f"photo:{photo['id']}:{obs['id']}"
                data["facts"].append({"id": uuid.uuid4().hex, "field": obs["field"], "value": obs["value"],
                    "basis": obs["value"], "kind": "photo_observation", "state": obs["state"], "source_ref": source_ref,
                    "at": now(), "turn_id": data["turns"][-1]["id"], "supersedes": []})
                if obs["state"] == "known":
                    for observation in extract(obs["value"], data["turns"][-1]["id"]):
                        observation.update(kind="photo_observation", time=obs["time"], source_ref=source_ref)
                        data["observations"].append(observation)
            photo["status"] = "viewed_by_attestation_not_professional_review"
            data["risk"] = assess(data["observations"], data["domain"], data.get("routine", False))
        data["photo_context"] = data.get("photo_context", 0) + 1
        if data["answers"]:
            # Reuse the existing stale guard without inventing a user turn.
            data["answers"][-1]["stale_after_turn"] = data["turns"][-1]["id"]
        try:
            data = self.store.write(data, req["base_revision"])
        except Exception:
            if op == "photo-add":
                self.store.remove_local(photo["relative_path"])
            raise
        return {"session_revision": data["revision"], "photo": photo,
                "risk": data["risk"], "notice": "照片元信息为用户提供，观察为查看者声明；不证明病因、尺寸或安全"}

    def apply_question_responses(self, data, req):
        responses = req.get("question_responses", [])
        if not isinstance(responses, list) or len(responses) > 3 or not all(isinstance(r, dict) for r in responses):
            raise RoadError("question_responses 须为最多 3 项的对象数组")
        if not responses:
            return req
        req = copy.deepcopy(req)
        seen = set()
        raw = text(req.get("text"), "text")
        for r in responses:
            qid = r.get("question_id")
            matches = [q for q in data["question_log"] if q.get("id") == qid]
            if len(matches) != 1 or qid in seen or matches[0].get("status") not in {"pending", "unanswered"}:
                raise RoadError("答复须对应本咨询未答问题，不能重复提交")
            seen.add(qid)
            q = matches[0]
            if r.get("submitted") is not True:
                raise RoadError("未提交的预选项或未回复不能记为用户答复")
            reply = text(r.get("text"), "question_response.text", 4000)
            if normalized(reply) not in normalized(raw):
                raise RoadError("问题答复必须保留在本轮用户原话中")
            state = r.get("state")
            if state not in {"known", "unknown", "unavailable", "unsafe", "contradictory"}:
                raise RoadError("问题答复需要明确事实状态")
            if normalized(reply) in {"不清楚", "不知道", "无法确定"} and state != "unknown":
                raise RoadError("不清楚须记录为 unknown，不能作为已知事实")
            if any(f.get("field") == q["field"] for f in req.get("facts", [])):
                raise RoadError("问题答复自动保存该字段，不能同时传入重复事实")
            req.setdefault("facts", []).append({"field": q["field"], "value": reply, "basis": reply,
                                                "kind": "user_report", "state": state})
        return req

    def ask_questions(self, req):
        self.require_allowed(req)
        data = self.session(req)
        fields = req.get("fields")
        if (not isinstance(fields, list) or not 1 <= len(fields) <= 3
                or not all(isinstance(f, str) and f in QUESTIONS for f in fields)
                or len(set(fields)) != len(fields)):
            raise RoadError("fields 须为 1～3 个不同的提问字段")
        if any(q.get("status") == "pending" for q in data["question_log"]):
            raise RoadError("已有待答问题；先恢复或关闭该轮，不重复发问")
        supplied = {f["field"] for f in self.active_facts(data) if f["kind"] != "system_hypothesis"}
        asked = {q["field"] for q in data["question_log"]}
        if supplied.intersection(fields) or asked.intersection(fields):
            raise RoadError("此项已提供或已问过，不重复追问")
        impacts = req.get("decision_impact")
        if not isinstance(impacts, dict) or set(impacts) != set(fields):
            raise RoadError("decision_impact 须逐一对应 fields，写明不同答案会改变什么；不能只写通用目的")
        questions = []
        for field in fields:
            impact = text(impacts[field], "decision_impact." + field, 4000)
            q = {"id": uuid.uuid4().hex, "field": field, "question": QUESTIONS[field][0],
                 "purpose": QUESTIONS[field][1], "decision_impact": impact,
                 "status": "pending", "at": now()}
            if field in QUESTION_OPTIONS:
                q["options"] = QUESTION_OPTIONS[field]
            questions.append(q)
        data["question_log"].extend(questions)
        data = self.store.write(data, req.get("base_revision"))
        return {"session_revision": data["revision"], "questions": copy.deepcopy(questions),
                "display_status": "host_must_prompt",
                "notice": "这里只保存待答问题及答案影响；宿主还须实际调用弹窗或正文提问。"}

    def close_questions(self, req):
        self.require_allowed(req)
        data = self.session(req)
        ids = req.get("question_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
            raise RoadError("question_ids 须为不重复的问题 ID 数组")
        pending = {q.get("id"): q for q in data["question_log"] if q.get("status") == "pending"}
        if any(qid not in pending for qid in ids):
            raise RoadError("只能关闭本咨询待答问题")
        reason = text(req.get("reason"), "reason", 1000)
        for qid in ids:
            pending[qid].update(status="unanswered", closed_at=now(), close_reason=reason)
        data = self.store.write(data, req.get("base_revision"))
        return {"session_revision": data["revision"], "status": "unanswered", "facts_added": 0}

    def briefing(self, data):
        facts = self.active_facts(data)
        supplied = {f["field"] for f in facts if f["kind"] != "system_hypothesis"}
        asked = {x["field"] for x in data["question_log"]}
        order = ["traffic", "facility", "progression", "component" if data["domain"] == "bridge" else "location",
                 "drainage", "rain", "dimensions", "road_class"]
        candidates = [x for x in order if x not in supplied and x not in asked]
        # Do not repeatedly ask after unavailable/unsafe facts; facts of those states count as supplied.
        pending = [q for q in data["question_log"] if q.get("status") == "pending"]
        questions = [{"field": x, "question": QUESTIONS[x][0], "purpose": QUESTIONS[x][1],
                      "decision_impact": DECISION_IMPACT[x]} for x in candidates[:3]] if not pending else []
        cards = []
        for path in sorted((self.project / "data/knowledge").glob("*.json")):
            card = load_json(path)
            if card.get("domain") in {data["domain"], "general"}:
                cards.append(card)
        return {"risk": data["risk"], "facts": facts, "next_questions": questions,
                "pending_questions": pending,
                "photos": copy.deepcopy(data.get("photos", [])),
                "question_stop": "没有可安全补充的信息时停止追问，输出调查和交接清单",
                "knowledge_cards": cards, "host_work": "结合原话与证据自主鉴别；卡片未专业审核，不直接当规范或确定原因",
                "case_query": {"domain": data["domain"], "tags": "使用观察现象和工程条件，不仅使用猜测的原因",
                               "scope": "默认 verified；需要背景线索时显式 scope=candidate，候选不得写入 case_refs"}}

    def resume_summary(self, data):
        """Derived view only: never rewrite history or infer completed field work."""
        answers = data["answers"]
        latest = answers[-1] if answers else None
        previous = answers[-2] if len(answers) > 1 else None
        baseline = latest.get("based_on_turn") if latest else None
        index = next((i for i, t in enumerate(data["turns"]) if t["id"] == baseline), -1)
        new_turns = data["turns"][index + 1:]
        old_labels = [h["label"] for h in previous.get("hypotheses", [])] if previous else []
        labels = [h["label"] for h in latest.get("hypotheses", [])] if latest else []
        replaced = {i for f in data["facts"] for i in f.get("supersedes", [])}
        supplied = {f["field"] for f in self.active_facts(data) if f["kind"] != "system_hypothesis"}
        unanswered = [q for q in data["question_log"] if q.get("status") == "unanswered"]
        unanswered += [{**q, "status": "legacy_unanswered"} for q in data["question_log"]
                       if "status" not in q and q["field"] not in supplied]
        return {
            "title": data["title"], "session_id": data["id"], "revision": data["revision"],
            "retention": data.get("retention", "saved"), "expires_at": data.get("expires_at"),
            "risk": data["risk"],
            "latest_opinion": ({"summary": latest["summary"], "at": latest["at"],
                                "stale": bool(latest.get("stale_after_turn")), "candidates": labels} if latest else None),
            "new_information": [{"id": t["id"], "text": t["text"], "at": t["at"],
                                 "correction_reason": t.get("correction_reason", "")} for t in new_turns],
            "photo_updates": (copy.deepcopy(data.get("photos", [])) if
                data.get("photo_context", 0) != (latest or {}).get("photo_context", 0) else []),
            "opinion_changes": ({"previous_summary": previous["summary"],
                                 "summary_changed": previous["summary"] != latest["summary"],
                                 "added_candidates": [x for x in labels if x not in old_labels],
                                 "removed_candidates": [x for x in old_labels if x not in labels],
                                 "notice": "仅比较已保存意见，不代表已查明或排除病因"} if previous else None),
            "corrected_facts": [f for f in data["facts"] if f["id"] in replaced],
            "information_gaps": [f for f in self.active_facts(data) if f["state"] != "known"],
            "pending_questions": [q for q in data["question_log"] if q.get("status") == "pending"],
            "unanswered_questions": unanswered,
            "follow_up_checks": copy.deepcopy(latest.get("next_checks", [])) if latest else [],
            "checks_status": "完成情况未记录；上次建议可能因新信息过时，须重新核对",
            "handoff": latest.get("handoff", []) if latest else [],
            "next_action": "先分析新增信息并更新意见" if latest and latest.get("stale_after_turn") else "核对待答问题与后续核查进展",
        }

    def turn(self, req):
        data = self.session(req)
        expected = req.get("base_revision")
        if expected != data["revision"]:
            raise RoadError("请提供最新 base_revision，防止覆盖另一轮修改")
        self.add_turn_data(data, req)
        data = self.store.write(data, expected)
        return {"session": self.public_view(data),
                "briefing": self.briefing(data) if self.readable(data) else None}

    def attach(self, req, receipt):
        if not req.get("session_id"):
            return None
        data = self.session(req)
        expected = req.get("base_revision")
        if expected != data["revision"]:
            raise RoadError("证据关联需要最新 base_revision")
        data["evidence_ids"].append(receipt["id"])
        data["queries"].append({"id": receipt["id"], "kind": receipt["kind"], "at": receipt["created_at"],
                                "status": receipt["payload"].get("status")})
        return self.store.write(data, expected)["revision"]

    def require_allowed(self, req):
        if req.get("session_id") and not self.readable(self.session(req)):
            raise RoadError("此咨询未获外部模型读取许可，禁止将关联的原文／查询结果返回当前模型")

    def spec_op(self, op, req):
        self.require_allowed(req)
        specs = self.specs()
        if op == "spec-list":
            result = specs.books(req.get("query", ""))
        elif op == "spec-search":
            result = specs.search(req.get("query"), req.get("book_id"), req.get("limit", 20))
        elif op in {"spec-toc", "spec-clause"}:
            result = specs.navigate(op[5:], req.get("book_id"), req.get("clause"))
        elif op == "spec-read":
            result = specs.read(req.get("book_id"), req.get("page"))
        elif op == "spec-render":
            result = specs.render(req.get("read_receipt_id"))
        else:
            raise RoadError("未允许的规范操作")
        receipt = self.store.receipt(op, result)
        revision = self.attach(req, receipt)
        return {"receipt": receipt, "session_revision": revision}

    def review(self, req):
        self.require_allowed(req)
        data = self.session(req)
        read_id = req.get("read_receipt_id")
        if read_id not in data["evidence_ids"]:
            raise RoadError("只能审阅已关联本咨询的回源记录")
        receipt = self.store.get_receipt(read_id)
        page = receipt["payload"]
        if receipt["kind"] != "spec-read" or page.get("status") != "page_read":
            raise RoadError("不能审阅未成功回源的记录")
        quote = text(req.get("quote"), "quote", 6000)
        if normalized(quote) not in normalized(page["raw_text"]):
            raise RoadError("摘录不能在原页定位")
        if req.get("applicability") not in {"applicable", "conditional", "not_applicable", "unknown"}:
            raise RoadError("适用性状态无效")
        note = text(req.get("applicability_note"), "applicability_note", 4000)
        scope = text(req.get("verification_scope"), "verification_scope", 4000)
        visual_id = req.get("visual_receipt_id")
        visual_ok = False
        if visual_id:
            image = self.store.get_receipt(visual_id)
            payload = image["payload"]
            if image["kind"] != "spec-render" or payload.get("read_receipt_id") != read_id:
                raise RoadError("图片与回源页不对应")
            image_path = self.store.path(payload["relative_path"]) if payload.get("relative_path") else Path(payload["path"])
            if file_hash(image_path) != payload["sha256"]:
                raise RoadError("核对图片已变化")
            text(req.get("visual_note"), "visual_note", 3000)
            if req.get("viewed") is not True:
                raise RoadError("必须实际查看后声明 viewed，并记录核对内容")
            visual_ok = True
        if file_hash(page["source_path"]) != page["source_sha256"]:
            raise RoadError("原文件变化，需重新回源")
        eligible = page["index_source_matches"] and (not page["needs_visual"] or visual_ok)
        supported = eligible and req["applicability"] in {"applicable", "conditional"}
        record = {"id": uuid.uuid4().hex, "read_receipt_id": read_id, "quote": quote,
                  "applicability": req["applicability"], "applicability_note": note,
                  "verification_scope": scope, "reviewer": text(req.get("reviewer"), "reviewer", 200),
                  "based_on_turn": data["turns"][-1]["id"],
                  "photo_context": data.get("photo_context", 0),
                  "reviewer_kind": "agent_or_user_attestation_not_professional_certification",
                  "at": now(), "visual_receipt_id": visual_id, "visual_note": req.get("visual_note"),
                  "eligible": bool(supported), "source_eligible": bool(eligible),
                  "notice": "程序核对定位和指纹；适用性／看图为具名审阅声明，不证明语义完整或工程专业审核"}
        data["reviews"].append(record)
        data = self.store.write(data, req.get("base_revision"))
        return {"review": record, "session_revision": data["revision"]}

    def answer(self, req):
        self.require_allowed(req)
        data = self.session(req)
        answer = copy.deepcopy(req.get("answer"))
        if not isinstance(answer, dict):
            raise RoadError("answer 必须为对象")
        profile = answer.get("analysis_profile")
        if profile is not None and (not isinstance(profile, str) or profile not in PROFILES or PROFILES[profile][0] != data["domain"]):
            raise RoadError("分析模板与咨询领域不匹配")
        if profile and PROFILES[profile][1]:
            context = answer.get("analysis_context")
            if not isinstance(context, dict) or set(context) != set(PROFILES[profile][1]):
                raise RoadError("须按分析模板记录 analysis_context；未知内容明确写出")
            for key in PROFILES[profile][1]:
                text(context[key], "analysis_context." + key, 3000)
        validate_deliveries(answer, text)
        for field in ("summary", "limitations"):
            if field == "summary":
                text(answer.get(field), field, 8000)
            elif not isinstance(answer.get(field), list) or not answer[field]:
                raise RoadError("必须列出判断边界")
        facts = {f["id"]: f for f in self.active_facts(data)}
        validate_comparison(answer, facts, text)
        for photo in data.get("photos", []):
            checked_photo(self.store, data, photo["id"])
        for hyp in answer.get("hypotheses", []):
            text(hyp.get("label"), "hypothesis.label", 2000)
            if "probability" in hyp:
                raise RoadError("不能生成病因百分比概率")
            for key in ("support_fact_ids", "against_fact_ids"):
                if any(x not in facts or facts[x]["kind"] == "system_hypothesis" or facts[x]["state"] != "known"
                       for x in hyp.get(key, [])):
                    raise RoadError("病因支持／反证包含未知或已纠正的事实")
            if not hyp.get("uncertainties"):
                raise RoadError("候选原因必须说明待核实项")
            if profile:
                text(hyp.get("reasoning"), "hypothesis.reasoning", 3000)
                text(hyp.get("discriminator"), "hypothesis.discriminator", 3000)
        reviews = {r["id"]: r for r in data["reviews"]}
        for claim in answer.get("claims", []):
            text(claim.get("text"), "claim.text", 4000)
            refs = claim.get("review_ids", [])
            if not refs or any(x not in reviews or not reviews[x]["eligible"] for x in refs):
                raise RoadError("有依据判断必须绑定适用且已回源核验的 review_ids；无依据内容写入假设／缺口")
            for rid in refs:
                if reviews[rid].get("based_on_turn") != data["turns"][-1]["id"]:
                    raise RoadError("用户信息已更新，需要对当前情境重新核对适用性，不能直接沿用旧审阅")
                if reviews[rid].get("photo_context", 0) != data.get("photo_context", 0):
                    raise RoadError("照片资料已变化，需要重新核对规范适用性")
                page = self.store.get_receipt(reviews[rid]["read_receipt_id"])["payload"]
                if file_hash(page["source_path"]) != page["source_sha256"]:
                    raise RoadError("引用源已变化，请重新核验")
        for ref in answer.get("case_refs", []):
            query_id = ref.get("query_receipt_id")
            if query_id not in data["evidence_ids"]:
                raise RoadError("案例必须来自本咨询的实际查询")
            query = self.store.get_receipt(query_id)
            if query["kind"] != "case-search":
                raise RoadError("案例引用不是案例查询记录")
            matched = [m for m in query["payload"].get("matches", []) if m["case_id"] == ref.get("case_id")]
            if not matched:
                raise RoadError("案例未在实际查询结果中")
            if matched[0].get("evidence_status") == "unverified_candidate" or query["payload"].get("scope") == "candidate":
                raise RoadError("候选案例未经人工审核，不能作为 case_refs 依据；先审核发布为 verified")
            current = self.cases.validate(load_json(self.cases._path("verified", ref["case_id"])), published=True)
            if digest(canonical(current)) != digest(canonical(matched[0]["case"])):
                raise RoadError("案例版本已变化，请重新查询")
            for key in ("similarities", "differences", "borrow_scope"):
                text(ref.get(key), "case_ref." + key, 3000)
        checks = answer.get("next_checks", [])
        if not checks:
            raise RoadError("必须给出具体下一步调查／资料准备")
        for item in checks:
            text(item.get("action"), "next_check.action", 3000)
            text(item.get("purpose"), "next_check.purpose", 3000)
            if profile:
                text(item.get("different_results"), "next_check.different_results", 3000)
        for item in answer.get("options", []):
            if not item.get("conditions") or not item.get("limitations"):
                raise RoadError("处理方向必须说明条件和限制")
        blob = json.dumps(answer, ensure_ascii=False)
        if re.search(r"可(?:以)?恢复通行|可以解除警戒|保证结构安全|确定无需上报|100%解决", blob):
            raise RoadError("咨询不得签发恢复通行、安全保证或确定性处治指令")
        for q in answer.get("questions", []):
            field = q.get("field")
            if field not in QUESTIONS:
                raise RoadError("问题字段无效")
            if any(f["field"] == field and f["kind"] != "system_hypothesis" for f in facts.values()):
                raise RoadError("此信息已经提供／明确无法获取，不重复追问；必要时说明新的区分问题")
            if any(x["field"] == field for x in data["question_log"]):
                raise RoadError("已问过该项；未知／无法获取时应停止循环")
            impact = q.get("decision_impact")
            impact = DECISION_IMPACT[field] if impact is None else text(impact, "question.decision_impact", 4000)
            q["decision_impact"] = impact
            data["question_log"].append({"field": field, "question": text(q.get("question"), "question", 1000),
                                         "purpose": text(q.get("purpose"), "purpose", 1000),
                                         "decision_impact": impact, "at": now()})
        if len(answer.get("questions", [])) > 3:
            raise RoadError("每轮最多追问 3 个关键问题")
        answer.update(at=now(), based_on_turn=data["turns"][-1]["id"],
                      photo_context=data.get("photo_context", 0),
                      risk_snapshot=copy.deepcopy(data["risk"]), id=uuid.uuid4().hex,
                      technical_review="not_professionally_reviewed")
        data["answers"].append(answer)
        data = self.store.write(data, req.get("base_revision"))
        return {"session_revision": data["revision"], "answer": answer,
                "risk": data["risk"], "notice": "原始事实、工具和规则状态自动加入记录；模型正文仍需读者审阅"}

    def render_evidence(self, data, latest):
        lines = ["## 规范依据与核验范围"]
        for claim in latest.get("claims", []):
            lines.append(f"- 判断：{claim['text']}")
            for rid in claim["review_ids"]:
                review = next(r for r in data["reviews"] if r["id"] == rid)
                page = self.store.get_receipt(review["read_receipt_id"])["payload"]
                current = Path(page["source_path"]).exists() and file_hash(page["source_path"]) == page["source_sha256"]
                page_label = "虚拟页" if page.get("virtual") else "PDF/物理页"
                lines += [f"  - {page['std_no']}，版本 {page['version']}，{page_label} {page['page']}；来源当前一致：{current}",
                          f"  - 原文：{review['quote']}", f"  - 适用性：{review['applicability']}，{review['applicability_note']}",
                          f"  - 实际范围：{review['verification_scope']}；审阅者：{review['reviewer']}"]
        if not latest.get("claims"):
            lines.append("暂无已绑定且完成相应核验的规范判断，不等于没有规范要求。")
        return lines

    def render_report(self, data, handoff=False):
        latest = data["answers"][-1] if data["answers"] else {}
        lines = [f"# {data['title']}", "", "AI 辅助咨询 · 未经工程专业审阅",
                 f"咨询 {data['id']} · 修订 {data['revision']}", "",
                 f"## 风险筛查：{data['risk']['label']}", data["risk"]["notice"],
                 data["risk"]["limitation"], "", "## 现有信息（保留来源）"]
        for f in self.active_facts(data):
            lines.append(f"- [{fact_label(f)}] {f['value']}" + ("" if handoff else f"（事实 {f['id']}）"))
        if not data["facts"]:
            lines.append("尚未结构化提取，用户原话见 JSON 中 turns；不能视为信息已核实。")
        lines += ["", "## 当前意见", latest.get("summary", "尚未保存 Agent 分析")]
        if latest.get("analysis_profile") in PROFILES:
            for key, label in PROFILES[latest["analysis_profile"]][1].items():
                lines.append(f"- {label}：{latest['analysis_context'][key]}")
        if latest.get("stale_after_turn"):
            lines.append("⚠ 新信息出现后，此意见已过时，必须重新分析；原意见仅用于追溯。")
        for hyp in latest.get("hypotheses", []):
            lines += [f"- 候选：{hyp['label']}", f"  待核实：{'；'.join(hyp['uncertainties'])}",
                      f"  支持事实：{hyp.get('support_fact_ids', [])}；反证事实：{hyp.get('against_fact_ids', [])}"]
            if hyp.get("reasoning"):
                lines.append(f"  分析与证据缺口：{hyp['reasoning']}")
            if hyp.get("discriminator"):
                lines.append(f"  区分线索：{hyp['discriminator']}")
        lines += ["", "## 信息缺口与追问"]
        for item in latest.get("questions", []):
            lines.append(f"- {item['question']}；目的：{item['purpose']}")
            if item.get("decision_impact"):
                lines.append(f"  答案影响：{item['decision_impact']}")
        for item in self.active_facts(data):
            if item["state"] != "known":
                lines.append(f"- {STATE_LABELS.get(item['state'], item['state'])}：{item['value']}")
        lines += ["", "## 下一步"]
        for check in latest.get("next_checks", []):
            lines.append(f"- {check['action']}；目的：{check['purpose']}")
            if check.get("different_results"):
                lines.append(f"  不同结果的下一步：{check['different_results']}")
        for kind, content in latest.get("deliverables", {}).items():
            title, fields = DELIVERIES[kind]
            lines += ["", f"## {title}（草稿）"]
            for key, label in fields.items():
                lines += [f"### {label}", *[f"- {x}" for x in content[key]]]
        recovery = self.resume_summary(data)
        lines += ["", "## 续办摘要"]
        for turn in recovery["new_information"]:
            lines.append(f"- 上次意见后补充：{turn['text']}")
        changes = recovery["opinion_changes"]
        if changes:
            lines += [f"- 前次意见：{changes['previous_summary']}",
                      f"- 候选新增：{'；'.join(changes['added_candidates']) or '无'}；候选移除：{'；'.join(changes['removed_candidates']) or '无'}",
                      f"- {changes['notice']}"]
        for q in recovery["pending_questions"] + recovery["unanswered_questions"]:
            lines.append(f"- [{q['status']}] {q['question']}")
            if q.get("decision_impact"):
                lines.append(f"  答案影响：{q['decision_impact']}")
        lines.append(f"- 核查进度：{recovery['checks_status']}")
        lines += ["", *self.render_evidence(data, latest)]
        lines += ["", "## 参考处理方向"]
        for option in latest.get("options", []):
            lines.append(f"- {option.get('approach', '')}；条件：{option['conditions']}；限制：{option['limitations']}")
        lines += ["", *comparison_lines(latest, self.active_facts(data)), "", *photo_lines(data)]
        lines += ["", "## 真实案例参考"]
        for ref in latest.get("case_refs", []):
            query = self.store.get_receipt(ref["query_receipt_id"])["payload"]
            case = next(m["case"] for m in query["matches"] if m["case_id"] == ref["case_id"])
            try:
                current = self.cases.validate(load_json(self.cases._path("verified", ref["case_id"])), published=True)
                state = "当前可引用" if digest(canonical(current)) == digest(canonical(case)) else "版本或内容已变化，需重新查询"
            except RoadError:
                state = "当前不可引用，保留历史记录"
            lines += [f"- {case['case_id']} r{case['revision']}，{state}；来源：{case['source']}",
                      f"  - 相同：{ref['similarities']}；不同：{ref['differences']}",
                      f"  - 本次借鉴：{ref['borrow_scope']}；审核范围：{case['allowed_claims']}",
                      f"  - 病因：{case['cause_status']}；处治：{case['treatment_status']}；后效：{case['follow_up_status']}"]
        if not latest.get("case_refs"):
            lines.append("尚未引用达到审核与适用要求的真实案例；不能虚构案例填充。")
        lines += ["", "## 专业交接", *[f"- {x}" for x in latest.get("handoff", [])],
                  "", "## 判断边界", *[f"- {x}" for x in latest.get("limitations", ["未完成咨询"])],
                 ]
        if not handoff:
            lines += ["", "## 工具与变更记录",
                  *[f"- {q['at']} {q['kind']} {q['status']}（{q['id']}）" for q in data["queries"]],
                  "", f"客户端：{json.dumps(data['host'], ensure_ascii=False)}",
                  "案例引用须另附经审核查询结果与差异；没有合格案例时不编造。",
                  "全部历史轮次、纠正、原始查询和先前意见保存在版本化 JSON 及 receipts 中。"]
        return "\n".join(lines) + "\n"

    def export(self, req):
        if req.get("user_requested") is not True:
            raise RoadError("仅在用户明确要求导出时生成文件")
        data = self.session(req)
        kind = req.get("kind", "consultation")
        file_format = req.get("format", "markdown")
        if not isinstance(file_format, str) or file_format not in {"markdown", "docx"}:
            raise RoadError("导出 format 仅支持 markdown 或 docx")
        if type(req.get("include_photos", False)) is not bool:
            raise RoadError("include_photos 须为布尔值")
        if file_format == "markdown" and req.get("include_photos"):
            raise RoadError("照片嵌入当前仅支持 Word，需明确请求 format=docx")
        history = req.get("history_only", False)
        if type(history) is not bool or (history and (kind != "consultation" or file_format != "markdown")):
            raise RoadError("历史记录仅支持完整Markdown／JSON，不作为专项或Word意见交付")
        check = check_delivery(self, data, kind, file_format, req.get("include_photos", False))
        if req.get("expected_check_sha256") is not None and req["expected_check_sha256"] != check["content_sha256"]:
            raise RoadError("检查后内容、来源或导出范围已变化，请重新运行交付检查")
        if not history and not check["exportable"]:
            raise RoadError("交付前检查未通过：" + "；".join(dict.fromkeys(e["message"] for e in check["errors"])) + "。可调用delivery-check查看定位。")
        for photo in data.get("photos", []):
            checked_photo(self.store, data, photo["id"])
        if file_format == "docx":
            latest = data["answers"][-1] if data["answers"] else {}
            if not latest or latest.get("stale_after_turn"):
                raise RoadError("导出 Word 前须先形成当前有效意见；关键缺口可以明确保留")
            runtime_path(self.config)
        if kind == "consultation":
            report_text = self.render_report(data, handoff=file_format == "docx")
        else:
            latest = data["answers"][-1] if data["answers"] else {}
            report_text = render_delivery(data, kind, self.active_facts(data), self.render_evidence(data, latest))
        if history:
            report_text = "历史记录 仅供追溯 不作为当前意见交付\n\n" + report_text
        returned_check = check if self.readable(data) else {
            "status": check["status"], "exportable": check["exportable"], "notice": "检查细节受当前资料权限限制，不向模型返回"}
        folder = self.store.path(f"exports/{data['id']}/r{data['revision']}")
        if file_format == "docx":
            images = []
            if req.get("include_photos"):
                for photo in data.get("photos", []):
                    _, path = checked_photo(self.store, data, photo["id"])
                    meta = photo["metadata"]
                    images.append({"path": str(path), "sha256": photo["sha256"], "label": photo["label"], "caption":
                        f"位置：{meta['location']}；拍摄时间：{meta['capture_time']}；方向：{meta['direction']}。用户提供，未经核实；图片不证明隐蔽病因。"})
            # Separate names avoid replacing a text-only export with one containing photos.
            report = folder / (f"{kind}-with-photos.docx" if req.get("include_photos") else f"{kind}.docx")
            export_word({"title": data["title"], "report": report_text, "images": images}, report, self.config)
            return {"status": "exported_locally", "kind": kind, "docx": str(report),
                    "delivery_check": returned_check,
                    "external_model_allowed": self.readable(data), "visual_review": "pending_actual_render_and_view"}
        folder.mkdir(parents=True, exist_ok=True)
        # Full history is exported only for the explicitly selected full report.
        payload = data if kind == "consultation" else {"kind": kind, "session_id": data["id"],
            "revision": data["revision"], "answer_id": data["answers"][-1]["id"], "report": report_text}
        name = "consultation-history" if history else kind
        atomic_json(folder / f"{name}.json", payload)
        report = folder / f"{name}.md"
        report.write_text(report_text, encoding="utf-8")
        return {"status": "historical_export_not_for_delivery" if history else "exported_locally", "kind": kind,
                "delivery_check": returned_check, "json": str(folder / f"{name}.json"), "markdown": str(report),
                "external_model_allowed": self.readable(data)}

    def dispatch(self, req):
        if not isinstance(req, dict):
            raise RoadError("请求须为 JSON 对象")
        op = req.get("op")
        cleanup = self.store.purge_expired()
        for field in ("facts", "observations"):
            if field in req and (not isinstance(req[field], list)
                                 or not all(isinstance(x, dict) for x in req[field])):
                raise RoadError(f"{field} 必须是对象数组")
        for field in ("privacy", "host"):
            if field in req and not isinstance(req[field], dict):
                raise RoadError(f"{field} 必须是对象")
        if op == "start":
            return self.start(req)
        if op == "save":
            return self.save_session(req)
        if op == "finish":
            data = self.session(req)
            if req.get("base_revision") != data["revision"]:
                raise RoadError("结束咨询须使用最新修订")
            if is_saved(data):
                return {"status": "saved_consultation_retained"}
            self.store.discard_temporary(data["id"], expected=req.get("base_revision"))
            return {"status": "temporary_consultation_removed"}
        if op == "cleanup":
            return cleanup
        if op == "turn":
            return self.turn(req)
        if op in {"photo-add", "photo-show", "photo-observe"}:
            return self.photo_op(req)
        if op == "question-ask":
            return self.ask_questions(req)
        if op == "question-close":
            return self.close_questions(req)
        if op in {"show", "resume"}:
            if op == "resume" and "revision" in req:
                raise RoadError("恢复使用最新修订；旧版本用 show + revision 只读核查")
            data = self.store.read(req.get("session_id"), req.get("revision"))
            return {"session": self.public_view(data), "briefing": self.briefing(data) if self.readable(data) else None,
                    "resume_summary": self.resume_summary(data) if self.readable(data) else None,
                    "historical_read_only": "revision" in req}
        if op == "sessions":
            # Do not leak titles for restricted records.
            return [{"id": x["id"], "revision": x["revision"], "updated_at": x["updated_at"],
                     **({"title": x["title"]} if x["privacy"]["external_model_allowed"] is True else {})}
                    for x in sorted(self.store.list_sessions(), key=lambda x: x["updated_at"], reverse=True)
                    if x["retention"] == "saved"]
        if op == "answer":
            return self.answer(req)
        if op == "permission":
            data = self.session(req)
            action = req.get("action")
            if action not in {"grant", "revoke"}:
                raise RoadError("许可操作只允许 grant 或 revoke")
            if action == "grant" and req.get("human_confirmation") != "用户明确允许当前模型读取此咨询及历史资料":
                raise RoadError("读取许可需真实用户明确授予，Agent 不得自行推定")
            basis = text(req.get("basis"), "permission.basis", 4000)
            data["privacy"] = {**data["privacy"], "external_model_allowed": action == "grant",
                               "authorization_basis": basis, "changed_at": now()}
            data = self.store.write(data, req.get("base_revision"))
            return {"session_id": data["id"], "session_revision": data["revision"], "privacy": data["privacy"],
                    "notice": "记录用户授权声明，不自动联网传输；授权范围由实际用户决定"}
        if op == "evidence-review":
            return self.review(req)
        if op in {"spec-list", "spec-search", "spec-toc", "spec-clause", "spec-read", "spec-render"}:
            return self.spec_op(op, req)
        if op == "delivery-check":
            self.require_allowed(req)
            return check_delivery(self, self.session(req), req.get("kind", "consultation"),
                                  req.get("format", "markdown"), req.get("include_photos", False))
        if op == "export":
            with self.store.lock(req.get("session_id")):
                return self.export(req)
        if op == "library-add":
            return self.library.add(req)
        if op == "library-list":
            return self.library.list(req.get("type"), req.get("topic"), req.get("domain"))
        if op == "library-source":
            return self.library.source(req.get("library_id"))
        if op == "library-toc":
            return self.library.toc(req.get("library_id"))
        if op == "library-read":
            return self.library.read(req.get("library_id"), req.get("page"))
        if op == "library-search":
            return self.library.search(req.get("query"), req.get("type"), req.get("topic"), req.get("limit", 5))
        if op == "library-render":
            return self.library.render(req.get("library_id"), req.get("page"))
        if op == "library-rebuild":
            return self.library.rebuild()
        if op == "case-search":
            self.require_allowed(req)
            result = self.cases.search(req.get("domain", "general"), req.get("tags", []),
                                       req.get("excluded_events"), req.get("scope", "verified"))
            receipt = self.store.receipt(op, result)
            return {"receipt": receipt, "session_revision": self.attach(req, receipt)}
        if op == "case-list":
            return self.cases.list_cases(req.get("area"))
        if op == "case-show":
            return self.cases.show(req.get("case_id"), req.get("area"))
        if op == "case-source":
            return self.cases.source_meta(req.get("case_id"))
        if op == "case-source-read":
            return self.cases.source_read(req.get("case_id"), req.get("page"))
        if op == "case-source-search":
            return self.cases.source_search(req.get("case_id"), req.get("query"), req.get("limit", 5))
        if op == "case-reject":
            return self.cases.reject(req.get("case_id"), req.get("reason"))
        if op == "case-import":
            return self.cases.import_case(req.get("case"))
        if op == "case-publish":
            return self.cases.publish(req.get("case_id"), req.get("reviews", []),
                                      req.get("allowed_claims", []), req.get("human_confirmation"))
        if op == "case-withdraw":
            return self.cases.withdraw(req.get("case_id"), req.get("reason"))
        if op == "case-rebuild":
            return self.cases.rebuild()
        if op == "doctor":
            specs = self.specs()
            return {"version": __version__, "python": __import__("sys").version.split()[0],
                    "project": str(self.project), "store": str(self.store.root),
                    "spec_skill_exists": (specs.skill / "scripts/spec.py").is_file(),
                    "shelf_books": len(specs.shelf()), "network_calls": "none",
                    "host_discovery": "read SKILL.md and execute tools; catalogue refresh not asserted",
                    "locks": [p.name for p in self.store.path("locks").glob("*.lock")],
                    "knowledge_review": "pending_professional_review",
                    "default_retention": "temporary", "temporary_hours": TEMPORARY_HOURS,
                    "cleanup": cleanup, "cleanup_schedule": "on_tool_call_or_explicit_finish"}
        if op == "backup":
            # Snapshot all restricted data locally; never copy into repository or network path.
            destination = Path(text(req.get("destination"), "destination", 2000)).resolve()
            if destination.is_relative_to(self.project) or destination.is_relative_to(self.store.root):
                raise RoadError("备份必须位于独立的本地仓库外目录")
            if str(destination).startswith("\\\\") or destination.exists():
                raise RoadError("只允许新的本地备份目录，不覆盖")
            if list(self.store.path("locks").glob("*.lock")):
                raise RoadError("有活跃写入或残留锁，先核实再备份")
            saved = [x for x in self.store.list_sessions() if x["retention"] == "saved"]
            if not saved:
                raise RoadError("没有已保存咨询可备份；临时状态不进入长期备份")
            paths = set()
            for row in saved:
                sid = row["id"]
                data = self.store.read(sid)
                for folder in (f"sessions/{sid}", f"exports/{sid}"):
                    for p in self.store.path(folder).rglob("*"):
                        if p.is_file():
                            paths.add(p.relative_to(self.store.root).as_posix())
                for rid in data["evidence_ids"]:
                    paths.add(f"receipts/{rid}.json")
                    receipt = self.store.get_receipt(rid)
                    if receipt["kind"] == "spec-render":
                        rel = receipt["payload"].get("relative_path")
                        if not rel:
                            legacy = Path(receipt["payload"]["path"])
                            rel = legacy.relative_to(self.store.root).as_posix()
                        if Path(rel).parts[0] != "images":
                            raise RoadError("备份图片路径无效")
                        paths.add(rel)
            original_files = {rel: file_hash(self.store.path(rel)) for rel in paths}
            destination.mkdir(parents=True)
            for rel in paths:
                output = inside(destination, rel)
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.store.path(rel), output)
            current_files = {rel: file_hash(self.store.path(rel)) for rel in paths}
            if (any(self.store.read(row["id"])["revision"] != row["revision"] for row in saved)
                    or original_files != current_files or any(
                    not (destination / relative).is_file() or file_hash(destination / relative) != sha
                    for relative, sha in original_files.items())):
                raise RoadError("备份期间数据变化，未确认快照一致；保留目标供核查，另选新目录重新备份")
            atomic_json(destination / "backup-manifest.json", {"at": now(), "files": original_files})
            return {"status": "backup_created", "path": str(destination),
                    "notice": "仅备份主动保存的咨询及关联资料，不包含临时会话；继承同等保密与外发限制"}
        if op == "backup-verify":
            manifest = load_json(self.store.path("backup-manifest.json"))
            for relative, sha in manifest["files"].items():
                target = self.store.path(relative)
                if not target.is_file() or file_hash(target) != sha:
                    raise RoadError(f"备份校验失败：{relative}")
            return {"status": "backup_verified", "files": len(manifest["files"]),
                    "notice": "仅证明所列快照文件一致；恢复后新写入会改变快照校验"}
        if op == "receipt":
            self.require_allowed(req)
            data = self.session(req)
            if req.get("receipt_id") not in data["evidence_ids"]:
                raise RoadError("只能恢复属于本咨询的工具记录")
            item = self.store.get_receipt(req["receipt_id"])
            if item["kind"] == "spec-render" and item["payload"].get("relative_path"):
                item["resolved_path"] = str(self.store.path(item["payload"]["relative_path"]))
            return item
        raise RoadError(f"未允许的操作：{op}")
