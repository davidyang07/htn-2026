"""In-memory registry of live runtime sessions.

Deliberately separate from ``app/orchestrator/registry.py``. That one is typed
``dict[UUID, ExperimentRunner]`` and ``routes_graph.py``/``routes_history.py``
reach into ``.state`` (a ``WorldState``) and ``.config`` (an
``ExperimentConfig``) on whatever comes out of it. Registering a
``LiveRuntimeSession`` there would be a typing lie that breaks those routes at
runtime (docs/ARCHITECTURE.md §6).

P0 holds sessions in memory only, exactly as M0 experiments did
(docs/ARCHITECTURE.md §8).
"""

from uuid import UUID

from app.runtime.session import LiveRuntimeSession


class RuntimeRegistry:
    """A dict, with a demo-shaped extra: the id of the most recent session.

    The /demo screen opens with no session id in hand and needs to attach to
    whatever the WorkSwarm run just created, so "the current one" is a real
    requirement rather than convenience.
    """

    def __init__(self) -> None:
        self._sessions: dict[UUID, LiveRuntimeSession] = {}
        self._latest_id: UUID | None = None

    def add(self, session: LiveRuntimeSession) -> None:
        self._sessions[session.session_id] = session
        self._latest_id = session.session_id

    def get(self, session_id: UUID) -> LiveRuntimeSession | None:
        return self._sessions.get(session_id)

    def latest(self) -> LiveRuntimeSession | None:
        if self._latest_id is None:
            return None
        return self._sessions.get(self._latest_id)

    def remove(self, session_id: UUID) -> None:
        self._sessions.pop(session_id, None)
        if self._latest_id == session_id:
            self._latest_id = None

    def clear(self) -> None:
        """Reset Demo. Drops every session, including the current one."""
        self._sessions.clear()
        self._latest_id = None

    def __len__(self) -> int:
        return len(self._sessions)


runtime_registry = RuntimeRegistry()
