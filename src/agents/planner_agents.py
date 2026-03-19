import os
import uuid
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from jinja2 import Template
from camel.messages import BaseMessage

from base_agents import BaseAgent
from prompts.planner_interview_prompts import PLANNER_PROMPT_TEMPLATE
from config import Config
import yaml

class PlannerAgent(BaseAgent):
    """Planner Agent for interview planning with chat history support.

    Features:
    - Maintains a conversation history (list of messages) that is sent to the LLM each request
    - Utilities to add/clear/replace history
    - Renders system prompt from PLANNER_PROMPT_TEMPLATE + instruction YAML
    - Sends messages to underlying ChatAgent or model with compatibility fallbacks
    """

    def __init__(self, tools: Optional[list] = None, instruction_path: Optional[str] = None, test: bool = True):
        # profile_data may be used by BaseAgent.get_name(); initialize to empty
        self.profile_data: Dict[str, Any] = {}
        self.instruction_path = (
            instruction_path
            or os.path.join(os.path.dirname(__file__), "..", "docs", "planner-instruction.yaml")
        )
        self.test = test
        # conversation history: list of BaseMessage-like objects
        self.chat_history: List[Any] = []
        super().__init__(tools=tools)

    # -------- history utilities --------
    def add_interviewee_message(self, text: str) -> None:
        """Append a interviewee message to the chat history."""
        msg = {'role_name': "interviewee", 'content': text}

        self.chat_history.append(msg)

    def add_planner_message(self, text: str) -> None:
        """Append an planner message to the chat history."""
     
        msg = {'role_name': "planner", 'content': text}

        self.chat_history.append(msg)

    def clear_history(self) -> None:
        """Clear the stored chat history."""
        self.chat_history = []

    def set_history(self, messages: List[Any]) -> None:
        """Replace the chat history with a list of BaseMessage-like objects."""
        self.chat_history = messages[:]

    # -------- prompt / instruction loading --------
    def _create_system_message(self) -> BaseMessage:
        """Render planner system prompt and return as a BaseMessage."""
        instruction_set = self._load_profile(self.instruction_path)
        rendered = Template(PLANNER_PROMPT_TEMPLATE).render(
            instruction_set=instruction_set,
            timestamp=datetime.now().isoformat(),
            instruction_id=str(uuid.uuid4()),
        )
    
        return BaseMessage.make_system_message(role_name="system", content=rendered)


    def _create_step_message(self, interviewee_text: str) -> BaseMessage:
        """Create a interviewee message to send to ChatAgent from a raw string."""
        return BaseMessage.make_user_message(role_name="interviewee", content=interviewee_text)
    
    # -------- core respond (uses history) --------
    def respond(self, message: str) -> str:
        """Send the interviewee's message (plus history) to the chat agent and return the agent's text response.

        Behavior:
        - Append the incoming interviewee message to history
        - Build messages list: [system] + history
        - Call ChatAgent/model with that messages list, trying common method names
        - Append planner response to history and return the text
        """
        # append interviewee message to history
        self.add_interviewee_message(message)
        parsed = self.parse_json_response(message)
        interviewee_msg = parsed.get("reply", parsed if isinstance(parsed, str) else "") if self.test else parsed
        input_msg = self._create_step_message(interviewee_msg)
        # try using agent.step if available; keep compatibility with different camel versions
        agent = getattr(self, "agent", None)
        if agent is None:
            # if no agent available, return a simulated acknowledgement
            simulated = json.dumps({"ack": interviewee_msg or message})
            self.add_planner_message(simulated)
            return simulated

        # If agent has a step or chat method that accepts a single message, try those.
        for method_name in ("step", "chat", "respond", "run", "send"):
            method = getattr(agent, method_name, None)
            if callable(method):
                try:
                    resp = method(input_msg)
                    # Expect resp.msg.content or resp.content or str
                    if hasattr(resp, "msg") and hasattr(resp.msg, "content"):
                        out = resp.msg.content
                    elif hasattr(resp, "content"):
                        out = resp.content
                    elif isinstance(resp, str):
                        out = resp
                    else:
                        out = str(resp)
                    self.add_planner_message(out)
                    return out
                except Exception:
                    continue

        # fallback: if no suitable method produced output, return input back
        out = str(input_msg.content)
        self.add_planner_message(out)
        return out  


# ----------------- Simulated test harness -----------------
if __name__ == "__main__":
    sample_msgs = [
        json.dumps({"reply": "我小时候经常去河边玩，那时候家里很穷，但很快乐。"}, ensure_ascii=False),
    ]

    # Initialize agent and inject mock
    agent = PlannerAgent(test=True)
    
    for msg in sample_msgs:
        print(">>>Interviewee ->", msg)
        planner_resp = agent.respond(msg)
        print(">>>Planner  ->", planner_resp)
        # append both sides to records (store parsed interviewee content and planner reply)
        parsed = agent.parse_json_response(msg)
        interviewee_text = parsed.get("reply") if isinstance(parsed, dict) else str(parsed)

    # Save to project's data/interviews directory
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    out_dir = os.path.join(project_root, Config.DATA_DIR, "interviews")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"planner_simulated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path = os.path.join(out_dir, fname)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"created_at": datetime.now().isoformat(), "conversation": list(agent.chat_history)}, f, ensure_ascii=False, indent=2)

    print(f"Conversation saved to: {out_path}")