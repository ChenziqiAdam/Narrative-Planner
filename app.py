import json
import os
import uuid
import re

from flask import Flask, Response, jsonify, render_template_string, request, session

from agents.interviewee_agent import IntervieweeAgent
from agents.interviewer_agent import InterviewerAgent
from config import Config

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
        }
    return _sessions[session_id]


def extract_reply(raw: str) -> str:
    """Extract the 'reply' field if the response is JSON, otherwise return raw."""
    try:
        # strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        data = json.loads(cleaned)
        if isinstance(data, dict) and "reply" in data:
            return data["reply"]
    except (json.JSONDecodeError, ValueError):
        pass
    return raw


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

    agents = get_session_agents(sid)
    agents["interviewer"].initialize_conversation(basic_info)
    agents["basic_info"] = basic_info

    # Get the opening question
    result = agents["interviewer"].get_next_question()
    question = result["question"]
    agents["history"].append({"role": "interviewer", "text": question})

    return jsonify({"question": question})


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
            response = agents["interviewee"].agent.step(prompt)
            raw_answer = response.msg.content
            answer = extract_reply(raw_answer)
            agents["interviewee"].history += f"Q: {last_question}\nA: {answer}\n"
            agents["history"].append({"role": "interviewee", "text": answer})
            yield f"data: {json.dumps({'role': 'interviewee', 'action': 'answer', 'text': answer}, ensure_ascii=False)}\n\n"

            # Interviewer decides next action
            result = agents["interviewer"].get_next_question(answer)
            action = result["action"]
            question = result["question"]

            if action == "end":
                agents["history"].append({"role": "interviewer", "text": "感谢您的分享，访谈到此结束。"})
                yield f"data: {json.dumps({'role': 'interviewer', 'action': 'end', 'text': '感谢您的分享，访谈到此结束。'}, ensure_ascii=False)}\n\n"
                break

            agents["history"].append({"role": "interviewer", "text": question})
            last_question = question
            yield f"data: {json.dumps({'role': 'interviewer', 'action': action, 'text': question}, ensure_ascii=False)}\n\n"

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


@app.route("/biography", methods=["POST"])
def biography():
    """Synthesize the interview transcript into a biography/memoir."""
    sid = session.get("session_id")
    if not sid or sid not in _sessions:
        return jsonify({"error": "请先完成访谈"}), 400

    agents = _sessions[sid]
    history = agents.get("history", [])
    if not history:
        return jsonify({"error": "访谈记录为空"}), 400

    transcript = "\n".join(
        f"{'访谈者' if m['role'] == 'interviewer' else '受访者'}: {m['text']}"
        for m in history
    )

    from openai import OpenAI
    client = OpenAI(api_key=Config.MOONSHOT_API_KEY, base_url=Config.MOONSHOT_BASE_URL)

    prompt = f"""以下是一段传记访谈的完整记录：

{transcript}

请根据上述访谈内容，以第一人称为受访者撰写一篇完整、流畅、情感真实的人生回忆录（memoir）。
要求：
1. 以受访者的口吻和语气写作，保留其语言特点
2. 按照人生阶段组织内容，结构清晰
3. 融入访谈中提到的具体细节、情感和转折点
4. 篇幅在800-1200字之间
5. 语言生动，有文学感，体现人物性格"""

    response = client.chat.completions.create(
        model=Config.MODEL_NAME,
        messages=[
            {"role": "system", "content": "你是一位擅长传记写作的文学编辑，能将口述访谈整理成优美的人生回忆录。"},
            {"role": "user", "content": prompt},
        ],
    )

    biography_text = response.choices[0].message.content

    # Save biography
    bio_path = agents["save_path"].replace(".txt", "_biography.txt")
    with open(bio_path, "w", encoding="utf-8") as f:
        f.write(biography_text)

    return jsonify({"biography": biography_text})


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
#setup-card { background: #fff; border-radius: 16px; padding: 36px; width: 480px; box-shadow: 0 4px 20px rgba(0,0,0,.1); }
#setup-card h2 { font-size: 1.1rem; color: #6b4f3a; margin-bottom: 20px; }
#setup-card textarea { width: 100%; height: 100px; padding: 12px; border: 1px solid #ddd; border-radius: 8px; font-size: .95rem; resize: vertical; font-family: inherit; }
#setup-card textarea:focus { outline: none; border-color: #6b4f3a; }
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

#chat-controls { padding: 14px 20px; background: #faf7f3; border-top: 1px solid #eee; display: flex; gap: 10px; flex-shrink: 0; }
#run-btn { flex: 1; padding: 11px; background: #6b4f3a; color: #fff; border: none; border-radius: 10px; font-size: .95rem; cursor: pointer; }
#run-btn:disabled { opacity: .5; cursor: not-allowed; }
#bio-btn { flex: 1; padding: 11px; background: #3a6b4f; color: #fff; border: none; border-radius: 10px; font-size: .95rem; cursor: pointer; }
#bio-btn:disabled { opacity: .5; cursor: not-allowed; }

/* Biography panel */
#bio-panel { width: 42%; display: flex; flex-direction: column; }
#bio-panel h2 { padding: 12px 20px; font-size: .9rem; font-weight: 600; color: #3a6b4f; background: #f3faf7; border-bottom: 1px solid #eee; flex-shrink: 0; }
#bio-content { flex: 1; overflow-y: auto; padding: 20px; font-size: .93rem; line-height: 1.9; color: #2c2c2c; white-space: pre-wrap; }
#bio-placeholder { color: #bbb; font-style: italic; font-size: .88rem; margin-top: 40px; text-align: center; }
#bio-actions { padding: 14px 20px; background: #f3faf7; border-top: 1px solid #eee; display: flex; gap: 10px; flex-shrink: 0; }
#copy-btn { flex: 1; padding: 10px; background: transparent; color: #3a6b4f; border: 1px solid #3a6b4f; border-radius: 10px; font-size: .9rem; cursor: pointer; }
#copy-btn:disabled { opacity: .4; cursor: not-allowed; }
</style>
</head>
<body>

<header>
  <h1>传记访谈系统 · 自动对话</h1>
  <span id="status-badge">就绪</span>
</header>

<!-- Setup screen -->
<div id="setup">
  <div id="setup-card">
    <h2>开始新访谈</h2>
    <textarea id="basic-info" placeholder="请输入受访者基本信息，例如：&#10;出生于1942年，四川成都人，曾是纺织厂工人，经历过文革和改革开放，育有三个子女，现独居。"></textarea>
    <p style="font-size:.82rem;color:#999;margin:10px 0 18px">访谈者将自动决定何时深入、推进或结束访谈。</p>
    <button id="start-btn" onclick="startInterview()">开始访谈</button>
  </div>
</div>

<!-- Main interview + biography view -->
<div id="main">
  <div id="chat-panel">
    <h2>访谈对话</h2>
    <div id="chat"></div>
    <div id="chat-controls">
      <button id="run-btn" onclick="runAutoInterview()" disabled>▶ 自动运行访谈</button>
      <button id="bio-btn" onclick="generateBiography()" disabled>📖 生成回忆录</button>
    </div>
  </div>
  <div id="bio-panel">
    <h2>人生回忆录</h2>
    <div id="bio-content"><div id="bio-placeholder">完成访谈后点击「生成回忆录」</div></div>
    <div id="bio-actions">
      <button id="copy-btn" onclick="copyBio()" disabled>复制全文</button>
    </div>
  </div>
</div>

<script>
const setupEl  = document.getElementById('setup');
const mainEl   = document.getElementById('main');
const chatEl   = document.getElementById('chat');
const statusEl = document.getElementById('status-badge');
const runBtn   = document.getElementById('run-btn');
const bioBtn   = document.getElementById('bio-btn');
const copyBtn  = document.getElementById('copy-btn');
const bioContent = document.getElementById('bio-content');

let interviewDone = false;

function setStatus(text, color='rgba(255,255,255,.2)') {
  statusEl.textContent = text;
  statusEl.style.background = color;
}

const actionLabels = { continue: '深入', next_phase: '下一阶段', end: '结束访谈' };

function appendMsg(role, text, action) {
  const labels = { interviewer: '访谈者', interviewee: '受访者', system: '' };
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  if (role !== 'system') {
    const lbl = document.createElement('div');
    lbl.className = 'label';
    lbl.textContent = labels[role] || role;
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
      body: JSON.stringify({ basic_info: basicInfo })
    });
    const data = await res.json();
    if (data.error) { alert(data.error); startBtn.disabled = false; startBtn.textContent = '开始访谈'; return; }

    setupEl.style.display = 'none';
    mainEl.style.display = 'flex';

    appendMsg('system', '访谈已开始');
    appendMsg('interviewer', data.question);
    runBtn.disabled = false;
    setStatus('已就绪');
  } catch(e) {
    alert('启动失败，请检查服务器');
    startBtn.disabled = false;
    startBtn.textContent = '开始访谈';
  }
}

function runAutoInterview() {
  runBtn.disabled = true;
  bioBtn.disabled = true;
  setStatus('访谈进行中…', 'rgba(255,200,100,.4)');

  const evtSource = new EventSource('/auto_interview');

  evtSource.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.role === 'done') {
      evtSource.close();
      interviewDone = true;
      bioBtn.disabled = false;
      setStatus('访谈完成', 'rgba(100,200,150,.4)');
      appendMsg('system', '访谈已由访谈者自然结束，可点击「生成回忆录」');
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

async function generateBiography() {
  bioBtn.disabled = true;
  copyBtn.disabled = true;
  bioContent.innerHTML = '<div id="bio-placeholder">正在撰写回忆录，请稍候…</div>';
  setStatus('生成中…', 'rgba(255,200,100,.4)');

  try {
    const res = await fetch('/biography', { method: 'POST' });
    const data = await res.json();
    if (data.error) { bioContent.textContent = '错误：' + data.error; return; }
    bioContent.textContent = data.biography;
    copyBtn.disabled = false;
    setStatus('回忆录已生成', 'rgba(100,200,150,.4)');
  } catch(e) {
    bioContent.textContent = '生成失败，请重试。';
    setStatus('生成失败', 'rgba(255,100,100,.4)');
  } finally {
    bioBtn.disabled = false;
  }
}

function copyBio() {
  navigator.clipboard.writeText(bioContent.textContent).then(() => {
    const orig = copyBtn.textContent;
    copyBtn.textContent = '已复制！';
    setTimeout(() => copyBtn.textContent = orig, 2000);
  });
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    if not Config.MOONSHOT_API_KEY:
        print("错误: 请先在 .env 文件中设置 MOONSHOT_API_KEY")
        exit(1)
    app.run(debug=True, host="0.0.0.0", port=9999)
