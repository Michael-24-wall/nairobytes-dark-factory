"""Real agent runtime backed by a local opencode server.

The factory pipeline drives genuine LLM agents through the opencode session
API. Nothing here simulates a model response: if the runtime is unreachable
or an agent does not emit an explicit verdict, the stage fails closed.
"""

import os
import re
import time

import httpx

VERDICT_PATTERN = re.compile(r"FACTORY_VERDICT:\s*(PASS|FAIL)", re.IGNORECASE)

# Per-role work budgets. The architect only writes one markdown document, so it is
# bounded hard on every axis: the observed failure was an architect that spent 1184s
# inside tool calls (a 287s `npm install` and a 601s database spike) and produced its
# plan at t=1833s, 933s after the run was already marked failed. A planning role that
# is allowed to execute code has no bounded deliverable; the executor roles keep
# generous budgets because running tests and builds is their actual job.
#
# Wall clock is per role too, because generation time dominates execution roles: in the
# first live verification run the builder spent only 16s inside tool calls out of a 901s
# stage, the rest being real model generation for a 35-file application. It was not
# looping; it was doing assigned work that simply does not fit in a planning-sized budget.
#
# ``idle_timeout`` must exceed the slowest legitimate single generation step, because a
# role producing one large artifact shows no observable progress while the model is
# streaming it: the messages API reports nothing until the step completes. Measured on
# this runtime, one 26 KB plan took 92s in one attempt and was still streaming at 196s in
# another, so the architect idle limit is set well above that. It exists to catch a dead
# session, not to ration thinking time; the real bounds on runaway work are
# ``max_tool_calls``, ``tool_call_timeout`` and ``tool_seconds``.
ROLE_BUDGETS = {
    "architect": {"timeout": 420.0, "max_tool_calls": 8, "tool_call_timeout": 60.0,
                  "idle_timeout": 300.0, "tool_seconds": 240.0},
    "builder": {"timeout": 2400.0, "max_tool_calls": 250, "tool_call_timeout": 900.0,
                "idle_timeout": 900.0},
    "breaker": {"timeout": 2400.0, "max_tool_calls": 250, "tool_call_timeout": 900.0,
                "idle_timeout": 900.0},
    "repair": {"timeout": 2400.0, "max_tool_calls": 250, "tool_call_timeout": 900.0,
               "idle_timeout": 900.0},
    "verifier": {"timeout": 2400.0, "max_tool_calls": 250, "tool_call_timeout": 900.0,
                 "idle_timeout": 900.0},
}


class AgentRuntimeUnavailable(RuntimeError):
    """The opencode agent runtime could not be reached."""


class AgentTimeout(RuntimeError):
    """An agent exceeded one of its budgets. Carries diagnostics; never a PASS."""

    def __init__(self, message, *, role="", session_id="", elapsed=0.0, last_tool="",
                 last_tool_title="", tool_calls=0, kind="timeout", budget=None):
        super().__init__(message)
        self.role = role
        self.session_id = session_id
        self.elapsed = elapsed
        self.last_tool = last_tool
        self.last_tool_title = last_tool_title
        self.tool_calls = tool_calls
        self.kind = kind
        self.budget = dict(budget or {})

    def diagnostics(self) -> dict:
        return {
            "role": self.role,
            "session_id": self.session_id,
            "elapsed_seconds": round(self.elapsed, 1),
            "last_tool": self.last_tool,
            "last_tool_title": self.last_tool_title[:200],
            "tool_calls": self.tool_calls,
            "kind": self.kind,
            "budget": self.budget,
            "reason": str(self),
        }


def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class AgentBudget:
    """Work budget for one agent stage.

    A wall-clock deadline alone does not bound an agent: a single tool call can
    occupy the entire stage, and an agent that keeps starting new tool calls never
    produces its deliverable. The budget is therefore enforced on three axes:

    ``timeout``          total wall clock for the stage.
    ``tool_seconds``     total time spent inside tool calls.
    ``max_tool_calls``   number of distinct tool calls the agent may start.
    ``tool_call_timeout``wall clock for any single tool call.
    ``idle_timeout``     wall clock with no new tool call and no new message.

    Exceeding any of them aborts the session and raises ``AgentTimeout`` with the
    offending axis recorded, so the stage fails closed and diagnosably instead of
    running until the global timeout.
    """

    def __init__(self, timeout=900.0, tool_seconds=None, max_tool_calls=None,
                 tool_call_timeout=None, idle_timeout=None):
        self.timeout = timeout
        self.tool_seconds = tool_seconds
        self.max_tool_calls = max_tool_calls
        self.tool_call_timeout = tool_call_timeout
        self.idle_timeout = idle_timeout

    def describe(self) -> dict:
        return {
            "timeout_seconds": round(self.timeout, 1),
            "tool_seconds": self.tool_seconds,
            "max_tool_calls": self.max_tool_calls,
            "tool_call_timeout": self.tool_call_timeout,
            "idle_timeout": self.idle_timeout,
        }

    @classmethod
    def merge(cls, base, overrides):
        """Build a budget from a described budget plus overrides keyed either way.

        ``describe`` reports ``timeout_seconds`` for readability while the constructor
        takes ``timeout``; both spellings are accepted so a caller can layer role limits
        over an existing budget without special-casing the key.
        """
        def normalize(key):
            return "timeout" if key == "timeout_seconds" else key

        values = {normalize(key): value for key, value in base.describe().items()}
        values.update({normalize(key): value for key, value in dict(overrides or {}).items()})
        return cls(**values)


class AgentRuntime:
    def __init__(self, base_url=None, provider_id=None, model_id=None, timeout=None,
                 poll_interval=None, transport=None, budget=None):
        self.base_url = (base_url or os.getenv("OPENCODE_URL") or "http://127.0.0.1:4097").rstrip("/")
        self.provider_id = provider_id or os.getenv("FACTORY_MODEL_PROVIDER_ID") or "opencode"
        self.model_id = model_id or os.getenv("FACTORY_MODEL_ID") or "big-pickle"
        self.poll_interval = poll_interval or float(os.getenv("FACTORY_AGENT_POLL_INTERVAL", "2"))
        self.transport = transport  # injectable for tests; None = real network
        self.budget = budget if budget is not None else AgentBudget(
            timeout=timeout if timeout is not None else _env_int("FACTORY_AGENT_TIMEOUT", 900),
            tool_seconds=_env_float("FACTORY_AGENT_TOOL_SECONDS", 0) or None,
            max_tool_calls=_env_int("FACTORY_AGENT_MAX_TOOL_CALLS", 0) or None,
            tool_call_timeout=_env_float("FACTORY_AGENT_TOOL_CALL_TIMEOUT", 0) or None,
            idle_timeout=_env_float("FACTORY_AGENT_IDLE_TIMEOUT", 0) or None,
        )

    @property
    def timeout(self):
        return self.budget.timeout

    def budget_for(self, role):
        """Return the work budget for ``role``.

        A role that only produces a document gets tighter budgets than a role that
        legitimately runs tests and builds. Unknown roles fall back to the
        environment defaults. This is the only place role budgets are defined.
        """
        if role in ROLE_BUDGETS:
            return AgentBudget.merge(self.budget, ROLE_BUDGETS[role])
        return self.budget

    # -- runtime discovery -------------------------------------------------

    def available(self) -> bool:
        try:
            if self.transport is not None:
                # Honour the injected transport so discovery is as testable as the
                # session calls; otherwise this would reach the real network.
                with httpx.Client(timeout=4.0, transport=self.transport) as client:
                    response = client.get(f"{self.base_url}/global/health")
            else:
                response = httpx.get(f"{self.base_url}/global/health", timeout=4)
        except httpx.HTTPError:
            return False
        if response.status_code != 200:
            return False
        try:
            return bool(response.json().get("healthy"))
        except ValueError:
            return False

    def describe(self) -> dict:
        return {
            "base_url": self.base_url,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "timeout_seconds": self.budget.timeout,
            "role_budgets": {role: AgentBudget.merge(self.budget, limits).describe()
                             for role, limits in ROLE_BUDGETS.items()},
        }

    def require(self):
        if not self.available():
            raise AgentRuntimeUnavailable(
                f"opencode agent runtime is not reachable at {self.base_url}. "
                "Start it with `opencode serve` and retry."
            )

    # -- session lifecycle -------------------------------------------------

    def _create_session(self, client, directory):
        response = client.post(f"{self.base_url}/session", params={"directory": directory})
        if response.status_code >= 400:
            raise AgentRuntimeUnavailable(f"session creation failed: {response.status_code} {response.text[:200]}")
        payload = response.json()
        session_id = payload.get("id") or payload.get("info", {}).get("id")
        if not session_id:
            raise AgentRuntimeUnavailable("session creation returned no session id")
        return session_id

    def _prompt_async(self, client, session_id, directory, system, prompt):
        body = {
            "model": {"providerID": self.provider_id, "modelID": self.model_id},
            "parts": [{"type": "text", "text": prompt}],
        }
        if system:
            body["system"] = system
        response = client.post(
            f"{self.base_url}/session/{session_id}/prompt_async",
            params={"directory": directory},
            json=body,
        )
        if response.status_code >= 400:
            raise AgentRuntimeUnavailable(f"prompt rejected: {response.status_code} {response.text[:200]}")

    def _messages(self, client, session_id, directory):
        response = client.get(
            f"{self.base_url}/session/{session_id}/message",
            params={"directory": directory},
        )
        if response.status_code >= 400:
            return []
        try:
            payload = response.json()
        except ValueError:
            return []
        return payload if isinstance(payload, list) else []

    @staticmethod
    def _collect_tool_observations(messages):
        """Return the latest per-tool status so callers can emit progress once.

        The key is the tool call id (unique per call), and each observation keeps the
        real tool name and title. The failed live run reported opaque ids such as
        ``call_01a101cc0b7571aca16d3f9b`` as the "tool", which made the required
        "last known tool call" diagnostic unreadable.
        """
        observations = {}
        for message in messages:
            for part in message.get("parts", []) or []:
                if part.get("type") != "tool":
                    continue
                state = part.get("state", {}) or {}
                tool = part.get("tool") or state.get("title") or "tool"
                status = state.get("status") or "pending"
                key = part.get("callID") or part.get("id") or tool
                previous = observations.get(key)
                if previous is None or previous["status"] != status:
                    observations[key] = {
                        "tool": tool,
                        "title": state.get("title") or "",
                        "status": status,
                        "time": state.get("time", {}) or {},
                    }
        return observations

    @staticmethod
    def _tool_wall_seconds(observations):
        """Seconds an agent has spent inside tool calls, from real tool timings."""
        total = 0.0
        for observation in observations.values():
            timing = observation.get("time") or {}
            start, end = timing.get("start"), timing.get("end")
            if start and end:
                total += max(0.0, (end - start) / 1000.0)
        return total

    @staticmethod
    def _running_tool(observations):
        """Return (call_id, observation) of the tool call currently executing."""
        for key, observation in observations.items():
            if observation["status"] in {"pending", "running"}:
                return key, observation
        return None, None

    @staticmethod
    def _final_text(messages):
        """Prefer the last assistant message; fall back to the longest text seen.

        Agents stream a preamble ("I'll inspect...") in an early message and the
        real handoff in the final one, so the tail is authoritative.
        """
        per_message = []
        for message in messages:
            if (message.get("info", {}) or {}).get("role") != "assistant":
                continue
            texts = [
                part["text"].strip()
                for part in message.get("parts", []) or []
                if part.get("type") == "text" and (part.get("text") or "").strip()
            ]
            if texts:
                per_message.append(texts)
        if per_message:
            return per_message[-1][-1]
        everything = [
            part["text"].strip()
            for message in messages
            for part in message.get("parts", []) or []
            if part.get("type") == "text" and (part.get("text") or "").strip()
        ]
        return max(everything, key=len) if everything else ""

    def _abort(self, client, session_id, directory):
        """Stop a session so a looping agent cannot keep working past its deliverable."""
        try:
            client.post(f"{self.base_url}/session/{session_id}/abort", params={"directory": directory})
        except httpx.HTTPError:
            pass

    @staticmethod
    def _is_complete(messages):
        """An agent emits one assistant message per step, so the first completed
        message does not mean the agent finished. Every assistant message must be
        completed before the run is over."""
        assistants = [
            message for message in messages
            if (message.get("info", {}) or {}).get("role") == "assistant"
        ]
        if not assistants:
            return False
        return all(
            (message.get("info", {}) or {}).get("time", {}).get("completed")
            for message in assistants
        )

    # -- public API --------------------------------------------------------

    def run(self, role, mandate, prompt, directory, on_progress=None, should_cancel=None,
            completion_check=None, budget=None):
        """Run one agent to completion and return its text, verdict and evidence.

        Bounded completion contract: the stage ends when EITHER every assistant
        message has finished (the agent stopped on its own) OR ``completion_check()``
        reports that the stage's required artifact now exists, the agent is not in
        the middle of a tool call, and a hand-off message has already been produced.
        In the second case the session is aborted so a looping agent cannot keep
        doing unrelated work past its assigned deliverable.

        Every budget breach aborts the session before raising. The previous live run
        raised on the wall clock without aborting, so the agent kept working for a
        further 971 seconds and kept mutating the workspace after the run had already
        been recorded as failed.

        ``on_progress(kind, detail)`` is called as the agent works so callers can
        stream the run into the database while it is still in flight.
        """
        self.require()
        limits = budget or self.budget_for(role)
        started = time.monotonic()
        deadline = started + limits.timeout
        completed_by = None
        session_id = ""
        last_tool = ""
        last_tool_title = ""
        reported_tools = {}
        messages = []
        observations = {}
        last_progress = time.monotonic()

        def elapsed():
            return time.monotonic() - started

        def fail(message, kind):
            """Abort the real session, then fail the stage with full diagnostics."""
            self._abort(client, session_id, directory)
            raise AgentTimeout(
                message, role=role, session_id=session_id, elapsed=elapsed(),
                last_tool=last_tool, last_tool_title=last_tool_title,
                tool_calls=len(reported_tools), kind=kind,
                budget=limits.describe(),
            )

        with httpx.Client(timeout=60.0, transport=self.transport) as client:
            session_id = self._create_session(client, directory)
            if on_progress:
                on_progress("session", f"{role} session {session_id} opened on {self.model_id}")
            self._prompt_async(client, session_id, directory, mandate, prompt)

            while True:
                if should_cancel and should_cancel():
                    fail(f"{role} was cancelled by the operator", "cancelled")

                previous_count = len(reported_tools)
                previous_ids = (len(messages), last_tool)
                messages = self._messages(client, session_id, directory)
                observations = self._collect_tool_observations(messages)
                for key, observation in observations.items():
                    status = observation["status"]
                    if reported_tools.get(key) == status:
                        continue
                    reported_tools[key] = status
                    last_tool = observation["tool"]
                    last_tool_title = observation["title"]
                    if on_progress and status in {"running", "completed", "error"}:
                        label = f"{observation['tool']} ({observation['title'][:80]})" if observation["title"] else observation["tool"]
                        on_progress("tool", f"{role}: {label} {status}")

                # Artifact contract: the assigned deliverable exists, the agent is
                # not in the middle of a tool call, and a hand-off exists.
                running_key, running_observation = self._running_tool(observations)
                running = running_observation is not None
                if completion_check is not None and not running and self._final_text(messages):
                    try:
                        artifact_ready = bool(completion_check())
                    except Exception:  # noqa: BLE001 - a broken check must never mask progress
                        artifact_ready = False
                    if artifact_ready:
                        completed_by = "artifact"
                        self._abort(client, session_id, directory)
                        break

                if self._is_complete(messages):
                    completed_by = "agent"
                    break

                # --- work budgets: fail closed and diagnosably, never hang ---
                if limits.max_tool_calls is not None and len(reported_tools) > limits.max_tool_calls:
                    fail(f"{role} started {len(reported_tools)} tool calls, over its budget of "
                         f"{limits.max_tool_calls}", "tool_call_budget")

                if running_observation is not None and limits.tool_call_timeout is not None:
                    timing = running_observation.get("time") or {}
                    start = timing.get("start")
                    if start:
                        running_for = time.time() - start / 1000.0
                        if running_for > limits.tool_call_timeout:
                            fail(f"{role} tool call {running_observation['tool']} "
                                 f"({running_observation['title'][:80]}) ran {running_for:.0f}s, over its "
                                 f"{limits.tool_call_timeout:.0f}s budget", "tool_call_timeout")

                if limits.tool_seconds is not None:
                    tool_wall = self._tool_wall_seconds(observations)
                    if running_observation is not None:
                        timing = running_observation.get("time") or {}
                        start = timing.get("start")
                        if start:
                            tool_wall += max(0.0, time.time() - start / 1000.0)
                    if tool_wall > limits.tool_seconds:
                        fail(f"{role} spent {tool_wall:.0f}s inside tool calls, over its "
                             f"{limits.tool_seconds:.0f}s budget", "tool_seconds")

                if limits.idle_timeout is not None:
                    progressed = (len(reported_tools) != previous_count
                                  or (len(messages), last_tool) != previous_ids)
                    if progressed:
                        last_progress = time.monotonic()
                    elif time.monotonic() - last_progress > limits.idle_timeout:
                        fail(f"{role} made no progress for {limits.idle_timeout:.0f}s "
                             f"(last tool {last_tool or 'n/a'})", "idle_timeout")

                if time.monotonic() > deadline:
                    fail(f"{role} exceeded {limits.timeout}s without finishing", "timeout")
                time.sleep(self.poll_interval)

        text = self._final_text(messages)
        matches = VERDICT_PATTERN.findall(text)
        verdict = matches[-1].upper() if matches else None
        errors = [
            (part.get("state", {}) or {}).get("error")
            for message in messages
            for part in message.get("parts", []) or []
            if part.get("type") == "tool" and (part.get("state", {}) or {}).get("status") == "error"
        ]
        errors = [error for error in errors if error]
        return {
            "role": role,
            "session_id": session_id,
            "text": text,
            "verdict": verdict,
            "tool_calls": len(reported_tools),
            "errors": errors,
            "completed": True,
            "completed_by": completed_by,
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "last_tool": last_tool,
            "last_tool_title": last_tool_title[:200],
            "tool_seconds": round(self._tool_wall_seconds(observations), 1),
            "budget": limits.describe(),
        }