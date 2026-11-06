"""
Judging agent: a Worker LLM uses Google Drive tools, and a Guardian checks
every tool call before it runs.

  config.py   settings from .env
  llm.py      watsonx.ai client
  tools.py    the tool registry
  drive/      storage backends (no security logic)
  guardian/   the security layer
  worker/     the agent loop
"""
