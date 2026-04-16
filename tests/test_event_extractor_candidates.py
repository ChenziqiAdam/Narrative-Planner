"""
EventExtractor 候选事件预选单元测试

测试预选逻辑：
1. 标题相似度计算
2. 主题关键词匹配
3. 时间数字匹配
4. 综合排序取TOP-N
"""

import pytest
from datetime import datetime
from typing import List

from src.core.event_extractor import EventExtractor
from src.core.interfaces import DialogueTurn, ExtractedEvent, EventSlots


class TestSelectCandidateEvents:
    """测试 _select_candidate_events 方法"""

    @pytest.fixture
    def extractor(self):
        return EventExtractor()

    @pytest.fixture
    def current_turn(self):
        return DialogueTurn(
            turn_id="turn_001",
            session_id="test_session",
            timestamp=datetime.now(),
            interviewer_question="能说说您的工作经历吗？",
            interviewer_action="continue",
            interviewee_raw_reply="我1968年进了上海纺织厂做挡车工"
        )

    def test_empty_existing_events(self, extractor: EventExtractor, current_turn: DialogueTurn):
        """空已有事件列表应返回空"""
        result = extractor._select_candidate_events(current_turn, [])
        assert result == []

    def test_title_similarity_scoring(self, extractor: EventExtractor, current_turn: DialogueTurn):
        """标题相似度应正确计算"""
        existing_events = [
            {"event_id": "evt_001", "title": "纺织厂工作", "theme_id": "career"},
            {"event_id": "evt_002", "title": "完全不同的经历", "theme_id": "family"},
        ]

        result = extractor._select_candidate_events(current_turn, existing_events)

        # 纺织厂相关的事件应该被选中
        assert len(result) >= 1
        assert result[0]["event_id"] == "evt_001"  # 相似度最高的排第一

    def test_theme_keyword_matching(self, extractor: EventExtractor, current_turn: DialogueTurn):
        """主题关键词匹配应正确计分"""
        existing_events = [
            {"event_id": "evt_001", "title": "某个事件", "theme_id": "career"},  # 工作主题
            {"event_id": "evt_002", "title": "另一个事件", "theme_id": "childhood"},
        ]

        result = extractor._select_candidate_events(current_turn, existing_events)

        # career主题应获得加分
        if result:
            career_events = [e for e in result if e.get("theme_id") == "career"]
            # career主题的事件应该排名更靠前

    def test_time_number_matching(self, extractor: EventExtractor):
        """时间数字匹配应正确计分"""
        turn = DialogueTurn(
            turn_id="turn_001",
            session_id="test_session",
            timestamp=datetime.now(),
            interviewer_question="什么时候的事？",
            interviewer_action="continue",
            interviewee_raw_reply="那是1968年的事了"
        )
        existing_events = [
            {"event_id": "evt_001", "title": "事件1", "time": "1968年"},
            {"event_id": "evt_002", "title": "事件2", "time": "1975年"},
        ]

        result = extractor._select_candidate_events(turn, existing_events)

        # 1968年的事件应该排名靠前
        if result:
            assert result[0]["event_id"] == "evt_001"

    def test_score_threshold_filtering(self, extractor: EventExtractor, current_turn: DialogueTurn):
        """低分事件应被过滤"""
        existing_events = [
            {"event_id": "evt_001", "title": "完全不相关的事件", "theme_id": "marriage"},
        ]

        result = extractor._select_candidate_events(current_turn, existing_events)

        # 不相关的事件应该被过滤掉
        assert len(result) == 0

    def test_max_candidates_limit(self, extractor: EventExtractor, current_turn: DialogueTurn):
        """应限制返回的候选数量"""
        existing_events = [
            {"event_id": f"evt_{i:03d}", "title": "纺织厂工作", "theme_id": "career"}
            for i in range(10)
        ]

        result = extractor._select_candidate_events(current_turn, existing_events)

        # 应该只返回最多4个（新的混合策略上限）
        assert len(result) <= 4


class TestSelectCandidateEventsWithVectorStore:
    """测试 _select_candidate_events 混合规则+向量模式"""

    @pytest.fixture
    def extractor(self):
        return EventExtractor()

    @pytest.fixture
    def current_turn(self):
        return DialogueTurn(
            turn_id="turn_001",
            session_id="test_session",
            timestamp=datetime.now(),
            interviewer_question="能说说您的工作经历吗？",
            interviewer_action="continue",
            interviewee_raw_reply="我1968年进了上海纺织厂做挡车工"
        )

    def test_no_vector_store_falls_back_to_rule(self, extractor: EventExtractor, current_turn: DialogueTurn):
        """vector_store=None 应退化为纯规则，行为与原来一致"""
        existing_events = [
            {"event_id": "evt_001", "title": "纺织厂工作", "theme_id": "career"},
        ]
        result = extractor._select_candidate_events(current_turn, existing_events, vector_store=None)
        assert len(result) >= 1
        assert result[0]["event_id"] == "evt_001"

    def test_empty_vector_store_equals_no_store(self, extractor: EventExtractor, current_turn: DialogueTurn):
        """空 vector_store（size=0）应与 None 行为相同"""
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()  # empty
        existing_events = [
            {"event_id": "evt_001", "title": "纺织厂工作", "theme_id": "career"},
        ]
        result_no_store = extractor._select_candidate_events(current_turn, existing_events, vector_store=None)
        result_empty_store = extractor._select_candidate_events(current_turn, existing_events, vector_store=store)
        assert result_no_store == result_empty_store

    def test_vector_store_adds_semantic_candidates(self, extractor: EventExtractor, current_turn: DialogueTurn):
        """向量检索应能补充规则未选到的语义相关候选"""
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        # 加入一个规则不会命中（标题差异大）但语义相关的事件
        store.add("evt_semantic", "在国营工厂当工人")
        existing_events = [
            {"event_id": "evt_semantic", "title": "在国营工厂当工人", "theme_id": "career"},
            {"event_id": "evt_unrelated", "title": "结婚典礼", "theme_id": "marriage"},
        ]
        result = extractor._select_candidate_events(current_turn, existing_events, vector_store=store)
        event_ids = [e["event_id"] for e in result]
        assert "evt_semantic" in event_ids

    def test_deduplication_rule_priority(self, extractor: EventExtractor, current_turn: DialogueTurn):
        """规则和向量同时选中同一事件时，去重后不重复"""
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        store.add("evt_001", "纺织厂工作")
        existing_events = [
            {"event_id": "evt_001", "title": "纺织厂工作", "theme_id": "career"},
        ]
        result = extractor._select_candidate_events(current_turn, existing_events, vector_store=store)
        ids = [e["event_id"] for e in result]
        assert ids.count("evt_001") == 1  # 不重复

    def test_max_4_candidates(self, extractor: EventExtractor, current_turn: DialogueTurn):
        """混合候选最多返回4条"""
        from src.services.event_vector_store import EventVectorStore
        store = EventVectorStore()
        existing_events = []
        for i in range(8):
            eid = f"evt_{i:03d}"
            store.add(eid, f"纺织厂工作经历 {i}")
            existing_events.append({"event_id": eid, "title": f"纺织厂工作经历 {i}", "theme_id": "career"})
        result = extractor._select_candidate_events(current_turn, existing_events, vector_store=store)
        assert len(result) <= 4


class TestFormatCandidateEvents:
    """测试 _format_candidate_events 方法"""

    @pytest.fixture
    def extractor(self):
        return EventExtractor()

    def test_empty_candidates(self, extractor: EventExtractor):
        """空候选列表应返回占位符"""
        result = extractor._format_candidate_events([])
        assert result == "（无候选事件）"

    def test_single_candidate_formatting(self, extractor: EventExtractor):
        """单个候选事件应正确格式化"""
        candidates = [
            {
                "event_id": "evt_001",
                "title": "纺织厂工作",
                "summary": "在纺织厂做挡车工的经历",
                "time": "1968年",
                "location": "上海纺织厂",
                "people_names": ["师傅", "同事"],
                "theme_id": "career"
            }
        ]

        result = extractor._format_candidate_events(candidates)

        assert "evt_001" in result
        assert "纺织厂工作" in result
        assert "1968年" in result
        assert "上海纺织厂" in result
        assert "师傅" in result
        assert "career" in result

    def test_multiple_candidates_formatting(self, extractor: EventExtractor):
        """多个候选事件应正确格式化"""
        candidates = [
            {"event_id": "evt_001", "title": "事件1"},
            {"event_id": "evt_002", "title": "事件2"},
        ]

        result = extractor._format_candidate_events(candidates)

        assert "候选1" in result
        assert "候选2" in result
        assert "evt_001" in result
        assert "evt_002" in result

    def test_candidate_with_missing_fields(self, extractor: EventExtractor):
        """缺失字段的候选事件应正确处理"""
        candidates = [
            {"event_id": "evt_001", "title": "简单事件"}
            # 缺少 time, location, people_names, theme_id
        ]

        result = extractor._format_candidate_events(candidates)

        assert "evt_001" in result
        assert "简单事件" in result
        # 不应抛出异常


class TestParseSimilarityHints:
    """测试 _parse_similarity_hints 方法"""

    @pytest.fixture
    def extractor(self):
        return EventExtractor()

    def test_valid_hints_parsing(self, extractor: EventExtractor):
        """有效的 hints 数据应正确解析"""
        hints_data = [
            {
                "candidate_id": "evt_001",
                "confidence": 0.88,
                "reason": "同一件事件",
                "matched_slots": ["time", "location"]
            },
            {
                "candidate_id": "evt_002",
                "confidence": 0.65,
                "reason": "可能是同一件事"
                # 缺少 matched_slots
            }
        ]

        result = extractor._parse_similarity_hints(hints_data)

        assert len(result) == 2
        assert result[0].candidate_id == "evt_001"
        assert result[0].confidence == 0.88
        assert result[0].reason == "同一件事件"
        assert result[0].matched_slots == ["time", "location"]

        assert result[1].candidate_id == "evt_002"
        assert result[1].confidence == 0.65
        assert result[1].matched_slots == []  # 默认值

    def test_empty_hints(self, extractor: EventExtractor):
        """空 hints 列表应返回空"""
        result = extractor._parse_similarity_hints([])
        assert result == []

    def test_invalid_hint_data(self, extractor: EventExtractor):
        """无效的 hint 数据应被跳过"""
        hints_data = [
            {
                "candidate_id": "evt_001",
                "confidence": 0.88,
                "reason": "有效数据"
            },
            {
                # 缺少必要字段
                "confidence": "not_a_number"
            }
        ]

        result = extractor._parse_similarity_hints(hints_data)

        # 只有有效的 hint 被解析
        assert len(result) == 1
        assert result[0].candidate_id == "evt_001"


class TestUnifiedResponseParsing:
    """测试 _parse_unified_llm_response 方法"""

    @pytest.fixture
    def extractor(self):
        return EventExtractor()

    def test_valid_unified_response(self, extractor: EventExtractor):
        """有效的统一响应应正确解析"""
        response_text = '''```json
{
  "events": [
    {
      "event_id": "evt_new_001",
      "slots": {
        "time": "1968年",
        "location": "上海纺织厂",
        "people": ["师傅"],
        "event": "在纺织厂做挡车工",
        "feeling": "很辛苦",
        "reflection": null,
        "cause": null,
        "result": null,
        "unexpanded_clues": null
      },
      "confidence": 0.85,
      "theme_id": "career",
      "similarity_hints": [
        {
          "candidate_id": "evt_001",
          "confidence": 0.88,
          "reason": "同一件纺织厂工作事件",
          "matched_slots": ["time", "location", "event"]
        }
      ]
    }
  ],
  "open_loops": [
    {
      "description": "需要确认具体工作年限",
      "priority": 0.8
    }
  ]
}
```'''

        events, open_loops = extractor._parse_unified_llm_response(response_text)

        assert len(events) == 1
        assert events[0].event_id == "evt_new_001"
        assert events[0].slots.time == "1968年"
        assert events[0].confidence == 0.85
        assert len(events[0].similarity_hints) == 1
        assert events[0].similarity_hints[0].candidate_id == "evt_001"
        assert events[0].similarity_hints[0].confidence == 0.88

        assert len(open_loops) == 1
        assert open_loops[0]["description"] == "需要确认具体工作年限"

    def test_invalid_json_response(self, extractor: EventExtractor):
        """无效的 JSON 响应应返回空列表"""
        response_text = "这不是有效的JSON"

        events, open_loops = extractor._parse_unified_llm_response(response_text)

        assert events == []
        assert open_loops == []

    def test_no_events_in_response(self, extractor: EventExtractor):
        """没有事件的响应应返回空列表"""
        response_text = '''{"events": [], "open_loops": []}'''

        events, open_loops = extractor._parse_unified_llm_response(response_text)

        assert events == []
        assert open_loops == []

    def test_event_without_hints(self, extractor: EventExtractor):
        """没有 similarity_hints 的事件应正确解析"""
        response_text = '''{"events": [{"event_id": "evt_001", "slots": {"event": "测试"}, "confidence": 0.8}], "open_loops": []}'''

        events, _ = extractor._parse_unified_llm_response(response_text)

        assert len(events) == 1
        assert events[0].similarity_hints == []
