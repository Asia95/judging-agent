from judging_agent.guardian import scope as scope_mod
from judging_agent.guardian.scope import DEFAULT_SENSITIVE_HINTS, derive_scope
from judging_agent.tools import Action


def _llm_returns(monkeypatch, data):
    monkeypatch.setattr(scope_mod, "chat_json", lambda model, system, user: (data, ""))


def test_write_implies_read_and_read_implies_list(monkeypatch):
    _llm_returns(monkeypatch, {"intent": "edit", "actions": ["write"]})
    scope = derive_scope("edit a file", model=None)
    assert scope.actions == (Action.LIST, Action.READ, Action.WRITE)
    assert scope.source == "llm"


def test_a_string_instead_of_a_list_is_ignored_not_split_into_letters(monkeypatch):
    """B7"""
    _llm_returns(monkeypatch, {"intent": "x", "actions": ["read"], "out_of_bounds_hints": "payroll"})
    assert derive_scope("task", model=None).out_of_bounds_hints == ()


def test_lists_are_lowercased_and_capped_at_five(monkeypatch):
    _llm_returns(monkeypatch, {"actions": ["read"], "relevant_locations": ["A", "B", "C", "D", "E", "F"]})
    assert derive_scope("task", model=None).relevant_locations == ("a", "b", "c", "d", "e")


def test_llm_failure_gives_a_strict_fallback_that_says_so(monkeypatch):
    """B6: the fallback used to have no hints at all (fail-open) and was silent."""
    def boom(model, system, user):
        raise ConnectionError("watsonx down")
    monkeypatch.setattr(scope_mod, "chat_json", boom)
    scope = derive_scope("summarise invoices", model=None)
    assert scope.source == "fallback"
    assert scope.actions == (Action.LIST, Action.READ)
    assert scope.out_of_bounds_hints == DEFAULT_SENSITIVE_HINTS


def test_unusable_answers_also_fall_back(monkeypatch):
    _llm_returns(monkeypatch, None)
    assert derive_scope("task", model=None).source == "fallback"
    _llm_returns(monkeypatch, {"actions": ["delete"]})
    assert derive_scope("task", model=None).source == "fallback"
