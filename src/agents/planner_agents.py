import os
import uuid
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from jinja2 import Template
from camel.messages import BaseMessage

from src.agents.base_agents import BaseAgent
from prompts.planner_interview_prompts import PLANNER_PROMPT_TEMPLATE
import yaml

class PlannerAgent(BaseAgent):
    """Planner Agent for interview planning with chat history and Graph RAG memory tools support.

    Features:
    - Maintains a conversation history (list of messages) that is sent to the LLM each request
    - Utilities to add/clear/replace history
    - Renders system prompt from PLANNER_PROMPT_TEMPLATE + instruction YAML
    - Sends messages to underlying ChatAgent or model with compatibility fallbacks
    - **NEW**: Integrates Graph RAG memory tools for intelligent planning decisions
    """

    def __init__(
        self, 
        tools: Optional[list] = None, 
        instruction_path: Optional[str] = None, 
        test: bool = True,
        use_graph_memory_tools: bool = True,
        memory_manager = None,
        interview_id: Optional[str] = None
    ):
        # profile_data may be used by BaseAgent.get_name(); initialize to empty
        self.profile_data: Dict[str, Any] = {}
        self.instruction_path = (
            instruction_path
            or os.path.join(os.path.dirname(__file__), "..", "docs", "planner-instruction.yaml")
        )
        self.test = test
        self.use_graph_memory_tools = use_graph_memory_tools
        self.memory_manager = memory_manager  # Accept external memory manager
        
        # 生成或使用提供的采访ID
        if interview_id is None:
            interview_id = f"planner_interview_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.interview_id = interview_id
        
        # conversation history: list of BaseMessage-like objects
        self.chat_history: List[Any] = []
        
        # Optionally load Graph RAG memory tools (SYNCHRONOUS VERSION)
        self.graph_memory_tools: List[Any] = []
        if use_graph_memory_tools:
            try:
                from src.tools.planner_tools import create_planner_query_tools
                from src.memory.manager_sync import EnhancedGraphMemoryManager
                
                # Use provided memory manager or initialize a default one
                if self.memory_manager is None:
                    self.memory_manager = EnhancedGraphMemoryManager()
                    self.memory_manager.initialize_sync()  # Synchronous initialization
                
                # 传递采访ID以确保数据隔离
                self.graph_memory_tools = create_planner_query_tools(
                    self.memory_manager, 
                    interview_id=self.interview_id
                )
                print(f"[PlannerAgent] Loaded {len(self.graph_memory_tools)} Planner query tools for interview: {self.interview_id}")
            except (ImportError, Exception) as e:
                print(f"[PlannerAgent] Warning: Could not load graph memory tools: {e}")
                self.graph_memory_tools = []
                self.use_graph_memory_tools = False
        
        # If tools not provided, use Graph RAG tools if available
        if tools is None and self.graph_memory_tools:
            tools = self.graph_memory_tools
        
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

    def _create_step_message(self, last_question, interviewee_text: str) -> BaseMessage:
        """Create a interviewee message to send to ChatAgent from a raw string."""
        promot = f"{{last question by interviewer: {last_question}, interviewee reply: {interviewee_text}}}"
        return BaseMessage.make_user_message(role_name="interviewee", content=promot)
    
    # -------- core respond (uses history) --------
    def respond(self, message, last_question:str) -> str:
        """Send the interviewee's message (plus history) to the chat agent and return the agent's text response.

        Behavior:
        - Append the incoming interviewee message to history
        - Build messages list: [system] + history
        - Call ChatAgent/model with that messages list, trying common method names
        - Append planner response to history and return the text
        
        The ChatAgent now has access to Graph RAG memory tools, which it can call
        to make more informed planning decisions.
        """
        # append interviewee message to history
        self.add_interviewee_message(message)
        if isinstance(message,str):
            if self.test:
                parsed = self.parse_json_response(message)
                interviewee_msg = parsed.get("reply", parsed if isinstance(parsed, str) else "") 
            else:
                interviewee_msg = message
        else:
            interviewee_msg = message.get("reply", message if isinstance(message, str) else "") 
        input_msg = self._create_step_message(last_question, interviewee_msg)
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
    
    
    # -------- 内存提取和处理 --------
    def extract_and_save_memories(self, interview_text: str = "") -> Dict[str, Any]:
        """
        在访谈完成后提取和去重记忆
        
        这个方法应该被调用一次，在整个访谈完成后，用于触发 MemoryExtractionAgent
        进行智能记忆提取和向量去重。
        
        Args:
            interview_text: 整个访谈的文本（可选，如果不提供会从图数据库生成摘要）
        
        Returns:
            包含提取统计的字典
        """
        try:
            from src.agents.memory_extraction_agent import MemoryExtractionAgent
            
            if not self.memory_manager:
                print("[PlannerAgent] ✗ 内存管理器未初始化")
                return {"error": "Memory manager not initialized"}
            
            print(f"[PlannerAgent] 触发访谈后内存提取 (interview_id={self.interview_id})")
            
            # 创建 MemoryExtractionAgent 实例
            extraction_agent = MemoryExtractionAgent(
                memory_manager=self.memory_manager,
                interview_id=self.interview_id,
                dedup_threshold=0.80
            )
            
            # 提取和存储记忆
            result = extraction_agent.extract_and_store(interview_text)
            
            print(f"[PlannerAgent] ✓ 内存提取完成: {result}")
            return result
        
        except ImportError as e:
            print(f"[PlannerAgent] ✗ 无法导入 MemoryExtractionAgent: {e}")
            return {"error": f"Import error: {e}"}
        except Exception as e:
            print(f"[PlannerAgent] ✗ 内存提取失败: {e}")
            return {"error": f"Extraction error: {e}"}
    
    
    def get_memory_query_result(self, query_text: str, top_k: int = 5) -> List[Dict]:
        """
        查询已有的记忆信息（支持向量去重后的查询）
        
        Args:
            query_text: 查询文本
            top_k: 返回的最大结果数
        
        Returns:
            查询结果列表
        """
        if not self.memory_manager:
            return []
        
        try:
            results = self.memory_manager.query_by_text_similarity(
                text=query_text,
                top_k=top_k,
                interview_id=self.interview_id
            )
            return results if results else []
        except Exception as e:
            print(f"[PlannerAgent] 查询记忆失败: {e}")
            return []  


# ----------------- Simulated test harness -----------------
if __name__ == "__main__":
    sample_msgs = [
        json.dumps({"reply": "我小时候经常去河边玩，那时候家里很穷，但很快乐。"}, ensure_ascii=False),
    ]

    # Initialize agent and inject mock
    agent = PlannerAgent(test=True)
    
    for msg in sample_msgs:
        print(">>>Interviewee ->", msg)
        planner_resp = agent.respond(msg, last_question="What was your childhood like?")
        print(">>>Planner  ->", planner_resp)
        # append both sides to records (store parsed interviewee content and planner reply)
        parsed = agent.parse_json_response(msg)
        interviewee_text = parsed.get("reply") if isinstance(parsed, dict) else str(parsed)

    # Save to project's data/interviews directory
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    out_dir = os.path.join(project_root, "data", "interviews")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"planner_simulated_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path = os.path.join(out_dir, fname)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"created_at": datetime.now().isoformat(), "conversation": list(agent.chat_history)}, f, ensure_ascii=False, indent=2)

    print(f"Conversation saved to: {out_path}")