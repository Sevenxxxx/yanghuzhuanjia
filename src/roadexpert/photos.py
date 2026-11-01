"""Controlled photo intake; the host must actually view before attesting observations."""
import hashlib
import io
import uuid
from pathlib import Path

from .storage import RoadError, now
from .specs import file_hash

KIND_LABELS = {"user_report": "用户陈述", "photo_observation": "图片观察", "report_record": "报告记载", "system_hypothesis": "系统假设"}
STATE_LABELS = {"known": "已提供", "unknown": "不清楚", "unavailable": "无法取得", "unsafe": "无法安全取得", "contradictory": "存在冲突"}


def fact_label(fact):
    return f"{KIND_LABELS.get(fact['kind'], fact['kind'])}／{STATE_LABELS.get(fact['state'], fact['state'])}"


def prepare_photo(req, validate_text):
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RoadError("照片处理需要本机Pillow环境；不会自动安装或上传") from exc
    if req.get("user_provided") is not True:
        raise RoadError("只能登记用户明确提供并允许处理的照片")
    basis = validate_text(req.get("authorization_basis"), "photo.authorization_basis", 2000)
    source = Path(validate_text(req.get("path"), "photo.path", 2000))
    if not source.is_absolute() or str(source).startswith("\\\\") or not source.is_file():
        raise RoadError("照片须为已获准的本机绝对路径文件")
    if source.stat().st_size > 20 * 1024 * 1024:
        raise RoadError("单张照片不得超过20MB")
    raw = source.read_bytes()
    if len(raw) > 20 * 1024 * 1024:
        raise RoadError("单张照片不得超过20MB")
    try:
        with Image.open(io.BytesIO(raw)) as original:
            if original.format not in {"JPEG", "PNG", "WEBP"} or original.width * original.height > 25_000_000:
                raise RoadError("仅支持不超过2500万像素的 JPEG、PNG、WEBP")
            original.load()
            image = ImageOps.exif_transpose(original).convert("RGBA")
            clean = Image.new("RGB", image.size, "white")
            clean.paste(image, mask=image.getchannel("A"))
            output = io.BytesIO()
            clean.save(output, format="PNG")  # No EXIF/GPS or arbitrary source metadata.
    except (OSError, Image.DecompressionBombError) as exc:
        raise RoadError("无法解码照片") from exc
    metadata = {}
    for key in ("location", "capture_time", "direction"):
        metadata[key] = validate_text(req.get(key, "不清楚"), "photo." + key, 1000)
    return {"id": uuid.uuid4().hex, "label": validate_text(req.get("label", source.stem), "photo.label", 200),
            "metadata": metadata, "metadata_kind": "user_supplied_not_verified", "authorization_basis": basis,
            "source_sha256": hashlib.sha256(raw).hexdigest(), "at": now(), "width": clean.width,
            "height": clean.height, "observations": [], "status": "registered_not_viewed"}, output.getvalue()


def checked_photo(store, data, photo_id):
    rows = [p for p in data.get("photos", []) if p["id"] == photo_id]
    if len(rows) != 1:
        raise RoadError("照片不属于本咨询")
    photo = rows[0]
    expected = f"sessions/{data['id']}/photos/{photo['id']}.png"
    if photo.get("relative_path") != expected:
        raise RoadError("照片路径与本咨询不匹配")
    path = store.path(expected)
    if not path.is_file() or file_hash(path) != photo["sha256"]:
        raise RoadError("照片副本缺失或变化，请重新登记并查看")
    return photo, path


def validate_photo_fact(store, data, item):
    observation = photo_observation(store, data, item.get("source_ref", ""))
    if any(item.get(k, "known" if k == "state" else None) != observation.get(k) for k in ("field", "value", "state")):
        raise RoadError("照片事实必须对应已记录的实际观察和状态")


def photo_observation(store, data, ref):
    parts = ref.split(":") if isinstance(ref, str) else []
    if len(parts) != 3 or parts[0] != "photo":
        raise RoadError("新照片事实须引用 photo:照片ID:观察ID")
    photo, _ = checked_photo(store, data, parts[1])
    matches = [o for o in photo["observations"] if o["id"] == parts[2]]
    if not matches:
        raise RoadError("照片事实必须对应已记录的实际观察")
    return matches[0]


def photo_lines(data):
    lines = []
    if data.get("photos"):
        lines = ["## 照片资料与观察边界", "以下保留历次看图记录；当前采用哪些事实及其纠正状态，以现有信息和当前意见为准。"]
    for photo in data.get("photos", []):
        meta = photo["metadata"]
        status = "已登记，尚未实际查看" if photo["status"] == "registered_not_viewed" else "查看者已声明看图，未经工程专业审核"
        lines += [f"### {photo['label']}",
                  f"- 用户提供的位置：{meta['location']}；拍摄时间：{meta['capture_time']}；方向：{meta['direction']}。元信息未经核实。",
                  f"- 查看状态：{status}。"]
        for note in photo["observations"]:
            lines += [f"- 图片观察：{note['value']}；区域：{note['region']}。",
                      f"  观察限制：{note['limitation']}；观察者：{note['viewer']}；时间适用：{ {'unknown':'不清楚','current':'本次现状','historical':'历史记录'}[note['time']]}。"]
    return lines
