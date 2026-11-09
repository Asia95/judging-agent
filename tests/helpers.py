"""Small builders and fakes shared by the tests (import with `from helpers import ...`)."""

from langchain_core.messages import AIMessage

from evals.scenarios import fixture as fx
from judging_agent.drive.base import TEXT_MIME, ResourceMeta
from judging_agent.guardian import Decision, Layer, TaskScope, Verdict
from judging_agent.guardian.context import CallContext
from judging_agent.guardian.decision import Tier
from judging_agent.guardian.provenance import Sighting
from judging_agent.tools import Action


def meta(path="/Finance/Invoices/inv.txt", owner="owner@company.com", is_folder=False,
         mime=TEXT_MIME, ancestors=(), id="file-1") -> ResourceMeta:
    return ResourceMeta(id=id, name=path.rsplit("/", 1)[-1], path=path, owner=owner,
                        mime_type=mime, is_folder=is_folder, ancestors=tuple(ancestors))


def make_ctx(action=Action.READ, tier=Tier.MEDIUM, args=None, resource=None, history=(),
             tool="drive_read_file", resource_arg="file_id") -> CallContext:
    return CallContext(
        task="t", scope=TaskScope(intent="t"), tool=tool, action=action,
        args=args if args is not None else {resource_arg: "file-1"}, resource_arg=resource_arg,
        resource=resource or meta(), sighting=Sighting("task"), tier=tier, tier_reason="r",
        history=tuple(history), taint=(),
    )


class AllowJudge:
    """A judge that allows everything: shows what the rules and the engine enforce on their own."""
    name = "allow-all"

    def __init__(self):
        self.calls = 0

    def decide(self, ctx):
        self.calls += 1
        return Decision(Verdict.ALLOW, "allow everything", Layer.LLM, ctx.tier)


def scenario(name):
    return next(s for s in fx.ALL_SCENARIOS if s.name == name)


class SpyDrive:
    """Wraps a Drive backend: records every call that touches files, and can make some fail.

    touched: [(method, resource_id), ...]   fail: method names that raise ConnectionError
    """

    def __init__(self, inner=None, fail=()):
        self.inner = inner or fx.build_drive()
        self.fail = set(fail)
        self.touched: list[tuple[str, str]] = []

    def __getattr__(self, name):            # get_metadata, user_email, nodes, writes, ...
        return getattr(self.inner, name)

    def _touch(self, method, resource_id, *rest):
        self.touched.append((method, resource_id))
        if method in self.fail:
            raise ConnectionError("network down")
        return getattr(self.inner, method)(resource_id, *rest)

    def list_folder(self, folder_id, max_results=50):
        return self._touch("list_folder", folder_id, max_results)

    def read_file(self, file_id):
        return self._touch("read_file", file_id)

    def update_file(self, file_id, content):
        return self._touch("update_file", file_id, content)

    def create_file(self, folder_id, name, content):
        return self._touch("create_file", folder_id, name, content)


# ── A scripted worker model (no network) ──────────────────────────────────────

class ScriptedChatModel:
    """Answers with the given AIMessages in order; records the tools it was offered and what it saw."""

    def __init__(self, *replies: AIMessage):
        self.replies = list(replies)
        self.offered: list[str] = []
        self.seen: list[list] = []

    def bind_tools(self, tools):
        self.offered = [t["function"]["name"] for t in tools]
        return self

    def invoke(self, messages):
        self.seen.append(list(messages))
        return self.replies.pop(0)


def call(name, args, id="c1"):
    return {"name": name, "args": args, "id": id, "type": "tool_call"}


def wants(*calls):
    return AIMessage(content="", tool_calls=list(calls))


def answer(text):
    return AIMessage(content=text)
