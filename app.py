from flask import Flask, request, jsonify, session, render_template_string
from agents.interviewee_agent import IntervieweeAgent
import os
import uuid

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Store agent instances per session
_agents: dict[str, IntervieweeAgent] = {}

PROFILE_PATH = os.path.join(os.path.dirname(__file__), "prompts/roles/elder_profile_example.json")
MODEL_TYPE = os.getenv("MODEL_TYPE", "deepseek-chat")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "https://api.deepseek.com/v1")
API_KEY = os.getenv("API_KEY")


def get_agent(session_id: str) -> IntervieweeAgent:
    if session_id not in _agents:
        save_path = os.path.join(os.path.dirname(__file__), f"data/raw/session_{session_id}.txt")
        _agents[session_id] = IntervieweeAgent(
            profile_path=PROFILE_PATH,
            model_type=MODEL_TYPE,
            model_base_url=MODEL_BASE_URL,
            api_key=API_KEY,
            save_path=save_path,
        )
    return _agents[session_id]


HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>老人访谈</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: "PingFang SC", "Microsoft YaHei", sans-serif; background: #f5f1eb; height: 100vh; display: flex; flex-direction: column; }
  header { background: #6b4f3a; color: #fff; padding: 16px 24px; font-size: 1.2rem; font-weight: bold; }
  #chat { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 16px; }
  .msg { max-width: 70%; padding: 12px 16px; border-radius: 18px; line-height: 1.6; word-break: break-word; }
  .msg.user { align-self: flex-end; background: #6b4f3a; color: #fff; border-bottom-right-radius: 4px; }
  .msg.agent { align-self: flex-start; background: #fff; color: #333; border-bottom-left-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,.1); }
  .msg.agent .name { font-size: .75rem; color: #888; margin-bottom: 4px; }
  .typing { opacity: .5; font-style: italic; }
  footer { padding: 16px 24px; background: #fff; border-top: 1px solid #ddd; display: flex; gap: 12px; }
  footer input { flex: 1; padding: 12px 16px; border: 1px solid #ccc; border-radius: 24px; font-size: 1rem; outline: none; }
  footer input:focus { border-color: #6b4f3a; }
  footer button { padding: 12px 24px; background: #6b4f3a; color: #fff; border: none; border-radius: 24px; font-size: 1rem; cursor: pointer; }
  footer button:disabled { opacity: .5; cursor: not-allowed; }
</style>
</head>
<body>
<header>老人访谈系统</header>
<div id="chat"></div>
<footer>
  <input id="inp" type="text" placeholder="请输入您的问题…" autocomplete="off" />
  <button id="btn" onclick="send()">发送</button>
</footer>
<script>
const chat = document.getElementById('chat');
const inp  = document.getElementById('inp');
const btn  = document.getElementById('btn');

inp.addEventListener('keydown', e => { if (e.key === 'Enter') send(); });

function appendMsg(role, text, isTyping=false) {
  const d = document.createElement('div');
  d.className = 'msg ' + role + (isTyping ? ' typing' : '');
  if (role === 'agent') {
    const name = document.createElement('div');
    name.className = 'name';
    name.textContent = '受访者';
    d.appendChild(name);
  }
  const p = document.createElement('p');
  p.textContent = text;
  d.appendChild(p);
  chat.appendChild(d);
  chat.scrollTop = chat.scrollHeight;
  return d;
}

async function send() {
  const q = inp.value.trim();
  if (!q) return;
  inp.value = '';
  btn.disabled = true;
  appendMsg('user', q);
  const placeholder = appendMsg('agent', '正在思考…', true);
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q})
    });
    const data = await res.json();
    placeholder.remove();
    appendMsg('agent', data.answer || data.error || '（无回答）');
  } catch(e) {
    placeholder.remove();
    appendMsg('agent', '请求失败，请重试。');
  }
  btn.disabled = false;
  inp.focus();
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    if "session_id" not in session:
        session["session_id"] = uuid.uuid4().hex
    return render_template_string(HTML)


@app.route("/chat", methods=["POST"])
def chat():
    if "session_id" not in session:
        session["session_id"] = uuid.uuid4().hex
    sid = session["session_id"]

    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "问题不能为空"}), 400

    agent = get_agent(sid)
    prompt = agent._load_step_prompt(agent.history, question)
    response = agent.agent.step(prompt)
    answer = response.msg.content
    agent.history += f"Q: {question}\nA: {answer}\n"

    # Persist history
    os.makedirs(os.path.dirname(agent.save_path), exist_ok=True)
    with open(agent.save_path, "w", encoding="utf-8") as f:
        f.write(agent.history)

    return jsonify({"answer": answer})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
