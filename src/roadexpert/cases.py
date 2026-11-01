"""Small JSON case catalogue. Import is not approval; search revalidates sources."""
from pathlib import Path

from .storage import RoadError, atomic_json, canonical, digest, load_json, now, safe_id, inside

ALIASES = {
    "塌陷": {"塌陷", "沉陷", "局部沉陷"},
    "沉降": {"沉降", "沉陷", "不均匀沉降"},
    "裂缝": {"裂缝", "开裂"},
    "排水": {"排水", "渗水", "积水", "冲刷"},
    "落石": {"落石", "掉块", "崩塌"},
}
DOMAINS = {"pavement", "slope", "bridge", "general"}


class Cases:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def _path(self, area, case_id):
        return inside(self.root, f"{area}/{safe_id(case_id)}.json")

    def validate(self, case, published=False):
        if not isinstance(case, dict):
            raise RoadError("案例必须为 JSON 对象")
        safe_id(case.get("case_id"))
        if case.get("domain") not in DOMAINS:
            raise RoadError("案例 domain 无效")
        if (case.get("is_synthetic") or case.get("source", {}).get("type") == "synthetic"
                or "synthetic" in str(case.get("status", ""))):
            raise RoadError("合成资料不能进入真实案例库")
        for field in ("title", "event_id"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                raise RoadError(f"案例缺少 {field}")
        if not isinstance(case.get("tags"), list) or not all(isinstance(x, str) for x in case["tags"]):
            raise RoadError("标签必须是字符串数组")
        source = case.get("source", {})
        if not source.get("url") and not source.get("internal_id"):
            raise RoadError("案例必须有原始来源或获准内部标识")
        if case.get("security_level") != "public_deidentified" or source.get("external_model_allowed") is not True:
            raise RoadError("本项目目录只接收获准的公开／脱敏可外发案例；受限资料留在仓库外")
        if published:
            if case.get("status") != "published" or case.get("source_grade") not in {"S1", "S2"}:
                raise RoadError("案例尚未达到可引用来源门槛")
            for field in ("cause_status", "treatment_status", "follow_up_status"):
                if not case.get(field):
                    raise RoadError(f"案例缺少证据分项 {field}")
            reviews = case.get("reviews", [])
            for area in ("source_facts", "professional_evidence", "rights_privacy"):
                if not any(r.get("scope") == area and r.get("decision") == "approved"
                           and r.get("reviewer") and r.get("reviewed_at")
                           and r.get("actor_kind") == "human" and r.get("basis") for r in reviews):
                    raise RoadError(f"缺少人工审核范围 {area}")
            if not case.get("allowed_claims") or not all(isinstance(x, str) and x for x in case["allowed_claims"]):
                raise RoadError("缺少明确可引用范围")
        return case

    def import_case(self, case):
        self.validate(case)
        path = self._path("incoming", case["case_id"])
        if path.exists() or self._path("verified", case["case_id"]).exists():
            raise RoadError("案例编号已存在；修订请保留历史，不能覆盖导入")
        case = dict(case, status="pending_review", revision=1, reviews=[], allowed_claims=[])
        atomic_json(path, case)
        return {"status": "pending_review", "case_id": case["case_id"]}

    def publish(self, case_id, reviews, allowed_claims, confirmation):
        if confirmation != "已取得相应专业人员和资料权限审核":
            raise RoadError("仅凭模型判断不能发布；需要人类审核确认及完整记录")
        case = load_json(self._path("incoming", case_id))
        case.update(status="published", reviews=reviews, allowed_claims=allowed_claims)
        self.validate(case, published=True)
        if self._path("verified", case_id).exists():
            raise RoadError("已存在可引用版本，不能覆盖")
        atomic_json(self._path("verified", case_id), case)
        self.rebuild()
        return {"status": "published", "case_id": case_id, "notice": "审核为外部人工声明，软件不独立证明审核身份或工程结论"}

    def withdraw(self, case_id, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise RoadError("必须说明撤回原因")
        path = self._path("verified", case_id)
        case = load_json(path)
        old_revision = case["revision"]
        history = self._path(f"history/{safe_id(case_id)}", str(old_revision))
        atomic_json(history, case)
        case.update(status="withdrawn", revision=old_revision + 1,
                    withdrawal={"reason": reason, "at": now()})
        atomic_json(path, case)
        self.rebuild()
        return {"status": "withdrawn", "case_id": case_id, "historical_consultations_unchanged": True}

    def rebuild(self):
        rows, excluded = [], []
        for path in sorted((self.root / "verified").glob("*.json")):
            try:
                case = self.validate(load_json(path), published=True)
                if path.stem != case["case_id"]:
                    raise RoadError("文件与案例编号不一致")
                rows.append({"case_id": case["case_id"], "revision": case["revision"],
                             "domain": case["domain"], "tags": case["tags"],
                             "event_id": case["event_id"], "sha256": digest(canonical(case))})
            except RoadError as exc:
                excluded.append({"file": path.name, "reason": str(exc)})
        index = {"schema_version": 1, "generated_at": now(), "cases": rows, "excluded": excluded}
        atomic_json(self.root / "index.json", index)
        return {"status": "rebuilt", "count": len(rows), "excluded": excluded}

    def search(self, domain, tags, excluded_events=None):
        if domain not in DOMAINS or not isinstance(tags, list) or not all(isinstance(x, str) for x in tags):
            raise RoadError("案例查询须使用有效领域和现象／条件标签数组")
        try:
            index = load_json(self.root / "index.json")
            if index.get("schema_version") != 1 or not isinstance(index.get("cases"), list):
                raise RoadError("索引结构无效")
            if not all(isinstance(row, dict) and all(k in row for k in ("case_id", "sha256"))
                       for row in index["cases"]):
                raise RoadError("案例索引行损坏")
        except RoadError as exc:
            return {"status": "index_unavailable", "complete": False, "matches": [], "error": str(exc)}
        expanded = set(tags)
        for group in ALIASES.values():
            if expanded & group:
                expanded |= group
        matches, unavailable = [], []
        indexed = {r["case_id"] for r in index["cases"]}
        actual = {p.stem for p in (self.root / "verified").glob("*.json")}
        excluded_names = {Path(e["file"]).stem for e in index.get("excluded", [])}
        if actual - indexed - excluded_names:
            unavailable.append("存在尚未索引的案例文件")
        for row in index["cases"]:
            try:
                case = self.validate(load_json(self._path("verified", row["case_id"])), published=True)
                if digest(canonical(case)) != row["sha256"]:
                    raise RoadError("索引与案例内容不一致，请重建")
                if case["event_id"] in (excluded_events or []):
                    continue
                shared = expanded & set(case["tags"])
                if case["domain"] == domain and shared:
                    matches.append({"case_id": case["case_id"], "revision": case["revision"],
                                    "score": len(shared), "matched_tags": sorted(shared), "case": case,
                                    "required_comparison": "主 Agent 仍须说明关键差异、缺项和本次借鉴范围"})
            except (RoadError, KeyError, TypeError) as exc:
                unavailable.append(f"{row.get('case_id')}: {exc}")
        matches.sort(key=lambda x: (-x["score"], x["case_id"]))
        return {"status": "search_incomplete" if unavailable else "matched" if matches else "no_qualified_cases",
                "complete": not unavailable, "matches": matches[:3], "unavailable": unavailable,
                "query_basis": {"domain": domain, "observation_tags": tags, "expanded_tags": sorted(expanded)},
                "notice": "相似现象不证明原因相同；标签查询不得只寻找支持初始猜测的案例"}
