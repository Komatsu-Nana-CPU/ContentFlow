"""输入边界与不可变审核快照。"""

from dataclasses import asdict, dataclass
import hashlib
import json
import re


class FlowError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Content:
    title: str
    script: str
    video_terms: tuple[str, ...]

    @classmethod
    def parse(cls, value: object) -> "Content":
        if not isinstance(value, dict):
            raise FlowError("content", "生成结果必须是 JSON 对象。")
        title, script, terms = (value.get(k) for k in ("title", "script", "video_terms"))
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
            raise FlowError("content", "标题不能为空，且最多 100 字。")
        if not isinstance(script, str) or not 1 <= len(script.strip()) <= 1500:
            raise FlowError("content", "旁白不能为空，且最多 1500 字。")
        if not re.search(r"[\u4e00-\u9fff]", script):
            raise FlowError("content", "请提供中文旁白。")
        if not isinstance(terms, (list, tuple)) or len(terms) != 4:
            raise FlowError("content", "请提供按叙事顺序排列的 4 个英文画面关键词。")
        if any(not isinstance(t, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 ,'\-]{1,79}", t.strip()) for t in terms):
            raise FlowError("content", "每个画面关键词须为 2–80 字符的英文短语。")
        cleaned = tuple(t.strip() for t in terms)
        if len(set(t.lower() for t in cleaned)) != 4:
            raise FlowError("content", "四个画面关键词不能重复。")
        return cls(title.strip(), script.strip(), cleaned)

    def as_dict(self) -> dict:
        return {**asdict(self), "video_terms": list(self.video_terms)}


def validate_topic(topic: str) -> str:
    if not isinstance(topic, str) or not 1 <= len(topic.strip()) <= 120:
        raise FlowError("topic", "请输入 1–120 字的主题。")
    return topic.strip()


def fingerprint(topic: str, content: Content, source: str) -> str:
    if source != "pixabay":
        raise FlowError("source", "本轮仅使用 Pixabay 在线素材，请重新审核历史草稿。")
    value = {"topic": validate_topic(topic), "content": content.as_dict(), "source": source}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def video_payload(topic: str, content: Content, source: str, font_name: str = "C:/Windows/Fonts/msyhbd.ttc") -> dict:
    fingerprint(topic, content, source)
    return {
        "video_subject": content.title, "video_script": content.script,
        "video_terms": list(content.video_terms), "video_source": source,
        "video_aspect": "9:16", "match_materials_to_script": True,
        "video_concat_mode": "sequential", "video_transition_mode": None,
        "video_fit_mode": "cover", "video_clip_duration": 5, "video_count": 1,
        "voice_name": "zh-CN-XiaoxiaoNeural-Female", "voice_rate": 1.0,
        "voice_volume": 1.0, "custom_audio_file": None, "video_language": "zh-CN",
        "bgm_type": "", "bgm_file": "", "bgm_volume": 0.0,
        "subtitle_enabled": True, "subtitle_display_mode": "sentence",
        "subtitle_animation": "none", "subtitle_position": "bottom",
        "font_name": font_name, "font_size": 60,
        "text_fore_color": "#FFFFFF", "stroke_color": "#000000",
        "stroke_width": 1.5, "n_threads": 2,
    }
