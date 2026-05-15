import json
import os
import sys
import time
import uuid
import re
from datetime import datetime

# 离线模式：防止 sentence-transformers 尝试从 HuggingFace 下载模型
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, Response, jsonify, render_template_string, request, session

from src.agents.baseline_agent import BaselineAgent as InterviewerAgent
from src.agents.interviewee_agent import IntervieweeAgent, extract_interviewee_reply
from src.agents.planner_interview_agent import PlannerInterviewAgentSync
from src.legacy.planner_interview_agent import LegacyPlannerInterviewAgentSync
from src.config import Config
from src.orchestration.baseline_evaluation_runtime import BaselineEvaluationRuntime
from src.services.interview_logger import (
    CoverageLog,
    DialogueLog,
    EvaluationLog,
    PlannerDecisionLog,
    SessionSummary,
    TurnLogData,
    create_baseline_logger,
    create_planner_logger,
)

app = Flask(__name__)
app.secret_key = os.urandom(24)
_GRAPH_RESET_ON_PORT_OPEN_DONE = False

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "prompts/roles/elder_profile_1.json")

# Per-session agent pairs
_sessions: dict[str, dict] = {}


def _reset_graphrag_once_for_server() -> None:
    """Reset GraphRAG once per Flask server process, before serving traffic."""
    global _GRAPH_RESET_ON_PORT_OPEN_DONE
    if _GRAPH_RESET_ON_PORT_OPEN_DONE:
        return
    _GRAPH_RESET_ON_PORT_OPEN_DONE = True

    if os.getenv("RESET_GRAPHRAG_ON_SERVER_START", "true").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        app.logger.info("GraphRAG startup reset disabled by RESET_GRAPHRAG_ON_SERVER_START")
        return

    try:
        from src.storage.neo4j.manager import Neo4jGraphManager

        neo4j = Neo4jGraphManager()
        neo4j.initialize()
        reset_result = neo4j.reset_interview_graph(preserve_topics=True)
        neo4j.sync_themes_to_neo4j()
        neo4j.close()
        app.logger.info("GraphRAG reset on server start: %s", reset_result)
    except Exception:
        app.logger.exception("GraphRAG reset on server start failed")


@app.before_request
def _reset_graphrag_before_first_request():
    _reset_graphrag_once_for_server()


def get_session_agents(session_id: str) -> dict:
    if session_id not in _sessions:
        save_path = os.path.join(os.path.dirname(__file__), f"data/raw/session_{session_id}.txt")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        _sessions[session_id] = {
            "interviewer": InterviewerAgent(),
            "interviewee": IntervieweeAgent(
                profile_path=PROFILE_PATH,
                save_path=save_path,
            ),
            "history": [],   # list of {"role": "interviewer"|"interviewee", "text": str}
            "save_path": save_path,
            "mode": "ai",    # "ai" or "user"
            "turn_count": 0,
        }
    return _sessions[session_id]


def extract_reply(raw: str) -> str:
    """Extract the 'reply' field if the response is JSON, otherwise return raw."""
    return extract_interviewee_reply(raw)

    try:
        # strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(cleaned)
        if isinstance(data, dict):
            for key in ("reply", "response", "answer"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return "这个问题我得再想想。"
        if isinstance(data, str):
            return data.strip()
    except (json.JSONDecodeError, ValueError):
        pass
    return (raw or "").strip()


def _build_compare_interviewee(session_data: dict) -> IntervieweeAgent:
    """Create a compare-mode interviewee instance for one session only."""
    cached = session_data.get("_interviewee_agent")
    if cached is not None:
        return cached

    interviewee = IntervieweeAgent(profile_path=PROFILE_PATH)
    interviewee.initialize_conversation(session_data.get("elder_info", {}))
    session_data["_interviewee_agent"] = interviewee
    session_data["_interviewee_restored_pairs"] = 0
    return interviewee


def _restore_compare_interviewee_history(session_data: dict, interviewee: IntervieweeAgent) -> None:
    """Replay only dialogue pairs that the cached interviewee has not seen."""
    restored_pairs = int(session_data.get("_interviewee_restored_pairs", 0) or 0)
    seen_pairs = 0

    for index in range(len(session_data.get("history", [])) - 1):
        current = session_data["history"][index]
        following = session_data["history"][index + 1]
        if current.get("role") != "interviewer" or following.get("role") != "interviewee":
            continue

        seen_pairs += 1
        if seen_pairs <= restored_pairs:
            continue

        # This is restoration from the app session, not a newly generated turn;
        # avoid triggering summarization LLM calls while catching up.
        interviewee.record_turn(
            current.get("text", ""),
            following.get("text", ""),
            allow_compression=False,
        )

    session_data["_interviewee_restored_pairs"] = seen_pairs


def _count_compare_interviewee_pairs(session_data: dict) -> int:
    count = 0
    history = session_data.get("history", [])
    for index in range(len(history) - 1):
        if (
            history[index].get("role") == "interviewer"
            and history[index + 1].get("role") == "interviewee"
        ):
            count += 1
    return count


def _run_compare_interviewee_turn(interviewee: IntervieweeAgent, question: str) -> tuple[str, list[dict], dict]:
    """Returns (answer, memory_calls, timing) where memory_calls is the tool call log."""
    prompt = interviewee._load_step_prompt(interviewee.history, question)
    _t0 = time.perf_counter()
    raw_reply, memory_calls = interviewee.step_with_metadata(prompt)
    _total_ms = (time.perf_counter() - _t0) * 1000
    answer = extract_reply(raw_reply)
    interviewee.record_turn(question, answer)
    return answer, memory_calls, {"interviewee_total_ms": round(_total_ms, 1)}


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "session_id" not in session:
        session["session_id"] = uuid.uuid4().hex
    return render_template_string(HTML)


@app.route("/start", methods=["POST"])
def start():
    """Initialize a new interview session with optional basic_info."""
    if "session_id" not in session:
        session["session_id"] = uuid.uuid4().hex
    sid = session["session_id"]

    # Reset session
    if sid in _sessions:
        del _sessions[sid]

    data = request.get_json(force=True)
    basic_info = (data.get("basic_info") or "").strip()
    if not basic_info:
        return jsonify({"error": "请提供受访者基本信息"}), 400

    mode = (data.get("mode") or "ai").strip()  # "ai" or "user"

    agents = get_session_agents(sid)
    agents["interviewer"].initialize_conversation(basic_info)
    agents["basic_info"] = basic_info
    agents["mode"] = mode

    # Get the opening question
    result = agents["interviewer"].get_next_question()
    question = result.get("question", "") if isinstance(result, dict) else result
    agents["history"].append({"role": "interviewer", "text": question})

    return jsonify({"question": question, "mode": mode})


@app.route("/user_reply", methods=["POST"])
def user_reply():
    """
    User-mode: accept user's answer, store it, then get interviewer's next question.
    Returns: {"action": str, "question": str, "done": bool}
    """
    sid = session.get("session_id")
    if not sid or sid not in _sessions:
        return jsonify({"error": "请先调用 /start 初始化访谈"}), 400

    agents = _sessions[sid]
    if agents.get("mode") != "user":
        return jsonify({"error": "当前不是用户模式"}), 400

    data = request.get_json(force=True)
    answer = (data.get("answer") or "").strip()
    if not answer:
        return jsonify({"error": "回答不能为空"}), 400

    # Record user's answer
    agents["history"].append({"role": "interviewee", "text": answer})

    # Interviewer gets next question
    result = agents["interviewer"].get_next_question(answer)
    question = result.get("question", "") if isinstance(result, dict) else result
    action = result.get("action", "continue") if isinstance(result, dict) else "continue"
    agents["turn_count"] += 1

    if agents["turn_count"] >= 50:
        end_text = "感谢您的分享，访谈到此结束。"
        agents["history"].append({"role": "interviewer", "text": end_text})

        # Save full transcript
        transcript = "\n".join(
            f"{'访谈者' if m['role'] == 'interviewer' else '受访者'}: {m['text']}"
            for m in agents["history"]
        )
        with open(agents["save_path"], "w", encoding="utf-8") as f:
            f.write(transcript)

        return jsonify({"action": "end", "question": end_text, "done": True})

    agents["history"].append({"role": "interviewer", "text": question})
    return jsonify({"action": action, "question": question, "done": False})


@app.route("/auto_interview", methods=["GET"])
def auto_interview():
    """
    SSE stream: runs until the interviewer decides to end.
    Each event: {"role": "interviewer"|"interviewee", "action": str, "text": str}
    Final event: {"role": "done"}
    """
    sid = session.get("session_id")
    if not sid or sid not in _sessions:
        return jsonify({"error": "请先调用 /start 初始化访谈"}), 400

    agents = _sessions[sid]

    def generate():
        last_question = agents["history"][-1]["text"]

        while True:
            # Interviewee answers
            prompt = agents["interviewee"]._load_step_prompt(agents["interviewee"].history, last_question)
            raw_answer, memory_calls = agents["interviewee"].step_with_metadata(prompt)
            answer = extract_reply(raw_answer)
            agents["interviewee"].history += f"Q: {last_question}\nA: {answer}\n"
            agents["history"].append({"role": "interviewee", "text": answer})
            yield f"data: {json.dumps({'role': 'interviewee', 'action': 'answer', 'text': answer, 'memory_calls': memory_calls}, ensure_ascii=False)}\n\n"

            # Interviewer gets next question
            result = agents["interviewer"].get_next_question(answer)
            question = result.get("question", "") if isinstance(result, dict) else result
            iv_action = result.get("action", "continue") if isinstance(result, dict) else "continue"
            agents["turn_count"] += 1

            if agents["turn_count"] >= 50:
                agents["history"].append({"role": "interviewer", "text": "感谢您的分享，访谈到此结束。"})
                yield f"data: {json.dumps({'role': 'interviewer', 'action': 'end', 'text': '感谢您的分享，访谈到此结束。'}, ensure_ascii=False)}\n\n"
                break

            agents["history"].append({"role": "interviewer", "text": question})
            last_question = question
            yield f"data: {json.dumps({'role': 'interviewer', 'action': iv_action, 'text': question}, ensure_ascii=False)}\n\n"

        # Save full transcript
        transcript = "\n".join(
            f"{'访谈者' if m['role'] == 'interviewer' else '受访者'}: {m['text']}"
            for m in agents["history"]
        )
        with open(agents["save_path"], "w", encoding="utf-8") as f:
            f.write(transcript)

        yield f"data: {json.dumps({'role': 'done'}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


# ── HTML ─────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>忆述 · 传记访谈系统</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root {
  --brand: #5c3d2e;
  --brand-light: #7a5243;
  --brand-bg: #fdf8f4;
  --accent: #c8956c;
  --accent-hover: #b07a53;
  --surface: #ffffff;
  --border: #e8e0d8;
  --text-primary: #2d1f17;
  --text-secondary: #6b5a50;
  --text-muted: #a08a7e;
  --radius-sm: 8px;
  --radius-md: 14px;
  --radius-lg: 20px;
  --shadow-card: 0 2px 12px rgba(92,61,46,.08), 0 1px 3px rgba(92,61,46,.05);
  --shadow-hover: 0 8px 28px rgba(92,61,46,.14), 0 2px 8px rgba(92,61,46,.07);
  --transition: 0.22s cubic-bezier(.4,0,.2,1);
}
body { font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", system-ui, sans-serif; background: var(--brand-bg); height: 100vh; display: flex; flex-direction: column; overflow: hidden; color: var(--text-primary); font-size: 15px; line-height: 1.6; }

/* ── Header ── */
header { background: var(--brand); color: #fff; padding: 0 28px; height: 56px; display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; box-shadow: 0 1px 0 rgba(0,0,0,.12); }
.header-brand { display: flex; align-items: center; gap: 10px; }
.header-logo { width: 28px; height: 28px; opacity: .92; }
header h1 { font-size: 1.05rem; font-weight: 700; letter-spacing: .02em; }
#status-badge { font-size: .78rem; padding: 4px 12px; border-radius: 20px; background: rgba(255,255,255,.18); letter-spacing: .01em; }

/* ── Landing / Setup ── */
#setup { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 32px 20px; gap: 32px; overflow-y: auto; }

.landing-hero { text-align: center; max-width: 540px; }
.landing-hero h2 { font-size: 1.7rem; font-weight: 700; color: var(--text-primary); line-height: 1.3; margin-bottom: 10px; }
.landing-hero p { font-size: .97rem; color: var(--text-secondary); max-width: 400px; margin: 0 auto; }

/* Mode cards */
.mode-cards { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; max-width: 760px; width: 100%; }
.mode-card { flex: 1; min-width: 200px; max-width: 230px; background: var(--surface); border: 2px solid var(--border); border-radius: var(--radius-lg); padding: 24px 20px 22px; cursor: pointer; text-align: center; transition: border-color var(--transition), box-shadow var(--transition), transform var(--transition); box-shadow: var(--shadow-card); user-select: none; }
.mode-card:hover { border-color: var(--accent); box-shadow: var(--shadow-hover); transform: translateY(-3px); }
.mode-card.selected { border-color: var(--brand); background: #fdf5ef; box-shadow: var(--shadow-hover); transform: translateY(-3px); }
.mode-card.link-card { text-decoration: none; color: inherit; display: flex; flex-direction: column; align-items: center; }
.mode-card-icon { width: 52px; height: 52px; margin: 0 auto 14px; background: var(--brand-bg); border-radius: 14px; display: flex; align-items: center; justify-content: center; transition: background var(--transition); }
.mode-card:hover .mode-card-icon, .mode-card.selected .mode-card-icon { background: #f0e6dc; }
.mode-card-icon svg { color: var(--brand); }
.mode-card-title { font-size: 1rem; font-weight: 700; color: var(--text-primary); margin-bottom: 6px; }
.mode-card-desc { font-size: .82rem; color: var(--text-muted); line-height: 1.5; }
.mode-card input[type=radio] { display: none; }

/* Info form (shown after mode select) */
#info-form { width: 100%; max-width: 520px; display: none; flex-direction: column; gap: 14px; animation: fadeUp .25s ease; }
@keyframes fadeUp { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
#info-form label { font-size: .88rem; font-weight: 600; color: var(--text-secondary); margin-bottom: 2px; display: block; }
#basic-info { width: 100%; height: 96px; padding: 12px 14px; border: 1.5px solid var(--border); border-radius: var(--radius-md); font-size: .94rem; font-family: inherit; resize: vertical; background: var(--surface); color: var(--text-primary); line-height: 1.6; transition: border-color var(--transition); }
#basic-info:focus { outline: none; border-color: var(--brand); box-shadow: 0 0 0 3px rgba(92,61,46,.1); }
#start-btn { padding: 13px 24px; background: var(--brand); color: #fff; border: none; border-radius: var(--radius-md); font-size: 1rem; font-weight: 600; cursor: pointer; transition: background var(--transition), opacity var(--transition); letter-spacing: .01em; }
#start-btn:hover { background: var(--brand-light); }
#start-btn:disabled { opacity: .5; cursor: not-allowed; }

/* ── Main layout ── */
#main { flex: 1; display: none; flex-direction: row; overflow: hidden; }

/* Chat panel */
#chat-panel { flex: 1; display: flex; flex-direction: column; }
.chat-panel-header { padding: 12px 22px; font-size: .9rem; font-weight: 600; color: var(--brand); background: #faf6f2; border-bottom: 1px solid var(--border); flex-shrink: 0; display: flex; align-items: center; gap: 8px; }
.chat-panel-header svg { color: var(--brand); opacity: .7; }
#chat { flex: 1; overflow-y: auto; padding: 22px; display: flex; flex-direction: column; gap: 16px; }
#chat::-webkit-scrollbar { width: 5px; }
#chat::-webkit-scrollbar-thumb { background: rgba(92,61,46,.15); border-radius: 3px; }

.msg { max-width: 76%; padding: 12px 16px; border-radius: var(--radius-md); line-height: 1.7; word-break: break-word; font-size: .93rem; }
.msg .label { font-size: .72rem; margin-bottom: 5px; opacity: .6; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.msg.interviewer { align-self: flex-start; background: #e9f3fd; color: #1a3f6b; border-bottom-left-radius: 4px; }
.msg.interviewee { align-self: flex-end; background: var(--surface); color: var(--text-primary); border-bottom-right-radius: 4px; box-shadow: var(--shadow-card); }
.msg.system { align-self: center; background: transparent; color: var(--text-muted); font-size: .8rem; font-style: italic; padding: 4px 0; }
.action-badge { display: inline-block; font-size: .68rem; padding: 2px 8px; border-radius: 8px; margin-left: 6px; vertical-align: middle; font-weight: 700; }
.action-badge.continue { background: #dbeafe; color: #1e40af; }
.action-badge.next_phase { background: #fef3c7; color: #92400e; }
.action-badge.end { background: #fee2e2; color: #991b1b; }
.msg-memory-calls { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
.msg-memory-chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px; border-radius: 999px; font-size: .66rem; font-weight: 700; background: #f0e8ff; color: #5b21b6; border: 1px solid #d8b4fe; cursor: default; position: relative; }
.msg-memory-chip svg { flex-shrink: 0; }
.msg-memory-chip:hover .msg-memory-tip { display: block; }
.msg-memory-tip { display: none; position: absolute; bottom: calc(100% + 6px); left: 0; min-width: 220px; max-width: 320px; max-height: 280px; overflow-y: auto; background: #1e1b2e; color: #e2d9ff; font-size: .7rem; font-weight: 400; padding: 8px 10px; border-radius: 8px; z-index: 100; white-space: pre-wrap; word-break: break-word; box-shadow: 0 6px 20px rgba(0,0,0,.35); line-height: 1.45; }
.typing-dots span { display: inline-block; animation: blink 1.2s infinite; font-size: 1rem; }
.typing-dots span:nth-child(2) { animation-delay: .2s; }
.typing-dots span:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%,80%,100% { opacity:0 } 40% { opacity:1 } }

/* Controls */
#chat-controls-ai { padding: 14px 22px; background: #faf6f2; border-top: 1px solid var(--border); display: flex; gap: 10px; flex-shrink: 0; align-items: flex-start; }
#run-btn { display: flex; align-items: center; gap: 7px; padding: 11px 18px; background: var(--brand); color: #fff; border: none; border-radius: var(--radius-sm); font-size: .93rem; font-weight: 600; cursor: pointer; transition: background var(--transition); white-space: nowrap; flex-shrink: 0; }
#run-btn:hover { background: var(--brand-light); }
#run-btn:disabled { opacity: .5; cursor: not-allowed; }
#ai-input-area { flex: 1; display: flex; flex-direction: column; gap: 8px; }
#ai-input { width: 100%; padding: 10px 13px; border: 1.5px solid var(--border); border-radius: var(--radius-sm); font-size: .92rem; font-family: inherit; resize: none; height: 58px; line-height: 1.5; transition: border-color var(--transition); }
#ai-input:focus { outline: none; border-color: var(--brand); }
#ai-input:disabled { background: #f5f0eb; color: #bbb; }
#ai-send-btn { padding: 9px 15px; background: var(--brand); color: #fff; border: none; border-radius: var(--radius-sm); font-size: .9rem; cursor: pointer; transition: background var(--transition); }
#ai-send-btn:hover { background: var(--brand-light); }
#ai-send-btn:disabled { opacity: .5; cursor: not-allowed; }

#chat-controls-user { padding: 14px 22px; background: #faf6f2; border-top: 1px solid var(--border); display: none; flex-direction: column; gap: 10px; flex-shrink: 0; }
#user-input { width: 100%; padding: 12px 14px; border: 1.5px solid var(--border); border-radius: var(--radius-sm); font-size: .93rem; font-family: inherit; resize: none; height: 82px; line-height: 1.6; transition: border-color var(--transition); }
#user-input:focus { outline: none; border-color: var(--brand); }
#user-input:disabled { background: #f5f0eb; color: #bbb; }
#user-controls-row { display: flex; gap: 10px; align-items: center; }
#send-btn { flex: 1; padding: 11px; background: var(--brand); color: #fff; border: none; border-radius: var(--radius-sm); font-size: .94rem; font-weight: 600; cursor: pointer; transition: background var(--transition); }
#send-btn:hover { background: var(--brand-light); }
#send-btn:disabled { opacity: .5; cursor: not-allowed; }
.user-hint { font-size: .77rem; color: var(--text-muted); }

/* ── Footer / landing ── */
.landing-footer { font-size: .78rem; color: var(--text-muted); text-align: center; }

@media (max-width: 640px) {
  .mode-cards { gap: 10px; }
  .mode-card { min-width: 160px; padding: 18px 14px; }
  #setup { padding: 20px 14px; gap: 22px; }
  .landing-hero h2 { font-size: 1.35rem; }
}
</style>
</head>
<body>

<header>
  <div class="header-brand">
    <svg class="header-logo" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="4" y="3" width="15" height="22" rx="2.5" stroke="rgba(255,255,255,.85)" stroke-width="1.6"/>
      <path d="M8 8h7M8 12h7M8 16h4" stroke="rgba(255,255,255,.65)" stroke-width="1.4" stroke-linecap="round"/>
      <circle cx="21" cy="21" r="5" fill="rgba(255,255,255,.15)" stroke="rgba(255,255,255,.7)" stroke-width="1.4"/>
      <path d="M21 18.5v2.7l1.5 1.5" stroke="rgba(255,255,255,.85)" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <h1 id="header-title">忆述 · 传记访谈</h1>
  </div>
  <span id="status-badge">就绪</span>
</header>

<!-- Landing / Setup screen -->
<div id="setup">
  <div class="landing-hero">
    <h2>记录每一段珍贵的人生故事</h2>
    <p>选择访谈模式，开启您的传记访谈之旅</p>
  </div>

  <!-- Mode cards -->
  <div class="mode-cards">
    <!-- AI mode -->
    <label class="mode-card selected" id="mode-ai-label">
      <input type="radio" name="mode" value="ai" checked onchange="selectMode('ai')">
      <div class="mode-card-icon">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="11" width="18" height="10" rx="2"/>
          <path d="M12 11V7"/><circle cx="12" cy="5" r="2"/>
          <circle cx="8.5" cy="15.5" r="1" fill="currentColor" stroke="none"/>
          <circle cx="12" cy="15.5" r="1" fill="currentColor" stroke="none"/>
          <circle cx="15.5" cy="15.5" r="1" fill="currentColor" stroke="none"/>
          <path d="M3 16l-1.5 1M21 16l1.5 1"/>
        </svg>
      </div>
      <div class="mode-card-title">AI 模拟受访者</div>
      <div class="mode-card-desc">由 AI 扮演受访者自动回答，适合系统测试与内容演示</div>
    </label>

    <!-- User mode -->
    <label class="mode-card" id="mode-user-label">
      <input type="radio" name="mode" value="user" onchange="selectMode('user')">
      <div class="mode-card-icon">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="7" r="4"/>
          <path d="M4 21c0-4.418 3.582-8 8-8s8 3.582 8 8"/>
        </svg>
      </div>
      <div class="mode-card-title">亲自回答访谈</div>
      <div class="mode-card-desc">由您本人真实作答，记录真实的人生回忆与故事</div>
    </label>

    <!-- Compare mode -->
    <a class="mode-card link-card" href="/compare" id="mode-compare-card">
      <div class="mode-card-icon">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">
          <rect x="2" y="4" width="9" height="16" rx="2"/>
          <rect x="13" y="4" width="9" height="16" rx="2"/>
          <path d="M7 9h3M7 12h3M7 15h3M14 9h3M14 12h3M14 15h3"/>
        </svg>
      </div>
      <div class="mode-card-title">版本对比</div>
      <div class="mode-card-desc">并排对比不同访谈策略的效果，分析访谈质量差异</div>
    </a>
  </div>

  <!-- Subject info form (shown after AI/User mode selected) -->
  <div id="info-form">
    <div>
      <label for="basic-info">受访者基本信息</label>
      <textarea id="basic-info" placeholder="例如：出生于1942年，四川成都人，曾是纺织厂工人，经历过文革和改革开放，育有三个子女，现独居。"></textarea>
    </div>
    <button id="start-btn" onclick="startInterview()">开始访谈</button>
  </div>

  <div class="landing-footer">忆述 · Narrative Planner &nbsp;—&nbsp; 让每段故事都值得被记录</div>
</div>

<!-- Main interview view -->
<div id="main">
  <div id="chat-panel">
    <div class="chat-panel-header">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>
      </svg>
      访谈对话
    </div>
    <div id="chat"></div>

    <!-- AI mode controls -->
    <div id="chat-controls-ai">
      <button id="run-btn" onclick="runAutoInterview()" disabled>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="5,3 19,12 5,21"/></svg>
        自动运行访谈
      </button>
      <div id="ai-input-area">
        <textarea id="ai-input" placeholder="可在此输入干预内容（可选）…" onkeydown="handleAiKey(event)" disabled></textarea>
        <button id="ai-send-btn" onclick="sendAiIntervention()" disabled>发送干预</button>
      </div>
    </div>

    <!-- User mode controls -->
    <div id="chat-controls-user">
      <textarea id="user-input" placeholder="请输入您的回答…" onkeydown="handleUserKey(event)"></textarea>
      <div id="user-controls-row">
        <button id="send-btn" onclick="sendUserReply()">发送回答</button>
        <span class="user-hint">Ctrl+Enter 快速发送</span>
      </div>
    </div>
  </div>
</div>

<script>
const setupEl  = document.getElementById('setup');
const mainEl   = document.getElementById('main');
const chatEl   = document.getElementById('chat');
const statusEl = document.getElementById('status-badge');
const runBtn   = document.getElementById('run-btn');
const sendBtn  = document.getElementById('send-btn');
const userInput = document.getElementById('user-input');
const aiInput = document.getElementById('ai-input');
const aiSendBtn = document.getElementById('ai-send-btn');
const infoForm = document.getElementById('info-form');

let interviewDone = false;
let currentMode = 'ai';

// Show info form on load (AI mode is pre-selected)
infoForm.style.display = 'flex';

function setStatus(text, color='rgba(255,255,255,.2)') {
  statusEl.textContent = text;
  statusEl.style.background = color;
}

function selectMode(mode) {
  currentMode = mode;
  document.getElementById('mode-ai-label').classList.toggle('selected', mode === 'ai');
  document.getElementById('mode-user-label').classList.toggle('selected', mode === 'user');
  document.getElementById('mode-compare-card').classList.remove('selected');
  infoForm.style.display = 'flex';
}

const TOOL_SVGS = {
  search_memories_by_keywords: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/></svg>',
  search_memories_by_tags: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 01-2.83 0L2 12V2h10l8.59 8.59a2 2 0 010 2.82z"/><circle cx="7" cy="7" r="1.5" fill="currentColor" stroke="none"/></svg>',
  get_memories_by_period: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>',
  get_memory_by_id: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a5 5 0 015 5c0 5-5 13-5 13S7 12 7 7a5 5 0 015-5z"/><circle cx="12" cy="7" r="2"/></svg>',
  get_related_memories: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></svg>',
};
const TOOL_LABELS = { search_memories_by_keywords: '关键词', search_memories_by_tags: '标签', get_memories_by_period: '时期', get_memory_by_id: '记忆ID', get_related_memories: '关联' };

const actionLabels = { continue: '深入', next_phase: '下一阶段', end: '结束访谈' };

function appendMsg(role, text, action, memoryCalls) {
  const labels = { interviewer: '访谈者', interviewee: '受访者', system: '' };
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  if (role !== 'system') {
    const lbl = document.createElement('div');
    lbl.className = 'label';
    lbl.textContent = (role === 'interviewee' && currentMode === 'user') ? '受访者（您）' : (labels[role] || role);
    if (action && actionLabels[action]) {
      const badge = document.createElement('span');
      badge.className = 'action-badge ' + action;
      badge.textContent = actionLabels[action];
      lbl.appendChild(badge);
    }
    d.appendChild(lbl);
  }
  const p = document.createElement('p');
  p.textContent = text;
  d.appendChild(p);
  if (memoryCalls && memoryCalls.length > 0) {
    const memDiv = document.createElement('div');
    memDiv.className = 'msg-memory-calls';
    for (const call of memoryCalls) {
      const chip = document.createElement('span');
      chip.className = 'msg-memory-chip';
      const cnt = Array.isArray(call.result) ? call.result.length : (call.result ? 1 : 0);
      const svg = TOOL_SVGS[call.tool] || '';
      const label = TOOL_LABELS[call.tool] || call.tool;
      const argsStr = JSON.stringify(call.args, null, 2);
      const fullResult = JSON.stringify(call.result, null, 2);
      chip.innerHTML = svg + label + ' (' + cnt + ')<span class="msg-memory-tip">工具：' + call.tool + '\\n参数：' + argsStr + '\\n结果：' + (fullResult || '无') + '</span>';
      memDiv.appendChild(chip);
    }
    d.appendChild(memDiv);
  }
  chatEl.appendChild(d);
  chatEl.scrollTop = chatEl.scrollHeight;
  return d;
}

function appendTyping(role) {
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  const lbl = document.createElement('div');
  lbl.className = 'label';
  lbl.textContent = role === 'interviewer' ? '访谈者' : '受访者';
  d.appendChild(lbl);
  d.innerHTML += '<p class="typing-dots"><span>●</span><span>●</span><span>●</span></p>';
  chatEl.appendChild(d);
  chatEl.scrollTop = chatEl.scrollHeight;
  return d;
}

async function startInterview() {
  const basicInfo = document.getElementById('basic-info').value.trim();
  if (!basicInfo) { alert('请输入受访者基本信息'); return; }

  const startBtn = document.getElementById('start-btn');
  startBtn.disabled = true;
  startBtn.textContent = '初始化中…';

  try {
    const res = await fetch('/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ basic_info: basicInfo, mode: currentMode })
    });
    const data = await res.json();
    if (data.error) { alert(data.error); startBtn.disabled = false; startBtn.textContent = '开始访谈'; return; }

    setupEl.style.display = 'none';
    mainEl.style.display = 'flex';

    if (currentMode === 'user') {
      document.getElementById('chat-controls-ai').style.display = 'none';
      document.getElementById('chat-controls-user').style.display = 'flex';
      document.getElementById('header-title').textContent = '忆述 · 亲历模式';
      userInput.disabled = false;
      sendBtn.disabled = false;
      aiInput.disabled = true;
      aiSendBtn.disabled = true;
    } else {
      document.getElementById('chat-controls-ai').style.display = 'flex';
      document.getElementById('chat-controls-user').style.display = 'none';
      document.getElementById('header-title').textContent = '忆述 · 自动对话';
      runBtn.disabled = false;
      aiInput.disabled = false;
      aiSendBtn.disabled = false;
    }

    appendMsg('system', '访谈已开始');
    appendMsg('interviewer', data.question);
    setStatus('已就绪');
  } catch(e) {
    alert('启动失败，请检查服务器');
    startBtn.disabled = false;
    startBtn.textContent = '开始访谈';
  }
}

function handleUserKey(e) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendUserReply(); }
}

async function sendUserReply() {
  const answer = userInput.value.trim();
  if (!answer) return;
  sendBtn.disabled = true;
  userInput.disabled = true;
  userInput.value = '';
  appendMsg('interviewee', answer);
  setStatus('访谈者思考中…', 'rgba(255,200,100,.4)');
  const typingEl = appendTyping('interviewer');
  try {
    const res = await fetch('/user_reply', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ answer }) });
    const data = await res.json();
    typingEl.remove();
    if (data.error) { appendMsg('system', '错误：' + data.error); setStatus('出错', 'rgba(255,100,100,.4)'); return; }
    appendMsg('interviewer', data.question, data.action);
    if (data.done) {
      interviewDone = true; sendBtn.disabled = true; userInput.disabled = true;
      setStatus('访谈完成', 'rgba(100,200,150,.4)'); appendMsg('system', '访谈已结束');
    } else {
      sendBtn.disabled = false; userInput.disabled = false; userInput.focus();
      setStatus('等待您的回答', 'rgba(255,255,255,.2)');
    }
  } catch(e) {
    typingEl.remove(); appendMsg('system', '网络错误，请重试');
    setStatus('连接中断', 'rgba(255,100,100,.4)'); sendBtn.disabled = false; userInput.disabled = false;
  }
}

function runAutoInterview() {
  runBtn.disabled = true; aiInput.disabled = true; aiSendBtn.disabled = true;
  setStatus('访谈进行中…', 'rgba(255,200,100,.4)');
  const evtSource = new EventSource('/auto_interview');
  evtSource.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.role === 'done') {
      evtSource.close(); interviewDone = true; aiInput.disabled = false; aiSendBtn.disabled = false;
      setStatus('访谈完成', 'rgba(100,200,150,.4)'); appendMsg('system', '访谈已由访谈者自然结束'); return;
    }
    appendMsg(msg.role, msg.text, msg.action, msg.memory_calls);
  };
  evtSource.onerror = () => { evtSource.close(); setStatus('连接中断', 'rgba(255,100,100,.4)'); runBtn.disabled = false; };
}

function handleAiKey(e) {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sendAiIntervention(); }
}

async function sendAiIntervention() {
  const text = aiInput.value.trim();
  if (!text) return;
  aiSendBtn.disabled = true; aiInput.disabled = true;
  appendMsg('system', '[用户干预] ' + text);
  aiInput.value = ''; aiInput.disabled = false; aiSendBtn.disabled = false; aiInput.focus();
}
</script>
</body>
</html>
"""


# ── Compare Mode Routes ───────────────────────────────────────────────────────

# 对比模式会话存储
_compare_sessions: dict[str, dict] = {}


def _build_aligned_turn_payload(
    *,
    question: str = "",
    action: str = "continue",
    done: bool = False,
    extracted_events: list | None = None,
    graph_update: dict | None = None,
    current_graph_state: dict | None = None,
    turn_evaluation: dict | None = None,
    session_metrics: dict | None = None,
    planner_plan: dict | None = None,
    memory_calls: list | None = None,
    debug_trace: dict | None = None,
) -> dict:
    """
    Build a stable cross-mode response schema for frontend integration.
    Baseline/Planner both expose the same keys; unsupported fields are empty.
    """
    return {
        "question": question,
        "action": action,
        "done": done,
        "extracted_events": extracted_events or [],
        "graph_update": graph_update or {},
        "current_graph_state": current_graph_state or {},
        "turn_evaluation": turn_evaluation or {},
        "session_metrics": session_metrics or {},
        "planner_plan": planner_plan or {},
        "memory_calls": memory_calls or [],
        "debug_trace": debug_trace or {},
    }


def _log_compare_turn(
    session: dict,
    *,
    question: str,
    answer: str,
    action: str = "continue",
    turn_evaluation: dict | None = None,
    current_graph_state: dict | None = None,
    planner_plan: dict | None = None,
    memory_calls: list | None = None,
    debug_trace: dict | None = None,
) -> None:
    logger = session.get("logger")
    if not logger:
        return

    turn_index = max(
        len([item for item in session.get("history", []) if item.get("role") == "interviewee"]) - 1,
        0,
    )
    turn_evaluation = turn_evaluation or {}
    current_graph_state = current_graph_state or {}
    debug_trace = debug_trace or {}
    planner_plan = planner_plan or {}

    coverage_metrics = current_graph_state.get("coverage_metrics", {}) or {}
    theme_richness = coverage_metrics.get("theme_richness", {}) or {}
    coverage_after = coverage_metrics.get(
        "overall_richness",
        coverage_metrics.get("overall_coverage", 0.0),
    )
    coverage_before = debug_trace.get("coverage", {}).get("before")
    if coverage_before is None:
        decision_ctx = debug_trace.get("decision_ctx", {}) or {}
        coverage_before = max(float(coverage_after or 0.0) - float(turn_evaluation.get("coverage_gain", 0.0) or 0.0), 0.0)
        if isinstance(decision_ctx.get("overall_coverage"), (int, float)):
            coverage_after = decision_ctx.get("overall_coverage")

    planning = debug_trace.get("planning", {}) or {}
    candidate_scores = {}
    for item in planning.get("candidate_actions", []) or []:
        if isinstance(item, dict) and item.get("action"):
            candidate_scores[str(item["action"])] = item.get("score", 0.0)

    log_data = TurnLogData(
        turn_id=str(turn_evaluation.get("turn_id") or f"turn_{turn_index:03d}"),
        turn_index=turn_index,
        timestamp=datetime.now().isoformat(),
        dialogue=DialogueLog(
            interviewer_question=question or "",
            interviewee_answer=answer or "",
            interviewer_action=action or "continue",
        ),
        coverage=CoverageLog(
            before=float(coverage_before or 0.0),
            after=float(coverage_after or 0.0),
            delta=float(turn_evaluation.get("coverage_gain", 0.0) or 0.0),
            slot_coverage=theme_richness,
        ),
        evaluation=EvaluationLog(
            question_quality_score=float(turn_evaluation.get("question_quality_score", 0.0) or 0.0),
            information_gain_score=float(turn_evaluation.get("information_gain_score", 0.0) or 0.0),
            non_redundancy_score=float(turn_evaluation.get("non_redundancy_score", 0.0) or 0.0),
            slot_targeting_score=float(turn_evaluation.get("slot_targeting_score", 0.0) or 0.0),
            emotional_alignment_score=float(turn_evaluation.get("emotional_alignment_score", 0.0) or 0.0),
            planner_alignment_score=float(turn_evaluation.get("planner_alignment_score", 0.0) or 0.0),
            coverage_gain=float(turn_evaluation.get("coverage_gain", 0.0) or 0.0),
            targeted_slots=list(turn_evaluation.get("targeted_slots", []) or planning.get("missing_dimensions", []) or []),
            notes=list(turn_evaluation.get("notes", []) or []),
        ),
        planner_decision=PlannerDecisionLog(
            next_action=planning.get("next_action", action or "continue"),
            recommended_theme_id=(planning.get("focus") or {}).get("id") if isinstance(planning.get("focus"), dict) else None,
            recommended_theme_title=(planning.get("focus") or {}).get("label") if isinstance(planning.get("focus"), dict) else None,
            targeted_slots=list(planner_plan.get("target_slots", []) or planning.get("missing_dimensions", []) or []),
            decision_signals={
                "stage": planning.get("stage", ""),
                "selected_action": planning.get("selected_action", ""),
                "question_intent": planning.get("question_intent", ""),
                "emotion_energy": planning.get("emotion_energy"),
                "emotion_valence": planning.get("emotion_valence"),
            },
            decision_scores=candidate_scores,
            low_info_streak=int((debug_trace.get("decision_ctx", {}) or {}).get("low_info_streak", 0) or 0),
        ) if session.get("type") == "planner" else None,
        memory_calls=memory_calls or [],
        debug_trace=debug_trace,
    )
    try:
        logger.log_turn(log_data)
    except Exception:
        app.logger.exception("Failed to write interview turn log for session %s", logger.session_id)


def _finalize_interview_log(session: dict, end_reason: str = "") -> None:
    logger = session.get("logger")
    if not logger:
        return
    evaluations = [turn.evaluation for turn in logger.turns if turn.evaluation]
    coverage = logger.turns[-1].coverage if logger.turns else CoverageLog()
    try:
        logger.finalize_session(
            SessionSummary(
                total_turns=len(logger.turns),
                final_coverage=coverage.after,
                final_slot_coverage=coverage.slot_coverage,
                extracted_events_count=len(session.get("extracted_events", []) or []),
                average_turn_quality=(
                    sum(item.question_quality_score for item in evaluations) / len(evaluations)
                    if evaluations else 0.0
                ),
                average_information_gain=(
                    sum(item.information_gain_score for item in evaluations) / len(evaluations)
                    if evaluations else 0.0
                ),
                final_action=(session.get("history") or [{}])[-1].get("action", "end"),
                end_reason=end_reason,
            )
        )
    except Exception:
        app.logger.exception("Failed to finalize interview log for session %s", logger.session_id)


@app.route("/compare")
def compare_interface():
    """返回对比调试界面"""
    return render_template_string(COMPARE_HTML)


# ========== Debug Route ==========
@app.route("/api/debug/config")
def debug_config():
    """调试：检查 Config 状态"""
    return jsonify({
        "config_module": Config.__module__,
        "has_openai_key": hasattr(Config, 'OPENAI_API_KEY'),
        "openai_key_set": bool(Config.OPENAI_API_KEY) if hasattr(Config, 'OPENAI_API_KEY') else False,
        "openai_key_preview": Config.OPENAI_API_KEY[:10] + "..." if hasattr(Config, 'OPENAI_API_KEY') and Config.OPENAI_API_KEY else None
    })

# ========== Baseline 相关 API ==========

@app.route("/api/baseline/start", methods=["POST"])
def baseline_start():
    """
    启动Baseline访谈
    Body: { "elder_info": str, "mode": "ai"|"user" }
    Response: { "session_id": str, "first_question": str }
    """
    data = request.get_json(force=True)
    elder_info = data.get("elder_info", {})
    mode = data.get("mode", "ai")

    if not elder_info:
        return jsonify({"error": "请提供受访者基本信息"}), 400

    # Debug: Check Config
    if not Config.get_api_key():
        return jsonify({
            "error": "Config OPENAI_API_KEY not set",
            "config_module": Config.__module__,
            "has_key": bool(Config.get_api_key()),
            "dir": [x for x in dir(Config) if not x.startswith('_')]
        }), 500

    # 生成会话ID
    session_id = uuid.uuid4().hex

    # 创建BaselineAgent
    agent = InterviewerAgent(session_id)

    # 构建基本信息文本
    basic_info_text = elder_info if isinstance(elder_info, str) else _build_basic_info_text(elder_info)
    agent.initialize_conversation(basic_info_text)

    # 获取首条问题
    result = agent.get_next_question()
    question = result["question"] if isinstance(result, dict) else result
    first_action = result.get("action", "continue") if isinstance(result, dict) else "continue"
    scorer = BaselineEvaluationRuntime(session_id)
    scorer.initialize_session(elder_info if isinstance(elder_info, dict) else {"background": basic_info_text})
    interview_logger = create_baseline_logger(
        session_id,
        elder_info if isinstance(elder_info, dict) else {"background": basic_info_text},
        mode,
    )

    # 存储会话
    _compare_sessions[session_id] = {
        "type": "baseline",
        "agent": agent,
        "logger": interview_logger,
        "history": [{"role": "interviewer", "text": question, "action": first_action}],
        "scorer": scorer,
        "mode": mode,
        "elder_info": elder_info,
        "start_time": datetime.now().isoformat()
    }

    return jsonify({
        "session_id": session_id,
        "first_question": question,
        "mode": mode
    })


@app.route("/api/baseline/reply", methods=["POST"])
def baseline_reply():
    """
    用户回复（User模式）
    Body: { "session_id": str, "answer": str }
    Response: { "question": str, "action": str, "done": bool }
    """
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    answer = data.get("answer", "").strip()

    if not session_id or session_id not in _compare_sessions:
        return jsonify({"error": "会话不存在"}), 400

    if not answer:
        return jsonify({"error": "回答不能为空"}), 400

    session = _compare_sessions[session_id]
    agent = session["agent"]
    scorer = session["scorer"]
    previous_question = session["history"][-1] if session["history"] else {"text": "", "action": "continue"}

    # 记录回答
    session["history"].append({"role": "interviewee", "text": answer})

    # 获取下一个问题
    result = agent.get_next_question(answer)

    # 处理返回值
    if isinstance(result, dict):
        question = result.get("question", "")
        action = result.get("action", "continue")
    else:
        question = result
        action = "continue"

    turn_evaluation = scorer.submit_turn(
        previous_question.get("text", ""),
        answer,
        previous_question.get("action", "continue"),
    )
    session["history"].append({"role": "interviewer", "text": question, "action": action})
    _log_compare_turn(
        session,
        question=previous_question.get("text", ""),
        answer=answer,
        action=previous_question.get("action", "continue"),
        turn_evaluation=turn_evaluation,
        debug_trace={"pipeline": "baseline"},
    )

    # 检查是否应该结束
    done = action == "end" or len(session["history"]) >= 100

    if done:
        # 保存对话
        _save_conversation(session_id, session)

    return jsonify(
        _build_aligned_turn_payload(
            question=question,
            action=action,
            done=done,
            turn_evaluation=turn_evaluation,
            debug_trace={"pipeline": "baseline"},
        )
    )


@app.route("/api/baseline/auto")
def baseline_auto():
    """
    SSE流 - AI自动对话
    Query: session_id, single_turn (可选，为1时只运行一轮)
    Events: { "role": "interviewer"|"interviewee", "text": str, "action": str }
    """
    session_id = request.args.get("session_id")
    single_turn = request.args.get("single_turn") == "1"

    if not session_id or session_id not in _compare_sessions:
        return jsonify({"error": "会话不存在"}), 400

    session = _compare_sessions[session_id]

    def generate():
        agent = session["agent"]
        scorer = session["scorer"]
        interviewee = _build_compare_interviewee(session)
        _restore_compare_interviewee_history(session, interviewee)

        # single_turn模式下只运行一轮
        max_turns = 1 if single_turn else 20
        for turn in range(max_turns):
            # 获取上一个问题
            last_question_entry = session["history"][-1] if session["history"] else {"text": "", "action": "continue"}
            last_question = last_question_entry.get("text", "")

            # AI受访者回答
            answer, memory_calls, interviewee_timing = _run_compare_interviewee_turn(interviewee, last_question)

            session["history"].append({"role": "interviewee", "text": answer})
            session["_interviewee_restored_pairs"] = _count_compare_interviewee_pairs(session)
            yield f"data: {json.dumps({'role': 'interviewee', 'action': 'answer', 'text': answer, 'memory_calls': memory_calls, 'timing': interviewee_timing}, ensure_ascii=False)}\n\n"

            # 访谈者提问
            _t_iv = time.perf_counter()
            result = agent.get_next_question(answer)
            _iv_ms = (time.perf_counter() - _t_iv) * 1000
            question = result.get("question", "")
            action = result.get("action", "continue")
            _raw_usage = result.get("llm_usage") or {}
            _baseline_token_usage = {
                "interviewer_prompt_tokens": _raw_usage.get("prompt_tokens"),
                "interviewer_completion_tokens": _raw_usage.get("completion_tokens"),
                "prompt_tokens": _raw_usage.get("prompt_tokens"),
                "completion_tokens": _raw_usage.get("completion_tokens"),
            } if _raw_usage else {}

            turn_evaluation = scorer.submit_turn(
                last_question,
                answer,
                last_question_entry.get("action", "continue"),
            )
            session["history"].append({"role": "interviewer", "text": question, "action": action})
            _log_compare_turn(
                session,
                question=last_question,
                answer=answer,
                action=last_question_entry.get("action", "continue"),
                turn_evaluation=turn_evaluation,
                memory_calls=memory_calls,
                debug_trace={"pipeline": "baseline"},
            )
            aligned = _build_aligned_turn_payload(
                question=question,
                action=action,
                done=False,
                turn_evaluation=turn_evaluation,
                debug_trace={"pipeline": "baseline"},
            )
            yield f"data: {json.dumps({'role': 'interviewer', 'action': aligned['action'], 'text': aligned['question'], 'turn_evaluation': aligned['turn_evaluation'], 'debug_trace': aligned['debug_trace'], 'timing': {'interviewer_llm_ms': round(_iv_ms, 1), 'token_usage': _baseline_token_usage}}, ensure_ascii=False)}\n\n"

            if action == "end":
                break

        # 只有非单轮模式或结束时才保存对话
        if not single_turn or (session["history"] and len(session["history"]) >= 100):
            _save_conversation(session_id, session)
        yield f"data: {json.dumps({'role': 'done'}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


# ========== Planner 相关 API ==========

@app.route("/api/baseline/evaluation/<session_id>")
def baseline_evaluation(session_id):
    if session_id not in _compare_sessions:
        return jsonify({"error": "Session not found"}), 400

    session = _compare_sessions[session_id]
    if session["type"] != "baseline":
        return jsonify({"error": "Not a baseline session"}), 400

    scorer = session.get("scorer")
    if scorer is None:
        return jsonify({"error": "Baseline scorer unavailable"}), 500
    return jsonify(scorer.get_evaluation_state())


@app.route("/api/planner/start", methods=["POST"])
def planner_start():
    """
    启动Planner访谈
    Body: {
      "elder_info": dict,
      "mode": "ai"|"user",
      "version": "graphrag"|"legacy",           # 可选，默认 graphrag
      "decision_weight_vector": [float, ...],   # 可选，按固定顺序
      "decision_weights": {"new_info_weight": ...}  # 可选
    }
    Response: { "session_id": str, "first_question": str, "initial_graph": dict, "decision_weight_payload": dict }
    """
    data = request.get_json(force=True)
    elder_info = data.get("elder_info", {})
    mode = data.get("mode", "ai")
    version = data.get("version", "graphrag")
    decision_weight_vector = data.get("decision_weight_vector")
    decision_weights = data.get("decision_weights")

    if not elder_info:
        return jsonify({"error": "请提供受访者基本信息"}), 400

    weight_input = None
    if decision_weight_vector is not None:
        if not isinstance(decision_weight_vector, list) or not all(
            isinstance(item, (int, float)) for item in decision_weight_vector
        ):
            return jsonify({"error": "decision_weight_vector 必须是数字列表"}), 400
        weight_input = [float(item) for item in decision_weight_vector]
    elif decision_weights is not None:
        if not isinstance(decision_weights, dict):
            return jsonify({"error": "decision_weights 必须是字典"}), 400
        weight_input = decision_weights

    # 生成会话ID
    session_id = uuid.uuid4().hex

    # 创建PlannerAgent（同步包装器）
    try:
        if version == "legacy":
            agent = LegacyPlannerInterviewAgentSync(
                session_id,
                decision_weights=weight_input,
            )
        else:
            agent = PlannerInterviewAgentSync(
                session_id,
                decision_weights=weight_input,
            )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    agent.initialize_conversation(elder_info)

    # 获取首条问题
    result = agent.get_next_question()
    if version == "legacy":
        decision_weight_payload = agent.async_agent.orchestrator.get_decision_weight_payload()
    else:
        decision_weight_payload = agent.async_agent.orchestrator.get_decision_weight_payload()
    interview_logger = create_planner_logger(
        session_id,
        elder_info if isinstance(elder_info, dict) else {"background": str(elder_info)},
        mode,
    )

    # 存储会话
    _compare_sessions[session_id] = {
        "type": "planner",
        "version": version,
        "agent": agent,
        "logger": interview_logger,
        "history": [{"role": "interviewer", "text": result["question"], "action": result.get("action", "continue")}],
        "mode": mode,
        "elder_info": elder_info,
        "start_time": datetime.now().isoformat(),
        "extracted_events": [],
        "decision_weight_payload": decision_weight_payload,
    }

    return jsonify({
        "session_id": session_id,
        "first_question": result["question"],
        "mode": mode,
        "initial_graph": result.get("current_graph_state", {}),
        "decision_weight_payload": decision_weight_payload,
        "planner_plan": result.get("planner_plan", {}),
        "debug_trace": result.get("debug_trace", {}),
    })


@app.route("/api/planner/reply", methods=["POST"])
def planner_reply():
    """
    用户回复（User模式），同时触发事件提取和图谱更新
    Body: { "session_id": str, "answer": str }
    Response: {
        "question": str, "action": str, "done": bool,
        "extracted_events": list, "graph_update": dict
    }
    """
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    answer = data.get("answer", "").strip()

    if not session_id or session_id not in _compare_sessions:
        return jsonify({"error": "会话不存在"}), 400

    if not answer:
        return jsonify({"error": "回答不能为空"}), 400

    session = _compare_sessions[session_id]
    agent = session["agent"]
    previous_question = session["history"][-1] if session["history"] else {"text": "", "action": "continue"}

    # 记录回答
    session["history"].append({"role": "interviewee", "text": answer})

    # 获取下一个问题（包含事件提取和图谱更新）
    result = agent.get_next_question(answer)

    # 记录问题
    session["history"].append({"role": "interviewer", "text": result["question"], "action": result.get("action", "continue")})

    # 累计提取的事件
    session["extracted_events"].extend(result.get("extracted_events", []))
    _broadcast_planner_graph_update(session_id, result)
    _log_compare_turn(
        session,
        question=previous_question.get("text", ""),
        answer=answer,
        action=previous_question.get("action", "continue"),
        turn_evaluation=result.get("turn_evaluation", {}),
        current_graph_state=result.get("current_graph_state", {}),
        planner_plan=result.get("planner_plan", {}),
        debug_trace=result.get("debug_trace", {}),
    )

    # 检查是否应该结束
    done = result["action"] == "end" or len(session["history"]) >= 100

    if done:
        # 保存对话和图谱
        _save_conversation(session_id, session)

    return jsonify(
        _build_aligned_turn_payload(
            question=result.get("question", ""),
            action=result.get("action", "continue"),
            done=done,
            extracted_events=result.get("extracted_events", []),
            graph_update=result.get("graph_changes", {}),
            current_graph_state=result.get("current_graph_state", {}),
            turn_evaluation=result.get("turn_evaluation", {}),
            session_metrics=result.get("session_metrics", {}),
            planner_plan=result.get("planner_plan", {}),
            debug_trace=result.get("debug_trace", {}),
        )
    )


@app.route("/api/planner/auto")
def planner_auto():
    """
    SSE流 - AI自动对话，实时推送图谱更新
    Query: session_id, single_turn (可选，为1时只运行一轮)
    Events: { "role": "...", "text": "...", "extracted_events": [...], "graph_delta": {...} }
    """
    session_id = request.args.get("session_id")
    single_turn = request.args.get("single_turn") == "1"

    if not session_id or session_id not in _compare_sessions:
        return jsonify({"error": "会话不存在"}), 400

    session = _compare_sessions[session_id]

    def generate():
        try:
            agent = session["agent"]
            interviewee = _build_compare_interviewee(session)

            # 从已有会话恢复访谈历史，避免多轮自动/单轮调试时丢上下文
            _restore_compare_interviewee_history(session, interviewee)

            # single_turn模式下只运行一轮
            max_turns = 1 if single_turn else 20
            for turn in range(max_turns):
                # 获取上一个问题
                last_question_entry = session["history"][-1] if session["history"] else {"text": "", "action": "continue"}
                last_question = last_question_entry.get("text", "")

                # AI受访者回答
                answer, memory_calls, interviewee_timing = _run_compare_interviewee_turn(interviewee, last_question)

                session["history"].append({"role": "interviewee", "text": answer})
                session["_interviewee_restored_pairs"] = _count_compare_interviewee_pairs(session)
                yield f"data: {json.dumps({'role': 'interviewee', 'text': answer, 'extracted_events': [], 'graph_delta': {}, 'memory_calls': memory_calls, 'timing': interviewee_timing}, ensure_ascii=False)}\n\n"

                # 获取下一个问题（包含事件提取）
                result = agent.get_next_question(answer)

                # 累计提取的事件
                session["extracted_events"].extend(result.get("extracted_events", []))
                _broadcast_planner_graph_update(session_id, result)

                # 构建计时汇总
                _dt = result.get("debug_trace", {})
                planner_timing = {
                    "retrieval_ms": _dt.get("retrieval_ms"),
                    "extraction_ms": _dt.get("extraction_ms"),
                    "write_ms": _dt.get("write_ms"),
                    "interviewer_llm_ms": _dt.get("interviewer_llm_ms"),
                    "token_usage": _dt.get("token_usage"),
                }

                # 发送事件
                session["history"].append({"role": "interviewer", "text": result["question"], "action": result.get("action", "continue")})
                _log_compare_turn(
                    session,
                    question=last_question,
                    answer=answer,
                    action=last_question_entry.get("action", "continue"),
                    turn_evaluation=result.get("turn_evaluation", {}),
                    current_graph_state=result.get("current_graph_state", {}),
                    planner_plan=result.get("planner_plan", {}),
                    memory_calls=memory_calls,
                    debug_trace=result.get("debug_trace", {}),
                )

                aligned = _build_aligned_turn_payload(
                    question=result.get("question", ""),
                    action=result.get("action", "continue"),
                    done=False,
                    extracted_events=result.get("extracted_events", []),
                    graph_update=result.get("graph_changes", {}),
                    current_graph_state=result.get("current_graph_state", {}),
                    turn_evaluation=result.get("turn_evaluation", {}),
                    session_metrics=result.get("session_metrics", {}),
                    planner_plan=result.get("planner_plan", {}),
                    debug_trace=result.get("debug_trace", {}),
                )
                interviewer_data = {
                    'role': 'interviewer',
                    'action': aligned['action'],
                    'text': aligned['question'],
                    'extracted_events': aligned['extracted_events'],
                    'graph_delta': aligned['graph_update'],
                    'turn_evaluation': aligned['turn_evaluation'],
                    'session_metrics': aligned['session_metrics'],
                    'planner_plan': aligned['planner_plan'],
                    'debug_trace': aligned['debug_trace'],
                    'timing': planner_timing,
                }
                yield f"data: {json.dumps(interviewer_data, ensure_ascii=False)}\n\n"

                if result["action"] == "end":
                    break

            # 只有非单轮模式或结束时才保存对话
            if not single_turn or (session["history"] and len(session["history"]) >= 100):
                _save_conversation(session_id, session)
            yield f"data: {json.dumps({'role': 'done'}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            app.logger.exception("planner_auto error")
            yield f"data: {json.dumps({'role': 'error', 'text': f'自动对话出错: {exc}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'role': 'done'}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


@app.route("/api/planner/graph/<session_id>")
def planner_graph(session_id):
    """获取当前图谱状态"""
    if session_id not in _compare_sessions:
        return jsonify({"error": "会话不存在"}), 400

    session = _compare_sessions[session_id]
    if session["type"] != "planner":
        return jsonify({"error": "非Planner会话"}), 400

    agent = session["agent"]
    return jsonify(agent.get_graph_state())


@app.route("/api/planner/report/<session_id>")
def planner_report(session_id):
    """GraphRAG 运行报告：会话概览 + Neo4j 统计 + 轮次汇总 + 覆盖率 + embedding 状态"""
    if session_id not in _compare_sessions:
        return jsonify({"error": "会话不存在"}), 400
    session = _compare_sessions[session_id]
    if session["type"] != "planner":
        return jsonify({"error": "非 Planner 会话"}), 400

    # 1. 会话基本信息
    agent = session["agent"]
    orch = agent.async_agent
    turn_count = len(session.get("history", [])) // 2
    report = {
        "session_id": session_id,
        "turn_count": turn_count,
        "start_time": session.get("start_time", ""),
        "mode": session.get("mode", ""),
    }

    # 2. Neo4j 图谱统计
    neo4j_stats = {"nodes": [], "relationships": [], "themes": []}
    try:
        neo4j = orch.orchestrator._get_neo4j_manager()
        rows = neo4j.driver.execute_query(
            "MATCH (n) RETURN labels(n)[0] AS type, count(n) AS cnt ORDER BY cnt DESC"
        )
        neo4j_stats["nodes"] = [{"type": r["type"], "count": r["cnt"]} for r in (rows or [])]
        rows = neo4j.driver.execute_query(
            "MATCH ()-[r]->() RETURN type(r) AS rel_type, count(r) AS cnt ORDER BY cnt DESC"
        )
        neo4j_stats["relationships"] = [{"type": r["rel_type"], "count": r["cnt"]} for r in (rows or [])]
        rows = neo4j.driver.execute_query(
            """
            MATCH (t:Topic) OPTIONAL MATCH (t)-[:INCLUDES]->(e:Event)
            RETURN t.id AS id, t.name AS name, t.status AS status, count(e) AS event_count
            ORDER BY t.id
            """
        )
        neo4j_stats["themes"] = [
            {"id": r["id"], "name": r.get("name", r["id"]), "status": r.get("status", "pending"), "event_count": r.get("event_count", 0)}
            for r in (rows or [])
        ]
    except Exception:
        pass
    report["neo4j"] = neo4j_stats

    # 3. 覆盖率
    try:
        gs = agent.get_graph_state()
        report["coverage"] = gs.get("coverage_metrics", {})
    except Exception:
        report["coverage"] = {}

    # 4. 每轮 timing 汇总
    turn_timings = []
    for msg in session.get("history", []):
        t = msg.get("timing") or {}
        if t and isinstance(t, dict):
            turn_timings.append(t)
    report["turn_timings"] = turn_timings[-20:]  # 最近 20 轮

    # 5. Embedding 状态
    try:
        from src.services.embedding_service import EmbeddingService
        report["embedding"] = EmbeddingService().get_status()
    except Exception:
        report["embedding"] = {"provider": "unknown"}

    return jsonify(report)


# ========== 通用辅助函数 ==========

def _generate_baseline_interviewee_reply(elder_info, question: str, history: list[dict]) -> str:
    """Generate a clean control-group reply without memory/tool backends."""
    from openai import OpenAI

    basic_info = _build_basic_info_text(elder_info)
    recent_history = "\n".join(
        f"{item['role']}: {item['text']}"
        for item in history[-6:]
    ) or "无"

    try:
        client = OpenAI(**Config.get_openai_client_kwargs())
        response = client.chat.completions.create(
            model=Config.get_model_name("interviewee"),
            max_tokens=4096,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你现在扮演一位正在接受传记访谈的老人。"
                        "请只以受访者身份自然回答，不要调用任何工具，不要虚构系统能力。"
                        f"\n受访者基本信息：{basic_info}"
                    ),
                },
                {
                    "role": "user",
                    "content": f"最近对话：\n{recent_history}\n\n当前问题：{question}",
                },
            ],
        )
        return response.choices[0].message.content or "我想再想一想。"
    except Exception as exc:
        app.logger.error("Baseline interviewee reply failed: %s", exc)
        return "这个问题我一下子还没想好，但我可以继续回忆。"


def _build_basic_info_text(elder_info):
    """构建老人信息文本"""
    if isinstance(elder_info, str):
        return elder_info

    parts = []
    if elder_info.get("name"):
        parts.append(f"姓名：{elder_info['name']}")
    if elder_info.get("birth_year"):
        parts.append(f"出生于{elder_info['birth_year']}年")
    if elder_info.get("hometown"):
        parts.append(f"家乡：{elder_info['hometown']}")
    if elder_info.get("background"):
        parts.append(f"背景：{elder_info['background']}")

    return "，".join(parts) if parts else "一位老人"


def _save_conversation(session_id, session):
    """保存对话记录"""
    _finalize_interview_log(session, "conversation_saved")
    results_dir = "results/conversations"
    os.makedirs(results_dir, exist_ok=True)

    agent_type = session["type"]
    output_file = os.path.join(results_dir, f"{agent_type}_{session_id}.txt")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"=== {agent_type.upper()} Interview - Session {session_id} ===\n\n")
        f.write(f"Elder Info: {session.get('elder_info', {})}\n\n")
        for msg in session["history"]:
            role_label = {"system": "系统", "user": "受访者", "interviewee": "受访者",
                         "assistant": "访谈者", "interviewer": "访谈者"}.get(msg["role"], msg["role"])
            f.write(f"[{role_label}]: {msg['text']}\n\n")

    # 如果是Planner，同时保存图谱
    if agent_type == "planner":
        session["agent"].save_conversation()


def _broadcast_planner_graph_update(session_id: str, result: dict):
    """Push the latest planner graph state to any connected dashboard."""
    current_graph_state = result.get("current_graph_state")
    if not current_graph_state and session_id in _compare_sessions:
        current_graph_state = _compare_sessions[session_id]["agent"].get_graph_state()

    if current_graph_state:
        broadcast_to_dashboard(
            session_id,
            {
                "type": "graph_update",
                "data": current_graph_state,
            },
        )


# ========== WebSocket for Dashboard ==========

from flask_sock import Sock
sock = Sock(app)

# WebSocket连接管理
_ws_connections: dict[str, list] = {}


@sock.route("/ws/planner/<session_id>")
def planner_websocket(ws, session_id):
    """
    WebSocket连接，用于向数据看板推送实时图谱更新
    """
    if session_id not in _ws_connections:
        _ws_connections[session_id] = []
    _ws_connections[session_id].append(ws)

    # 发送初始连接成功消息
    ws.send(json.dumps({
        "type": "connection_established",
        "session_id": session_id
    }, ensure_ascii=False))

    # 如果有现有图谱状态，立即发送
    if session_id in _compare_sessions and _compare_sessions[session_id]["type"] == "planner":
        agent = _compare_sessions[session_id]["agent"]
        ws.send(json.dumps({
            "type": "graph_init",
            "data": agent.get_graph_state()
        }, ensure_ascii=False))

    # 保持连接，接收心跳
    try:
        while True:
            message = ws.receive()
            if message:
                data = json.loads(message)
                if data.get("type") == "ping":
                    ws.send(json.dumps({"type": "pong"}))
    except Exception as e:
        pass
    finally:
        # 清理连接
        if session_id in _ws_connections and ws in _ws_connections[session_id]:
            _ws_connections[session_id].remove(ws)


def broadcast_to_dashboard(session_id: str, message: dict):
    """向所有连接的数据看板广播消息"""
    if session_id not in _ws_connections:
        return

    message_json = json.dumps(message, ensure_ascii=False)
    dead_connections = []

    for ws in _ws_connections[session_id]:
        try:
            ws.send(message_json)
        except Exception:
            dead_connections.append(ws)

    # 清理断开的连接
    for ws in dead_connections:
        _ws_connections[session_id].remove(ws)


# ── Compare HTML Template ─────────────────────────────────────────────────────

COMPARE_HTML = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>传记访谈系统 - 版本对比</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #f5f1eb;
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Top Bar */
        .top-bar {
            background: linear-gradient(135deg, #6b4f3a 0%, #8b6f5a 100%);
            color: #fff;
            padding: 12px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-shrink: 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .brand { display: flex; align-items: baseline; gap: 12px; }
        .brand h1 { font-size: 1.2rem; font-weight: bold; }
        .brand .subtitle { font-size: 0.85rem; opacity: 0.8; }

        .global-controls {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .btn-icon {
            background: rgba(255,255,255,0.15);
            border: none;
            color: #fff;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.9rem;
            transition: background 0.2s;
        }
        .btn-icon:hover { background: rgba(255,255,255,0.25); }
        .btn-primary {
            background: #3a6b4f;
            border: none;
            color: #fff;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.95rem;
            font-weight: 600;
            transition: all 0.2s;
        }
        .btn-primary:hover:not(:disabled) { background: #2d523c; }
        .btn-primary:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .btn-secondary {
            background: transparent;
            border: 1px solid rgba(255,255,255,0.4);
            color: #fff;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.95rem;
            transition: all 0.2s;
        }
        .btn-secondary:hover { background: rgba(255,255,255,0.1); }

        .status-indicator {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 0.85rem;
        }
        .status-indicator .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #aaa;
        }
        .status-indicator.connected .dot { background: #4caf50; }
        .status-indicator.disconnected .dot { background: #f44336; }

        /* Modal */
        .modal {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.5);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
        }
        .modal.active { display: flex; }
        .modal-content {
            background: #fff;
            border-radius: 16px;
            width: 90%;
            max-width: 600px;
            max-height: 90vh;
            overflow-y: auto;
            box-shadow: 0 8px 32px rgba(0,0,0,0.2);
        }
        .modal-header {
            padding: 20px 24px;
            border-bottom: 1px solid #eee;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .modal-header h2 { font-size: 1.1rem; color: #333; }
        .btn-close {
            background: none;
            border: none;
            font-size: 1.5rem;
            color: #999;
            cursor: pointer;
            padding: 0;
            width: 32px;
            height: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
        }
        .btn-close:hover { background: #f5f5f5; color: #333; }

        form { padding: 24px; }
        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 16px;
        }
        .form-row.full-width { grid-template-columns: 1fr; }
        label {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        label span {
            font-size: 0.85rem;
            color: #666;
            font-weight: 500;
        }
        label input,
        label textarea,
        label select {
            padding: 10px 12px;
            border: 1px solid #ddd;
            border-radius: 8px;
            font-size: 0.95rem;
            font-family: inherit;
        }
        label input:focus,
        label textarea:focus,
        label select:focus {
            outline: none;
            border-color: #6b4f3a;
        }
        label textarea { resize: vertical; min-height: 80px; }

        .form-actions {
            display: flex;
            justify-content: flex-end;
            gap: 12px;
            margin-top: 24px;
            padding-top: 20px;
            border-top: 1px solid #eee;
        }

        /* Main Container */
        .compare-container {
            flex: 1;
            display: grid;
            grid-template-columns: 1fr 1fr 320px;
            gap: 20px;
            padding: 20px;
            overflow: hidden;
        }

        /* Panel */
        .panel {
            background: #fff;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .panel-header {
            padding: 16px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #eee;
        }
        .baseline-panel .panel-header {
            background: linear-gradient(135deg, #e8e4e0 0%, #f5f1eb 100%);
        }
        .planner-panel .panel-header {
            background: linear-gradient(135deg, #e3f2fd 0%, #f3f9ff 100%);
        }
        .panel-title {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .badge {
            font-size: 0.7rem;
            padding: 4px 10px;
            border-radius: 12px;
            font-weight: 600;
        }
        .badge.control {
            background: #9e9e9e;
            color: #fff;
        }
        .badge.experiment {
            background: #2196f3;
            color: #fff;
        }
        .badge.legacy {
            background: #7b5ea7;
            color: #fff;
        }
        .version-select {
            font-size: 0.8rem;
            padding: 4px 8px;
            border: 1px solid #ddd;
            border-radius: 8px;
            background: #fff;
            color: #333;
            cursor: pointer;
            outline: none;
        }
        .version-select:focus { border-color: #6b4f3a; }
        .version-select:disabled { background: #f5f5f5; cursor: not-allowed; }
        .panel-title h2 {
            font-size: 1.1rem;
            color: #333;
        }
        .panel-status {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 0.85rem;
        }
        .status-text {
            color: #666;
        }
        .mode-indicator {
            background: rgba(0,0,0,0.05);
            padding: 4px 10px;
            border-radius: 12px;
            color: #666;
        }

        .panel-body {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Chat Container */
        .chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: #999;
        }
        .empty-icon { font-size: 3rem; margin-bottom: 16px; }
        .empty-state p { font-size: 0.95rem; margin-bottom: 8px; }
        .empty-state .hint { font-size: 0.85rem; opacity: 0.7; }

        .message {
            max-width: 85%;
            padding: 12px 16px;
            border-radius: 16px;
            line-height: 1.6;
            font-size: 0.92rem;
        }
        .message .msg-text {
            word-break: break-word;
        }
        .message.system, .message.error {
            align-self: center;
            max-width: 90%;
            background: #fff3e0;
            color: #8a5300;
            border: 1px solid #ffd194;
            border-radius: 10px;
        }
        .message.interviewer {
            align-self: flex-start;
            background: #e8f4fd;
            color: #1a4a6b;
            border-bottom-left-radius: 4px;
        }
        .message.interviewee {
            align-self: flex-end;
            background: #f5f5f5;
            color: #333;
            border-bottom-right-radius: 4px;
        }
        .msg-label {
            font-size: 0.75rem;
            margin-bottom: 4px;
            opacity: 0.7;
            font-weight: 600;
        }
        .action-tag {
            display: inline-block;
            font-size: 0.65rem;
            padding: 2px 8px;
            border-radius: 10px;
            margin-left: 6px;
            background: rgba(0,0,0,0.1);
        }
        .message-evaluation {
            margin-top: 10px;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .evaluation-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 4px 8px;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 600;
            background: rgba(255,255,255,0.7);
            color: #35546a;
        }
        .evaluation-chip.pending {
            background: rgba(255,255,255,0.9);
            color: #8a6b2d;
        }
        .evaluation-chip.score {
            background: #d7f0ff;
            color: #0f4c75;
        }
        .evaluation-chip.info {
            background: #e8f6ea;
            color: #1b5e20;
        }
        .evaluation-chip.slot {
            background: #f5e9ff;
            color: #6a1b9a;
        }
        .evaluation-chip.coverage {
            background: #fff1d6;
            color: #8a5300;
        }
        .evaluation-chip.notes {
            background: #fff3f0;
            color: #8f3b2e;
        }

        /* Memory calls */
        .memory-calls {
            margin-top: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
        }
        .memory-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 3px 8px;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 600;
            background: #f0e8ff;
            color: #5b21b6;
            cursor: pointer;
            border: 1px solid #d8b4fe;
            position: relative;
        }
        .memory-chip:hover .memory-tooltip,
        .memory-tooltip:hover {
            display: block;
        }
        .memory-tooltip {
            display: none;
            position: absolute;
            bottom: calc(100% + 6px);
            left: 0;
            min-width: 220px;
            max-width: 320px;
            max-height: 300px;
            overflow-y: auto;
            background: #1e1b2e;
            color: #e2d9ff;
            font-size: 0.72rem;
            font-weight: 400;
            padding: 8px 10px;
            border-radius: 8px;
            z-index: 100;
            white-space: pre-wrap;
            word-break: break-word;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            line-height: 1.5;
        }
        .debug-calls {
            margin-top: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
        }
        .debug-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 3px 8px;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 600;
            background: #e8f6ea;
            color: #1b5e20;
            cursor: pointer;
            border: 1px solid #b7dfbe;
            position: relative;
        }
        .debug-chip.warning {
            background: #fff3e0;
            color: #8a5300;
            border-color: #ffd194;
        }
        .debug-chip:hover .debug-tooltip,
        .debug-tooltip:hover {
            display: block;
        }
        .debug-tooltip {
            display: none;
            position: absolute;
            bottom: calc(100% + 6px);
            left: 0;
            min-width: 240px;
            max-width: 420px;
            max-height: 340px;
            overflow-y: auto;
            background: #102027;
            color: #d9f5ff;
            font-size: 0.72rem;
            font-weight: 400;
            padding: 8px 10px;
            border-radius: 8px;
            z-index: 101;
            white-space: pre-wrap;
            word-break: break-word;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            line-height: 1.5;
        }

        /* Timing chips */
        .timing-chips {
            margin-top: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
        }
        .timing-chip {
            display: inline-flex;
            align-items: center;
            gap: 3px;
            padding: 3px 8px;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 600;
            background: #e0f2f1;
            color: #00695c;
        }
        .timing-chip.slow {
            background: #fff3e0;
            color: #e65100;
        }
        .token-chip {
            display: inline-flex;
            align-items: center;
            gap: 3px;
            padding: 3px 8px;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 600;
            background: #ede7f6;
            color: #512da8;
        }

        /* Token summary */
        .token-summary {
            background: linear-gradient(180deg, #ede7f6 0%, #e8eaf6 100%);
            border: 1px solid #ce93d8;
            border-radius: 12px;
            padding: 14px;
            margin-top: 8px;
        }
        .token-summary.placeholder {
            color: #607d8b;
            font-size: 0.84rem;
            line-height: 1.6;
        }
        .token-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 5px 0;
            border-top: 1px solid rgba(0,0,0,0.06);
        }
        .token-row:first-child { border-top: none; }
        .token-label {
            font-size: 0.78rem;
            color: #455a64;
            font-weight: 500;
        }
        .token-value {
            font-size: 0.78rem;
            font-weight: 700;
            color: #37474f;
        }

        /* Timing summary */
        .timing-summary {
            background: linear-gradient(180deg, #e0f7fa 0%, #e8f5e9 100%);
            border: 1px solid #b2dfdb;
            border-radius: 12px;
            padding: 14px;
        }
        .timing-summary.placeholder {
            color: #607d8b;
            font-size: 0.84rem;
            line-height: 1.6;
        }
        .timing-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 6px 0;
        }
        .timing-row + .timing-row {
            border-top: 1px solid rgba(0,0,0,0.06);
        }
        .timing-label {
            font-size: 0.78rem;
            color: #455a64;
            font-weight: 500;
        }
        .timing-bar-container {
            flex: 1;
            margin: 0 12px;
            height: 6px;
            background: rgba(0,0,0,0.06);
            border-radius: 3px;
            overflow: hidden;
        }
        .timing-bar {
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s ease;
        }
        .timing-bar.baseline { background: #9e9e9e; }
        .timing-bar.planner { background: #2196f3; }
        .timing-value {
            font-size: 0.78rem;
            font-weight: 700;
            color: #37474f;
            min-width: 48px;
            text-align: right;
        }

        /* Plan chips */
        .plan-chips {
            margin-top: 8px;
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
        }
        .plan-chip {
            display: inline-flex;
            align-items: center;
            gap: 3px;
            padding: 3px 8px;
            border-radius: 999px;
            font-size: 0.68rem;
            font-weight: 600;
        }
        .plan-chip.stage { background: #e3f2fd; color: #1565c0; }
        .plan-chip.focus { background: #fce4ec; color: #c62828; }
        .plan-chip.completeness { background: #e8f5e9; color: #2e7d32; }
        .plan-chip.emotion { background: #fff8e1; color: #f57f17; }
        .plan-chip.intent { background: #f3e5f5; color: #6a1b9a; }

        /* Controls */
        .controls {
            padding: 16px 20px;
            border-top: 1px solid #eee;
            background: #fafafa;
        }
        .control-group {
            display: flex;
            gap: 10px;
        }
        .control-group.user-controls {
            flex-direction: column;
        }
        .control-group textarea {
            width: 100%;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 10px;
            font-size: 0.93rem;
            resize: none;
            min-height: 80px;
            font-family: inherit;
        }
        .btn-run, .btn-send, .btn-bio {
            padding: 12px 20px;
            border: none;
            border-radius: 10px;
            font-size: 0.95rem;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-run {
            width: 100%;
            background: #6b4f3a;
            color: #fff;
        }
        .btn-run:hover:not(:disabled) { background: #5a4230; }
        .btn-send {
            background: #6b4f3a;
            color: #fff;
        }
        .btn-send:hover:not(:disabled) { background: #5a4230; }
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Events Panel (Right side) */
        .events-panel {
            background: #fff;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .events-panel .panel-header {
            background: linear-gradient(135deg, #f3e5f5 0%, #f8f4fa 100%);
        }
        .events-list-container {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
        }
        .events-panel h4 {
            font-size: 0.85rem;
            color: #666;
            margin-bottom: 12px;
        }
        .event-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .event-item {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            background: #fff;
            border-radius: 8px;
            font-size: 0.85rem;
        }
        .event-icon { font-size: 1rem; }
        .event-title { flex: 1; }
        .event-confidence {
            font-size: 0.75rem;
            color: #4caf50;
            font-weight: 600;
        }
        .no-events {
            color: #999;
            font-size: 0.85rem;
            text-align: center;
            padding: 20px;
        }
        .side-section + .side-section {
            margin-top: 18px;
        }
        .side-section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 12px;
        }
        .section-action {
            border: none;
            border-radius: 999px;
            padding: 6px 12px;
            font-size: 0.75rem;
            font-weight: 600;
            cursor: pointer;
            background: #ede7f6;
            color: #5e35b1;
        }
        .section-action:hover:not(:disabled) {
            background: #e0d5f2;
        }
        .evaluation-summary {
            background: linear-gradient(180deg, #fcf8ff 0%, #f7f3ff 100%);
            border: 1px solid #eadfff;
            border-radius: 12px;
            padding: 14px;
        }
        .evaluation-summary.placeholder {
            color: #7b6f90;
            font-size: 0.84rem;
            line-height: 1.6;
        }
        .summary-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        .summary-item {
            background: rgba(255,255,255,0.9);
            border-radius: 10px;
            padding: 10px 12px;
        }
        .summary-label {
            display: block;
            font-size: 0.72rem;
            color: #6f5f86;
            margin-bottom: 4px;
        }
        .summary-value {
            display: block;
            font-size: 1rem;
            font-weight: 700;
            color: #3f2d5f;
        }
        .summary-meta {
            margin-top: 12px;
            font-size: 0.78rem;
            color: #75658a;
            line-height: 1.6;
        }
        .summary-compare {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .summary-agent {
            background: rgba(255,255,255,0.72);
            border-radius: 12px;
            padding: 12px;
        }
        .summary-agent.empty-agent {
            background: rgba(255,255,255,0.52);
        }
        .summary-agent-title {
            font-size: 0.82rem;
            font-weight: 700;
            color: #4c3a66;
            margin-bottom: 10px;
        }

        /* Footer */
        .compare-footer {
            background: #fff;
            padding: 12px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px solid #eee;
            font-size: 0.85rem;
            color: #666;
        }
        .btn-text {
            background: none;
            border: none;
            color: #6b4f3a;
            cursor: pointer;
            font-size: 0.85rem;
            padding: 6px 12px;
            border-radius: 6px;
        }
        .btn-text:hover { background: #f5f1eb; }
        .btn-text:disabled { color: #999; cursor: not-allowed; }

        /* === Report Drawer === */
        .btn-report-toggle {
            position: fixed; right: 0; top: 50%; transform: translateY(-50%);
            z-index: 1001; background: #2563eb; color: #fff; border: none;
            border-radius: 6px 0 0 6px; padding: 12px 8px; font-size: 18px;
            cursor: pointer; writing-mode: vertical-lr; letter-spacing: 2px;
            box-shadow: -2px 0 8px rgba(0,0,0,.15);
        }
        .btn-report-toggle:hover { background: #1d4ed8; }
        .drawer-overlay {
            display: none; position: fixed; inset: 0; background: rgba(0,0,0,.3);
            z-index: 1002;
        }
        .drawer-overlay.show { display: block; }
        .report-drawer {
            position: fixed; top: 0; right: -440px; width: 420px; height: 100vh;
            background: #fff; z-index: 1003; transition: right .3s ease;
            box-shadow: -4px 0 16px rgba(0,0,0,.1); display: flex; flex-direction: column;
            overflow: hidden;
        }
        .report-drawer.open { right: 0; }
        .drawer-header {
            display: flex; justify-content: space-between; align-items: center;
            padding: 16px 20px; border-bottom: 1px solid #e5e7eb;
            background: #f9fafb;
        }
        .drawer-header h3 { margin: 0; font-size: 16px; color: #111827; }
        .drawer-close { background: none; border: none; font-size: 20px; cursor: pointer; color: #6b7280; padding: 4px 8px; }
        .drawer-close:hover { color: #111827; }
        .drawer-body { flex: 1; overflow-y: auto; padding: 16px 20px; }
        .report-section { margin-bottom: 20px; }
        .report-section h4 {
            font-size: 13px; color: #6b7280; text-transform: uppercase;
            letter-spacing: .5px; margin: 0 0 10px; padding-bottom: 6px;
            border-bottom: 1px solid #f3f4f6;
        }
        .report-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .report-table th, .report-table td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #f3f4f6; }
        .report-table th { color: #6b7280; font-weight: 500; }
        .report-table td { color: #111827; }
        .report-kv { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
        .report-kv .k { color: #6b7280; }
        .report-kv .v { color: #111827; font-weight: 500; }
        .richness-bar { height: 8px; border-radius: 4px; background: #e5e7eb; overflow: hidden; flex: 1; margin: 0 8px; }
        .richness-fill { height: 100%; border-radius: 4px; background: #3b82f6; transition: width .3s; }
        .timing-bar-row { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; font-size: 12px; }
        .timing-bar-row .turn-label { width: 32px; text-align: right; color: #6b7280; flex-shrink: 0; }
        .timing-bar-stack { display: flex; height: 16px; border-radius: 3px; overflow: hidden; flex: 1; background: #f3f4f6; }
        .timing-bar-stack .seg { height: 100%; }
        .seg-retrieval { background: #3b82f6; }
        .seg-extraction { background: #f59e0b; }
        .seg-write { background: #10b981; }
        .timing-legend { display: flex; gap: 14px; font-size: 11px; color: #6b7280; margin-bottom: 10px; }
        .timing-legend span::before { content: ''; display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }
        .timing-legend .l-ret::before { background: #3b82f6; }
        .timing-legend .l-ext::before { background: #f59e0b; }
        .timing-legend .l-wri::before { background: #10b981; }
        .status-ok { color: #10b981; font-weight: 500; }
        .status-warn { color: #f59e0b; font-weight: 500; }
        .btn-refresh-report {
            background: #2563eb; color: #fff; border: none; border-radius: 6px;
            padding: 6px 14px; font-size: 13px; cursor: pointer;
        }
        .btn-refresh-report:hover { background: #1d4ed8; }
    </style>
</head>
<body>
    <!-- Top Bar -->
    <header class="top-bar">
        <div class="brand">
            <a href="/" style="display:inline-flex;align-items:center;gap:6px;color:rgba(255,255,255,.7);text-decoration:none;font-size:.85rem;margin-right:12px;padding:5px 10px;border-radius:6px;border:1px solid rgba(255,255,255,.25);transition:background .2s;" onmouseover="this.style.background='rgba(255,255,255,.12)'" onmouseout="this.style.background='transparent'">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
              返回首页
            </a>
            <h1 style="display:inline-flex;align-items:center;gap:8px;">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="9" height="16" rx="2"/><rect x="13" y="4" width="9" height="16" rx="2"/><path d="M7 9h3M7 12h3M7 15h3M14 9h3M14 12h3M14 15h3"/></svg>
              访谈系统对比调试
            </h1>
            <span class="subtitle">版本对比测试</span>
        </div>

        <div class="global-controls">
            <button id="btn-config" class="btn-icon">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:inline;vertical-align:middle;margin-right:4px"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
              老人信息
            </button>
            <div id="dashboard-status" class="status-indicator">
                <span class="dot"></span>
                <span class="label">数据看板</span>
            </div>
            <button id="btn-start-compare" class="btn-primary" disabled>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none" style="display:inline;vertical-align:middle;margin-right:5px"><polygon points="5,3 19,12 5,21"/></svg>
              开始对比测试
            </button>
        </div>
    </header>

    <!-- Config Modal -->
    <div id="config-modal" class="modal">
        <div class="modal-content">
            <header class="modal-header">
                <h2>老人信息配置</h2>
                <button class="btn-close" onclick="closeConfig()">&times;</button>
            </header>
            <form id="elder-config-form">
                <div class="form-row">
                    <label>
                        <span>姓名</span>
                        <input type="text" name="name" placeholder="如：王淑芬">
                    </label>
                    <label>
                        <span>出生年份</span>
                        <input type="number" name="birth_year" placeholder="如：1942">
                    </label>
                </div>
                <div class="form-row full-width">
                    <label>
                        <span>家乡</span>
                        <input type="text" name="hometown" placeholder="如：四川成都">
                    </label>
                </div>
                <div class="form-row full-width">
                    <label>
                        <span>生平简介</span>
                        <textarea name="background" rows="4" placeholder="请输入老人的基本生平信息，如：曾是纺织厂工人，经历过文革和改革开放，育有三个子女..."></textarea>
                    </label>
                </div>
                <div class="form-row">
                    <label>
                        <span>访谈模式</span>
                        <select name="mode">
                            <option value="ai">AI自动对话</option>
                            <option value="user">我亲自回答</option>
                        </select>
                    </label>
                    <label>
                        <span>数据看板URL</span>
                        <input type="url" name="dashboard_url" value="http://localhost:3000">
                    </label>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn-secondary" onclick="closeConfig()">取消</button>
                    <button type="submit" class="btn-primary">保存配置</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Main Compare Area -->
    <main class="compare-container">
        <!-- Baseline Panel -->
        <section class="panel baseline-panel" id="baseline-panel">
            <header class="panel-header">
                <div class="panel-title">
                    <span class="badge control" id="left-badge">对照组</span>
                    <h2 id="left-title">Baseline 版</h2>
                </div>
                <div class="panel-status">
                    <select id="left-version-select" class="version-select" onchange="onVersionChange()">
                        <option value="baseline">Baseline</option>
                        <option value="graphrag">GraphRAG Planner</option>
                        <option value="legacy">Legacy Planner</option>
                    </select>
                    <span class="status-text" id="baseline-status">等待开始</span>
                    <span class="mode-indicator" id="baseline-mode">-</span>
                </div>
            </header>
            <div class="panel-body">
                <div class="chat-container" id="baseline-chat">
                    <div class="empty-state">
                        <div class="empty-icon" style="font-size:36px;opacity:.4;">—</div>
                        <p>请先配置老人信息并开始测试</p>
                    </div>
                </div>
                <div class="controls" id="baseline-controls">
                    <div class="control-group ai-controls" style="display:none;">
                        <button id="baseline-run-btn" class="btn-run" disabled>▶ 自动运行</button>
                    </div>
                    <div class="control-group user-controls" style="display:none;">
                        <textarea id="baseline-input" placeholder="请输入回答..." disabled></textarea>
                        <button id="baseline-send-btn" class="btn-send" disabled>发送</button>
                    </div>
                </div>
            </div>
        </section>

        <!-- Planner Panel -->
        <section class="panel planner-panel" id="planner-panel">
            <header class="panel-header">
                <div class="panel-title">
                    <span class="badge experiment" id="right-badge">实验组</span>
                    <h2 id="right-title">GraphRAG Planner</h2>
                </div>
                <div class="panel-status">
                    <select id="right-version-select" class="version-select" onchange="onVersionChange()">
                        <option value="baseline">Baseline</option>
                        <option value="graphrag" selected>GraphRAG Planner</option>
                        <option value="legacy">Legacy Planner</option>
                    </select>
                    <span class="status-text" id="planner-status">等待开始</span>
                    <span class="mode-indicator" id="planner-mode">-</span>
                </div>
            </header>
            <div class="panel-body">
                <div class="chat-container" id="planner-chat">
                    <div class="empty-state">
                        <div class="empty-icon" style="font-size:36px;opacity:.4;">—</div>
                        <p>Planner版本将实时构建事件图谱</p>
                        <p class="hint">数据看板连接后可在新窗口查看完整可视化</p>
                    </div>
                </div>
                <div class="controls" id="planner-controls">
                    <div class="control-group ai-controls" style="display:none;">
                        <button id="planner-run-btn" class="btn-run" disabled>▶ 自动运行</button>
                    </div>
                    <div class="control-group user-controls" style="display:none;">
                        <textarea id="planner-input" placeholder="请输入回答..." disabled></textarea>
                        <button id="planner-send-btn" class="btn-send" disabled>发送</button>
                    </div>
                </div>
            </div>
        </section>

        <!-- Events Panel (Right) -->
        <section class="events-panel" id="events-panel">
            <header class="panel-header">
                <div class="panel-title">
                    <span class="badge" style="background: #9c27b0; color: #fff; display:inline-flex; align-items:center; padding:2px 6px;">
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a5 5 0 015 5c0 5-5 13-5 13S7 12 7 7a5 5 0 015-5z"/><circle cx="12" cy="7" r="2"/></svg>
                    </span>
                    <h2>最近提取的事件</h2>
                </div>
            </header>
            <div class="events-list-container" id="events-list-container">
                <p class="no-events">暂无事件</p>
            </div>
        </section>
    </main>

    <!-- Report Drawer -->
    <button id="btn-report" class="btn-report-toggle" onclick="toggleReport()">报告</button>
    <div id="drawer-overlay" class="drawer-overlay" onclick="toggleReport()"></div>
    <aside id="report-drawer" class="report-drawer">
        <div class="drawer-header">
            <h3>GraphRAG 运行报告</h3>
            <div style="display:flex;gap:8px;align-items:center">
                <button class="btn-refresh-report" onclick="loadReport()">刷新</button>
                <button class="drawer-close" onclick="toggleReport()"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
            </div>
        </div>
        <div class="drawer-body" id="report-content">
            <p style="color:#9ca3af;font-size:13px">开始对比测试后点击刷新查看报告</p>
        </div>
    </aside>

    <!-- Footer -->
    <footer class="compare-footer">
        <span id="session-info">会话: 未开始</span>
        <div>
            <button id="btn-reset" class="btn-text" onclick="resetTest()"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4.95"/></svg>重置测试</button>
        </div>
    </footer>

    <script>
        // Global state
        let config = null;
        let baselineSessionId = null;
        let plannerSessionId = null;
        let leftPanelVersion = "baseline";
        let rightPanelVersion = "graphrag";
        let currentMode = "ai";
        let dashboardWindow = null;
        let allExtractedEvents = [];  // 累积所有提取的事件
        let baselineAutoFinished = false;
        let plannerAutoFinished = false;
        let baselineEvaluationPollTimer = null;
        let plannerEvaluationPollTimer = null;
        let plannerMetricsActivated = false;
        let baselineQuestionQueue = [];
        let baselineQuestionMap = new Map();
        let plannerQuestionQueue = [];
        let plannerQuestionMap = new Map();
        let latestBaselineEvaluationSnapshot = null;
        let latestPlannerEvaluationSnapshot = null;
        let baselineEvaluationStatusText = "idle";
        let plannerEvaluationStatusText = "idle";

        // Timing accumulator
        const timingAccum = { baseline: [], planner: [] };
        // Token accumulator: { baseline: [...], planner: [...] }
        const tokenAccum = { baseline: [], planner: [] };

        function accumulateTiming(kind, timing) {
            if (!timing || typeof timing !== "object") return;
            timingAccum[kind].push(timing);
            if (timing.token_usage && typeof timing.token_usage === "object") {
                tokenAccum[kind].push(timing.token_usage);
                renderTokenSummary();
            }
            renderTimingSummary();
        }

        function avgMs(arr, key) {
            const vals = arr.map(r => r[key]).filter(v => v != null);
            if (vals.length === 0) return null;
            return vals.reduce((a, b) => a + b, 0) / vals.length;
        }

        function renderTimingSummary() {
            const el = document.getElementById("timing-summary-content");
            if (!el) return;

            const bAvgIv = avgMs(timingAccum.baseline, "interviewee_total_ms");
            const bAvgQ = avgMs(timingAccum.baseline, "interviewer_llm_ms");
            const pAvgIv = avgMs(timingAccum.planner, "interviewee_total_ms");
            const pAvgRet = avgMs(timingAccum.planner, "retrieval_ms");
            const pAvgExt = avgMs(timingAccum.planner, "extraction_ms");
            const pAvgWr = avgMs(timingAccum.planner, "write_ms");

            const bTurns = timingAccum.baseline.length;
            const pTurns = timingAccum.planner.length;

            if (bTurns === 0 && pTurns === 0) {
                el.innerHTML = '<div class="timing-summary placeholder">计时数据将在对话开始后自动显示</div>';
                return;
            }

            const maxMs = Math.max(bAvgIv || 0, bAvgQ || 0, pAvgIv || 0, pAvgRet || 0, pAvgExt || 0, pAvgWr || 0, 1);

            function row(label, bVal, pVal) {
                const bStr = bVal != null ? `${(bVal/1000).toFixed(1)}s` : "-";
                const pStr = pVal != null ? `${(pVal/1000).toFixed(1)}s` : "-";
                const bW = bVal != null ? Math.max(2, (bVal / maxMs) * 100) : 0;
                const pW = pVal != null ? Math.max(2, (pVal / maxMs) * 100) : 0;
                return `
                    <div class="timing-row">
                        <span class="timing-label">${label}</span>
                        <div class="timing-bar-container">
                            <div class="timing-bar baseline" style="width:${bW}%"></div>
                        </div>
                        <span class="timing-value">${bStr}</span>
                    </div>
                    <div class="timing-row">
                        <span class="timing-label"></span>
                        <div class="timing-bar-container">
                            <div class="timing-bar planner" style="width:${pW}%"></div>
                        </div>
                        <span class="timing-value">${pStr}</span>
                    </div>`;
            }

            el.innerHTML = `
                <div class="timing-summary">
                    <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                        <span style="font-size:0.72rem;color:#9e9e9e">● Baseline (${bTurns} turns)</span>
                        <span style="font-size:0.72rem;color:#2196f3">● Planner (${pTurns} turns)</span>
                    </div>
                    ${row("受访者", bAvgIv, pAvgIv)}
                    ${row("检索", null, pAvgRet)}
                    ${row("提取", null, pAvgExt)}
                    ${row("写入", null, pAvgWr)}
                    ${row("访谈者", bAvgQ, null)}
                </div>`;
        }

        function sumTokens(arr, key) {
            return arr.reduce((acc, r) => acc + (r[key] || 0), 0);
        }

        function renderTokenSummary() {
            const el = document.getElementById("token-summary-content");
            if (!el) return;
            const bTurns = tokenAccum.baseline;
            const pTurns = tokenAccum.planner;
            if (bTurns.length === 0 && pTurns.length === 0) {
                el.innerHTML = '<div class="token-summary placeholder">Token 数据将在对话开始后显示</div>';
                return;
            }

            function trow(label, bIn, bOut, pIn, pOut) {
                const bStr = (bIn != null || bOut != null)
                    ? `↑${(bIn||0).toLocaleString()} / ↓${(bOut||0).toLocaleString()}`
                    : "—";
                const pStr = (pIn != null || pOut != null)
                    ? `↑${(pIn||0).toLocaleString()} / ↓${(pOut||0).toLocaleString()}`
                    : "—";
                return `<div class="token-row">
                    <span class="token-label">${label}</span>
                    <span class="token-value" style="color:#9e9e9e;min-width:120px;text-align:right">${bStr}</span>
                    <span class="token-value" style="color:#512da8;min-width:120px;text-align:right">${pStr}</span>
                </div>`;
            }

            // Baseline: only interviewer (no extraction module)
            const bIvIn  = bTurns.length ? sumTokens(bTurns, "interviewer_prompt_tokens") : null;
            const bIvOut = bTurns.length ? sumTokens(bTurns, "interviewer_completion_tokens") : null;
            const bTotIn  = bTurns.length ? sumTokens(bTurns, "prompt_tokens") : null;
            const bTotOut = bTurns.length ? sumTokens(bTurns, "completion_tokens") : null;
            const bAvgIn  = bTurns.length ? Math.round(bTotIn / bTurns.length) : null;
            const bAvgOut = bTurns.length ? Math.round(bTotOut / bTurns.length) : null;

            // Planner: interviewer + extraction
            const pIvIn  = pTurns.length ? sumTokens(pTurns, "interviewer_prompt_tokens") : null;
            const pIvOut = pTurns.length ? sumTokens(pTurns, "interviewer_completion_tokens") : null;
            const pExIn  = pTurns.length ? sumTokens(pTurns, "extraction_prompt_tokens") : null;
            const pExOut = pTurns.length ? sumTokens(pTurns, "extraction_completion_tokens") : null;
            const pTotIn  = pTurns.length ? sumTokens(pTurns, "total_prompt_tokens") : null;
            const pTotOut = pTurns.length ? sumTokens(pTurns, "total_completion_tokens") : null;
            const pAvgIn  = pTurns.length ? Math.round(pTotIn / pTurns.length) : null;
            const pAvgOut = pTurns.length ? Math.round(pTotOut / pTurns.length) : null;

            const bLabel = bTurns.length ? `Baseline (${bTurns.length})` : "Baseline (—)";
            const pLabel = pTurns.length ? `Planner (${pTurns.length})` : "Planner (—)";
            const bAvgStr = bAvgIn != null ? `avg ↑${bAvgIn.toLocaleString()} / ↓${bAvgOut.toLocaleString()}` : "";
            const pAvgStr = pAvgIn != null ? `avg ↑${pAvgIn.toLocaleString()} / ↓${pAvgOut.toLocaleString()}` : "";

            el.innerHTML = `
                <div class="token-summary">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;gap:8px;">
                        <span style="font-size:0.7rem;font-weight:600;flex:1"></span>
                        <span style="font-size:0.7rem;color:#9e9e9e;min-width:120px;text-align:right">${bLabel}</span>
                        <span style="font-size:0.7rem;color:#512da8;min-width:120px;text-align:right">${pLabel}</span>
                    </div>
                    <div style="display:flex;justify-content:flex-end;gap:0;margin-bottom:6px;">
                        <span style="font-size:0.65rem;color:#9e9e9e;min-width:120px;text-align:right">${bAvgStr}</span>
                        <span style="font-size:0.65rem;color:#7b1fa2;min-width:120px;text-align:right">${pAvgStr}</span>
                    </div>
                    ${trow("访谈者", bIvIn, bIvOut, pIvIn, pIvOut)}
                    ${pExIn != null ? trow("提取", null, null, pExIn, pExOut) : ""}
                    <div class="token-row" style="border-top:2px solid rgba(81,45,168,0.15);margin-top:4px;padding-top:8px;">
                        <span class="token-label" style="font-weight:700">总计</span>
                        <span class="token-value" style="color:#616161;min-width:120px;text-align:right">${bTotIn != null ? "↑" + bTotIn.toLocaleString() + " / ↓" + bTotOut.toLocaleString() : "—"}</span>
                        <span class="token-value" style="color:#512da8;min-width:120px;text-align:right">${pTotIn != null ? "↑" + pTotIn.toLocaleString() + " / ↓" + pTotOut.toLocaleString() : "—"}</span>
                    </div>
                </div>`;
        }

        // DOM elements
        const configModal = document.getElementById("config-modal");
        const btnConfig = document.getElementById("btn-config");
        const btnStart = document.getElementById("btn-start-compare");
        const configForm = document.getElementById("elder-config-form");

        // Initialize panel styles from default select values
        applyVersionStyle("left", document.getElementById("left-version-select").value);
        applyVersionStyle("right", document.getElementById("right-version-select").value);
        const footerActions = document.querySelector(".compare-footer > div");

        if (footerActions && !document.getElementById("planner-eval-status")) {
            const statusSpan = document.createElement("span");
            statusSpan.id = "planner-eval-status";
            statusSpan.style.marginRight = "12px";
            statusSpan.textContent = "Evaluation: idle";
            footerActions.prepend(statusSpan);
        }

        initializePlannerSidePanel();

        // Config modal
        btnConfig.onclick = () => configModal.classList.add("active");
        function closeConfig() { configModal.classList.remove("active"); }

        // Config form submission
        configForm.onsubmit = async (e) => {
            e.preventDefault();
            const formData = new FormData(configForm);
            config = {
                name: formData.get("name"),
                birth_year: formData.get("birth_year"),
                hometown: formData.get("hometown"),
                background: formData.get("background"),
                mode: formData.get("mode"),
                dashboard_url: formData.get("dashboard_url")
            };
            currentMode = config.mode;
            closeConfig();
            btnStart.disabled = false;
            btnStart.textContent = "▶ 开始对比测试";
        };

        function buildDashboardUrl(sessionId) {
            const url = new URL(config.dashboard_url, window.location.origin);
            url.searchParams.set("session", sessionId || "pending");
            url.searchParams.set("backend", window.location.origin);
            return url.toString();
        }

        function openDashboardLoadingWindow() {
            const popup = window.open("", "Dashboard", "width=1200,height=800");
            if (!popup) {
                return null;
            }
            popup.document.write(`
                <!DOCTYPE html>
                <html lang="zh-CN">
                <head>
                    <meta charset="UTF-8">
                    <title>数据看板初始化中</title>
                    <style>
                        body {
                            margin: 0;
                            min-height: 100vh;
                            display: grid;
                            place-items: center;
                            font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
                            background: linear-gradient(135deg, #f5f1eb 0%, #efe6d9 100%);
                            color: #5b4636;
                        }
                        .card {
                            padding: 28px 32px;
                            border-radius: 16px;
                            background: rgba(255,255,255,0.92);
                            box-shadow: 0 16px 40px rgba(107,79,58,0.15);
                            text-align: center;
                        }
                        .hint {
                            margin-top: 8px;
                            font-size: 14px;
                            color: #7b6758;
                        }
                    </style>
                </head>
                <body>
                    <div class="card">
                        <div>数据看板初始化中...</div>
                        <div class="hint">访谈会话创建成功后将自动进入图谱页面</div>
                    </div>
                </body>
                </html>
            `);
            popup.document.close();
            return popup;
        }

        function finishAutoTurn(kind, ended) {
            const runBtn = document.getElementById(`${kind}-run-btn`);
            const status = document.getElementById(`${kind}-status`);
            if (ended) {
                status.textContent = "已完成";
                runBtn.disabled = true;
                if (kind === "baseline") {
                    baselineAutoFinished = true;
                } else {
                    plannerAutoFinished = true;
                }
                return;
            }

            status.textContent = "等待下一轮";
            runBtn.disabled = false;
        }

        async function requestJson(url, options) {
            const res = await fetch(url, options);
            const text = await res.text();
            const contentType = res.headers.get("content-type") || "";

            let data = null;
            if (text) {
                try {
                    data = JSON.parse(text);
                } catch (err) {
                    data = null;
                }
            }

            if (!res.ok) {
                const plainText = text
                    .replace(/<[^>]+>/g, " ")
                    .replace(/\\s+/g, " ")
                    .trim();
                const message =
                    data?.error ||
                    data?.message ||
                    plainText ||
                    `${url} 请求失败 (${res.status})`;
                throw new Error(message);
            }

            if (data !== null) {
                return data;
            }

            throw new Error(`${url} 未返回 JSON，实际 content-type: ${contentType || "unknown"}`);
        }

        function initializePlannerSidePanel() {
            const container = document.getElementById("events-list-container");
            if (!container) return;

            container.innerHTML = `
                <section class="side-section">
                    <div class="side-section-header">
                        <h4>Overall Metrics</h4>
                        <button id="btn-generate-metrics" class="section-action" disabled>Generate</button>
                    </div>
                    <div id="evaluation-summary" class="evaluation-summary placeholder">
                        Click Generate to compare baseline and planner coverage, average question quality, and information gain.
                    </div>
                </section>
                <section class="side-section">
                    <div class="side-section-header">
                        <h4>Timing</h4>
                    </div>
                    <div id="timing-summary-content">
                        <div class="timing-summary placeholder">计时数据将在对话开始后自动显示</div>
                    </div>
                </section>
                <section class="side-section">
                    <div class="side-section-header">
                        <h4>Tokens</h4>
                    </div>
                    <div id="token-summary-content">
                        <div class="token-summary placeholder">Token 数据将在 Planner 对话开始后显示</div>
                    </div>
                </section>
                <section class="side-section">
                    <div class="side-section-header">
                        <h4>Recent Events</h4>
                    </div>
                    <div id="events-list-content">
                        <p class="no-events">No events yet</p>
                    </div>
                </section>
            `;

            const btnGenerateMetrics = document.getElementById("btn-generate-metrics");
            if (btnGenerateMetrics) {
                btnGenerateMetrics.onclick = fetchCombinedEvaluationSummary;
            }
        }

        async function fetchCombinedEvaluationSummary() {
            const btnGenerateMetrics = document.getElementById("btn-generate-metrics");
            if (!btnGenerateMetrics) return;

            plannerMetricsActivated = true;
            btnGenerateMetrics.disabled = true;
            btnGenerateMetrics.textContent = "Loading...";
            try {
                const leftEvalEndpoint = leftPanelVersion === "baseline" ? "/api/baseline/evaluation" : "/api/planner/evaluation";
                const rightEvalEndpoint = rightPanelVersion === "baseline" ? "/api/baseline/evaluation" : "/api/planner/evaluation";
                const [baselineSnapshot, plannerSnapshot] = await Promise.all([
                    baselineSessionId ? requestJson(`${leftEvalEndpoint}/${baselineSessionId}`) : Promise.resolve(null),
                    plannerSessionId ? requestJson(`${rightEvalEndpoint}/${plannerSessionId}`) : Promise.resolve(null),
                ]);
                if (baselineSnapshot) {
                    applyBaselineEvaluationSnapshot(baselineSnapshot);
                }
                if (plannerSnapshot) {
                    applyPlannerEvaluationSnapshot(plannerSnapshot);
                }
                renderEvaluationSummary();
            } catch (err) {
                renderEvaluationSummaryError(err.message);
            } finally {
                btnGenerateMetrics.disabled = false;
                btnGenerateMetrics.textContent = "Refresh";
            }
        }

        function resetPlannerTracking() {
            plannerMetricsActivated = false;
            baselineQuestionQueue = [];
            baselineQuestionMap = new Map();
            plannerQuestionQueue = [];
            plannerQuestionMap = new Map();
            latestBaselineEvaluationSnapshot = null;
            latestPlannerEvaluationSnapshot = null;
            stopBaselineEvaluationPolling();
            stopPlannerEvaluationPolling();
            updateBaselineEvaluationStatus("idle");
            updatePlannerEvaluationStatus("idle");
            initializePlannerSidePanel();
        }

        function updateCombinedEvaluationStatus() {
            const statusEl = document.getElementById("planner-eval-status");
            if (statusEl) {
                statusEl.textContent = `Evaluation: B ${baselineEvaluationStatusText} | P ${plannerEvaluationStatusText}`;
            }
        }

        function updateBaselineEvaluationStatus(text) {
            baselineEvaluationStatusText = text;
            updateCombinedEvaluationStatus();
        }

        function updatePlannerEvaluationStatus(text) {
            plannerEvaluationStatusText = text;
            updateCombinedEvaluationStatus();
        }

        function formatPercent(value) {
            return `${Math.round((value || 0) * 100)}%`;
        }

        function formatCoverageGain(value) {
            return `${Math.round((value || 0) * 100)}pt`;
        }

        function renderPendingEvaluation(container, text = "Waiting for answer") {
            container.innerHTML = `<span class="evaluation-chip pending">${text}</span>`;
        }

        function renderTurnEvaluation(container, evaluation) {
            if (!container) return;
            if (!evaluation || !evaluation.turn_id) {
                renderPendingEvaluation(container);
                return;
            }

            if (evaluation.status === "pending" || evaluation.question_quality_score === undefined) {
                renderPendingEvaluation(container, "Scoring...");
                return;
            }

            const notes = Array.isArray(evaluation.notes) ? evaluation.notes : [];
            const targetSlots = Array.isArray(evaluation.targeted_slots) ? evaluation.targeted_slots : [];
            const noteText = notes.length > 0 ? notes.join(" | ") : "";
            const slotText = targetSlots.length > 0 ? `Slots ${targetSlots.join("/")}` : "No slot target";
            container.innerHTML = `
                <span class="evaluation-chip score">Question ${formatPercent(evaluation.question_quality_score)}</span>
                <span class="evaluation-chip info">Gain ${formatPercent(evaluation.information_gain_score)}</span>
                <span class="evaluation-chip slot">${slotText}</span>
                <span class="evaluation-chip coverage">Coverage ${formatCoverageGain(evaluation.coverage_gain)}</span>
                ${noteText ? `<span class="evaluation-chip notes" title="${noteText}">Notes</span>` : ""}
            `;
        }

        function appendScoredQuestion(queueRef, container, text, action, debugTrace, timingData) {
            const msg = appendMessage(container, "interviewer", text, action, null, debugTrace, timingData);
            const evaluationEl = document.createElement("div");
            evaluationEl.className = "message-evaluation";
            renderPendingEvaluation(evaluationEl);
            msg.appendChild(evaluationEl);

            const item = {
                element: msg,
                evaluationEl,
                turnId: null,
            };
            queueRef.push(item);
            return item;
        }

        function appendBaselineQuestion(container, text, action, debugTrace, timingData) {
            return appendScoredQuestion(baselineQuestionQueue, container, text, action, debugTrace, timingData);
        }

        function appendPlannerQuestion(container, text, action, debugTrace, timingData, plannerPlan) {
            const item = appendScoredQuestion(plannerQuestionQueue, container, text, action, debugTrace, timingData);
            if (plannerPlan && typeof plannerPlan === "object" && Object.keys(plannerPlan).length > 0) {
                const planDiv = document.createElement("div");
                planDiv.className = "plan-chips";
                const stageLabels = {
                    life_overview: "人生概览", event_deepening: "事件深挖",
                    theme_expansion: "主题拓展", reflection: "回顾反思", closing: "收尾总结",
                };
                const emotionLabels = { positive: "正面", neutral: "中性", negative: "低落" };
                if (plannerPlan.stage) {
                    const chip = document.createElement("span");
                    chip.className = "plan-chip stage";
                    chip.textContent = stageLabels[plannerPlan.stage] || plannerPlan.stage;
                    planDiv.appendChild(chip);
                }
                if (plannerPlan.focus && plannerPlan.focus.label) {
                    const chip = document.createElement("span");
                    chip.className = "plan-chip focus";
                    chip.textContent = plannerPlan.focus.label;
                    planDiv.appendChild(chip);
                }
                if (plannerPlan.event_completeness && plannerPlan.event_completeness.score != null) {
                    const chip = document.createElement("span");
                    chip.className = "plan-chip completeness";
                    chip.textContent = `完整度 ${Math.round(plannerPlan.event_completeness.score * 100)}%`;
                    planDiv.appendChild(chip);
                }
                if (plannerPlan.emotion_signal) {
                    const chip = document.createElement("span");
                    chip.className = "plan-chip emotion";
                    const e = plannerPlan.emotion_signal;
                    chip.textContent = `${emotionLabels[e.valence] || e.valence || ""} ${Math.round((e.energy || 0) * 100)}%`;
                    planDiv.appendChild(chip);
                }
                if (plannerPlan.question_intent) {
                    const chip = document.createElement("span");
                    chip.className = "plan-chip intent";
                    chip.textContent = plannerPlan.question_intent;
                    planDiv.appendChild(chip);
                }
                if (planDiv.children.length > 0) {
                    item.element.appendChild(planDiv);
                }
            }
            return item;
        }

        function bindPendingEvaluation(queueRef, mapRef, turnEvaluation, statusUpdater) {
            if (!turnEvaluation || !turnEvaluation.turn_id) return;

            const item = queueRef.find((candidate) => !candidate.turnId);
            if (!item) return;

            item.turnId = turnEvaluation.turn_id;
            item.element.dataset.turnId = turnEvaluation.turn_id;
            mapRef.set(turnEvaluation.turn_id, item);
            renderTurnEvaluation(item.evaluationEl, turnEvaluation);
            statusUpdater("background scoring");
        }

        function bindPendingBaselineTurnEvaluation(turnEvaluation) {
            bindPendingEvaluation(baselineQuestionQueue, baselineQuestionMap, turnEvaluation, updateBaselineEvaluationStatus);
        }

        function bindPendingTurnEvaluation(turnEvaluation) {
            bindPendingEvaluation(plannerQuestionQueue, plannerQuestionMap, turnEvaluation, updatePlannerEvaluationStatus);
        }

        function applyEvaluationSnapshot(mapRef, snapshot, statusUpdater, kind) {
            const evaluations = snapshot?.turn_evaluations || {};
            Object.entries(evaluations).forEach(([turnId, evaluation]) => {
                const item = mapRef.get(turnId);
                if (item) {
                    renderTurnEvaluation(item.evaluationEl, evaluation);
                }
            });

            const pendingCount = Array.isArray(snapshot?.pending_turn_ids) ? snapshot.pending_turn_ids.length : 0;
            const completedCount = snapshot?.completed_turn_count || 0;
            if (pendingCount > 0) {
                statusUpdater(`running ${pendingCount}, done ${completedCount}`);
            } else if (completedCount > 0) {
                statusUpdater(`done ${completedCount}`);
            } else {
                statusUpdater("waiting for first score");
            }

            if (plannerMetricsActivated) {
                renderEvaluationSummary();
            }

            if (kind === "baseline" && baselineAutoFinished && pendingCount === 0) {
                stopBaselineEvaluationPolling();
            }
            if (kind === "planner" && plannerAutoFinished && pendingCount === 0) {
                stopPlannerEvaluationPolling();
            }
        }

        function applyBaselineEvaluationSnapshot(snapshot) {
            latestBaselineEvaluationSnapshot = snapshot;
            applyEvaluationSnapshot(baselineQuestionMap, snapshot, updateBaselineEvaluationStatus, "baseline");
        }

        function applyPlannerEvaluationSnapshot(snapshot) {
            latestPlannerEvaluationSnapshot = snapshot;
            applyEvaluationSnapshot(plannerQuestionMap, snapshot, updatePlannerEvaluationStatus, "planner");
        }

        function renderMetricBlock(label, snapshot) {
            if (!snapshot) {
                return `
                    <div class="summary-agent empty-agent">
                        <div class="summary-agent-title">${label}</div>
                        <div class="summary-meta">No evaluation snapshot yet.</div>
                    </div>
                `;
            }

            const sessionMetrics = snapshot.session_metrics || {};
            const coverageMetrics = snapshot.coverage_metrics || {};
            const pendingCount = Array.isArray(snapshot.pending_turn_ids) ? snapshot.pending_turn_ids.length : 0;
            const completedCount = snapshot.completed_turn_count || 0;
            return `
                <div class="summary-agent">
                    <div class="summary-agent-title">${label}</div>
                    <div class="summary-grid">
                        <div class="summary-item">
                            <span class="summary-label">Coverage</span>
                            <span class="summary-value">${formatPercent(coverageMetrics.overall_coverage)}</span>
                        </div>
                        <div class="summary-item">
                            <span class="summary-label">People</span>
                            <span class="summary-value">${formatPercent(sessionMetrics.people_coverage)}</span>
                        </div>
                        <div class="summary-item">
                            <span class="summary-label">Question Quality</span>
                            <span class="summary-value">${formatPercent(sessionMetrics.average_turn_quality)}</span>
                        </div>
                        <div class="summary-item">
                            <span class="summary-label">Info Gain</span>
                            <span class="summary-value">${formatPercent(sessionMetrics.average_information_gain)}</span>
                        </div>
                    </div>
                    <div class="summary-meta">
                        Completed ${completedCount}, pending ${pendingCount}.<br>
                        Loop closure ${formatPercent(sessionMetrics.open_loop_closure_rate)}, contradiction resolution ${formatPercent(sessionMetrics.contradiction_resolution_rate)}.
                    </div>
                </div>
            `;
        }

        function renderEvaluationSummary() {
            const summaryEl = document.getElementById("evaluation-summary");
            if (!summaryEl) return;

            summaryEl.classList.remove("placeholder");
            summaryEl.innerHTML = `
                <div class="summary-compare">
                    ${renderMetricBlock("Baseline", latestBaselineEvaluationSnapshot)}
                    ${renderMetricBlock("Planner", latestPlannerEvaluationSnapshot)}
                </div>
            `;
        }

        function renderEvaluationSummaryError(message) {
            const summaryEl = document.getElementById("evaluation-summary");
            if (!summaryEl) return;

            summaryEl.classList.add("placeholder");
            summaryEl.textContent = `Failed to load metrics: ${message}`;
        }

        async function pollBaselineEvaluationState() {
            if (!baselineSessionId) return;

            try {
                const leftEvalEndpoint = leftPanelVersion === "baseline" ? "/api/baseline/evaluation" : "/api/planner/evaluation";
                const snapshot = await requestJson(`${leftEvalEndpoint}/${baselineSessionId}`);
                applyBaselineEvaluationSnapshot(snapshot);
            } catch (err) {
                console.warn("Baseline evaluation polling failed:", err);
            }
        }

        function startBaselineEvaluationPolling() {
            stopBaselineEvaluationPolling();
            if (!baselineSessionId) return;
            pollBaselineEvaluationState();
            baselineEvaluationPollTimer = window.setInterval(pollBaselineEvaluationState, 1500);
        }

        function stopBaselineEvaluationPolling() {
            if (baselineEvaluationPollTimer) {
                window.clearInterval(baselineEvaluationPollTimer);
                baselineEvaluationPollTimer = null;
            }
        }

        async function pollPlannerEvaluationState() {
            if (!plannerSessionId) return;

            try {
                const rightEvalEndpoint = rightPanelVersion === "baseline" ? "/api/baseline/evaluation" : "/api/planner/evaluation";
                const snapshot = await requestJson(`${rightEvalEndpoint}/${plannerSessionId}`);
                applyPlannerEvaluationSnapshot(snapshot);
            } catch (err) {
                console.warn("Planner evaluation polling failed:", err);
            }
        }

        function startPlannerEvaluationPolling() {
            stopPlannerEvaluationPolling();
            if (!plannerSessionId) return;
            pollPlannerEvaluationState();
            plannerEvaluationPollTimer = window.setInterval(pollPlannerEvaluationState, 1500);
        }

        function stopPlannerEvaluationPolling() {
            if (plannerEvaluationPollTimer) {
                window.clearInterval(plannerEvaluationPollTimer);
                plannerEvaluationPollTimer = null;
            }
        }

        // Start comparison
        btnStart.onclick = async () => {
            if (!config) return;

            const leftVersion  = document.getElementById("left-version-select").value;
            const rightVersion = document.getElementById("right-version-select").value;

            // Reset state
            allExtractedEvents = [];
            resetPlannerTracking();
            updateEventList([]);
            updatePlannerEvaluationStatus("starting");

            btnStart.disabled = true;
            btnStart.textContent = "初始化中...";
            baselineAutoFinished = false;
            plannerAutoFinished = false;

            // Lock version selects for the duration of this session
            document.getElementById("left-version-select").disabled = true;
            document.getElementById("right-version-select").disabled = true;

            // Open dashboard window only when a graphrag/legacy panel is present
            const hasPlanner = leftVersion !== "baseline" || rightVersion !== "baseline";
            if (hasPlanner && config.dashboard_url) {
                dashboardWindow = openDashboardLoadingWindow();
                updateDashboardStatus(Boolean(dashboardWindow));
            }

            try {
                // Start both sessions in parallel
                const [baselineResult, plannerResult] = await Promise.all([
                    startLeftPanel(),
                    startRightPanel()
                ]);

                baselineSessionId = baselineResult.session_id;
                plannerSessionId = plannerResult.session_id;
                leftPanelVersion = leftVersion;
                rightPanelVersion = rightVersion;

                // Update dashboard window with the planner session on the right (if any)
                if (dashboardWindow && plannerSessionId && rightVersion !== "baseline") {
                    dashboardWindow.location.href = buildDashboardUrl(plannerSessionId);
                }

                // Update UI
                document.getElementById("session-info").textContent =
                    `会话: ${getVersionLabel(leftVersion)}(${baselineSessionId.slice(0, 8)})... / ${getVersionLabel(rightVersion)}(${plannerSessionId.slice(0, 8)})...`;

                // Setup panels
                setupBaselinePanel(baselineResult);
                setupPlannerPanel(plannerResult);
                startBaselineEvaluationPolling();
                startPlannerEvaluationPolling();
                if (document.getElementById("btn-generate-metrics")) {
                    document.getElementById("btn-generate-metrics").disabled = false;
                }

                // Auto-start if AI mode
                if (currentMode === "ai") {
                    setTimeout(() => {
                        runBaselineAuto();
                        runPlannerAuto();
                    }, 500);
                }

            } catch (err) {
                if (dashboardWindow && !dashboardWindow.closed) {
                    dashboardWindow.document.body.innerHTML =
                        `<div style="font-family: PingFang SC, Microsoft YaHei, sans-serif; padding: 24px;">数据看板初始化失败：${err.message}</div>`;
                }
                updateDashboardStatus(false);
                alert("启动失败: " + err.message);
                btnStart.disabled = false;
                btnStart.textContent = "▶ 开始对比测试";
                document.getElementById("left-version-select").disabled = false;
                document.getElementById("right-version-select").disabled = false;
            }
        };

        function getVersionLabel(version) {
            return { baseline: "Baseline", graphrag: "GraphRAG Planner", legacy: "Legacy Planner" }[version] || version;
        }

        function onVersionChange() {
            const leftSel = document.getElementById("left-version-select");
            const rightSel = document.getElementById("right-version-select");
            const lv = leftSel.value;
            const rv = rightSel.value;

            // Prevent same version on both sides
            if (lv === rv) {
                // Pick any version that differs
                const all = ["baseline", "graphrag", "legacy"];
                const alt = all.find(v => v !== lv);
                rightSel.value = alt;
            }

            // Update panel titles and badges
            applyVersionStyle("left", document.getElementById("left-version-select").value);
            applyVersionStyle("right", document.getElementById("right-version-select").value);
        }

        function applyVersionStyle(side, version) {
            const badge = document.getElementById(side + "-badge");
            const title = document.getElementById(side + "-title");
            const panel = document.getElementById(side === "left" ? "baseline-panel" : "planner-panel");

            const configs = {
                baseline:  { label: "对照组", badgeClass: "control",    bg: "linear-gradient(135deg, #e8e4e0 0%, #f5f1eb 100%)", text: "Baseline" },
                graphrag:  { label: "实验组", badgeClass: "experiment",  bg: "linear-gradient(135deg, #e3f2fd 0%, #f3f9ff 100%)", text: "GraphRAG Planner" },
                legacy:    { label: "旧版本", badgeClass: "legacy",      bg: "linear-gradient(135deg, #ede7f6 0%, #f9f5ff 100%)", text: "Legacy Planner" },
            };
            const c = configs[version] || configs.baseline;
            badge.className = "badge " + c.badgeClass;
            badge.textContent = c.label;
            title.textContent = c.text;
            panel.querySelector(".panel-header").style.background = c.bg;
        }

        async function startLeftPanel() {
            const version = document.getElementById("left-version-select").value;
            if (version === "baseline") {
                return await requestJson("/api/baseline/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ elder_info: config, mode: config.mode })
                });
            } else {
                return await requestJson("/api/planner/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ elder_info: config, mode: config.mode, version })
                });
            }
        }

        async function startRightPanel() {
            const version = document.getElementById("right-version-select").value;
            if (version === "baseline") {
                return await requestJson("/api/baseline/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ elder_info: config, mode: config.mode })
                });
            } else {
                return await requestJson("/api/planner/start", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ elder_info: config, mode: config.mode, version })
                });
            }
        }

        // Legacy aliases kept for any inline callers
        async function startBaseline() { return startLeftPanel(); }
        async function startPlanner()  { return startRightPanel(); }

        function setupBaselinePanel(result) {
            const chat = document.getElementById("baseline-chat");
            const status = document.getElementById("baseline-status");
            const mode = document.getElementById("baseline-mode");

            chat.innerHTML = "";
            appendBaselineQuestion(chat, result.first_question);
            status.textContent = "进行中";
            mode.textContent = currentMode === "ai" ? "AI模式" : "用户模式";

            // Show controls
            if (currentMode === "ai") {
                document.querySelector("#baseline-controls .ai-controls").style.display = "block";
                document.querySelector("#baseline-controls .user-controls").style.display = "none";
                document.getElementById("baseline-run-btn").disabled = false;
            } else {
                document.querySelector("#baseline-controls .ai-controls").style.display = "none";
                document.querySelector("#baseline-controls .user-controls").style.display = "flex";
                document.getElementById("baseline-input").disabled = false;
                document.getElementById("baseline-send-btn").disabled = false;
            }
        }

        function setupPlannerPanel(result) {
            const chat = document.getElementById("planner-chat");
            const status = document.getElementById("planner-status");
            const mode = document.getElementById("planner-mode");

            chat.innerHTML = "";
            appendPlannerQuestion(chat, result.first_question, "continue", result.debug_trace);
            status.textContent = "进行中";
            mode.textContent = currentMode === "ai" ? "AI模式" : "用户模式";

            // Show controls
            if (currentMode === "ai") {
                document.querySelector("#planner-controls .ai-controls").style.display = "block";
                document.querySelector("#planner-controls .user-controls").style.display = "none";
                document.getElementById("planner-run-btn").disabled = false;
            } else {
                document.querySelector("#planner-controls .ai-controls").style.display = "none";
                document.querySelector("#planner-controls .user-controls").style.display = "flex";
                document.getElementById("planner-input").disabled = false;
                document.getElementById("planner-send-btn").disabled = false;
            }

        }

        function appendMessage(container, role, text, action, memoryCalls, debugTrace, timingData) {
            const msg = document.createElement("div");
            msg.className = `message ${role}`;

            let label = role === "interviewer" ? "访谈者" : "受访者";
            let actionTag = "";
            const labels = {
                system: "System",
                error: "System error",
            };
            label = labels[role] || label;
            if (action && action !== "continue") {
                actionTag = `<span class="action-tag">${action}</span>`;
            }

            msg.innerHTML = `
                <div class="msg-label">${label}${actionTag}</div>
                <div class="msg-text">${text}</div>
            `;

            // Timing chips
            if (timingData && typeof timingData === "object" && Object.keys(timingData).length > 0) {
                const timingDiv = document.createElement("div");
                timingDiv.className = "timing-chips";
                const labels = {
                    interviewee_total_ms: "受访者",
                    interviewee_llm_ms: "LLM",
                    interviewee_tool_ms: "工具",
                    interviewer_llm_ms: "访谈者",
                    retrieval_ms: "检索",
                    extraction_ms: "提取",
                    write_ms: "写入",
                };
                for (const [key, val] of Object.entries(timingData)) {
                    if (val == null || key === "token_usage") continue;
                    const chip = document.createElement("span");
                    const sec = (val / 1000).toFixed(1);
                    const lbl = labels[key] || key;
                    chip.className = `timing-chip${val > 5000 ? " slow" : ""}`;
                    chip.textContent = `${lbl} ${sec}s`;
                    timingDiv.appendChild(chip);
                }
                // Token chips — use total_* (planner) or prompt_tokens (baseline)
                const tu = timingData.token_usage;
                if (tu && typeof tu === "object") {
                    const totalIn = tu.total_prompt_tokens ?? tu.prompt_tokens;
                    const totalOut = tu.total_completion_tokens ?? tu.completion_tokens;
                    if (totalIn != null) {
                        const chip = document.createElement("span");
                        chip.className = "token-chip";
                        chip.textContent = `↑${totalIn.toLocaleString()} tok`;
                        chip.title = "Prompt tokens this turn";
                        timingDiv.appendChild(chip);
                    }
                    if (totalOut != null) {
                        const chip = document.createElement("span");
                        chip.className = "token-chip";
                        chip.textContent = `↓${totalOut.toLocaleString()} tok`;
                        chip.title = "Completion tokens this turn";
                        timingDiv.appendChild(chip);
                    }
                }
                msg.appendChild(timingDiv);
            }

            if (memoryCalls && memoryCalls.length > 0) {
                const memDiv = document.createElement("div");
                memDiv.className = "memory-calls";
                for (const call of memoryCalls) {
                    const chip = document.createElement("span");
                    chip.className = "memory-chip";
                    const toolLabel = {
                        search_memories_by_keywords: "关键词",
                        search_memories_by_tags: "标签",
                        get_memories_by_period: "时期",
                        get_memory_by_id: "记忆ID",
                        get_related_memories: "关联记忆",
                    }[call.tool] || call.tool;

                    const resultCount = Array.isArray(call.result) ? call.result.length : (call.result ? 1 : 0);
                    const argsStr = JSON.stringify(call.args, null, 2);
                    const fullResult = JSON.stringify(call.result, null, 2);

                    chip.innerHTML = `${toolLabel} (${resultCount})
                        <span class="memory-tooltip">调用：${call.tool}\n参数：${argsStr}\n结果：${fullResult || "无"}</span>`;
                    memDiv.appendChild(chip);
                }
                msg.appendChild(memDiv);
            }

            if (role === "interviewer" && debugTrace && Object.keys(debugTrace).length > 0) {
                const dbgDiv = document.createElement("div");
                dbgDiv.className = "debug-calls";

                const extraction = debugTrace.extraction || {};
                const merge = debugTrace.merge || {};
                const planning = debugTrace.planning || {};
                const plannerPlan = debugTrace.planner_plan || {};
                const toolTrace = debugTrace.tool_trace || [];
                const candidateCount = extraction.candidate_count || (extraction.candidate_events || []).length || 0;
                const hintCount = extraction.similarity_hint_count || 0;
                const decisions = merge.decisions || [];
                const fallbackReasons = merge.fallback_reasons || [];

                const chips = [
                    {
                        label: `候选 ${candidateCount}`,
                        tooltip: `候选事件:\n${JSON.stringify(extraction.candidate_events || [], null, 2)}`,
                        warning: false,
                    },
                    {
                        label: `Hints ${hintCount}`,
                        tooltip: `相似度建议:\n${JSON.stringify(extraction.similarity_hints || [], null, 2)}`,
                        warning: false,
                    },
                    {
                        label: `Merge ${decisions.length}`,
                        tooltip: `Merge 决策:\n${JSON.stringify(decisions, null, 2)}`,
                        warning: false,
                    },
                ];

                if (fallbackReasons.length > 0) {
                    chips.push({
                        label: `Fallback ${fallbackReasons.length}`,
                        tooltip: `Fallback 原因:\n${JSON.stringify(fallbackReasons, null, 2)}`,
                        warning: true,
                    });
                }

                if (Object.keys(planning).length > 0 || Object.keys(plannerPlan).length > 0) {
                    const action = planning.selected_action || planning.next_action || "plan";
                    const score = planning.event_completeness_score;
                    const scoreLabel = typeof score === "number" ? ` ${Math.round(score * 100)}%` : "";
                    chips.push({
                        label: `Plan ${action}${scoreLabel}`,
                        tooltip: `Planner 决策摘要:\n${JSON.stringify(plannerPlan || planning, null, 2)}`,
                        warning: false,
                    });
                }

                if (toolTrace.length > 0) {
                    chips.push({
                        label: `Tools ${toolTrace.length}`,
                        tooltip: `Planner 工具调用:\n${JSON.stringify(toolTrace, null, 2)}`,
                        warning: false,
                    });
                }

                chips.forEach((item) => {
                    const chip = document.createElement("span");
                    chip.className = `debug-chip ${item.warning ? "warning" : ""}`.trim();
                    chip.innerHTML = `${item.label}<span class="debug-tooltip">${item.tooltip}</span>`;
                    dbgDiv.appendChild(chip);
                });

                msg.appendChild(dbgDiv);
            }

            container.appendChild(msg);
            container.scrollTop = container.scrollHeight;
            return msg;
        }

        // Baseline controls
        document.getElementById("baseline-run-btn").onclick = runBaselineAuto;
        document.getElementById("baseline-send-btn").onclick = sendBaselineReply;
        document.getElementById("baseline-input").onkeydown = (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendBaselineReply();
            }
        };

        async function runBaselineAuto() {
            if (!baselineSessionId || baselineAutoFinished) return;
            document.getElementById("baseline-run-btn").disabled = true;
            document.getElementById("baseline-status").textContent = "本轮进行中";
            const chat = document.getElementById("baseline-chat");
            let interviewEnded = false;

            const leftAutoEndpoint = leftPanelVersion === "baseline" ? "/api/baseline/auto" : "/api/planner/auto";
            const evtSource = new EventSource(`${leftAutoEndpoint}?session_id=${baselineSessionId}&single_turn=1`);

            evtSource.onmessage = (e) => {
                const msg = JSON.parse(e.data);
                if (msg.role === "done") {
                    evtSource.close();
                    finishAutoTurn("baseline", interviewEnded);
                    return;
                }
                if (msg.role === "interviewer" && msg.action === "end") {
                    interviewEnded = true;
                }
                if (msg.role === "interviewer") {
                    bindPendingBaselineTurnEvaluation(msg.turn_evaluation);
                    appendBaselineQuestion(chat, msg.text, msg.action, msg.debug_trace, msg.timing);
                } else {
                    appendMessage(chat, msg.role, msg.text, msg.action, msg.memory_calls, null, msg.timing);
                }
                accumulateTiming("baseline", msg.timing);
            };

            evtSource.onerror = () => {
                evtSource.close();
                document.getElementById("baseline-status").textContent = "等待下一轮";
                document.getElementById("baseline-run-btn").disabled = false;
            };
        }

        async function sendBaselineReply() {
            const input = document.getElementById("baseline-input");
            const chat = document.getElementById("baseline-chat");
            const answer = input.value.trim();
            if (!answer) return;

            input.value = "";
            input.disabled = true;
            document.getElementById("baseline-send-btn").disabled = true;

            appendMessage(chat, "interviewee", answer);

            const leftReplyEndpoint = leftPanelVersion === "baseline" ? "/api/baseline/reply" : "/api/planner/reply";
            const data = await requestJson(leftReplyEndpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: baselineSessionId, answer })
            });
            bindPendingBaselineTurnEvaluation(data.turn_evaluation);
            appendBaselineQuestion(chat, data.question, data.action, data.debug_trace);

            if (data.done) {
                document.getElementById("baseline-status").textContent = "已完成";
            } else {
                input.disabled = false;
                document.getElementById("baseline-send-btn").disabled = false;
                input.focus();
            }
        }

        // Planner controls
        document.getElementById("planner-run-btn").onclick = runPlannerAuto;
        document.getElementById("planner-send-btn").onclick = sendPlannerReply;
        document.getElementById("planner-input").onkeydown = (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendPlannerReply();
            }
        };

        async function runPlannerAuto() {
            if (!plannerSessionId || plannerAutoFinished) return;
            document.getElementById("planner-run-btn").disabled = true;
            document.getElementById("planner-status").textContent = "本轮进行中";
            const chat = document.getElementById("planner-chat");
            let interviewEnded = false;

            const rightAutoEndpoint = rightPanelVersion === "baseline" ? "/api/baseline/auto" : "/api/planner/auto";
            const evtSource = new EventSource(`${rightAutoEndpoint}?session_id=${plannerSessionId}&single_turn=1`);

            evtSource.onmessage = (e) => {
                const msg = JSON.parse(e.data);
                if (msg.role === "done") {
                    evtSource.close();
                    finishAutoTurn("planner", interviewEnded);
                    return;
                }
                if (msg.role === "error") {
                    appendMessage(chat, "error", msg.text);
                    document.getElementById("planner-status").textContent = "Error";
                    return;
                }

                if (msg.role === "interviewee") {
                    appendMessage(chat, "interviewee", msg.text, null, msg.memory_calls, null, msg.timing);
                } else {
                    if (msg.action === "end") {
                        interviewEnded = true;
                    }
                    bindPendingTurnEvaluation(msg.turn_evaluation);
                    appendPlannerQuestion(chat, msg.text, msg.action, msg.debug_trace, msg.timing, msg.planner_plan);
                    if (msg.extracted_events && msg.extracted_events.length > 0) {
                        allExtractedEvents.push(...msg.extracted_events);
                        updateEventList(allExtractedEvents);
                    }
                }
                accumulateTiming("planner", msg.timing);

                // Broadcast to dashboard via WebSocket
                if (msg.graph_delta && dashboardWindow) {
                    // Dashboard will get updates via its own WebSocket connection
                }
            };

            evtSource.onerror = () => {
                evtSource.close();
                document.getElementById("planner-status").textContent = "等待下一轮";
                document.getElementById("planner-run-btn").disabled = false;
            };
        }

        async function sendPlannerReply() {
            const input = document.getElementById("planner-input");
            const chat = document.getElementById("planner-chat");
            const answer = input.value.trim();
            if (!answer) return;

            input.value = "";
            input.disabled = true;
            document.getElementById("planner-send-btn").disabled = true;

            appendMessage(chat, "interviewee", answer);

            const rightReplyEndpoint = rightPanelVersion === "baseline" ? "/api/baseline/reply" : "/api/planner/reply";
            const data = await requestJson(rightReplyEndpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: plannerSessionId, answer })
            });
            bindPendingTurnEvaluation(data.turn_evaluation);
            appendPlannerQuestion(chat, data.question, data.action, data.debug_trace, null, data.planner_plan);

            // Accumulate and update extracted events
            if (data.extracted_events && data.extracted_events.length > 0) {
                allExtractedEvents.push(...data.extracted_events);
                updateEventList(allExtractedEvents);
            }

            if (data.done) {
                document.getElementById("planner-status").textContent = "已完成";
            } else {
                input.disabled = false;
                document.getElementById("planner-send-btn").disabled = false;
                input.focus();
            }
        }

        function updateEventList(events) {
            const container = document.getElementById("events-list-content") || document.getElementById("events-list-container");
            if (!events || events.length === 0) {
                container.innerHTML = '<p class="no-events">暂无事件</p>';
                return;
            }
            const typeLabels = {Event:'事件', Person:'人物', Location:'地点', Emotion:'情感', Insight:'洞察'};
            container.innerHTML = `
                <h4>共 ${events.length} 个实体</h4>
                <div class="event-list">
                    ${events.slice(-15).reverse().map(e => {
                        const icon = typeLabels[e.entity_type] || e.entity_type || '实体';
                        const title = e.name || e.slots?.event || e.event || "未知";
                        const desc = e.description ? e.description.slice(0, 50) : '';
                        return `
                        <div class="event-item">
                            <span class="event-icon">${icon}</span>
                            <span class="event-title">${title}</span>
                            ${e.entity_type ? `<span style="font-size:11px;color:#9ca3af;margin-left:4px">${e.entity_type}</span>` : ''}
                            ${desc ? `<div style="font-size:11px;color:#6b7280;margin-left:24px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${desc}</div>` : ''}
                        </div>`;
                    }).join('')}
                </div>
            `;
        }

        function updateDashboardStatus(connected) {
            const indicator = document.getElementById("dashboard-status");
            indicator.className = "status-indicator " + (connected ? "connected" : "disconnected");
        }

        function resetTest() {
            if (confirm("确定要重置测试吗？所有进度将丢失。")) {
                location.reload();
            }
        }

        // ========== Report Drawer ==========
        function toggleReport() {
            const drawer = document.getElementById('report-drawer');
            const overlay = document.getElementById('drawer-overlay');
            const isOpen = drawer.classList.contains('open');
            drawer.classList.toggle('open');
            overlay.classList.toggle('show');
            if (!isOpen && plannerSessionId) loadReport();
        }

        async function loadReport() {
            if (!plannerSessionId) return;
            const content = document.getElementById('report-content');
            content.innerHTML = '<p style="color:#9ca3af">加载中...</p>';
            try {
                const data = await requestJson(`/api/planner/report/${plannerSessionId}`);
                renderReport(data, content);
            } catch (e) {
                content.innerHTML = `<p style="color:#ef4444">加载失败: ${e.message}</p>`;
            }
        }

        function renderReport(data, el) {
            const s = data.session_id || '';
            const t = data.turn_count || 0;
            const start = data.start_time ? new Date(data.start_time).toLocaleString('zh-CN') : '-';
            const mode = data.mode === 'ai' ? 'AI 自动' : '用户输入';

            let html = '';

            // Session overview
            html += '<div class="report-section"><h4>会话概览</h4>';
            html += `<div class="report-kv"><span class="k">会话 ID</span><span class="v">${s.slice(0,12)}...</span></div>`;
            html += `<div class="report-kv"><span class="k">对话轮次</span><span class="v">${t}</span></div>`;
            html += `<div class="report-kv"><span class="k">开始时间</span><span class="v">${start}</span></div>`;
            html += `<div class="report-kv"><span class="k">模式</span><span class="v">${mode}</span></div>`;
            html += '</div>';

            // Neo4j stats
            const neo4j = data.neo4j || {};
            if (neo4j.nodes && neo4j.nodes.length > 0) {
                html += '<div class="report-section"><h4>Neo4j 图谱节点</h4>';
                html += '<table class="report-table"><tr><th>类型</th><th>数量</th></tr>';
                for (const n of neo4j.nodes) {
                    html += `<tr><td>${n.type || '-'}</td><td>${n.count}</td></tr>`;
                }
                html += '</table></div>';
            }
            if (neo4j.relationships && neo4j.relationships.length > 0) {
                html += '<div class="report-section"><h4>Neo4j 关系</h4>';
                html += '<table class="report-table"><tr><th>关系类型</th><th>数量</th></tr>';
                for (const r of neo4j.relationships) {
                    html += `<tr><td>${r.type || '-'}</td><td>${r.count}</td></tr>`;
                }
                html += '</table></div>';
            }

            // Theme coverage
            if (neo4j.themes && neo4j.themes.length > 0) {
                const cov = data.coverage || {};
                const richness = cov.theme_richness || {};
                html += '<div class="report-section"><h4>主题覆盖</h4>';
                html += '<table class="report-table"><tr><th>主题</th><th>状态</th><th>事件</th><th>丰富度</th></tr>';
                for (const th of neo4j.themes) {
                    const r = richness[th.id] || 0;
                    const pct = Math.round(r * 100);
                    html += `<tr><td>${th.name || th.id}</td><td>${th.status}</td><td>${th.event_count}</td>`;
                    html += `<td><div style="display:flex;align-items:center"><div class="richness-bar"><div class="richness-fill" style="width:${pct}%"></div></div><span style="font-size:12px;min-width:36px">${pct}%</span></div></td></tr>`;
                }
                if (cov.overall_richness != null) {
                    const op = Math.round(cov.overall_richness * 100);
                    html += `<tr style="font-weight:600"><td>整体</td><td></td><td></td><td>${op}%</td></tr>`;
                }
                html += '</table></div>';
            }

            // Turn timing chart
            const timings = data.turn_timings || [];
            if (timings.length > 0) {
                const maxTotal = Math.max(...timings.map(t => (t.retrieval_ms || 0) + (t.extraction_ms || 0) + (t.write_ms || 0)), 1);
                html += '<div class="report-section"><h4>每轮延迟趋势</h4>';
                html += '<div class="timing-legend"><span class="l-ret">检索</span><span class="l-ext">提取</span><span class="l-wri">写入</span></div>';
                for (let i = 0; i < timings.length; i++) {
                    const t = timings[i];
                    const ret = t.retrieval_ms || 0;
                    const ext = t.extraction_ms || 0;
                    const wri = t.write_ms || 0;
                    const total = ret + ext + wri;
                    const scale = total / maxTotal * 100;
                    const retW = total > 0 ? ret / total * 100 : 0;
                    const extW = total > 0 ? ext / total * 100 : 0;
                    const wriW = total > 0 ? wri / total * 100 : 0;
                    html += `<div class="timing-bar-row"><span class="turn-label">T${i + 1}</span>`;
                    html += `<div class="timing-bar-stack" style="width:${scale}%">`;
                    html += `<div class="seg seg-retrieval" style="width:${retW}%"></div>`;
                    html += `<div class="seg seg-extraction" style="width:${extW}%"></div>`;
                    html += `<div class="seg seg-write" style="width:${wriW}%"></div>`;
                    html += `</div><span style="min-width:40px;text-align:right;color:#6b7280">${(total / 1000).toFixed(1)}s</span></div>`;
                }
                html += '</div>';
            }

            // Embedding status
            const emb = data.embedding || {};
            if (emb.provider) {
                const fallback = emb.fallback_active;
                html += '<div class="report-section"><h4>Embedding 服务</h4>';
                html += `<div class="report-kv"><span class="k">Provider</span><span class="v">${emb.provider}</span></div>`;
                html += `<div class="report-kv"><span class="k">维度</span><span class="v">${emb.dimension || '-'}</span></div>`;
                html += `<div class="report-kv"><span class="k">状态</span><span class="${fallback ? 'status-warn' : 'status-ok'}">${fallback ? 'Fallback (' + (emb.fallback_reason || '').slice(0, 60) + ')' : '正常'}</span></div>`;
                html += '</div>';
            }

            el.innerHTML = html;
        }
    </script>
</body>
</html>'''


@app.route("/api/planner/evaluation/<session_id>")
def planner_evaluation(session_id):
    if session_id not in _compare_sessions:
        return jsonify({"error": "Session not found"}), 400

    session = _compare_sessions[session_id]
    if session["type"] != "planner":
        return jsonify({"error": "Not a planner session"}), 400

    agent = session["agent"]
    return jsonify(agent.get_evaluation_state())


if __name__ == "__main__":
    if not Config.get_api_key():
        print("错误: 请先在 .env 文件中设置 OPENAI_API_KEY（或兼容的 MOONSHOT_API_KEY）")
        exit(1)
    app.run(debug=True, host="0.0.0.0", port=9999)
