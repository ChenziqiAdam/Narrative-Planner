"""
MergeEngine 智能合并单元测试

测试分层决策逻辑：
1. 高置信度建议（>=0.8）-> 直接合并
2. 中等置信度建议（0.5-0.8）-> LLM建议 + 硬编码验证
3. 低置信度建议（<0.5）-> 原有硬编码兜底
"""

import pytest
from datetime import datetime
from typing import List

from src.services.merge_engine import MergeEngine, MergeAction, MergeResult
from src.core.interfaces import ExtractedEvent, EventSlots, SimilarityHint
from src.state import SessionState, CanonicalEvent, ElderProfile


class TestMergeAction:
    """测试 MergeAction 数据类"""

    def test_merge_action_creation(self):
        """测试 MergeAction 创建"""
        action = MergeAction(
            action_type="UPDATE",
            target_event=None,
            confidence=0.85,
            reason="high_confidence"
        )
        assert action.action_type == "UPDATE"
        assert action.confidence == 0.85
        assert action.reason == "high_confidence"


class TestMergeEngineDecideAction:
    """测试 MergeEngine._decide_merge_action 方法"""

    @pytest.fixture
    def merge_engine(self):
        return MergeEngine(similarity_threshold=0.72)

    @pytest.fixture
    def empty_state(self):
        """创建空的会话状态"""
        return SessionState(
            session_id="test_session",
            mode="planner",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            elder_profile=ElderProfile()
        )

    @pytest.fixture
    def existing_event(self):
        """创建已有事件"""
        return CanonicalEvent(
            event_id="evt_001",
            title="纺织厂工作",
            summary="在纺织厂做挡车工",
            time="1968年",
            location="上海纺织厂",
            people_names=["师傅"],
        )

    def _create_extracted_event(
        self,
        hints: List[SimilarityHint] = None,
        event_text: str = "在纺织厂上班"
    ) -> ExtractedEvent:
        """辅助方法：创建提取的事件"""
        return ExtractedEvent(
            event_id="evt_new_001",
            extracted_at=datetime.now(),
            slots=EventSlots(
                time="1968年",
                location="上海纺织厂",
                event=event_text,
                people=["师傅"]
            ),
            confidence=0.8,
            similarity_hints=hints or []
        )

    def test_high_confidence_direct_update(
        self,
        merge_engine: MergeEngine,
        empty_state: SessionState,
        existing_event: CanonicalEvent
    ):
        """高置信度建议（>=0.8）应直接合并"""
        # 准备
        empty_state.canonical_events["evt_001"] = existing_event
        extracted = self._create_extracted_event(
            hints=[SimilarityHint(
                candidate_id="evt_001",
                confidence=0.90,
                reason="同一件纺织厂工作事件",
                matched_slots=["time", "location", "event"]
            )]
        )

        # 执行
        action = merge_engine._decide_merge_action(empty_state, extracted)

        # 验证
        assert action.action_type == "UPDATE"
        assert action.target_event == existing_event
        assert action.confidence == 0.90
        assert "high_confidence" in action.reason

    def test_medium_confidence_needs_verification(
        self,
        merge_engine: MergeEngine,
        empty_state: SessionState,
        existing_event: CanonicalEvent
    ):
        """中等置信度建议（0.5-0.8）需要二次验证"""
        # 准备
        empty_state.canonical_events["evt_001"] = existing_event
        extracted = self._create_extracted_event(
            hints=[SimilarityHint(
                candidate_id="evt_001",
                confidence=0.65,
                reason="可能是同一件事件",
                matched_slots=["time", "event"]
            )]
        )

        # 执行
        action = merge_engine._decide_merge_action(empty_state, extracted)

        # 验证
        assert action.action_type == "VERIFY_THEN_UPDATE"
        assert action.target_event == existing_event
        assert action.confidence == 0.65
        assert "medium_confidence" in action.reason

    def test_low_confidence_create_new(
        self,
        merge_engine: MergeEngine,
        empty_state: SessionState,
        existing_event: CanonicalEvent
    ):
        """低置信度建议（<0.5）应创建新事件"""
        # 准备
        empty_state.canonical_events["evt_001"] = existing_event
        extracted = self._create_extracted_event(
            hints=[SimilarityHint(
                candidate_id="evt_001",
                confidence=0.30,
                reason="不太确定",
                matched_slots=["location"]
            )]
        )

        # 执行
        action = merge_engine._decide_merge_action(empty_state, extracted)

        # 验证
        assert action.action_type == "CREATE_NEW"
        assert action.target_event is None
        assert action.confidence == 0.30
        assert "low_confidence" in action.reason

    def test_no_hints_fallback_to_legacy(
        self,
        merge_engine: MergeEngine,
        empty_state: SessionState
    ):
        """无相似度建议时应回退到硬编码"""
        extracted = self._create_extracted_event(hints=[])

        action = merge_engine._decide_merge_action(empty_state, extracted)

        assert action.action_type == "CREATE_NEW"
        assert action.reason == "no_llm_hints"

    def test_candidate_not_found_create_new(
        self,
        merge_engine: MergeEngine,
        empty_state: SessionState
    ):
        """候选事件不存在时应创建新事件"""
        extracted = self._create_extracted_event(
            hints=[SimilarityHint(
                candidate_id="evt_nonexistent",
                confidence=0.90,
                reason="高置信度但事件不存在"
            )]
        )

        action = merge_engine._decide_merge_action(empty_state, extracted)

        assert action.action_type == "CREATE_NEW"
        assert action.reason == "candidate_not_found"

    def test_multiple_hints_pick_highest(
        self,
        merge_engine: MergeEngine,
        empty_state: SessionState,
        existing_event: CanonicalEvent
    ):
        """多个建议时应选择置信度最高的"""
        # 准备：创建两个候选事件
        empty_state.canonical_events["evt_001"] = existing_event
        empty_state.canonical_events["evt_002"] = CanonicalEvent(
            event_id="evt_002",
            title="其他事件",
            summary="完全不同的经历"
        )

        extracted = self._create_extracted_event(
            hints=[
                SimilarityHint(
                    candidate_id="evt_002",
                    confidence=0.60,
                    reason="中等匹配"
                ),
                SimilarityHint(
                    candidate_id="evt_001",
                    confidence=0.90,
                    reason="高度匹配"
                )
            ]
        )

        action = merge_engine._decide_merge_action(empty_state, extracted)

        # 应选择置信度最高的 evt_001
        assert action.action_type == "UPDATE"
        assert action.target_event == existing_event
        assert action.confidence == 0.90


class TestMergeEngineVerifyWithRules:
    """测试硬编码验证逻辑"""

    @pytest.fixture
    def merge_engine(self):
        return MergeEngine(similarity_threshold=0.72)

    def test_verify_high_similarity_pass(self, merge_engine: MergeEngine):
        """高相似度应通过验证"""
        existing = CanonicalEvent(
            event_id="evt_001",
            title="纺织厂工作",
            summary="在纺织厂做挡车工",
            time="1968年",
            location="上海",
            people_names=["师傅"]
        )
        extracted = ExtractedEvent(
            event_id="evt_new",
            extracted_at=datetime.now(),
            slots=EventSlots(
                time="1968年",
                location="上海",
                event="纺织厂做挡车工",
                people=["师傅"]
            ),
            confidence=0.8
        )

        result = merge_engine._verify_with_rules(existing, extracted)

        assert result is True

    def test_verify_low_similarity_fail(self, merge_engine: MergeEngine):
        """低相似度应失败"""
        existing = CanonicalEvent(
            event_id="evt_001",
            title="纺织厂工作",
            summary="在纺织厂做挡车工"
        )
        extracted = ExtractedEvent(
            event_id="evt_new",
            extracted_at=datetime.now(),
            slots=EventSlots(
                event="结婚典礼"
            ),
            confidence=0.8
        )

        result = merge_engine._verify_with_rules(existing, extracted)

        assert result is False


class TestMergeEngineIntegration:
    """集成测试：完整的 merge 流程"""

    @pytest.fixture
    def merge_engine(self):
        return MergeEngine(similarity_threshold=0.72)

    @pytest.fixture
    def session_state(self):
        state = SessionState(
            session_id="test_session",
            mode="planner",
            created_at=datetime.now(),
            updated_at=datetime.now(),
            elder_profile=ElderProfile()
        )
        # 预置一个事件
        state.canonical_events["evt_001"] = CanonicalEvent(
            event_id="evt_001",
            title="纺织厂工作",
            summary="在纺织厂做挡车工",
            time="1968年",
            location="上海纺织厂"
        )
        return state

    def test_merge_with_high_confidence_updates_existing(
        self,
        merge_engine: MergeEngine,
        session_state: SessionState
    ):
        """高置信度建议应更新已有事件"""
        # 准备：提取的事件有高置信度匹配
        extracted = ExtractedEvent(
            event_id="evt_new_001",
            extracted_at=datetime.now(),
            slots=EventSlots(
                time="1968年",
                location="上海纺织厂",
                event="在纺织厂做挡车工，每天三班倒",
                feeling="很辛苦但充实"
            ),
            confidence=0.85,
            similarity_hints=[
                SimilarityHint(
                    candidate_id="evt_001",
                    confidence=0.88,
                    reason="同一件纺织厂工作事件",
                    matched_slots=["time", "location", "event"]
                )
            ]
        )

        # 执行
        result = merge_engine.merge(session_state, [extracted], "turn_001")

        # 验证
        assert len(result.updated_event_ids) == 1
        assert "evt_001" in result.updated_event_ids
        assert len(result.new_event_ids) == 0

        # 验证事件被更新
        updated_event = session_state.canonical_events["evt_001"]
        assert updated_event.merge_status == "updated_by_llm_hint"
        assert updated_event.feeling == "很辛苦但充实"

    def test_merge_with_medium_confidence_verifies_then_updates(
        self,
        merge_engine: MergeEngine,
        session_state: SessionState
    ):
        """中等置信度建议通过验证后更新"""
        extracted = ExtractedEvent(
            event_id="evt_new_001",
            extracted_at=datetime.now(),
            slots=EventSlots(
                time="1968年",
                location="上海纺织厂",
                event="在纺织厂工作"  # 相似但不完全相同
            ),
            confidence=0.7,
            similarity_hints=[
                SimilarityHint(
                    candidate_id="evt_001",
                    confidence=0.70,
                    reason="可能是同一件事",
                    matched_slots=["time", "location"]
                )
            ]
        )

        result = merge_engine.merge(session_state, [extracted], "turn_001")

        # 应该更新（相似度足够高通过验证）
        assert len(result.updated_event_ids) == 1
        updated_event = session_state.canonical_events["evt_001"]
        assert updated_event.merge_status == "updated_verified"

    def test_merge_with_low_confidence_creates_new(
        self,
        merge_engine: MergeEngine,
        session_state: SessionState
    ):
        """低置信度建议应创建新事件"""
        extracted = ExtractedEvent(
            event_id="evt_new_001",
            extracted_at=datetime.now(),
            slots=EventSlots(
                time="1970年",  # 不同时间
                location="北京",  # 不同地点
                event="完全不同的经历"
            ),
            confidence=0.6,
            similarity_hints=[
                SimilarityHint(
                    candidate_id="evt_001",
                    confidence=0.40,  # 低置信度
                    reason="不太确定"
                )
            ]
        )

        result = merge_engine.merge(session_state, [extracted], "turn_001")

        # 应该创建新事件
        assert len(result.new_event_ids) == 1
        assert len(result.updated_event_ids) == 0

    def test_merge_multiple_events(self, merge_engine: MergeEngine, session_state: SessionState):
        """一次合并多个事件"""
        extracted_list = [
            ExtractedEvent(  # 第一个：高置信度更新
                event_id="evt_new_001",
                extracted_at=datetime.now(),
                slots=EventSlots(time="1968年", location="上海", event="纺织厂工作"),
                similarity_hints=[
                    SimilarityHint(candidate_id="evt_001", confidence=0.90, reason="高匹配")
                ]
            ),
            ExtractedEvent(  # 第二个：无建议，创建新
                event_id="evt_new_002",
                extracted_at=datetime.now(),
                slots=EventSlots(time="1975年", location="北京", event="结婚"),
                similarity_hints=[]
            )
        ]

        result = merge_engine.merge(session_state, extracted_list, "turn_001")

        assert len(result.updated_event_ids) == 1
        assert len(result.new_event_ids) == 1
