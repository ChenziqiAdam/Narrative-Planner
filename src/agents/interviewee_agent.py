import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import Config
from prompts.roles.elderly_promot import ElderPromptGenerator
from tools.elder_tools import ElderMemorySystem, get_tool_schemas, get_tool_callables
from openai import OpenAI


class IntervieweeAgent:
    def __init__(self, profile_path, save_path):
        self.profile_path = profile_path
        self.save_path = save_path
        self.history = ""

        self._load_sys_prompt()
        self._load_tools()
        self._init_client()

    def _load_tools(self):
        self.memory_system = ElderMemorySystem(self.profile_path)
        self.tools = get_tool_schemas()
        self.tool_callables = get_tool_callables(self.memory_system)

    def _load_sys_prompt(self):
        generator = ElderPromptGenerator(template_path=Config.INTERVIEWEE_PROMPT_TEMPLATE)
        profile_data = generator.load_elder_profile(self.profile_path)
        self.sys_prompt = generator.generate_prompt(profile_data)

    def _load_step_prompt(self, history, question):
        return f"采访历史：{history}\n采访问题：{question}"

    def _init_client(self):
        self.client = OpenAI(
            api_key=Config.MOONSHOT_API_KEY,
            base_url=Config.MOONSHOT_BASE_URL,
        )

    def step(self, prompt: str) -> str:
        """Send a prompt and return the text reply, executing any tool calls."""
        messages = [
            {"role": "system", "content": self.sys_prompt},
            {"role": "user", "content": prompt},
        ]

        while True:
            response = self.client.chat.completions.create(
                model=Config.MODEL_NAME,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
            )
            msg = response.choices[0].message

            # No tool calls — return the text reply
            if not msg.tool_calls:
                return msg.content or ""

            # Append assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })

            # Execute each tool call and append results
            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)
                fn = self.tool_callables.get(fn_name)
                if fn:
                    result = fn(**fn_args)
                else:
                    result = {"error": f"unknown tool: {fn_name}"}
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

    # test mode
    def answer_questions(self, questions, save_path=None, test=False):
        if save_path is None:
            save_path = self.save_path
        responses = []
        if test:
            while True:
                question = input("请输入问题（输入exit退出）：")
                if question.lower() == "exit":
                    break
                prompt = self._load_step_prompt(self.history, question)
                answer = self.step(prompt)
                print(f"问题：{question}\n回答：{answer}\n")
                self.history += f"Q: {question}\nA: {answer}\n"
        else:
            for idx, question in enumerate(questions):
                history = "" if idx == 0 else self.history
                prompt = self._load_step_prompt(history, question)
                answer = self.step(prompt)
                self.history += f"Q: {question}\nA: {answer}\n"
                responses.append(answer)
                print(f"问题：{question}\n回答：{answer}\n")
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(self.history)
        print(f"已保存到 {save_path}")
        return responses


# test
if __name__ == "__main__":
    if not Config.MOONSHOT_API_KEY:
        print("错误: 请先在 .env 文件中设置 MOONSHOT_API_KEY")
        exit(1)
    agent = IntervieweeAgent(
        profile_path=os.path.join(os.path.dirname(__file__), "../prompts/roles/elder_profile_example.json"),
        save_path=os.path.join(os.path.dirname(__file__), "../data/raw/interviewee_answers.txt"),
    )
    questions = [
        "您叫什么名字",
        "您有什么故事要分享？"
    ]
    agent.answer_questions(questions)
