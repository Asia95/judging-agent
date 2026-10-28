"""
worker.py — the Worker agent.

The Worker receives a task and drives itself to completion using Drive tools.
It calls the watsonx.ai chat API with tool_choice="auto" and loops until the
model stops requesting tool calls, or max_turns is reached.

The Worker never touches the tools directly: every call goes through
ToolGateway.execute(), which judges it and only then runs it. Blocked calls
come back as an error result the model can see and react to.
"""

import json

from gateway import ToolGateway
from tools import TOOL_SCHEMAS
from watsonx_client import worker_model

_SYSTEM_PROMPT = (
    "You are a helpful assistant with access to Google Drive tools. "
    "Complete the task given by the user using only the tools available to you. "
    "Do not attempt to access files or folders that are not relevant to the task."
)


class Worker:
    def __init__(self, task: str, gateway: ToolGateway, model=None, max_turns: int = 20):
        self.task = task
        self.gateway = gateway
        self.max_turns = max_turns
        self._model = model or worker_model()
        self.messages: list[dict] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]

    def run(self) -> str:
        """Run until the model gives a final answer. Returns that answer."""
        print(f"\n[WORKER] Starting task: {self.task}\n")

        for _ in range(self.max_turns):
            response = self._model.chat(
                messages=self.messages,
                tools=TOOL_SCHEMAS,
                tool_choice_option="auto",
            )
            choice = response["choices"][0]
            message = choice["message"]
            self.messages.append(message)

            tool_calls = message.get("tool_calls") or []
            if choice.get("finish_reason") == "stop" or not tool_calls:
                final_answer = message.get("content") or "(no text response)"
                print(f"\n[WORKER] Done. Final answer:\n{final_answer}")
                return final_answer

            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                raw_args = tool_call["function"].get("arguments") or "{}"
                try:
                    tool_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    tool_args = None
                if not isinstance(tool_args, dict):
                    tool_args = {"_unparsed": raw_args}  # the gateway blocks this

                print(f"\n[WORKER] Requesting tool: {tool_name}({tool_args})")
                outcome = self.gateway.execute(tool_name, tool_args)
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": json.dumps(outcome.result),
                })

        print(f"\n[WORKER] Stopped after {self.max_turns} turns without a final answer.")
        return f"(stopped after {self.max_turns} turns)"
