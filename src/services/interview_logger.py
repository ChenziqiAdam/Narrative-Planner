"""
访谈会话日志记录器

实时记录 Baseline 和 Planner 模式的每一轮对话详情。
每轮对话立即写入文件，避免中断丢失数据。
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class DialogueLog:
    """对话记录"""
    interviewer_question: str
    interviewee_answer: str
    interviewer_action: str = "continue"


@dataclass
class ExtractionLog:
    """事件提取记录"""
    extracted_events: List[Dict[str, Any]] = field(default_factory=list)
    extraction_confidence: float = 0.0
    is_incremental_update: bool = False
    matched_event_id: Optional[str] = None


@dataclass
class CoverageLog:
    """覆盖率记录"""
    before: float = 0.0
    after: float = 0.0
    delta: float = 0.0
    slot_coverage: Dict[str, float] = field(default_factory=dict)


@dataclass
class EvaluationLog:
    """评估记录"""
    question_quality_score: float = 0.0
    information_gain_score: float = 0.0
    non_redundancy_score: float = 0.0
    slot_targeting_score: float = 0.0
    emotional_alignment_score: float = 0.0
    planner_alignment_score: float = 0.0
    coverage_gain: float = 0.0
    targeted_slots: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class PlannerDecisionLog:
    """Planner决策记录"""
    next_action: str = "continue"
    recommended_theme_id: Optional[str] = None
    recommended_theme_title: Optional[str] = None
    targeted_slots: List[str] = field(default_factory=list)
    decision_signals: Dict[str, Any] = field(default_factory=dict)
    decision_weights: Dict[str, float] = field(default_factory=dict)
    decision_scores: Dict[str, float] = field(default_factory=dict)
    low_info_streak: int = 0
    prefer_breadth_switch: bool = False
    suggest_close: bool = False


@dataclass
class TurnLogData:
    """单轮对话完整记录"""
    turn_id: str
    turn_index: int
    timestamp: str
    dialogue: DialogueLog
    extraction: Optional[ExtractionLog] = None
    coverage: CoverageLog = field(default_factory=CoverageLog)
    evaluation: Optional[EvaluationLog] = None
    planner_decision: Optional[PlannerDecisionLog] = None
    memory_calls: List[Dict[str, Any]] = field(default_factory=list)
    debug_trace: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionSummary:
    """会话摘要"""
    total_turns: int = 0
    final_coverage: float = 0.0
    final_slot_coverage: Dict[str, float] = field(default_factory=dict)
    extracted_events_count: int = 0
    average_turn_quality: float = 0.0
    average_information_gain: float = 0.0
    final_action: str = "end"
    end_reason: str = ""


class InterviewLogger:
    """
    访谈会话日志记录器

    实时记录每轮对话，立即写入文件，支持中断恢复。
    同时输出完整JSON文件和JSON Lines格式的轮次追加文件。
    """

    def __init__(
        self,
        session_id: str,
        session_type: str,  # "baseline" or "planner"
        elder_info: Dict[str, Any],
        mode: str = "ai",
        log_dir: str = "logs/interviews"
    ):
        self.session_id = session_id
        self.session_type = session_type
        self.elder_info = elder_info
        self.mode = mode
        self.log_dir = os.path.join(log_dir, session_type)
        self.created_at = datetime.now().isoformat()

        # 确保日志目录存在
        os.makedirs(self.log_dir, exist_ok=True)

        # 会话数据
        self.turns: List[TurnLogData] = []
        self.summary: Optional[SessionSummary] = None

        # 文件路径
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.full_log_path = os.path.join(
            self.log_dir,
            f"{session_type}_{session_id}_{timestamp}.json"
        )
        self.turns_log_path = os.path.join(
            self.log_dir,
            f"{session_type}_{session_id}_{timestamp}_turns.jsonl"
        )

        # 写入初始会话信息
        self._write_initial_session()

    def _write_initial_session(self) -> None:
        """写入初始会话信息"""
        session_data = {
            "session_id": self.session_id,
            "session_type": self.session_type,
            "created_at": self.created_at,
            "updated_at": datetime.now().isoformat(),
            "elder_info": self.elder_info,
            "mode": self.mode,
            "turns": [],
            "summary": None
        }
        self._write_json_file(session_data)

    def log_turn(self, turn_data: TurnLogData) -> None:
        """
        记录单轮对话并立即写入文件

        Args:
            turn_data: 单轮对话完整数据
        """
        self.turns.append(turn_data)

        # 实时写入完整日志文件
        self._write_full_log()

        # 追加写入轮次日志文件（JSON Lines格式）
        self._append_turn_file(turn_data)

    def _write_full_log(self) -> None:
        """写入完整会话日志（JSON格式）"""
        session_data = {
            "session_id": self.session_id,
            "session_type": self.session_type,
            "created_at": self.created_at,
            "updated_at": datetime.now().isoformat(),
            "elder_info": self.elder_info,
            "mode": self.mode,
            "turns": [self._turn_to_dict(turn) for turn in self.turns],
            "summary": asdict(self.summary) if self.summary else None
        }
        self._write_json_file(session_data)

    def _append_turn_file(self, turn_data: TurnLogData) -> None:
        """追加单轮记录到JSON Lines文件"""
        turn_dict = self._turn_to_dict(turn_data)
        with open(self.turns_log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(turn_dict, ensure_ascii=False) + '\n')

    def _turn_to_dict(self, turn_data: TurnLogData) -> Dict[str, Any]:
        """将TurnLogData转换为字典"""
        return {
            "turn_id": turn_data.turn_id,
            "turn_index": turn_data.turn_index,
            "timestamp": turn_data.timestamp,
            "dialogue": asdict(turn_data.dialogue),
            "extraction": asdict(turn_data.extraction) if turn_data.extraction else None,
            "coverage": asdict(turn_data.coverage),
            "evaluation": asdict(turn_data.evaluation) if turn_data.evaluation else None,
            "planner_decision": asdict(turn_data.planner_decision) if turn_data.planner_decision else None,
            "memory_calls": turn_data.memory_calls,
            "debug_trace": turn_data.debug_trace
        }

    def _write_json_file(self, data: Dict[str, Any]) -> None:
        """写入JSON文件（带临时文件保证原子性）"""
        temp_path = self.full_log_path + '.tmp'
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 原子重命名，避免写入中断导致文件损坏
            os.replace(temp_path, self.full_log_path)
        except Exception:
            # 清理临时文件
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def finalize_session(self, summary: SessionSummary) -> str:
        """
        结束会话，写入最终摘要

        Args:
            summary: 会话摘要数据

        Returns:
            完整日志文件路径
        """
        self.summary = summary
        self._write_full_log()
        return self.full_log_path

    def get_log_path(self) -> str:
        """获取完整日志文件路径"""
        return self.full_log_path

    def get_turns_log_path(self) -> str:
        """获取轮次追加日志文件路径"""
        return self.turns_log_path


# 便捷函数：创建 Baseline 日志记录器
def create_baseline_logger(
    session_id: str,
    elder_info: Dict[str, Any],
    mode: str = "ai"
) -> InterviewLogger:
    """创建 Baseline 模式日志记录器"""
    return InterviewLogger(
        session_id=session_id,
        session_type="baseline",
        elder_info=elder_info,
        mode=mode
    )


# 便捷函数：创建 Planner 日志记录器
def create_planner_logger(
    session_id: str,
    elder_info: Dict[str, Any],
    mode: str = "ai"
) -> InterviewLogger:
    """创建 Planner 模式日志记录器"""
    return InterviewLogger(
        session_id=session_id,
        session_type="planner",
        elder_info=elder_info,
        mode=mode
    )
