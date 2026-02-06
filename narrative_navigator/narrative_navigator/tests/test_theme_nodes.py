#!/usr/bin/env python3
"""
测试脚本：验证 McAdams 23 主题的加载和图谱初始化

运行方式:
    python -m tests.test_theme_nodes
    或
    python tests/test_theme_nodes.py
"""

import sys
import logging
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_theme_loading():
    """测试主题加载"""
    logger.info("=== 测试主题加载 ===")

    from core import ThemeLoader, NodeStatus, Domain

    # 创建加载器
    loader = ThemeLoader()

    # 加载主题
    themes = loader.load()

    # 验证数量
    assert len(themes) == 23, f"期望加载23个主题，实际加载了{len(themes)}个"
    logger.info(f"✓ 成功加载 {len(themes)} 个主题")

    # 验证每个主题的初始状态
    for theme_id, theme in themes.items():
        assert theme.status == NodeStatus.PENDING, f"{theme_id} 状态应为 PENDING"
        assert theme.exploration_depth == 0, f"{theme_id} 深度应为 0"
        assert theme.get_completion_ratio() == 0.0, f"{theme_id} 完成度应为 0"

    logger.info("✓ 所有主题初始状态正确")

    # 验证主题ID格式
    for i in range(1, 24):
        theme_id = f"THEME_{i:02d}"
        assert theme_id in themes or any(t.startswith(theme_id) for t in themes.keys()), \
            f"缺少主题: {theme_id}"

    logger.info("✓ 主题ID格式正确")

    # 验证领域分布
    domain_summary = loader.get_domains_summary()
    expected_counts = {
        "life_chapters": 1,
        "key_scenes": 8,
        "future_scripts": 3,
        "challenges": 4,
        "personal_ideology": 4,
        "context_management": 3,
    }

    for domain, expected_count in expected_counts.items():
        actual_count = domain_summary[domain]["count"]
        assert actual_count == expected_count, \
            f"{domain} 期望 {expected_count} 个主题，实际 {actual_count} 个"

    logger.info("✓ 领域分布正确")

    return True


def test_graph_manager():
    """测试图谱管理器"""
    logger.info("\n=== 测试图谱管理器 ===")

    from core import GraphManager, EventNode, NodeStatus

    # 创建图谱管理器
    manager = GraphManager(use_networkx=False)  # 使用简单结构

    # 验证初始化
    assert len(manager.theme_nodes) == 23, "应初始化23个主题节点"
    assert len(manager.event_nodes) == 0, "初始应无事件节点"
    logger.info("✓ 图谱初始化正确")

    # 验证覆盖率
    coverage = manager.calculate_coverage()
    assert coverage["overall"] == 0.0, "初始覆盖率应为0"
    logger.info(f"✓ 初始覆盖率: {coverage['overall']}")

    # 测试添加事件节点
    event = EventNode(
        event_id="test_event_001",
        theme_id="THEME_01_LIFE_CHAPTERS",
        title="测试事件",
        description="这是一个测试事件"
    )
    manager.add_event_node(event, "THEME_01_LIFE_CHAPTERS")

    assert len(manager.event_nodes) == 1, "应添加1个事件节点"
    logger.info("✓ 事件节点添加成功")

    # 验证主题状态更新
    theme = manager.theme_nodes["THEME_01_LIFE_CHAPTERS"]
    assert theme.status == NodeStatus.MENTIONED, "添加事件后主题应变为 MENTIONED"
    assert theme.exploration_depth == 1, "添加事件后主题深度应自动增加"
    logger.info("✓ 主题状态更新正确，深度自动增加")

    # 验证覆盖率变化（添加事件后覆盖率应变化）
    coverage = manager.calculate_coverage()
    assert coverage["overall"] > 0, "添加事件后覆盖率应大于0"
    logger.info(f"✓ 覆盖率更新: {coverage['overall']}")

    # 测试获取下一个候选主题
    next_theme = manager.get_next_candidate_theme()
    assert next_theme is not None, "应能获取下一个候选主题"
    logger.info(f"✓ 下一个候选主题: {next_theme.title}")

    # 测试标记主题完成
    manager.mark_theme_exhausted("THEME_01_LIFE_CHAPTERS")
    assert theme.status == NodeStatus.EXHAUSTED, "主题应标记为 EXHAUSTED"
    logger.info("✓ 主题完成状态更新正确")

    return True


def test_theme_state_transitions():
    """测试主题状态转换"""
    logger.info("\n=== 测试主题状态转换 ===")

    from core import ThemeNode, Domain, NodeStatus

    theme = ThemeNode(
        theme_id="TEST_THEME",
        domain=Domain.LIFE_CHAPTERS,
        title="测试主题",
        description="用于测试状态转换"
    )

    # 初始状态
    assert theme.status == NodeStatus.PENDING
    assert theme.get_completion_ratio() == 0.0
    logger.info("✓ 初始状态: PENDING")

    # 标记为已提及
    theme.mark_mentioned()
    assert theme.status == NodeStatus.MENTIONED
    assert theme.first_mentioned_at is not None
    logger.info("✓ 状态转换: PENDING -> MENTIONED")

    # 增加深度
    theme.increment_depth()
    assert theme.exploration_depth == 1
    theme.increment_depth()
    assert theme.exploration_depth == 2
    logger.info("✓ 深度更新正确")

    # 更新槽位
    theme.update_slot("test_slot", True)
    assert theme.slots_filled["test_slot"] == True
    logger.info("✓ 槽位更新正确")

    # 标记为已完成
    theme.mark_exhausted()
    assert theme.status == NodeStatus.EXHAUSTED
    assert theme.exhausted_at is not None
    logger.info("✓ 状态转换: MENTIONED -> EXHAUSTED")

    return True


def test_seed_questions():
    """测试种子问题"""
    logger.info("\n=== 测试种子问题 ===")

    from core import ThemeLoader

    loader = ThemeLoader()
    themes = loader.load()

    # 检查每个主题都有种子问题
    themes_with_questions = 0
    for theme_id, theme in themes.items():
        if theme.seed_questions:
            themes_with_questions += 1
            logger.info(f"  {theme_id}: {len(theme.seed_questions)} 个问题")

    # 大部分主题应该有种子问题（上下文管理的3个主题可能没有）
    assert themes_with_questions >= 20, f"至少应有20个主题有种子问题，实际{themes_with_questions}个"
    logger.info(f"✓ {themes_with_questions} 个主题有种子问题")

    # 测试获取下一个问题
    theme = themes["THEME_01_LIFE_CHAPTERS"]
    initial_index = theme.current_question_index
    question = theme.get_next_seed_question()
    assert question is not None, "应能获取种子问题"
    assert theme.current_question_index > initial_index, "问题索引应递增"
    logger.info(f"✓ 种子问题获取正确: {question[:50]}...")

    return True


def main():
    """运行所有测试"""
    logger.info("开始测试 McAdams 23 主题实现\n")

    tests = [
        test_theme_loading,
        test_graph_manager,
        test_theme_state_transitions,
        test_seed_questions,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
        except AssertionError as e:
            logger.error(f"✗ 测试失败: {e}")
            failed += 1
        except Exception as e:
            logger.error(f"✗ 测试出错: {e}")
            failed += 1

    logger.info(f"\n{'='*50}")
    logger.info(f"测试结果: {passed} 通过, {failed} 失败")
    logger.info(f"{'='*50}")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
