"""Focused tests for the live agent runtime.

These cover the failure that stopped the real live factory run
(db69954a-4cc8-4aa0-85ae-812a7997ab7d): an Architect that kept executing tool calls
instead of finishing its bounded plan, hit the 900s wall clock, and kept working for
a further 971s because the timeout never aborted the real session.

The runtime talks to opencode over httpx, so every test drives it through an injected
transport. No test makes a network call or starts an LLM.
"""

import json
import time

import httpx
import pytest

from app.backend.agent_runtime import (
    ROLE_BUDGETS,
    AgentBudget,
    AgentRuntime,
    AgentRuntimeUnavailable,
    AgentTimeout,
)

NOW_MS = int(time.time() * 1000)


def tool_part(call_id, tool, status, title="", start=None, end=None, error=None):
    """One tool part. ``start``/``end`` are epoch milliseconds like opencode sends."""
    part = {
        "type": "tool",
        "tool": tool,
        "callID": call_id,
        "state": {"status": status, "title": title or tool},
    }
    if start is not None:
        part["state"]["time"] = {"start": start}
    if end is not None:
        part["state"].setdefault("time", {})["end"] = end
    if error:
        part["state"]["error"] = error
    return part


def assistant(parts, completed=True, created=NOW_MS):
    info = {"role": "assistant", "id": f"msg_{created}"}
    info["time"] = {"created": created}
    if completed:
        info["time"]["completed"] = created + 1
    return {"info": info, "parts": parts}


def user_message(text, created=NOW_MS):
    """The prompt echo opencode stores first; a user message never ends a run."""
    return {"info": {"role": "user", "id": f"usr_{created}", "time": {"created": created}},
            "parts": [{"type": "text", "text": text}]}


def say(text, completed=True, created=NOW_MS):
    """An assistant text message."""
    return assistant([{"type": "text", "text": text}], completed=completed, created=created)


def working(*parts, created=NOW_MS):
    """An in-flight assistant step that has not completed yet."""
    return assistant(list(parts), completed=False, created=created)


def tool(name, status="completed", title="", started_ago_s=1.0, duration_s=0.5, call_id=None):
    """A tool part whose timings are anchored to now, so budgets behave realistically."""
    start = NOW_MS - int(started_ago_s * 1000)
    end = None if status in {"running", "pending"} else start + int(duration_s * 1000)
    return tool_part(call_id or f"c_{name}_{title}_{call_id}_{started_ago_s}", name, status,
                     title, start, end)


class FakeOpencode:
    """Minimal opencode session server driven by a scripted message sequence."""

    def __init__(self, script, health=True, session_id="ses_test"):
        # script: list of message lists, returned one per poll
        self.script = list(script)
        self.health = health
        self.session_id = session_id
        self.calls = []
        self.aborted = []
        self.polls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path == "/global/health":
            if not self.health:
                return httpx.Response(500, json={"healthy": False})
            return httpx.Response(200, json={"healthy": True})
        if path == "/session" and request.method == "POST":
            return httpx.Response(200, json={"id": self.session_id})
        if path.endswith("/prompt_async"):
            return httpx.Response(200, json={"ok": True})
        if path.endswith("/message"):
            index = min(self.polls, len(self.script) - 1)
            self.polls += 1
            return httpx.Response(200, json=self.script[index])
        if path.endswith("/abort"):
            self.aborted.append(path)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"error": "not found"})

    def transport(self):
        return httpx.MockTransport(self.handler)


def runtime_for(script, **kwargs):
    fake = FakeOpencode(script)
    kwargs.setdefault("poll_interval", 0.001)
    return AgentRuntime(transport=fake.transport(), **kwargs), fake


def unbounded(**overrides):
    """A budget with no limits, so a test only exercises the behaviour it targets."""
    values = {"timeout": 900.0, "tool_seconds": None, "max_tool_calls": None,
              "tool_call_timeout": None, "idle_timeout": None}
    values.update(overrides)
    return AgentBudget(**values)


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------


def test_runtime_unavailable_when_health_endpoint_fails():
    fake = FakeOpencode([[]], health=False)
    runtime = AgentRuntime(transport=fake.transport())
    assert runtime.available() is False
    with pytest.raises(AgentRuntimeUnavailable):
        runtime.run("architect", "mandate", "prompt", "dir")


def test_describe_reports_runtime_and_every_role_budget():
    runtime = AgentRuntime(base_url="http://runtime", timeout=900)
    described = runtime.describe()
    assert described["timeout_seconds"] == 900
    assert described["provider_id"]
    assert described["model_id"]
    assert set(described["role_budgets"]) == set(ROLE_BUDGETS)
    architect = described["role_budgets"]["architect"]
    assert architect["max_tool_calls"] == ROLE_BUDGETS["architect"]["max_tool_calls"]


# ---------------------------------------------------------------------------
# architect bounded responsibility
# ---------------------------------------------------------------------------


def test_architect_budget_bounds_tool_calls_and_execution_time():
    """The architect produces one markdown file; it may not run a feasibility spike."""
    merged = AgentBudget.merge(AgentBudget(timeout=900), ROLE_BUDGETS["architect"])
    assert merged.max_tool_calls == 8
    assert merged.tool_call_timeout == 60.0
    assert merged.tool_seconds == 240.0
    # Idle detection must outlast the slowest real generation step. A single 26 KB plan
    # write was still streaming at 196s on this runtime; an idle limit below that kills
    # a healthy architect mid-write instead of catching a dead session.
    assert merged.idle_timeout >= 300.0
    # The architect does not need a planning task's worth of wall clock either.
    assert merged.timeout <= 900.0
    assert merged.idle_timeout < merged.timeout


def test_architect_idle_timeout_outlasts_a_slow_single_write():
    """Regression: a 180s idle limit aborted the architect mid-generation of its plan."""
    architect = AgentBudget.merge(AgentBudget(timeout=900), ROLE_BUDGETS["architect"])
    observed_slowest_write_seconds = 196.0
    assert architect.idle_timeout > observed_slowest_write_seconds


def test_executor_roles_keep_generous_budgets_to_run_tests():
    """Generation time dominates executor roles, so their wall clock must be larger."""
    for role in ("builder", "breaker", "repair", "verifier"):
        limits = ROLE_BUDGETS[role]
        assert limits["tool_call_timeout"] >= 900.0, role
        assert limits["max_tool_calls"] >= 250, role
        assert limits["timeout"] >= 2400.0, role
        # Executors are allowed real execution time; the architect is not.
        assert "tool_seconds" not in limits, role


def test_architect_wall_clock_is_shorter_than_executor_wall_clock():
    architect = AgentBudget.merge(AgentBudget(timeout=900), ROLE_BUDGETS["architect"])
    builder = AgentBudget.merge(AgentBudget(timeout=900), ROLE_BUDGETS["builder"])
    assert architect.timeout < builder.timeout


def test_architect_budget_is_applied_by_role_not_by_global_timeout():
    runtime = AgentRuntime(timeout=900)
    architect = runtime.budget_for("architect")
    # Role budget overrides the global FACTORY_AGENT_TIMEOUT for the architect.
    assert architect.timeout == ROLE_BUDGETS["architect"]["timeout"]
    assert architect.max_tool_calls == 8
    assert architect.tool_call_timeout == 60.0
    # An unknown role falls back to the configured defaults, unconstrained.
    assert runtime.budget_for("some-future-role").max_tool_calls is None
    assert runtime.budget_for("some-future-role").timeout == 900


# ---------------------------------------------------------------------------
# completion contract
# ---------------------------------------------------------------------------


def test_agent_stops_on_its_own_and_returns_final_text():
    script = [
        [user_message("prompt"), working(tool("bash", "running", "ls", call_id="c1"))],
        [user_message("prompt"),
         assistant([tool("bash", "completed", "ls", call_id="c1")], created=NOW_MS + 1),
         say("Plan written. Handoff attached.", created=NOW_MS + 2)],
    ]
    runtime, fake = runtime_for(script)
    result = runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded())
    assert result["completed"] is True
    assert result["completed_by"] == "agent"
    assert result["text"].startswith("Plan written")
    assert result["verdict"] is None
    assert fake.aborted == []


def test_artifact_completion_aborts_a_looping_agent():
    """Artifact exists + handoff written -> stage completes and the session is aborted."""
    # The agent keeps calling tools and never finishes on its own.
    script = [
        [user_message("prompt"),
         working(tool("bash", "running", "npm install", call_id="c1"), created=NOW_MS + 1)],
        [user_message("prompt"),
         assistant([tool("bash", "completed", "npm install", call_id="c1")], created=NOW_MS + 1),
         working(tool("read", "running", "src/app.py", call_id="c2"), created=NOW_MS + 2)],
        [user_message("prompt"),
         assistant([tool("bash", "completed", "npm install", call_id="c1")], created=NOW_MS + 1),
         assistant([tool("read", "completed", "src/app.py", call_id="c2")], created=NOW_MS + 2),
         say("Plan written; handing off.", created=NOW_MS + 3)],
    ]
    runtime, fake = runtime_for(script)
    result = runtime.run("architect", "mandate", "prompt", "dir",
                         completion_check=lambda: True, budget=unbounded())
    assert result["completed"] is True
    assert result["completed_by"] == "artifact"
    assert fake.aborted, "the real session must be aborted so the agent stops working"


def test_artifact_completion_waits_while_a_tool_call_is_running():
    """A tool call in flight means the deliverable is not stable yet."""
    polls = []

    def artifact_exists():
        polls.append(len(polls) + 1)
        return True

    script = [
        # Poll 1: the write of the artifact itself is still running.
        [user_message("prompt"),
         working(tool("write", "running", "evidence/plan.md", call_id="c1"), created=NOW_MS + 1)],
        # Poll 2: the write finished, the hand-off was written, nothing is running.
        [user_message("prompt"),
         assistant([tool("write", "completed", "evidence/plan.md", call_id="c1")], created=NOW_MS + 1),
         say("Plan written.", created=NOW_MS + 2)],
    ]
    runtime, fake = runtime_for(script)
    result = runtime.run("architect", "mandate", "prompt", "dir",
                         completion_check=artifact_exists, budget=unbounded())
    # The artifact satisfied the contract from the very first poll, yet the stage did
    # not complete on that poll: the deliverable was still being written.
    assert len(polls) == 1, "the check is only consulted once nothing is running"
    assert result["text"].startswith("Plan written")
    assert fake.aborted


def test_broken_completion_check_never_masks_agent_progress():
    def broken():
        raise RuntimeError("check exploded")

    script = [[user_message("prompt"), say("Done. Handoff.")]]
    runtime, _fake = runtime_for(script)
    result = runtime.run("architect", "mandate", "prompt", "dir",
                         completion_check=broken, budget=unbounded())
    assert result["completed"] is True


def test_verdict_is_read_from_the_final_message_only():
    script = [
        [user_message("prompt"),
         say("Draft verdict FACTORY_VERDICT: FAIL"),
         assistant([tool("bash", "completed", "pytest", call_id="c1")], created=NOW_MS + 1),
         say("Real result.\nFACTORY_VERDICT: PASS", created=NOW_MS + 2)],
    ]
    runtime, _fake = runtime_for(script)
    result = runtime.run("breaker", "mandate", "prompt", "dir", budget=unbounded())
    assert result["verdict"] == "PASS"


def test_tool_errors_are_reported_not_hidden():
    script = [
        [user_message("prompt"),
         assistant([tool_part("c1", "bash", "error", "pytest", NOW_MS - 1000,
                             NOW_MS - 500, error="exit 1")], created=NOW_MS + 1),
         say("It failed. FACTORY_VERDICT: FAIL", created=NOW_MS + 2)],
    ]
    runtime, _fake = runtime_for(script)
    result = runtime.run("breaker", "mandate", "prompt", "dir", budget=unbounded())
    assert result["errors"] == ["exit 1"]
    assert result["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# real tool names in progress + diagnostics
# ---------------------------------------------------------------------------


def test_progress_reports_real_tool_names_not_opaque_call_ids():
    """The failed run recorded call_01a1... as the tool, making diagnosis impossible."""
    opaque = "call_01a101cc0b7571aca16d3f9b"
    script = [
        [user_message("prompt"),
         working(tool_part(opaque, "bash", "running", "npm install --no-audit", NOW_MS - 1000, None),
                 created=NOW_MS + 1)],
        [user_message("prompt"),
         assistant([tool_part(opaque, "bash", "completed", "npm install --no-audit",
                              NOW_MS - 1000, NOW_MS - 500)], created=NOW_MS + 1),
         say("Installed.", created=NOW_MS + 2)],
    ]
    runtime, _fake = runtime_for(script)
    seen = []
    runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded(),
                on_progress=lambda kind, detail: seen.append((kind, detail)))
    tool_messages = [detail for kind, detail in seen if kind == "tool"]
    assert tool_messages
    joined = " ".join(tool_messages)
    assert "bash" in joined
    assert "npm install" in joined
    assert opaque not in joined


def test_result_records_last_tool_name_and_title():
    script = [
        [user_message("prompt"),
         assistant([tool("edit", "completed", "evidence/plan.md", call_id="c1")], created=NOW_MS + 1),
         say("Handoff.", created=NOW_MS + 2)],
    ]
    runtime, _fake = runtime_for(script)
    result = runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded())
    assert result["last_tool"] == "edit"
    assert result["last_tool_title"] == "evidence/plan.md"
    assert result["tool_calls"] == 1
    assert result["tool_seconds"] >= 0.0


# ---------------------------------------------------------------------------
# work budgets: every breach fails closed AND aborts the real session
# ---------------------------------------------------------------------------


def test_tool_call_budget_breach_aborts_session_and_fails_closed():
    """This is the exact failure mode: an architect that keeps starting tool calls."""
    calls = [tool("bash", "completed", f"npm view {i}", call_id=f"c{i}") for i in range(10)]
    script = [[user_message("prompt"), working(*calls, created=NOW_MS + 1)]]
    runtime, fake = runtime_for(script)
    with pytest.raises(AgentTimeout) as raised:
        runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded(max_tool_calls=3))
    diagnostics = raised.value.diagnostics()
    assert diagnostics["kind"] == "tool_call_budget"
    assert diagnostics["tool_calls"] > 3
    assert fake.aborted, "the session must be aborted, not left running"


def test_single_long_tool_call_is_capped():
    """A 601s bash call consumed 2/3 of the failed run's budget in one shot."""
    script = [[user_message("prompt"),
               working(tool("bash", "running", "node spike2.mjs", started_ago_s=300.0, call_id="c1"),
                       created=NOW_MS + 1)]]
    runtime, fake = runtime_for(script)
    with pytest.raises(AgentTimeout) as raised:
        runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded(tool_call_timeout=60.0))
    diagnostics = raised.value.diagnostics()
    assert diagnostics["kind"] == "tool_call_timeout"
    assert diagnostics["last_tool"] == "bash"
    assert "node spike2.mjs" in diagnostics["last_tool_title"]
    assert fake.aborted


def test_total_tool_seconds_budget_is_enforced():
    calls = [tool("bash", "completed", f"step {i}", duration_s=9.0, call_id=f"c{i}")
             for i in range(4)]
    script = [[user_message("prompt"), working(*calls, created=NOW_MS + 1)]]
    runtime, fake = runtime_for(script)
    with pytest.raises(AgentTimeout) as raised:
        runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded(tool_seconds=10.0))
    assert raised.value.diagnostics()["kind"] == "tool_seconds"
    assert fake.aborted


def test_idle_timeout_fails_a_stalled_session():
    script = [[user_message("prompt"),
               working(tool("read", "completed", "a.py", call_id="c1"), created=NOW_MS + 1)]]
    runtime, fake = runtime_for(script)
    with pytest.raises(AgentTimeout) as raised:
        runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded(idle_timeout=0.0))
    assert raised.value.diagnostics()["kind"] == "idle_timeout"
    assert fake.aborted


def test_wall_clock_timeout_still_fails_and_aborts():
    script = [[user_message("prompt"),
               working(tool("bash", "running", "long", started_ago_s=0.1, call_id="c1"),
                       created=NOW_MS + 1)]]
    runtime, fake = runtime_for(script)
    with pytest.raises(AgentTimeout) as raised:
        runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded(timeout=0.0))
    assert raised.value.diagnostics()["kind"] == "timeout"
    assert fake.aborted


def test_operator_cancellation_aborts_and_reports_cancelled():
    script = [[user_message("prompt"),
               working(tool("bash", "running", "long", started_ago_s=0.1, call_id="c1"),
                       created=NOW_MS + 1)]]
    runtime, fake = runtime_for(script)
    with pytest.raises(AgentTimeout) as raised:
        runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded(),
                    should_cancel=lambda: True)
    assert raised.value.diagnostics()["kind"] == "cancelled"
    assert fake.aborted


def test_timeout_diagnostics_carry_full_failure_context():
    script = [[user_message("prompt"),
               working(tool("bash", "running", "npm install", started_ago_s=0.1, call_id="c9"),
                       created=NOW_MS + 1)]]
    runtime, _fake = runtime_for(script)
    with pytest.raises(AgentTimeout) as raised:
        runtime.run("architect", "mandate", "prompt", "dir",
                    budget=unbounded(timeout=0.0, max_tool_calls=5))
    diagnostics = raised.value.diagnostics()
    for key in ("role", "session_id", "elapsed_seconds", "last_tool", "tool_calls",
                "kind", "budget", "reason"):
        assert key in diagnostics, key
    assert diagnostics["role"] == "architect"
    assert diagnostics["session_id"] == "ses_test"
    assert diagnostics["budget"]["timeout_seconds"] == 0.0
    assert str(raised.value) in diagnostics["reason"]


def test_timeout_is_never_converted_into_a_result():
    """A timeout raises; it never returns a dict that a caller could score as done."""
    script = [[user_message("prompt"),
               working(tool("bash", "running", "x", started_ago_s=0.1, call_id="c1"),
                       created=NOW_MS + 1)]]
    runtime, _fake = runtime_for(script)
    with pytest.raises(AgentTimeout):
        runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded(timeout=0.0))


def test_run_is_not_complete_until_an_assistant_message_finishes():
    """opencode streams one assistant message per step; the first completion is not the end."""
    script = [
        [user_message("prompt"),
         say("Reading the file."),
         working(tool("read", "running", "a.py", call_id="c1"), created=NOW_MS + 1)],
        [user_message("prompt"),
         say("Reading the file."),
         assistant([tool("read", "completed", "a.py", call_id="c1")], created=NOW_MS + 1),
         working(tool("write", "running", "evidence/plan.md", call_id="c2"), created=NOW_MS + 2)],
        [user_message("prompt"),
         say("Reading the file."),
         assistant([tool("read", "completed", "a.py", call_id="c1")], created=NOW_MS + 1),
         assistant([tool("write", "completed", "evidence/plan.md", call_id="c2")], created=NOW_MS + 2),
         say("All done. Handoff.", created=NOW_MS + 3)],
    ]
    runtime, _fake = runtime_for(script)
    result = runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded())
    # It waited through two in-flight steps and returned the real final message.
    assert _fake.polls == 3
    assert result["text"].startswith("All done")


def test_scripted_transport_records_no_real_network_use():
    script = [[user_message("prompt"), say("Done.")]]
    runtime, fake = runtime_for(script)
    runtime.run("architect", "mandate", "prompt", "dir", budget=unbounded())
    methods = {method for method, _path in fake.calls}
    assert methods == {"GET", "POST"}
    assert json.dumps(fake.calls)  # sanity: the calls were recorded