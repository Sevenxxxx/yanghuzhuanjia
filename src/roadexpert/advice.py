"""Output contracts only; these checks do not validate engineering reasoning."""
from .storage import RoadError
from .photos import photo_lines, fact_label
from .comparison import comparison_lines

PROFILES = {
    "pavement-subsidence-v1": ("pavement", {}),
    "pavement-distress-v1": ("pavement", {
        "surface_type": "路面类型", "distribution": "病害分布与位置", "depth_status": "涉及层位及未知情况"}),
    "slope-instability-v1": ("slope", {
        "slope_type": "边坡及支挡类型", "movement_scope": "局部与整体变化线索", "drainage_relation": "水路与变化关系"}),
    "bridge-culvert-v1": ("bridge", {
        "facility_type": "桥梁或涵洞及结构类型", "component_location": "构件与异常位置", "associated_changes": "伴随变化及历史对比"}),
}

# Each field is required, but may explicitly describe missing information.
DELIVERIES = {
    "field_advice": ("现场处置建议", {
        "priority_actions": "先做什么", "pause_conditions": "何时暂停现场作业并报告",
        "handoff": "下一步找谁及交接资料"}),
    "inspection_brief": ("检测委托要点", {
        "objective": "拟解决的工程疑问", "scope": "对象、部位和范围",
        "available_materials": "已有资料及来源", "requested_work": "拟请检测单位核定的调查项目及目的",
        "constraints": "现场条件及实施前提", "expected_outputs": "要求提交的成果及其用途"}),
    "department_reply": ("部门回复草稿", {
        "conditional_conclusion": "条件化意见", "basis_and_gaps": "依据及证据缺口",
        "verification_checklist": "待核查事项", "coordination": "建议协调事项"}),
}


def validate_deliveries(answer, validate_text):
    deliveries = answer.get("deliverables", {})
    if not isinstance(deliveries, dict) or any(k not in DELIVERIES for k in deliveries):
        raise RoadError("deliverables 须为已支持交付类型的对象")
    for kind, content in deliveries.items():
        fields = DELIVERIES[kind][1]
        if not isinstance(content, dict) or set(content) != set(fields):
            raise RoadError(f"{kind} 需要完整交付字段：{', '.join(fields)}")
        for field, value in content.items():
            if not isinstance(value, list) or not value:
                raise RoadError(f"{kind}.{field} 须为非空文本数组；未知应明确写出")
            for item in value:
                validate_text(item, f"{kind}.{field}", 4000)


def render_delivery(data, kind, active_facts, evidence_lines):
    if not isinstance(kind, str) or kind not in DELIVERIES:
        raise RoadError("不支持的交付类型")
    latest = data["answers"][-1] if data["answers"] else {}
    if not latest or latest.get("stale_after_turn"):
        raise RoadError("请先结合最新信息更新意见，再导出专项交付")
    content = latest.get("deliverables", {}).get(kind)
    if content is None:
        raise RoadError("尚未形成所选交付内容；先按实际资料补充 answer.deliverables")
    title, fields = DELIVERIES[kind]
    lines = [f"# {data['title']} · {title}", "", "AI 辅助草稿 · 未经工程专业审阅，需核对后使用", "",
             "## 当前重点", latest["summary"]]
    for field, label in fields.items():
        lines += ["", f"## {label}", *[f"- {x}" for x in content[field]]]
    lines += ["", f"## 风险筛查：{data['risk']['label']}", data["risk"]["notice"], data["risk"]["limitation"],
              "", "## 现有信息（保留来源）"]
    for fact in active_facts:
        lines.append(f"- [{fact_label(fact)}] {fact['value']}")
    if not active_facts:
        lines.append("尚无结构化事实，资料缺口需核查；不能视为现场已核实。")
    lines += ["", *comparison_lines(latest, active_facts), "", *photo_lines(data), "", *evidence_lines,
              "", "## 判断边界", *[f"- {x}" for x in latest["limitations"]]]
    return "\n".join(lines) + "\n"
