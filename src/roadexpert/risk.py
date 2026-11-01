"""Conservative screening, not an engineering risk rating or a safety clearance."""
import re
import uuid

SIGNALS = {
    "sudden_collapse": (r"突然(?:发生|出现)?(?:局部)?(?:塌陷|坍塌)|突发(?:塌陷|坍塌)|(?:路面|道路).{0,6}(?:塌陷|坍塌)", "突发或道路塌陷"),
    "progression": (r"继续扩大|持续扩大|仍在扩大|持续变形|仍在发展|不断扩大|持续滑移|裂缝.{0,5}(?:扩大|扩展|加宽)", "异常持续发展"),
    "active_fall": (r"持续落石|仍在落石|不断掉块|持续掉块|正在滑塌|正在塌方", "正在发生的落石或滑塌"),
    "bridge_deformation": (r"异常变形|明显下挠|明显变位|异常振动|异常摆动|支座脱空|梁体移位", "结构异常变形或变位"),
    "traffic_affected": (r"影响通行|威胁通行|落石.{0,4}车道|占据车道|危及行车|危及车辆", "通行受到威胁"),
}
STATES = {"present", "absent", "unknown", "contradictory"}
TIMES = {"current", "historical", "hypothetical", "unknown"}
SOURCE_KINDS = {"user_report", "photo_observation", "report_record", "system_hypothesis"}
NOTICE = "优先按本单位既有预案与职责报告、警示并安排专业核查；不要为补资料进入危险区域。AI 不作恢复通行或解除警戒指令。"


def extract(text, turn_id):
    """Hints only. Keep exact span. Structured host extraction complements these rules."""
    out = []
    for clause in re.split(r"[，。；！\n,;!]", text):
        for key, (pattern, _) in SIGNALS.items():
            for match in re.finditer(pattern, clause):
                prefix = clause[max(0, match.start() - 16):match.start()]
                suffix = clause[match.end():match.end() + 10]
                context = prefix + match.group()
                state_prefix = prefix + re.split(r"塌陷|坍塌|扩大|变形|落石|掉块|滑移|通行|车道|行车|车辆",
                                                match.group(), maxsplit=1)[0]
                time = "current"
                if re.search(r"如果|假如|假设|假定|培训题|假想", context):
                    time = "hypothetical"
                elif re.search(r"去年|以前|过去|曾经|当时|历史上", context) and not re.search(r"现在|目前|今天|仍", context):
                    time = "historical"
                unknown = r"不清楚|不知道|不确定|不详|没提|未提|是否|不能排除|无法排除"
                if re.search(unknown, state_prefix) or re.search(r"不清楚|不知道|不确定|不详|未知", suffix):
                    state = "unknown"
                elif re.search(r"(?:没有|未见|并未|尚未|未|无|没|不再)(?:发现|发生|出现|存在|观察到|明显|发生过|继续|持续|异常|影响|路面|道路|的)*\s*$", state_prefix):
                    state = "absent"
                else:
                    state = "present"
                out.append({"id": uuid.uuid4().hex, "key": key, "state": state, "time": time,
                            "kind": "user_report", "origin": "text_rule_hint", "turn_id": turn_id,
                            "text": clause.strip(), "span": match.group(), "supersedes": []})
    return out


def assess(observations, domain, routine=False):
    superseded = {x for o in observations for x in o.get("supersedes", [])}
    active = [o for o in observations if o["id"] not in superseded and o["time"] == "current"
              and o["kind"] != "system_hypothesis"]
    conflicts = []
    for key in SIGNALS:
        states = {o["state"] for o in active if o["key"] == key}
        if "contradictory" in states or {"present", "absent"} <= states:
            conflicts.append(key)
    urgent = [o for o in active if o["state"] == "present"]
    relevant = {"bridge": {"progression", "bridge_deformation", "traffic_affected"},
                "pavement": {"sudden_collapse", "progression", "traffic_affected"},
                "slope": {"progression", "active_fall", "traffic_affected"}}.get(domain, set(SIGNALS))
    unknown = [key for key in SIGNALS if key in relevant and not any(
        o["key"] == key and o["state"] in {"present", "absent"} for o in active)]
    if urgent:
        status = "attention"
    elif unknown or conflicts:
        status = "undetermined"
    elif domain == "general":
        status = "undetermined"
    elif routine:
        status = "ordinary"
    else:
        status = "investigate"
    return {"status": status, "label": {"attention": "需立即关注的潜在高风险",
            "undetermined": "尚不能判断", "investigate": "需进一步调查", "ordinary": "普通咨询（非安全评估）"}[status],
            "trigger_ids": [o["id"] for o in urgent], "conflicts": conflicts,
            "unknown_keys": unknown, "notice": NOTICE if urgent else
            "未发现明确触发不等于已排除危险；请补关键条件，不能凭此解除现场控制。",
            "rule_version": "0.1.0-draft", "professional_review": "pending",
            "limitation": "规则为未获专业人员审阅的无数值初筛；文字抽取仅为线索，不能保证识别所有征兆。"}
