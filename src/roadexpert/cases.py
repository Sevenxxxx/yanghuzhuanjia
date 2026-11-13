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
AREAS = ("incoming", "verified", "rejected")


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

    def list_cases(self, area=None):
        if area is not None and area not in AREAS:
            raise RoadError("案例区域只允许 incoming、verified 或 rejected")
        rows, unavailable = [], []
        for name in ([area] if area else list(AREAS)):
            for path in sorted((self.root / name).glob("*.json")):
                try:
                    case = self.validate(load_json(path))
                    if path.stem != case["case_id"]:
                        raise RoadError("文件与案例编号不一致")
                    rows.append({"area": name, "case_id": case["case_id"],
                                 "revision": case.get("revision"), "title": case.get("title"),
                                 "domain": case.get("domain"), "status": case.get("status"),
                                 "source_grade": case.get("source_grade"),
                                 "review_status": case.get("review_status", "pending_review"),
                                 "tags": case.get("tags", []),
                                 "digest": case.get("digest"),
                                 "source": self.source_summary(case["case_id"]),
                                 "publisher": case.get("source", {}).get("publisher"),
                                 "url": case.get("source", {}).get("url")})
                except (RoadError, KeyError, TypeError) as exc:
                    unavailable.append({"area": name, "file": path.name, "reason": str(exc)})
        rows.sort(key=lambda row: (AREAS.index(row["area"]), row["case_id"]))
        return {"status": "listed" if not unavailable else "listing_incomplete",
                "counts": {name: sum(1 for row in rows if row["area"] == name) for name in AREAS},
                "cases": rows, "unavailable": unavailable}

    def show(self, case_id, area=None):
        if area is not None and area not in AREAS:
            raise RoadError("案例区域只允许 incoming、verified 或 rejected")
        for name in ([area] if area else list(AREAS)):
            path = self._path(name, case_id)
            if path.is_file():
                case = self.validate(load_json(path), published=name == "verified")
                return {"area": name, "case": case, "source": self.source_summary(case_id)}
        raise RoadError("未找到案例")

    def _source_folder(self, case_id):
        if not any(self._path(area, case_id).is_file() for area in ("incoming", "verified")):
            raise RoadError("案例不在候选或可引用库；拒绝／不存在案例不提供来源读取")
        return inside(self.root, f"sources/{safe_id(case_id)}")

    def source_meta(self, case_id):
        folder = self._source_folder(case_id)
        meta_path = folder / "source.json"
        if not meta_path.is_file():
            return {"case_id": case_id, "available": False, "access_level": "abstract_only",
                    "notice": "本地未存全文；只能使用案例库结构化摘要"}
        meta = load_json(meta_path)
        if meta.get("case_id") != case_id:
            raise RoadError("来源元数据与案例编号不一致")
        pdf_path = inside(folder, meta.get("file", "source.pdf"))
        if not pdf_path.is_file():
            raise RoadError("案例全文PDF缺失")
        if digest(pdf_path.read_bytes()) != meta.get("sha256_pdf"):
            raise RoadError("案例全文PDF已变化")
        text_path = inside(folder, meta.get("text_file", "source.txt"))
        if not text_path.is_file():
            raise RoadError("案例全文文本缺失")
        if digest(text_path.read_bytes()) != meta.get("sha256_text"):
            raise RoadError("案例全文文本已变化")
        return {"case_id": case_id, "available": True,
                "title": meta.get("title"), "source_url": meta.get("source_url"),
                "doi": meta.get("doi"), "access_level": meta.get("access_level"),
                "pages": meta.get("pages"), "chars": meta.get("chars"),
                "retrieved_at": meta.get("retrieved_at"), "rights_note": meta.get("rights_note"),
                "notice": "本地全文仅供检索定位；引用仍以来源原文和审核结论为准"}

    def source_read(self, case_id, page):
        meta = self.source_meta(case_id)
        if not meta.get("available"):
            raise RoadError("本地未存该案例全文，不能按页读取")
        folder = self._source_folder(case_id)
        pages = load_json(inside(folder, "pages.json"))
        if not isinstance(pages, list) or not pages:
            raise RoadError("案例分页文本缺失")
        if type(page) is not int or not 1 <= page <= len(pages):
            raise RoadError("页码超界")
        content = pages[page - 1].get("text", "")
        return {"case_id": case_id, "page": page, "pages": len(pages),
                "text": content[:12000], "truncated": len(content) > 12000,
                "access_level": meta["access_level"],
                "notice": "本页文本供定位；不等于已核对全文、图表或工程适用性"}

    def source_search(self, case_id, query, limit=5):
        if not isinstance(query, str) or not 1 <= len(query) <= 100:
            raise RoadError("来源检索词长度须为 1～100")
        if not isinstance(limit, int) or not 1 <= limit <= 10:
            raise RoadError("来源检索 limit 须为 1～10")
        meta = self.source_meta(case_id)
        if not meta.get("available"):
            raise RoadError("本地未存该案例全文，不能检索")
        folder = self._source_folder(case_id)
        pages = load_json(inside(folder, "pages.json"))
        hits = []
        for item in pages if isinstance(pages, list) else []:
            text = item.get("text", "")
            position = text.find(query)
            while position != -1 and len(hits) < limit:
                start, end = max(0, position - 80), min(len(text), position + len(query) + 80)
                hits.append({"page": item.get("page"), "excerpt": text[start:end]})
                position = text.find(query, position + len(query))
        return {"case_id": case_id, "query": query, "hits": hits,
                "truncated": len(hits) >= limit, "pages": meta.get("pages"),
                "access_level": meta.get("access_level"),
                "notice": "命中只说明字面出现；不等于原文支持当前工程判断"}

    def source_summary(self, case_id):
        try:
            meta = self.source_meta(case_id)
            return {"available": meta.get("available"), "access_level": meta.get("access_level")}
        except (RoadError, OSError):
            return None

    def reject(self, case_id, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise RoadError("必须说明拒绝原因")
        source = self._path("incoming", case_id)
        if not source.is_file():
            raise RoadError("只能拒绝候选库中的案例；已发布案例请使用撤回")
        case = self.validate(load_json(source))
        old = case.get("revision", 1)
        atomic_json(inside(self.root, f"history/{safe_id(case_id)}/{old}.json"), case)
        case.update(status="rejected", revision=old + 1,
                    rejection={"reason": reason, "at": now()})
        atomic_json(self._path("rejected", case_id), case)
        source.unlink()
        return {"status": "rejected", "case_id": case_id,
                "notice": "拒绝记录保留原因和旧版本；不会进入可引用案例库"}

    def _case_match(self, case, expanded, exact_tags, domain, excluded_events):
        if case["event_id"] in (excluded_events or []):
            return None
        shared = expanded & set(case["tags"])
        exact = exact_tags & set(case["tags"])
        if case["domain"] == domain and shared:
            return {"case_id": case["case_id"], "revision": case.get("revision"),
                    "score": len(shared), "exact_matches": len(exact),
                    "matched_tags": sorted(shared), "case": case,
                    "source": self.source_summary(case["case_id"]),
                    "required_comparison": "主 Agent 仍须说明关键差异、缺项和本次借鉴范围"}
        return None

    def _verified_matches(self, domain, expanded, exact_tags, excluded_events):
        try:
            index = load_json(self.root / "index.json")
            if index.get("schema_version") != 1 or not isinstance(index.get("cases"), list):
                raise RoadError("索引结构无效")
            if not all(isinstance(row, dict) and all(k in row for k in ("case_id", "sha256"))
                       for row in index["cases"]):
                raise RoadError("案例索引行损坏")
        except RoadError as exc:
            return [], [], str(exc)
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
                match = self._case_match(case, expanded, exact_tags, domain, excluded_events)
                if match:
                    match["evidence_status"] = "verified"
                    matches.append(match)
            except (RoadError, KeyError, TypeError) as exc:
                unavailable.append(f"{row.get('case_id')}: {exc}")
        matches.sort(key=lambda x: (-x["exact_matches"], -x["score"], x["case_id"]))
        return matches, unavailable, None

    def _candidate_matches(self, domain, expanded, exact_tags, excluded_events):
        matches, unavailable = [], []
        for path in sorted((self.root / "incoming").glob("*.json")):
            try:
                case = self.validate(load_json(path))
                if case.get("status") != "pending_review":
                    continue
                match = self._case_match(case, expanded, exact_tags, domain, excluded_events)
                if match:
                    match["evidence_status"] = "unverified_candidate"
                    matches.append(match)
            except (RoadError, KeyError, TypeError) as exc:
                unavailable.append(f"{path.stem}: {exc}")
        matches.sort(key=lambda x: (-x["exact_matches"], -x["score"], x["case_id"]))
        return matches[:3], unavailable

    def search(self, domain, tags, excluded_events=None, scope="verified"):
        if domain not in DOMAINS or not isinstance(tags, list) or not all(isinstance(x, str) for x in tags):
            raise RoadError("案例查询须使用有效领域和现象／条件标签数组")
        if scope not in {"verified", "candidate", "all"}:
            raise RoadError("case-search scope 只允许 verified、candidate 或 all")
        expanded = set(tags)
        exact_tags = set(tags)
        for group in ALIASES.values():
            if expanded & group:
                expanded |= group
        if scope == "candidate":
            matches, unavailable = self._candidate_matches(domain, expanded, exact_tags, excluded_events)
            return {"status": "search_incomplete" if unavailable else
                    "candidate_matches" if matches else "no_qualified_cases",
                    "complete": not unavailable, "scope": scope, "matches": matches,
                    "unavailable": unavailable,
                    "query_basis": {"domain": domain, "observation_tags": tags,
                                    "expanded_tags": sorted(expanded), "scope": scope},
                    "notice": "候选案例未经人工审核，只作背景线索；不得写入 case_refs，也不作为工程结论"}
        verified, verified_unavailable, index_error = self._verified_matches(domain, expanded, exact_tags, excluded_events)
        if scope == "verified":
            if index_error:
                return {"status": "index_unavailable", "complete": False, "scope": scope,
                        "matches": [], "error": index_error}
            return {"status": "search_incomplete" if verified_unavailable else
                    "matched" if verified else "no_qualified_cases",
                    "complete": not verified_unavailable, "scope": scope,
                    "matches": verified[:3], "unavailable": verified_unavailable,
                    "query_basis": {"domain": domain, "observation_tags": tags,
                                    "expanded_tags": sorted(expanded), "scope": scope},
                    "notice": "相似现象不证明原因相同；标签查询不得只寻找支持初始猜测的案例"}
        candidates, candidate_unavailable = self._candidate_matches(domain, expanded, exact_tags, excluded_events)
        matches = verified[:3] + candidates
        unavailable = list(verified_unavailable) + list(candidate_unavailable)
        if index_error:
            unavailable.insert(0, "索引: " + index_error)
        return {"status": "search_incomplete" if unavailable else
                "matched" if matches else "no_qualified_cases",
                "complete": not unavailable, "scope": scope, "matches": matches,
                "unavailable": unavailable,
                "query_basis": {"domain": domain, "observation_tags": tags,
                                "expanded_tags": sorted(expanded), "scope": scope},
                "notice": "已审核案例可引用；候选案例未审核，只作背景线索，不得写入 case_refs"}
