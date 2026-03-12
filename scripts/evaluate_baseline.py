#!/usr/bin/env python3
"""
Baseline 访谈评测脚本

评估指标：
1) 单问题率：助手回复是否严格为单个问题
2) 追问深度：围绕同一话题连续追问的平均深度（启发式）
3) 阶段覆盖率：人生阶段（童年/求学/工作/家庭/转折/感悟）的覆盖情况
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


STAGE_KEYWORDS: Dict[str, Sequence[str]] = {
    "童年": ("童年", "小时候", "儿时", "小的时候", "少年", "家乡"),
    "求学": ("读书", "上学", "学校", "老师", "同学", "大学", "中学", "小学"),
    "工作": ("工作", "单位", "职业", "岗位", "同事", "创业", "公司", "工厂"),
    "家庭": ("家庭", "结婚", "爱人", "配偶", "孩子", "父母", "婚姻", "儿女"),
    "转折": ("转折", "变化", "困难", "挫折", "机遇", "决定", "关键", "选择"),
    "感悟": ("感悟", "价值观", "后悔", "骄傲", "遗憾", "建议", "想法", "心得"),
}

STOPWORDS = {
    "然后",
    "就是",
    "那个",
    "这个",
    "我们",
    "你们",
    "他们",
    "自己",
    "觉得",
    "已经",
    "因为",
    "所以",
    "如果",
    "但是",
    "还是",
    "非常",
    "比较",
    "一个",
    "一些",
    "没有",
    "时候",
    "事情",
    "什么",
    "怎么",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="评测 Baseline 访谈质量")
    parser.add_argument("--input", required=True, help="输入文件路径（.json 或 .txt）")
    parser.add_argument(
        "--output-json",
        default="",
        help="可选：将评测结果写入 JSON 文件",
    )
    return parser.parse_args()


def load_turns(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"找不到输入文件: {path}")

    if path.suffix.lower() == ".json":
        return _load_from_json(path)
    return _load_from_text(path)


def _load_from_json(path: Path) -> List[Dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, dict):
        raw = payload.get("messages") or payload.get("conversation") or payload.get("transcript") or []
    else:
        raw = []

    turns: List[Dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role in {"system", ""} or not content:
            continue
        if role not in {"assistant", "user"}:
            continue
        turns.append({"role": role, "content": content})

    return turns


def _load_from_text(path: Path) -> List[Dict[str, str]]:
    content = path.read_text(encoding="utf-8")
    turns: List[Dict[str, str]] = []

    pattern = re.compile(r"^\s*(老人|用户|User|助手|Assistant)\s*[：:]\s*(.+?)\s*$", re.IGNORECASE)
    for line in content.splitlines():
        m = pattern.match(line)
        if not m:
            continue
        speaker, text = m.group(1), m.group(2).strip()
        if not text:
            continue
        role = "assistant" if speaker.lower() in {"助手", "assistant"} else "user"
        turns.append({"role": role, "content": text})

    return turns


def split_sentences(text: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"[。！？!?]\s*", text) if p.strip()]
    return parts


def is_single_question(text: str) -> bool:
    sentences = split_sentences(text)
    if len(sentences) != 1:
        return False
    return text.strip().endswith(("？", "?"))


def extract_tokens(text: str) -> List[str]:
    chunks = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text)
    tokens: List[str] = []

    for chunk in chunks:
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", chunk):
            # 简单中文切分：用 2-gram / 3-gram 增强重叠匹配稳定性（免依赖分词库）
            length = len(chunk)
            for n in (2, 3):
                if length < n:
                    continue
                for i in range(length - n + 1):
                    gram = chunk[i : i + n]
                    if gram not in STOPWORDS:
                        tokens.append(gram)
        else:
            token = chunk.lower()
            if token not in STOPWORDS:
                tokens.append(token)

    return tokens


def classify_stage(text: str) -> str:
    for stage, keywords in STAGE_KEYWORDS.items():
        if any(k in text for k in keywords):
            return stage
    return "未识别"


def top_keywords(text: str, k: int = 8) -> List[str]:
    tokens = [t for t in extract_tokens(text) if len(t) >= 2]
    counts = Counter(tokens)
    return [w for w, _ in counts.most_common(k)]


def evaluate(turns: Sequence[Dict[str, str]]) -> Dict[str, object]:
    assistant_turns = [t["content"] for t in turns if t["role"] == "assistant"]
    user_turns = [t["content"] for t in turns if t["role"] == "user"]

    if not assistant_turns:
        raise ValueError("输入中没有 assistant 回合，无法评测。")

    single_q_hits = sum(1 for text in assistant_turns if is_single_question(text))
    single_q_rate = single_q_hits / len(assistant_turns)

    stages = [classify_stage(text) for text in assistant_turns]
    covered = sorted({s for s in stages if s != "未识别"})
    stage_coverage_rate = len(covered) / len(STAGE_KEYWORDS)

    # 追问深度（启发式）：
    # 若 assistant 问题与上一条 user 回答存在关键词重叠，视为一次“跟进追问”。
    follow_depth_runs: List[int] = []
    current_depth = 0
    last_user_keywords: List[str] = []

    for turn in turns:
        role = turn["role"]
        text = turn["content"]
        if role == "user":
            last_user_keywords = top_keywords(text)
            continue
        overlap = 0
        if last_user_keywords:
            overlap = sum(1 for kw in last_user_keywords if kw in text)

        if overlap > 0:
            current_depth += 1
        else:
            if current_depth > 0:
                follow_depth_runs.append(current_depth)
            current_depth = 0

    if current_depth > 0:
        follow_depth_runs.append(current_depth)

    avg_follow_up_depth = round(
        (sum(follow_depth_runs) / len(follow_depth_runs)) if follow_depth_runs else 0.0,
        3,
    )
    follow_up_hit_rate = round(
        (sum(follow_depth_runs) / len(assistant_turns)) if assistant_turns else 0.0,
        3,
    )

    return {
        "counts": {
            "total_turns": len(turns),
            "assistant_turns": len(assistant_turns),
            "user_turns": len(user_turns),
        },
        "metrics": {
            "single_question_rate": round(single_q_rate, 3),
            "avg_follow_up_depth": avg_follow_up_depth,
            "follow_up_hit_rate": follow_up_hit_rate,
            "stage_coverage_rate": round(stage_coverage_rate, 3),
        },
        "stage_coverage": {
            "covered_stages": covered,
            "missing_stages": sorted([s for s in STAGE_KEYWORDS if s not in covered]),
            "assistant_stage_sequence": stages,
        },
        "notes": [
            "追问深度和命中率基于关键词重叠启发式计算，用于版本间相对比较。",
            "若对话较短，阶段覆盖率会天然偏低，建议至少 12 轮以上再比较。",
        ],
    }


def print_report(result: Dict[str, object]) -> None:
    counts = result["counts"]  # type: ignore[assignment]
    metrics = result["metrics"]  # type: ignore[assignment]
    coverage = result["stage_coverage"]  # type: ignore[assignment]

    print("=== Baseline 访谈评测报告 ===")
    print(f"总轮次: {counts['total_turns']} | 用户: {counts['user_turns']} | 助手: {counts['assistant_turns']}")
    print("")
    print("核心指标:")
    print(f"- 单问题率: {metrics['single_question_rate']:.3f}")
    print(f"- 追问深度(平均连续跟进): {metrics['avg_follow_up_depth']:.3f}")
    print(f"- 追问命中率: {metrics['follow_up_hit_rate']:.3f}")
    print(f"- 阶段覆盖率: {metrics['stage_coverage_rate']:.3f}")
    print("")
    print("阶段覆盖:")
    print(f"- 已覆盖: {', '.join(coverage['covered_stages']) if coverage['covered_stages'] else '无'}")
    print(f"- 未覆盖: {', '.join(coverage['missing_stages']) if coverage['missing_stages'] else '无'}")


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    turns = load_turns(input_path)
    result = evaluate(turns)
    print_report(result)

    if args.output_json:
        out_path = Path(args.output_json)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("")
        print(f"JSON 结果已写入: {out_path}")


if __name__ == "__main__":
    main()
