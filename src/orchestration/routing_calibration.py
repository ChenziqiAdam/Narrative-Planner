"""RoutingCalibration — 三阶段自适应路由校准。

阶段一（预热期）: 前 N 轮全量执行 extract/merge/project，收集校准数据。
阶段二（校准点）: LLM 分析预热数据，生成个性化关键词/阈值/权重。
阶段三（自适应期）: 用校准后的配置执行前置路由。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from statistics import mean, median
from typing import Any, Dict, List, Optional

from src.config import Config
from src.state.models import serialize_value

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────
# Data models
# ────────────────────────────────────────────────────────

@dataclass
class CalibrationRecord:
    """单轮校准快照。"""

    turn_id: str
    turn_index: int
    answer: str
    answer_len: int
    markers_hit: Dict[str, bool]
    marker_count: int
    targeted_slot: Optional[str]
    answered_targeted_slot: bool

    # 实际结果（extract/merge/project 执行后填入）
    actual_coverage_delta: float = 0.0
    actual_extracted_count: int = 0
    actual_touched_events: int = 0
    actual_new_events: int = 0
    actual_new_people: int = 0


@dataclass
class PersonalizedRoutingConfig:
    """校准后生成的个性化路由配置。"""

    calibrated: bool = False
    warmup_turns: int = 8
    recalibration_interval: int = 15

    # 个性化关键词（与默认列表合并，个性化词优先）
    personal_time_keywords: List[str] = field(default_factory=list)
    personal_location_keywords: List[str] = field(default_factory=list)
    personal_person_keywords: List[str] = field(default_factory=list)
    personal_feeling_keywords: List[str] = field(default_factory=list)
    personal_reflection_keywords: List[str] = field(default_factory=list)
    personal_event_keywords: List[str] = field(default_factory=list)
    personal_cause_result_keywords: List[str] = field(default_factory=list)

    # 个性化阈值
    short_answer_threshold: float = 24.0
    length_bonus_base: float = 180.0

    # 个性化标记权重
    weight_time: float = 0.18
    weight_location: float = 0.16
    weight_person: float = 0.17
    weight_event: float = 0.20
    weight_cause_result: float = 0.14
    weight_feeling: float = 0.11
    weight_reflection: float = 0.14
    weight_length: float = 0.24
    weight_answered_slot: float = 0.24
    weight_multi_marker: float = 0.10

    # 校准元信息
    calibration_turn: int = 0
    calibration_reasoning: str = ""
    last_recalibration_turn: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return serialize_value(self)


def seed_config_from_elder_info(
    config: PersonalizedRoutingConfig,
    elder_info: Dict[str, Any],
) -> None:
    """Pre-seed routing config from elder profile before warm-up begins.

    Uses birth_year, background, and hometown to generate an initial set of
    personalized keywords so that even the warm-up phase has some awareness
    of the elder's life context.
    """
    background = str(elder_info.get("background", "") or "")
    hometown = str(elder_info.get("hometown", "") or "")
    birth_year = elder_info.get("birth_year")

    # ── Time keywords from birth year / historical era ──
    time_kw: List[str] = []
    if birth_year:
        try:
            by = int(birth_year)
            # Approximate life-period expressions
            time_kw.append(f"{by}年")
            # Young adulthood (age 18-25)
            for y in range(by + 18, by + 26):
                time_kw.append(f"{y}年")
            # Historical era keywords based on birth decade
            if by <= 1940:
                time_kw.extend(["解放前", "抗战", "民国"])
            elif by <= 1950:
                time_kw.extend(["解放", "建国", "三年自然灾害"])
            elif by <= 1960:
                time_kw.extend(["文革", "上山下乡", "知青", "大跃进"])
            elif by <= 1970:
                time_kw.extend(["文革", "恢复高考", "改革开放"])
            elif by <= 1980:
                time_kw.extend(["改革开放", "下海", "国企改革"])
            elif by <= 1990:
                time_kw.extend(["下岗", "南下", "打工"])
        except (TypeError, ValueError):
            pass
    config.personal_time_keywords = time_kw

    # ── Location keywords from hometown and background ──
    location_kw: List[str] = []
    if hometown:
        location_kw.append(hometown)
        # Extract suffixes: 市/县/镇/村/省
        for suffix in ("省", "市", "县", "镇", "村", "区"):
            if suffix in hometown:
                parts = hometown.split(suffix)
                if parts[0]:
                    location_kw.append(parts[0])
    # Scan background for location-like tokens
    import re as _re
    _loc_pattern = _re.compile(
        r"[\u4e00-\u9fff]{1,8}(?:厂|矿|学校|医院|车间|部队|公社|农场|单位|研究所)"
    )
    location_kw.extend(_loc_pattern.findall(background))
    config.personal_location_keywords = list(dict.fromkeys(location_kw))

    # ── Person keywords from background ──
    _person_patterns = {
        "老伴": ["老伴", "爱人", "丈夫", "妻子", "对象"],
        "父亲": ["父亲", "爸爸", "爹"],
        "母亲": ["母亲", "妈妈", "娘"],
    }
    person_kw: List[str] = []
    for label, variants in _person_patterns.items():
        if any(v in background for v in variants):
            person_kw.extend(variants)
    # Extract named people patterns (X老师, X师傅, etc.)
    _named = _re.findall(r"[\u4e00-\u9fff]{1,3}(?:老师|师傅|叔叔|阿姨|伯伯|奶奶|爷爷)", background)
    person_kw.extend(_named)
    config.personal_person_keywords = list(dict.fromkeys(person_kw))

    # ── Event keywords from background ──
    _event_keywords_map = {
        "上学": ["上学", "读书", "学校", "考", "毕业"],
        "工作": ["工作", "工厂", "进厂", "上班", "车间", "单位", "分配"],
        "结婚": ["结婚", "对象", "婚礼", "嫁", "娶"],
        "参军": ["参军", "当兵", "入伍", "部队", "复员"],
        "迁移": ["搬", "调到", "去了", "下乡", "回城", "离开"],
        "生育": ["生孩子", "孩子出生", "有了", "生了个"],
    }
    event_kw: List[str] = []
    for label, keywords in _event_keywords_map.items():
        if any(kw in background for kw in keywords):
            event_kw.extend(keywords)
    config.personal_event_keywords = list(dict.fromkeys(event_kw))

    # ── Cause-result keywords from background ──
    _cause_keywords = ["因为", "所以", "后来", "结果", "导致", "从那以后"]
    cause_kw = [kw for kw in _cause_keywords if kw in background]
    config.personal_cause_result_keywords = cause_kw

    # ── Feeling keywords from background ──
    _feeling_keywords = ["辛苦", "高兴", "难过", "不容易", "踏实", "委屈", "自豪", "遗憾"]
    feeling_kw = [kw for kw in _feeling_keywords if kw in background]
    config.personal_feeling_keywords = feeling_kw

    # ── Reflection keywords from background ──
    _reflection_keywords = ["一辈子", "回头看", "明白", "价值", "改变", "最重要", "做人"]
    reflection_kw = [kw for kw in _reflection_keywords if kw in background]
    config.personal_reflection_keywords = reflection_kw

    # ── Adjust short threshold based on profile richness ──
    # If background is very detailed (>200 chars), the elder likely speaks more
    if len(background) > 200:
        config.short_answer_threshold = 30.0
        config.length_bonus_base = 220.0
    elif len(background) < 30:
        config.short_answer_threshold = 18.0
        config.length_bonus_base = 120.0

    logger.info(
        "Seeded routing config from elder info: time=%d, location=%d, person=%d, event=%d",
        len(config.personal_time_keywords),
        len(config.personal_location_keywords),
        len(config.personal_person_keywords),
        len(config.personal_event_keywords),
    )


# ────────────────────────────────────────────────────────
# Calibration buffer (warm-up data collector)
# ────────────────────────────────────────────────────────

class RoutingCalibrationBuffer:
    """预热期校准数据收集器。"""

    def __init__(self) -> None:
        self.records: List[CalibrationRecord] = []
        self.answer_lengths: List[int] = []
        self.time_expressions: List[str] = []
        self.location_tokens: List[str] = []
        self.person_names: List[str] = []
        self.feeling_phrases: List[str] = []
        self.reflection_phrases: List[str] = []
        self.event_summaries: List[str] = []

    def record_markers(
        self,
        turn_id: str,
        turn_index: int,
        answer: str,
        markers_hit: Dict[str, bool],
        marker_count: int,
        targeted_slot: Optional[str],
        answered_targeted_slot: bool,
    ) -> CalibrationRecord:
        rec = CalibrationRecord(
            turn_id=turn_id,
            turn_index=turn_index,
            answer=answer,
            answer_len=len(answer),
            markers_hit=markers_hit,
            marker_count=marker_count,
            targeted_slot=targeted_slot,
            answered_targeted_slot=answered_targeted_slot,
        )
        self.records.append(rec)
        self.answer_lengths.append(len(answer))
        return rec

    def record_outcomes(
        self,
        turn_id: str,
        coverage_delta: float,
        extracted_count: int,
        touched_events: int,
        new_events: int,
        new_people: int,
        extracted_events: List[Any],
    ) -> None:
        for rec in reversed(self.records):
            if rec.turn_id == turn_id:
                rec.actual_coverage_delta = coverage_delta
                rec.actual_extracted_count = extracted_count
                rec.actual_touched_events = touched_events
                rec.actual_new_events = new_events
                rec.actual_new_people = new_people
                break

        for event in extracted_events:
            slots = getattr(event, "slots", None)
            if slots:
                if getattr(slots, "time", None):
                    self.time_expressions.append(slots.time)
                if getattr(slots, "location", None):
                    self.location_tokens.append(slots.location)
                if getattr(slots, "people", None):
                    self.person_names.extend(slots.people)
                if getattr(slots, "feeling", None):
                    self.feeling_phrases.append(slots.feeling)
                if getattr(slots, "reflection", None):
                    self.reflection_phrases.append(slots.reflection)
            else:
                if getattr(event, "time", None):
                    self.time_expressions.append(event.time)
                if getattr(event, "location", None):
                    self.location_tokens.append(event.location)
                people = getattr(event, "people_names", None) or []
                self.person_names.extend(people)
                if getattr(event, "feeling", None):
                    self.feeling_phrases.append(event.feeling)
                if getattr(event, "reflection", None):
                    self.reflection_phrases.append(event.reflection)
                summary = getattr(event, "summary", None) or getattr(event, "event", None)
                if summary:
                    self.event_summaries.append(summary)

    @property
    def size(self) -> int:
        return len(self.records)

    def has_enough_data(self, min_turns: int = 8) -> bool:
        return self.size >= min_turns

    def get_statistics(self) -> Dict[str, Any]:
        if not self.records:
            return {}

        lengths = sorted(self.answer_lengths)
        marker_names = [
            "has_time_marker", "has_location_marker", "has_person_marker",
            "has_event_marker", "has_cause_result_marker", "has_feeling_marker",
            "has_reflection_marker",
        ]
        marker_gain = {}
        for name in marker_names:
            hit_deltas = [
                r.actual_coverage_delta
                for r in self.records
                if r.markers_hit.get(name)
            ]
            miss_deltas = [
                r.actual_coverage_delta
                for r in self.records
                if not r.markers_hit.get(name)
            ]
            marker_gain[name] = {
                "hit_avg": round(mean(hit_deltas), 4) if hit_deltas else 0.0,
                "miss_avg": round(mean(miss_deltas), 4) if miss_deltas else 0.0,
                "hit_count": len(hit_deltas),
            }

        return {
            "turn_count": self.size,
            "answer_length": {
                "p20": self._percentile(lengths, 20),
                "p50": self._percentile(lengths, 50),
                "p75": self._percentile(lengths, 75),
                "mean": round(mean(lengths), 1),
            },
            "time_expressions": list(dict.fromkeys(self.time_expressions))[:20],
            "location_tokens": list(dict.fromkeys(self.location_tokens))[:20],
            "person_names": list(dict.fromkeys(self.person_names))[:20],
            "feeling_phrases": list(dict.fromkeys(self.feeling_phrases))[:20],
            "reflection_phrases": list(dict.fromkeys(self.reflection_phrases))[:20],
            "event_summaries": list(dict.fromkeys(self.event_summaries))[:15],
            "marker_gain": marker_gain,
            "avg_coverage_delta": round(
                mean([r.actual_coverage_delta for r in self.records]), 4
            ),
            "high_value_turn_count": sum(
                1 for r in self.records
                if r.actual_new_events > 0 or r.actual_coverage_delta > 0.01
            ),
        }

    @staticmethod
    def _percentile(sorted_data: List[int], pct: int) -> int:
        if not sorted_data:
            return 0
        idx = max(0, int(len(sorted_data) * pct / 100) - 1)
        return sorted_data[min(idx, len(sorted_data) - 1)]


# ────────────────────────────────────────────────────────
# LLM-based calibrator
# ────────────────────────────────────────────────────────

_CALIBRATION_PROMPT = """\
你正在为一个回忆录访谈系统校准路由策略。

以下是与一位老人访谈前 {turn_count} 轮的实际数据：

## 已提取事件的关键信息
- 时间表达: {time_expressions}
- 地点: {locations}
- 人物: {people}
- 感受: {feelings}
- 反思: {reflections}

## 回答长度分布
P20={p20}字, P50={p50}字, P75={p75}字, 平均={mean_len}字

## 各标记命中时的实际信息增益（覆盖度变化）
{marker_gain_text}

## 统计摘要
- 平均每轮覆盖度变化: {avg_delta}
- 有高价值新信息的轮次: {high_value_turns}/{turn_count}

## 当前默认关键词列表（供参考）
- 时间: ["(18|19|20)\\d\\d年?", "小时候", "那年", "当时", "后来", ...]
- 地点: ["厂", "村", "县", "学校", "医院", "家", ...]
- 人物: ["父亲", "母亲", "老伴", "师傅", ...]
- 事件: ["上学", "工作", "结婚", "进了", "遇到", ...]
- 因果: ["因为", "所以", "后来", "导致", ...]
- 感受: ["难过", "高兴", "委屈", "自豪", ...]
- 反思: ["一辈子", "回头看", "明白", "价值", ...]

## 当前默认权重
- time=0.18, location=0.16, person=0.17, event=0.20
- cause_result=0.14, feeling=0.11, reflection=0.14
- length_bonus=0.24, answered_slot=0.24, multi_marker=0.10
- short_answer_threshold=24, length_bonus_base=180

## 任务

请分析该老人的说话风格和表达习惯，生成个性化的路由配置。

要求：
1. 补充该老人**特有**的时间/地点/人物/感受表达关键词（从已提取事件中发现的、不在默认列表中的）
2. 校准 is_short 阈值（基于该老人回答长度分布）
3. 调整各标记权重（如果某标记命中与未命中时的信息增益差异大，提权；差异小或无差异，降权）
4. 只输出 JSON，不要其他文字

## 输出格式

```json
{{
  "personal_time_keywords": ["关键词1", "关键词2"],
  "personal_location_keywords": ["关键词1"],
  "personal_person_keywords": ["人名1", "称谓1"],
  "personal_feeling_keywords": ["表达1"],
  "personal_reflection_keywords": ["表达1"],
  "personal_event_keywords": [],
  "personal_cause_result_keywords": [],
  "short_answer_threshold": 24,
  "length_bonus_base": 180,
  "weight_time": 0.18,
  "weight_location": 0.16,
  "weight_person": 0.17,
  "weight_event": 0.20,
  "weight_cause_result": 0.14,
  "weight_feeling": 0.11,
  "weight_reflection": 0.14,
  "weight_length": 0.24,
  "weight_answered_slot": 0.24,
  "weight_multi_marker": 0.10,
  "reasoning": "简要说明校准依据"
}}
```
"""


class RoutingCalibrator:
    """LLM 驱动的路由校准器。"""

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(**Config.get_openai_client_kwargs())
        return self._client

    def calibrate(
        self,
        buffer: RoutingCalibrationBuffer,
        config: PersonalizedRoutingConfig,
    ) -> PersonalizedRoutingConfig:
        """用 LLM 分析预热数据，返回校准后的配置。"""
        stats = buffer.get_statistics()
        if not stats:
            logger.warning("Calibration skipped: no statistics available")
            return config

        prompt = self._build_prompt(stats)
        response_text = self._call_llm(prompt)
        if not response_text:
            logger.warning("Calibration failed: empty LLM response")
            return config

        calibration_data = self._parse_response(response_text)
        if not calibration_data:
            logger.warning("Calibration failed: could not parse LLM response")
            return config

        self._apply_calibration(config, calibration_data, stats["turn_count"])
        logger.info(
            "Routing calibrated at turn %d: reasoning=%s",
            config.calibration_turn,
            config.calibration_reasoning[:80],
        )
        return config

    def _build_prompt(self, stats: Dict[str, Any]) -> str:
        marker_gain_lines = []
        for name, gain in stats.get("marker_gain", {}).items():
            marker_gain_lines.append(
                f"  {name}: 命中{gain['hit_count']}次, "
                f"命中时平均增益={gain['hit_avg']}, "
                f"未命中时平均增益={gain['miss_avg']}"
            )
        marker_gain_text = "\n".join(marker_gain_lines) or "  (无数据)"

        al = stats.get("answer_length", {})
        return _CALIBRATION_PROMPT.format(
            turn_count=stats.get("turn_count", 0),
            time_expressions=", ".join(stats.get("time_expressions", [])[:15]) or "(无)",
            locations=", ".join(stats.get("location_tokens", [])[:15]) or "(无)",
            people=", ".join(stats.get("person_names", [])[:15]) or "(无)",
            feelings=", ".join(stats.get("feeling_phrases", [])[:15]) or "(无)",
            reflections=", ".join(stats.get("reflection_phrases", [])[:15]) or "(无)",
            p20=al.get("p20", 0),
            p50=al.get("p50", 0),
            p75=al.get("p75", 0),
            mean_len=al.get("mean", 0),
            marker_gain_text=marker_gain_text,
            avg_delta=stats.get("avg_coverage_delta", 0),
            high_value_turns=stats.get("high_value_turn_count", 0),
        )

    def _call_llm(self, prompt: str) -> str:
        try:
            client = self._get_client()
            model = Config.get_model_name("extractor")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个路由策略校准助手。只输出 JSON，不要其他文字。",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=2048,
                temperature=0.3,
            )
            return response.choices[0].message.content or ""
        except Exception:
            logger.exception("LLM calibration call failed")
            return ""

    def _parse_response(self, text: str) -> Optional[Dict[str, Any]]:
        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text.strip())
        except (json.JSONDecodeError, IndexError):
            logger.exception("Failed to parse calibration response")
            return None

    def _apply_calibration(
        self,
        config: PersonalizedRoutingConfig,
        data: Dict[str, Any],
        turn_count: int,
    ) -> None:
        for key in (
            "personal_time_keywords",
            "personal_location_keywords",
            "personal_person_keywords",
            "personal_feeling_keywords",
            "personal_reflection_keywords",
            "personal_event_keywords",
            "personal_cause_result_keywords",
        ):
            if key in data and isinstance(data[key], list):
                setattr(config, key, [str(v) for v in data[key] if v])

        if "short_answer_threshold" in data:
            config.short_answer_threshold = max(float(data["short_answer_threshold"]), 8)
        if "length_bonus_base" in data:
            config.length_bonus_base = max(float(data["length_bonus_base"]), 20)

        for weight_key in (
            "weight_time", "weight_location", "weight_person", "weight_event",
            "weight_cause_result", "weight_feeling", "weight_reflection",
            "weight_length", "weight_answered_slot", "weight_multi_marker",
        ):
            if weight_key in data:
                setattr(config, weight_key, max(float(data[weight_key]), 0.0))

        config.calibration_reasoning = str(data.get("reasoning", ""))
        config.calibration_turn = turn_count
        config.last_recalibration_turn = turn_count
        config.calibrated = True
