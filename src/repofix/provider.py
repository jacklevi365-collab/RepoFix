import json
import math
import os
import shlex
import urllib.error
import urllib.request


class DeepSeek:
    def __init__(self, ledger, run_id, task_budget=2.0, max_tokens=2048):
        self.key = os.environ.get("DEEPSEEK_API_KEY")
        if not self.key:
            raise ValueError("Set DEEPSEEK_API_KEY in the environment; do not put keys in task files")
        self.model = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
        self.input_price = float(os.environ.get("REPOFIX_INPUT_RMB_PER_MILLION", "0"))
        self.output_price = float(os.environ.get("REPOFIX_OUTPUT_RMB_PER_MILLION", "0"))
        if not all(math.isfinite(p) and p > 0 for p in (self.input_price, self.output_price)):
            raise ValueError("Configure positive current RMB input/output prices per million tokens")
        self.ledger, self.run_id = ledger, run_id
        self.task_budget, self.max_tokens = task_budget, max_tokens

    def complete(self, messages, tools):
        payload = {"model": self.model, "messages": messages, "tools": tools,
                   "max_tokens": self.max_tokens, "thinking": {"type": "disabled"}}
        data = json.dumps(payload, ensure_ascii=False).encode()
        # UTF-8 bytes plus protocol margin are a conservative token estimate,
        # not a provider billing guarantee. No automatic paid retries.
        reserve = ((len(data)+8192)*self.input_price + self.max_tokens*self.output_price)/1_000_000
        call_id = self.ledger.reserve(self.run_id, reserve, self.task_budget)
        request = urllib.request.Request("https://api.deepseek.com/chat/completions", data=data,
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"DeepSeek HTTP {exc.code}; reservation retained; inspect account billing") from None
        choice=result['choices'][0]
        self.last_response_metadata={key:result.get(key) for key in ('id','model','system_fingerprint')}
        self.last_response_metadata['finish_reason']=choice.get('finish_reason')
        usage = result.get("usage") or {}
        if "prompt_tokens" in usage and "completion_tokens" in usage:
            cost = (usage["prompt_tokens"]*self.input_price + usage["completion_tokens"]*self.output_price)/1_000_000
            self.ledger.settle(call_id, cost)
        return choice["message"], usage


class ScriptedDemo:
    """Deterministic orchestration fixture, not an LLM or a performance benchmark."""
    def __init__(self):
        self.step = 0

    def complete(self, messages, tools):
        edit = 'from pathlib import Path; p=Path("stats.py"); p.write_text(p.read_text().replace("sum(values) / (len(values) - 1)", "sum(values) / len(values)"))'
        commands = ["ls -la; cat stats.py", "python -m unittest discover -v",
                    "python -c " + shlex.quote(edit),
                    "python -m unittest discover -v"]
        i = self.step
        self.step += 1
        if i >= len(commands):
            return {"role": "assistant", "content": "Candidate patch ready. Independent verification is still required."}, {}
        return {"role": "assistant", "content": None, "tool_calls": [{"id": f"demo-{i}",
            "type": "function", "function": {"name": "shell", "arguments": json.dumps({"command": commands[i]})}}]}, {}
