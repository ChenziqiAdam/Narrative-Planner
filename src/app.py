import json
import os
import sys
import uuid
import re
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, Response, jsonify, render_template_string, request, session

from src.agents.baseline_agent import BaselineAgent as InterviewerAgent
from src.agents.interviewee_agent import IntervieweeAgent
from src.config import Config

app = Flask(__name__)
app.secret_key = os.urandom(24)

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "prompts/roles/elder_profile_example.json")

# Per-session agent pairs
_sessions: dict[str, dict] = {}


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
    question = agents["interviewer"].get_next_question()
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
    question = agents["interviewer"].get_next_question(answer)
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
    return jsonify({"action": "continue", "question": question, "done": False})


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
            raw_answer = agents["interviewee"].step(prompt)
            answer = extract_reply(raw_answer)
            agents["interviewee"].history += f"Q: {last_question}\nA: {answer}\n"
            agents["history"].append({"role": "interviewee", "text": answer})
            yield f"data: {json.dumps({'role': 'interviewee', 'action': 'answer', 'text': answer}, ensure_ascii=False)}\n\n"

            # Interviewer gets next question
            question = agents["interviewer"].get_next_question(answer)
            agents["turn_count"] += 1

            if agents["turn_count"] >= 50:
                agents["history"].append({"role": "interviewer", "text": "感谢您的分享，访谈到此结束。"})
                yield f"data: {json.dumps({'role': 'interviewer', 'action': 'end', 'text': '感谢您的分享，访谈到此结束。'}, ensure_ascii=False)}\n\n"
                break

            agents["history"].append({"role": "interviewer", "text": question})
            last_question = question
            yield f"data: {json.dumps({'role': 'interviewer', 'action': 'continue', 'text': question}, ensure_ascii=False)}\n\n"

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
<title>传记访谈系统</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f1eb; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

header { background: #6b4f3a; color: #fff; padding: 14px 24px; display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
header h1 { font-size: 1.1rem; font-weight: bold; }
#status-badge { font-size: .8rem; padding: 4px 12px; border-radius: 12px; background: rgba(255,255,255,.2); }

/* Setup panel */
#setup { flex: 1; display: flex; align-items: center; justify-content: center; }
#setup-card { background: #fff; border-radius: 16px; padding: 36px; width: 500px; box-shadow: 0 4px 20px rgba(0,0,0,.1); }
#setup-card h2 { font-size: 1.1rem; color: #6b4f3a; margin-bottom: 20px; }
#setup-card textarea { width: 100%; height: 100px; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: .95rem; resize: vertical; font-family: inherit; }
#setup-card textarea:focus { outline: none; border-color: #6b4f3a; }

/* Mode selector */
.mode-selector { display: flex; gap: 10px; margin: 14px 0 18px; }
.mode-option { flex: 1; border: 2px solid #ddd; border-radius: 10px; padding: 12px 10px; cursor: pointer; text-align: center; transition: all .2s; }
.mode-option:hover { border-color: #6b4f3a; }
.mode-option.selected { border-color: #6b4f3a; background: #fdf8f4; }
.mode-option input[type=radio] { display: none; }
.mode-option .mode-icon { font-size: 1.4rem; display: block; margin-bottom: 4px; }
.mode-option .mode-label { font-size: .88rem; font-weight: 600; color: #4a3328; display: block; }
.mode-option .mode-desc { font-size: .75rem; color: #999; margin-top: 3px; display: block; }

#start-btn { width: 100%; padding: 13px; background: #6b4f3a; color: #fff; border: none; border-radius: 10px; font-size: 1rem; cursor: pointer; transition: opacity .2s; }
#start-btn:disabled { opacity: .5; cursor: not-allowed; }

/* Main layout */
#main { flex: 1; display: none; flex-direction: row; gap: 0; overflow: hidden; }

/* Chat panel */
#chat-panel { flex: 1; display: flex; flex-direction: column; border-right: 1px solid #ddd; }
#chat-panel h2 { padding: 12px 20px; font-size: .9rem; font-weight: 600; color: #6b4f3a; background: #faf7f3; border-bottom: 1px solid #eee; flex-shrink: 0; }
#chat { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }

.msg { max-width: 75%; padding: 11px 15px; border-radius: 16px; line-height: 1.65; word-break: break-word; font-size: .92rem; }
.msg .label { font-size: .72rem; margin-bottom: 4px; opacity: .65; font-weight: 600; }
.msg.interviewer { align-self: flex-start; background: #e8f4fd; color: #1a4a6b; border-bottom-left-radius: 4px; }
.action-badge { display: inline-block; font-size: .68rem; padding: 2px 7px; border-radius: 8px; margin-left: 6px; vertical-align: middle; font-weight: 600; }
.action-badge.continue { background: #d4edff; color: #1a4a6b; }
.action-badge.next_phase { background: #fff0cc; color: #7a5800; }
.action-badge.end { background: #ffe0e0; color: #7a0000; }
.msg.interviewee { align-self: flex-end; background: #fff; color: #333; border-bottom-right-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.msg.system { align-self: center; background: transparent; color: #999; font-size: .8rem; font-style: italic; }
.typing-dots span { display: inline-block; animation: blink 1.2s infinite; }
.typing-dots span:nth-child(2) { animation-delay: .2s; }
.typing-dots span:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%,80%,100% { opacity:0 } 40% { opacity:1 } }

/* AI mode controls */
#chat-controls-ai { padding: 14px 20px; background: #faf7f3; border-top: 1px solid #eee; display: flex; gap: 10px; flex-shrink: 0; }
#run-btn { flex: 1; padding: 11px; background: #6b4f3a; color: #fff; border: none; border-radius: 10px; font-size: .95rem; cursor: pointer; }
#run-btn:disabled { opacity: .5; cursor: not-allowed; }

/* AI mode input area (原回忆录位置) */
#ai-input-area { flex: 1; display: flex; flex-direction: column; gap: 8px; }
#ai-input { width: 100%; padding: 11px 14px; border: 1px solid #ddd; border-radius: 10px; font-size: .93rem; font-family: inherit; resize: none; height: 60px; line-height: 1.5; }
#ai-input:focus { outline: none; border-color: #6b4f3a; }
#ai-input:disabled { background: #f5f5f5; color: #aaa; }
#ai-send-btn { padding: 10px 16px; background: #6b4f3a; color: #fff; border: none; border-radius: 10px; font-size: .93rem; cursor: pointer; }
#ai-send-btn:disabled { opacity: .5; cursor: not-allowed; }

/* User mode input area */
#chat-controls-user { padding: 14px 20px; background: #faf7f3; border-top: 1px solid #eee; display: none; flex-direction: column; gap: 8px; flex-shrink: 0; }
#user-input { width: 100%; padding: 11px 14px; border: 1px solid #ddd; border-radius: 10px; font-size: .93rem; font-family: inherit; resize: none; height: 80px; line-height: 1.5; }
#user-input:focus { outline: none; border-color: #6b4f3a; }
#user-input:disabled { background: #f5f5f5; color: #aaa; }
#user-controls-row { display: flex; gap: 10px; }
#send-btn { flex: 1; padding: 10px; background: #6b4f3a; color: #fff; border: none; border-radius: 10px; font-size: .93rem; cursor: pointer; }
#send-btn:disabled { opacity: .5; cursor: not-allowed; }
</style>
</head>
<body>

<header>
  <h1 id="header-title">传记访谈系统</h1>
  <span id="status-badge">就绪</span>
</header>

<!-- Setup screen -->
<div id="setup">
  <div id="setup-card">
    <h2>开始新访谈</h2>
    <textarea id="basic-info" placeholder="请输入受访者基本信息，例如：&#10;出生于1942年，四川成都人，曾是纺织厂工人，经历过文革和改革开放，育有三个子女，现独居。"></textarea>

    <div class="mode-selector">
      <label class="mode-option selected" id="mode-ai-label">
        <input type="radio" name="mode" value="ai" checked onchange="selectMode('ai')">
        <span class="mode-icon">🤖</span>
        <span class="mode-label">AI 模拟受访者</span>
        <span class="mode-desc">由 AI 自动回答问题</span>
      </label>
      <label class="mode-option" id="mode-user-label">
        <input type="radio" name="mode" value="user" onchange="selectMode('user')">
        <span class="mode-icon">🧑</span>
        <span class="mode-label">我来亲自回答</span>
        <span class="mode-desc">由您本人回答访谈问题</span>
      </label>
    </div>

    <button id="start-btn" onclick="startInterview()">开始访谈</button>
  </div>
</div>

<!-- Main interview view -->
<div id="main">
  <div id="chat-panel">
    <h2>访谈对话</h2>
    <div id="chat"></div>

    <!-- AI mode controls -->
    <div id="chat-controls-ai">
      <button id="run-btn" onclick="runAutoInterview()" disabled>▶ 自动运行访谈</button>
      <div id="ai-input-area">
        <textarea id="ai-input" placeholder="AI模式下可在此输入干预内容（可选）…" onkeydown="handleAiKey(event)" disabled></textarea>
        <button id="ai-send-btn" onclick="sendAiIntervention()" disabled>发送干预</button>
      </div>
    </div>

    <!-- User mode controls -->
    <div id="chat-controls-user">
      <textarea id="user-input" placeholder="请输入您的回答…" onkeydown="handleUserKey(event)"></textarea>
      <div id="user-controls-row">
        <button id="send-btn" onclick="sendUserReply()">发送回答</button>
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

let interviewDone = false;
let currentMode = 'ai';

function setStatus(text, color='rgba(255,255,255,.2)') {
  statusEl.textContent = text;
  statusEl.style.background = color;
}

function selectMode(mode) {
  currentMode = mode;
  document.getElementById('mode-ai-label').classList.toggle('selected', mode === 'ai');
  document.getElementById('mode-user-label').classList.toggle('selected', mode === 'user');
}

const actionLabels = { continue: '深入', next_phase: '下一阶段', end: '结束访谈' };

function appendMsg(role, text, action) {
  const labels = { interviewer: '访谈者', interviewee: '受访者（您）', system: '' };
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

    // Show correct controls based on mode
    if (currentMode === 'user') {
      document.getElementById('chat-controls-ai').style.display = 'none';
      document.getElementById('chat-controls-user').style.display = 'flex';
      document.getElementById('header-title').textContent = '传记访谈系统 · 亲历模式';
      userInput.disabled = false;
      sendBtn.disabled = false;
      // AI模式输入框禁用
      aiInput.disabled = true;
      aiSendBtn.disabled = true;
    } else {
      document.getElementById('chat-controls-ai').style.display = 'flex';
      document.getElementById('chat-controls-user').style.display = 'none';
      document.getElementById('header-title').textContent = '传记访谈系统 · 自动对话';
      runBtn.disabled = false;
      // AI模式下输入框启用（用于干预）
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

// ── User mode ────────────────────────────────────────────────────────────────

function handleUserKey(e) {
  // Ctrl+Enter or Cmd+Enter to send
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    sendUserReply();
  }
}

async function sendUserReply() {
  const answer = userInput.value.trim();
  if (!answer) return;

  sendBtn.disabled = true;
  userInput.disabled = true;
  userInput.value = '';

  appendMsg('interviewee', answer);
  setStatus('访谈者思考中…', 'rgba(255,200,100,.4)');

  // Show typing indicator for interviewer
  const typingEl = appendTyping('interviewer');

  try {
    const res = await fetch('/user_reply', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ answer })
    });
    const data = await res.json();
    typingEl.remove();

    if (data.error) {
      appendMsg('system', '错误：' + data.error);
      setStatus('出错', 'rgba(255,100,100,.4)');
      return;
    }

    appendMsg('interviewer', data.question, data.action);

    if (data.done) {
      interviewDone = true;
      sendBtn.disabled = true;
      userInput.disabled = true;
      setStatus('访谈完成', 'rgba(100,200,150,.4)');
      appendMsg('system', '访谈已结束');
    } else {
      sendBtn.disabled = false;
      userInput.disabled = false;
      userInput.focus();
      setStatus('等待您的回答', 'rgba(255,255,255,.2)');
    }
  } catch(e) {
    typingEl.remove();
    appendMsg('system', '网络错误，请重试');
    setStatus('连接中断', 'rgba(255,100,100,.4)');
    sendBtn.disabled = false;
    userInput.disabled = false;
  }
}

// ── AI mode ──────────────────────────────────────────────────────────────────

function runAutoInterview() {
  runBtn.disabled = true;
  aiInput.disabled = true;
  aiSendBtn.disabled = true;
  setStatus('访谈进行中…', 'rgba(255,200,100,.4)');

  const evtSource = new EventSource('/auto_interview');

  evtSource.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.role === 'done') {
      evtSource.close();
      interviewDone = true;
      aiInput.disabled = false;
      aiSendBtn.disabled = false;
      setStatus('访谈完成', 'rgba(100,200,150,.4)');
      appendMsg('system', '访谈已由访谈者自然结束');
      return;
    }
    appendMsg(msg.role, msg.text, msg.action);
  };

  evtSource.onerror = () => {
    evtSource.close();
    setStatus('连接中断', 'rgba(255,100,100,.4)');
    runBtn.disabled = false;
  };
}

// ── AI Intervention ───────────────────────────────────────────────────────────

function handleAiKey(e) {
  // Ctrl+Enter or Cmd+Enter to send
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    sendAiIntervention();
  }
}

async function sendAiIntervention() {
  const text = aiInput.value.trim();
  if (!text) return;

  aiSendBtn.disabled = true;
  aiInput.disabled = true;

  // 显示干预消息
  appendMsg('system', '[用户干预] ' + text);

  // 这里可以添加向后端发送干预的逻辑
  // 目前仅作为展示用途

  aiInput.value = '';
  aiInput.disabled = false;
  aiSendBtn.disabled = false;
  aiInput.focus();
}
</script>
</body>
</html>
"""


# ── Compare Mode Routes ───────────────────────────────────────────────────────

# 对比模式会话存储
_compare_sessions: dict[str, dict] = {}


@app.route("/compare")
def compare_interface():
    """返回对比调试界面"""
    return render_template_string(COMPARE_HTML)


# ========== Debug Route ==========
@app.route("/api/debug/config")
def debug_config():
    """调试：检查 Config 状态"""
    from src.config import Config
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
    from src.config import Config
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

    # 存储会话
    _compare_sessions[session_id] = {
        "type": "baseline",
        "agent": agent,
        "history": [{"role": "interviewer", "text": question}],
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

    session["history"].append({"role": "interviewer", "text": question})

    # 检查是否应该结束
    done = action == "end" or len(session["history"]) >= 100

    if done:
        # 保存对话
        _save_conversation(session_id, session)

    return jsonify({
        "question": question,
        "action": action,
        "done": done
    })


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

        # single_turn模式下只运行一轮
        max_turns = 1 if single_turn else 20
        for turn in range(max_turns):
            # 获取上一个问题
            last_question = session["history"][-1]["text"] if session["history"] else ""

            # AI受访者回答
            answer = _generate_baseline_interviewee_reply(
                elder_info=session["elder_info"],
                question=last_question,
                history=session["history"],
            )

            session["history"].append({"role": "interviewee", "text": answer})
            yield f"data: {json.dumps({'role': 'interviewee', 'action': 'answer', 'text': answer}, ensure_ascii=False)}\n\n"

            # 访谈者提问
            result = agent.get_next_question(answer)
            if isinstance(result, dict):
                question = result.get("question", "")
                action = result.get("action", "continue")
            else:
                question = result
                action = "continue"

            session["history"].append({"role": "interviewer", "text": question})
            yield f"data: {json.dumps({'role': 'interviewer', 'action': action, 'text': question}, ensure_ascii=False)}\n\n"

            if action == "end":
                break

        # 只有非单轮模式或结束时才保存对话
        if not single_turn or (session["history"] and len(session["history"]) >= 100):
            _save_conversation(session_id, session)
        yield f"data: {json.dumps({'role': 'done'}, ensure_ascii=False)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})


# ========== Planner 相关 API ==========

@app.route("/api/planner/start", methods=["POST"])
def planner_start():
    """
    启动Planner访谈
    Body: { "elder_info": dict, "mode": "ai"|"user" }
    Response: { "session_id": str, "first_question": str, "initial_graph": dict }
    """
    from src.agents.planner_interview_agent import PlannerInterviewAgentSync

    data = request.get_json(force=True)
    elder_info = data.get("elder_info", {})
    mode = data.get("mode", "ai")

    if not elder_info:
        return jsonify({"error": "请提供受访者基本信息"}), 400

    # 生成会话ID
    session_id = uuid.uuid4().hex

    # 创建PlannerAgent（同步包装器）
    agent = PlannerInterviewAgentSync(session_id)
    agent.initialize_conversation(elder_info)

    # 获取首条问题
    result = agent.get_next_question()

    # 存储会话
    _compare_sessions[session_id] = {
        "type": "planner",
        "agent": agent,
        "history": [{"role": "interviewer", "text": result["question"]}],
        "mode": mode,
        "elder_info": elder_info,
        "start_time": datetime.now().isoformat(),
        "extracted_events": []
    }

    return jsonify({
        "session_id": session_id,
        "first_question": result["question"],
        "mode": mode,
        "initial_graph": result.get("current_graph_state", {})
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

    # 记录回答
    session["history"].append({"role": "interviewee", "text": answer})

    # 获取下一个问题（包含事件提取和图谱更新）
    result = agent.get_next_question(answer)

    # 记录问题
    session["history"].append({"role": "interviewer", "text": result["question"]})

    # 累计提取的事件
    session["extracted_events"].extend(result.get("extracted_events", []))
    _broadcast_planner_graph_update(session_id, result)

    # 检查是否应该结束
    done = result["action"] == "end" or len(session["history"]) >= 100

    if done:
        # 保存对话和图谱
        _save_conversation(session_id, session)

    return jsonify({
        "question": result["question"],
        "action": result["action"],
        "done": done,
        "extracted_events": result.get("extracted_events", []),
        "graph_update": result.get("graph_changes", {}),
        "current_graph_state": result.get("current_graph_state", {})
    })


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
        agent = session["agent"]
        interviewee = IntervieweeAgent(profile_path=PROFILE_PATH)
        interviewee.initialize_conversation(session["elder_info"])

        # 从已有会话恢复访谈历史，避免多轮自动/单轮调试时丢上下文
        for index in range(len(session["history"]) - 1):
            current = session["history"][index]
            following = session["history"][index + 1]
            if current.get("role") == "interviewer" and following.get("role") == "interviewee":
                interviewee.record_turn(current.get("text", ""), following.get("text", ""))

        # single_turn模式下只运行一轮
        max_turns = 1 if single_turn else 20
        for turn in range(max_turns):
            # 获取上一个问题
            last_question = session["history"][-1]["text"] if session["history"] else ""

            # AI受访者回答
            prompt = interviewee._load_step_prompt(interviewee.history, last_question)
            raw_answer = interviewee.step(prompt)
            answer = extract_reply(raw_answer)
            interviewee.record_turn(last_question, answer)

            session["history"].append({"role": "interviewee", "text": answer})
            yield f"data: {json.dumps({'role': 'interviewee', 'text': answer, 'extracted_events': [], 'graph_delta': {}}, ensure_ascii=False)}\n\n"

            # 获取下一个问题（包含事件提取）
            result = agent.get_next_question(answer)

            # 累计提取的事件
            session["extracted_events"].extend(result.get("extracted_events", []))
            _broadcast_planner_graph_update(session_id, result)

            # 发送事件
            session["history"].append({"role": "interviewer", "text": result["question"]})

            interviewer_data = {
                'role': 'interviewer',
                'action': result['action'],
                'text': result['question'],
                'extracted_events': result.get('extracted_events', []),
                'graph_delta': result.get('graph_changes', {})
            }
            yield f"data: {json.dumps(interviewer_data, ensure_ascii=False)}\n\n"

            if result["action"] == "end":
                break

        # 只有非单轮模式或结束时才保存对话
        if not single_turn or (session["history"] and len(session["history"]) >= 100):
            _save_conversation(session_id, session)
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
            model=Config.MODEL_NAME,
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
    <title>传记访谈系统 - Baseline vs Planner 对比</title>
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
    </style>
</head>
<body>
    <!-- Top Bar -->
    <header class="top-bar">
        <div class="brand">
            <h1>🔬 访谈系统对比调试</h1>
            <span class="subtitle">Baseline vs Planner</span>
        </div>

        <div class="global-controls">
            <button id="btn-config" class="btn-icon">⚙️ 老人信息</button>
            <div id="dashboard-status" class="status-indicator">
                <span class="dot"></span>
                <span class="label">数据看板</span>
            </div>
            <button id="btn-start-compare" class="btn-primary" disabled>▶ 开始对比测试</button>
        </div>
    </header>

    <!-- Config Modal -->
    <div id="config-modal" class="modal">
        <div class="modal-content">
            <header class="modal-header">
                <h2>👤 老人信息配置</h2>
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
                            <option value="ai">🤖 AI自动对话</option>
                            <option value="user">🧑 我亲自回答</option>
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
                    <span class="badge control">对照组</span>
                    <h2>Baseline 版</h2>
                </div>
                <div class="panel-status">
                    <span class="status-text" id="baseline-status">等待开始</span>
                    <span class="mode-indicator" id="baseline-mode">-</span>
                </div>
            </header>
            <div class="panel-body">
                <div class="chat-container" id="baseline-chat">
                    <div class="empty-state">
                        <div class="empty-icon">📝</div>
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
                    <span class="badge experiment">实验组</span>
                    <h2>Planner 版</h2>
                </div>
                <div class="panel-status">
                    <span class="status-text" id="planner-status">等待开始</span>
                    <span class="mode-indicator" id="planner-mode">-</span>
                </div>
            </header>
            <div class="panel-body">
                <div class="chat-container" id="planner-chat">
                    <div class="empty-state">
                        <div class="empty-icon">🌳</div>
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
                    <span class="badge" style="background: #9c27b0; color: #fff;">📌</span>
                    <h2>最近提取的事件</h2>
                </div>
            </header>
            <div class="events-list-container" id="events-list-container">
                <p class="no-events">暂无事件</p>
            </div>
        </section>
    </main>

    <!-- Footer -->
    <footer class="compare-footer">
        <span id="session-info">会话: 未开始</span>
        <div>
            <button id="btn-reset" class="btn-text" onclick="resetTest()">🔄 重置测试</button>
        </div>
    </footer>

    <script>
        // Global state
        let config = null;
        let baselineSessionId = null;
        let plannerSessionId = null;
        let currentMode = "ai";
        let dashboardWindow = null;
        let allExtractedEvents = [];  // 累积所有提取的事件
        let baselineAutoFinished = false;
        let plannerAutoFinished = false;

        // DOM elements
        const configModal = document.getElementById("config-modal");
        const btnConfig = document.getElementById("btn-config");
        const btnStart = document.getElementById("btn-start-compare");
        const configForm = document.getElementById("elder-config-form");

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

        // Start comparison
        btnStart.onclick = async () => {
            if (!config) return;

            // Reset state
            allExtractedEvents = [];
            updateEventList([]);

            btnStart.disabled = true;
            btnStart.textContent = "初始化中...";
            baselineAutoFinished = false;
            plannerAutoFinished = false;

            // Open dashboard window for Planner
            if (config.dashboard_url) {
                dashboardWindow = openDashboardLoadingWindow();
                updateDashboardStatus(Boolean(dashboardWindow));
            }

            try {
                // Start both sessions in parallel
                const [baselineResult, plannerResult] = await Promise.all([
                    startBaseline(),
                    startPlanner()
                ]);

                baselineSessionId = baselineResult.session_id;
                plannerSessionId = plannerResult.session_id;

                // Update dashboard window with correct session ID
                if (dashboardWindow && plannerSessionId) {
                    dashboardWindow.location.href = buildDashboardUrl(plannerSessionId);
                }

                // Update UI
                document.getElementById("session-info").textContent =
                    `会话: Baseline(${baselineSessionId.slice(0, 8)})... / Planner(${plannerSessionId.slice(0, 8)})...`;

                // Setup panels
                setupBaselinePanel(baselineResult);
                setupPlannerPanel(plannerResult);

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
            }
        };

        async function startBaseline() {
            return await requestJson("/api/baseline/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    elder_info: config,
                    mode: config.mode
                })
            });
        }

        async function startPlanner() {
            return await requestJson("/api/planner/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    elder_info: config,
                    mode: config.mode
                })
            });
        }

        function setupBaselinePanel(result) {
            const chat = document.getElementById("baseline-chat");
            const status = document.getElementById("baseline-status");
            const mode = document.getElementById("baseline-mode");

            chat.innerHTML = "";
            appendMessage(chat, "interviewer", result.first_question);
            status.textContent = "进行中";
            mode.textContent = currentMode === "ai" ? "🤖 AI模式" : "🧑 用户模式";

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
            appendMessage(chat, "interviewer", result.first_question);
            status.textContent = "进行中";
            mode.textContent = currentMode === "ai" ? "🤖 AI模式" : "🧑 用户模式";

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

        function appendMessage(container, role, text, action) {
            const msg = document.createElement("div");
            msg.className = `message ${role}`;

            let label = role === "interviewer" ? "访谈者" : "受访者";
            let actionTag = "";
            if (action && action !== "continue") {
                actionTag = `<span class="action-tag">${action}</span>`;
            }

            msg.innerHTML = `
                <div class="msg-label">${label}${actionTag}</div>
                <div class="msg-text">${text}</div>
            `;
            container.appendChild(msg);
            container.scrollTop = container.scrollHeight;
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

            const evtSource = new EventSource(`/api/baseline/auto?session_id=${baselineSessionId}&single_turn=1`);

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
                appendMessage(chat, msg.role, msg.text, msg.action);
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

            const data = await requestJson("/api/baseline/reply", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: baselineSessionId, answer })
            });
            appendMessage(chat, "interviewer", data.question, data.action);

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

            const evtSource = new EventSource(`/api/planner/auto?session_id=${plannerSessionId}&single_turn=1`);

            evtSource.onmessage = (e) => {
                const msg = JSON.parse(e.data);
                if (msg.role === "done") {
                    evtSource.close();
                    finishAutoTurn("planner", interviewEnded);
                    return;
                }

                if (msg.role === "interviewee") {
                    appendMessage(chat, "interviewee", msg.text);
                    // Accumulate and update extracted events
                    if (msg.extracted_events && msg.extracted_events.length > 0) {
                        allExtractedEvents.push(...msg.extracted_events);
                        updateEventList(allExtractedEvents);
                    }
                } else {
                    if (msg.action === "end") {
                        interviewEnded = true;
                    }
                    appendMessage(chat, "interviewer", msg.text, msg.action);
                }

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

            const data = await requestJson("/api/planner/reply", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: plannerSessionId, answer })
            });
            appendMessage(chat, "interviewer", data.question, data.action);

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
            const container = document.getElementById("events-list-container");
            if (!events || events.length === 0) {
                container.innerHTML = '<p class="no-events">暂无事件</p>';
                return;
            }
            container.innerHTML = `
                <h4>共 ${events.length} 个事件</h4>
                <div class="event-list">
                    ${events.slice(-10).reverse().map(e => `
                        <div class="event-item">
                            <span class="event-icon">📌</span>
                            <span class="event-title">${e.slots?.event || e.event || "未知事件"}</span>
                            <span class="event-confidence">${Math.round((e.confidence || 0) * 100)}%</span>
                        </div>
                    `).join('')}
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
    </script>
</body>
</html>'''


if __name__ == "__main__":
    if not Config.get_api_key():
        print("错误: 请先在 .env 文件中设置 OPENAI_API_KEY（或兼容的 MOONSHOT_API_KEY）")
        exit(1)
    app.run(debug=True, host="0.0.0.0", port=9999)
