#!/usr/bin/env python3
"""
Prompt 转写格式化器

将结构化数据（GraphSummary、MemoryCapsule 等）转写为自然语言描述，
使 LLM 更容易理解访谈上下文。

设计原则：
1. 信息密度优先：用最少 token 传递最多有用信息
2. 层次分明：清晰区分已讲/进行中/待探索
3. 行动导向：提示词应直接支持决策
"""

from typing import Dict, List, Optional
from datetime import datetime

from src.state import (
    PlannerContext,
    GraphSummary,
    MemoryCapsule,
    ElderProfile,
    TurnRecord,
    ThemeSummary,
)


class PromptFormatter:
    """将结构化数据转写为自然语言提示词"""

    # 访谈阶段定义
    STAGE_DESCRIPTIONS = {
        "opening": "开场阶段 - 建立信任，初步了解背景",
        "early": "早期阶段 - 深入当前话题，追问细节",
        "mid": "中期阶段 - 平衡深度与广度，关注覆盖",
        "late": "后期阶段 - 查漏补缺，适时收尾",
    }

    # 槽位中文映射
    SLOT_NAMES_CN = {
        "time": "时间",
        "location": "地点",
        "people": "人物",
        "event": "事件",
        "feeling": "感受",
        "reflection": "反思",
        "cause": "原因",
        "result": "结果",
    }

    def format_planner_context(self, context: PlannerContext) -> str:
        """
        格式化完整的 PlannerContext 为自然语言提示词

        Args:
            context: 规划器上下文

        Returns:
            格式化的自然语言描述
        """
        sections = [
            self._format_header(context),
            self._format_elder_profile(context.elder_profile),
            self._format_story_progress(context),
            self._format_theme_overview(context.graph_summary),
            self._format_memory_guidance(context.memory_capsule),
            self._format_recent_dialogue(context.recent_transcript),
        ]
        return "\n\n".join(filter(None, sections))

    def _format_header(self, context: PlannerContext) -> str:
        """格式化头部信息"""
        stage = self._determine_stage(context.turn_index)
        stage_desc = self.STAGE_DESCRIPTIONS.get(stage, "访谈进行中")

        return f"""【访谈会话】{context.session_id}
【当前轮次】第 {context.turn_index} 轮（{stage_desc}）"""

    def _format_elder_profile(self, profile: ElderProfile) -> str:
        """格式化长者画像"""
        parts = []
        if profile.name:
            parts.append(f"姓名：{profile.name}")
        if profile.age:
            parts.append(f"年龄：{profile.age}岁")
        elif profile.birth_year:
            parts.append(f"出生：{profile.birth_year}年")
        if profile.hometown:
            parts.append(f"家乡：{profile.hometown}")

        if not parts:
            return ""

        info = " | ".join(parts)
        background = f"\n背景：{profile.background_summary}" if profile.background_summary else ""

        return f"【长者信息】{info}{background}"

    def _format_story_progress(self, context: PlannerContext) -> str:
        """格式化故事进展摘要"""
        capsule = context.memory_capsule
        if not capsule:
            return ""

        lines = ["【访谈进展】"]

        # 当前故事线
        if capsule.current_storyline:
            lines.append(f"当前焦点：{capsule.current_storyline}")

        # 会话摘要
        if capsule.session_summary:
            lines.append(f"整体印象：{capsule.session_summary}")

        # 统计信息
        stats = []
        if capsule.active_event_ids:
            stats.append(f"已提取 {len(capsule.active_event_ids)} 个事件")
        if capsule.active_people_ids:
            stats.append(f"涉及 {len(capsule.active_people_ids)} 位人物")
        if capsule.open_loops:
            stats.append(f"{len(capsule.open_loops)} 条待追问线索")
        if capsule.contradictions:
            stats.append(f"{len(capsule.contradictions)} 个待解决矛盾")

        if stats:
            lines.append(" | ".join(stats))

        return "\n".join(lines)

    def _format_theme_overview(self, summary: GraphSummary) -> str:
        """格式化主题覆盖概览"""
        if not summary:
            return ""

        total = (
            len(summary.exhausted_themes)
            + len(summary.mentioned_themes)
            + len(summary.pending_themes)
        )
        if total == 0:
            return ""

        lines = [
            f"【主题覆盖】整体完成度 {summary.overall_coverage * 100:.0f}%（{total - len(summary.pending_themes)}/{total} 主题已涉及）"
        ]

        # 已穷尽的主题
        if summary.exhausted_themes:
            lines.append(f"\n✅ 已充分探索（{len(summary.exhausted_themes)} 个）：")
            for t in summary.exhausted_themes[:3]:
                lines.append(f"  • {t.title}")
            if len(summary.exhausted_themes) > 3:
                lines.append(f"    ... 等共 {len(summary.exhausted_themes)} 个")

        # 进行中的主题
        if summary.mentioned_themes:
            lines.append(f"\n🔄 进行中（{len(summary.mentioned_themes)} 个）：")
            for t in summary.mentioned_themes[:4]:
                missing = self._describe_missing(t)
                lines.append(f"  • {t.title}（{t.extracted_event_count} 个事件，{missing}）")

        # 空白主题（按优先级排序）
        if summary.pending_themes:
            lines.append(f"\n⬜ 待探索（{len(summary.pending_themes)} 个）：")
            for t in summary.pending_themes[:5]:
                deps = self._format_dependencies(t)
                priority_mark = "★" if t.priority >= 8 else ""
                lines.append(f"  • {priority_mark}{t.title}{deps}")

        return "\n".join(lines)

    def _format_memory_guidance(self, capsule: MemoryCapsule) -> str:
        """格式化记忆指导（开环、矛盾等）"""
        if not capsule:
            return ""

        sections = []

        # 开环线索
        if capsule.open_loops:
            lines = ["【待追问线索】"] + [
                f"  → {loop.description}"
                for loop in capsule.open_loops[:4]
            ]
            sections.append("\n".join(lines))

        # 矛盾提示
        if capsule.contradictions:
            lines = ["【需澄清矛盾】"] + [
                f"  ⚠ {note.description}"
                for note in capsule.contradictions[:2]
            ]
            sections.append("\n".join(lines))

        # 情绪状态指导
        if capsule.emotional_state:
            es = capsule.emotional_state
            energy_desc = self._describe_energy(es.cognitive_energy)
            valence_desc = self._describe_valence(es.valence)

            if energy_desc or valence_desc:
                guidance = f"【受访者状态】{energy_desc} {valence_desc}".strip()
                if es.evidence:
                    guidance += f"（依据：{', '.join(es.evidence[:2])}）"
                sections.append(guidance)

        # 避免重复提示
        if capsule.do_not_repeat:
            recent_qs = " | ".join(capsule.do_not_repeat[-3:])
            sections.append(f"【避免重复提问】{recent_qs}")

        return "\n\n".join(sections)

    def _format_recent_dialogue(self, transcript: List[TurnRecord]) -> str:
        """格式化最近对话"""
        if not transcript:
            return ""

        lines = ["【最近对话】"]

        for i, turn in enumerate(transcript, 1):
            q = turn.interviewer_question[:60] + "..." if len(turn.interviewer_question) > 60 else turn.interviewer_question
            a = turn.interviewee_answer[:100] + "..." if len(turn.interviewee_answer) > 100 else turn.interviewee_answer
            lines.append(f"\n第 {turn.turn_index} 轮：")
            lines.append(f"  问：{q}")
            lines.append(f"  答：{a}")

        return "\n".join(lines)

    def _determine_stage(self, turn_index: int) -> str:
        """确定访谈阶段"""
        if turn_index == 0:
            return "opening"
        if turn_index <= 3:
            return "early"
        if turn_index <= 8:
            return "mid"
        return "late"

    def _describe_missing(self, theme: ThemeSummary) -> str:
        """描述主题缺失的内容"""
        ratio = theme.completion_ratio
        if ratio < 0.2:
            return "刚提及，需大量补充"
        if ratio < 0.4:
            return "基本信息待完善"
        if ratio < 0.6:
            return "需深挖细节"
        if ratio < 0.8:
            return "可追问反思"
        return "接近完成"

    def _format_dependencies(self, theme: ThemeSummary) -> str:
        """格式化依赖关系"""
        if not theme.depends_on:
            return ""
        deps = ", ".join(theme.depends_on)
        return f"（建议先完成：{deps}）"

    def _describe_energy(self, energy: float) -> str:
        """描述精力状态"""
        if energy < 0.3:
            return "精力较低，建议简短提问或切换话题"
        if energy < 0.5:
            return "精力一般，避免连续追问"
        return ""

    def _describe_valence(self, valence: float) -> str:
        """描述情感效价"""
        if valence < -0.3:
            return "情绪偏负面，需要共情支持"
        if valence > 0.3:
            return "情绪积极，适合深入探索"
        return ""

    def format_for_planner_decision(self, context: PlannerContext) -> str:
        """
        专门为 Planner 决策优化的格式化输出

        包含明确的决策指导信息
        """
        base = self.format_planner_context(context)

        # 添加决策建议
        suggestions = self._generate_decision_suggestions(context)

        return f"""{base}

【决策建议】
{suggestions}
"""

    def _generate_decision_suggestions(self, context: PlannerContext) -> str:
        """生成决策建议"""
        suggestions = []
        capsule = context.memory_capsule
        summary = context.graph_summary

        # 基于开环的建议
        if capsule and capsule.open_loops:
            top_loop = capsule.open_loops[0]
            suggestions.append(f"1. 优先追问：{top_loop.description[:50]}")

        # 基于覆盖率的建议
        if summary and summary.pending_themes:
            top_pending = summary.pending_themes[0]
            if top_pending.priority >= 8:
                suggestions.append(f"2. 高优先级空白主题：{top_pending.title}")

        # 基于情绪状态的建议
        if capsule and capsule.emotional_state:
            es = capsule.emotional_state
            if es.cognitive_energy < 0.4:
                suggestions.append("3. 受访者精力较低，建议温和过渡或收尾")
            elif es.valence < -0.3:
                suggestions.append("3. 受访者情绪负面，建议共情后再继续")

        return "\n".join(suggestions) if suggestions else "根据当前上下文灵活决策"


# 便捷函数
def format_planner_context(context: PlannerContext) -> str:
    """便捷函数：快速格式化 PlannerContext"""
    formatter = PromptFormatter()
    return formatter.format_for_planner_decision(context)
