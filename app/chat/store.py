"""Round E chat — conversation storage.

Task 4 (durable): the in-process store keeps the FULL message dicts, writes
through to SQLite (``app/chat/persistence.py``, ``data/runtime/chat.db``,
gitignored) on every mutation, rehydrates at construction so conversations and
messages survive a process restart, and MIRRORS the schema-catalogued subset
to the graph as ``phx_dm_pce_conversation`` / ``phx_dm_pce_chat_message``
vertices (plus the ``phx_dm_pce_message_in_conversation`` edge) through the
tiered graph client on every write — best-effort, logged (precedent:
``InsightStore._mirror``). The runtime upsert is these vertices' loading job;
there is no CSV loading job (precedent: ``phx_dm_pce_agent_turn_log``).

Global persistence for now — every user sees every conversation (demo
simplification, recorded in DECISIONS.md; per-user scoping comes later).

Message rows carry the full Task-4 field set: message_id, conversation_id,
seq_no, role, text, tool_calls_json, guardrail_tag, guardrail_confidence,
guardrail_json, reasoning_steps_json, latency_ms, tokens_in, tokens_out,
est_cost_usd — token and cost per message feed the Trace screen like every
other agent call (the underlying LLM turns are ALSO turn-logged under the
conversation's ``chat|<conversation_id>`` scope). guardrail_json and
extra_json live in SQLite + in-process only (not graph-mirrored).
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from app.chat.persistence import ChatPersistence
from app.shared.logging import get_logger

_log = get_logger("app.chat.store")

CONVERSATION_VERTEX = "phx_dm_pce_conversation"
MESSAGE_VERTEX = "phx_dm_pce_chat_message"
MESSAGE_IN_CONVERSATION_EDGE = "phx_dm_pce_message_in_conversation"

_CONVERSATION_ATTRS = ("conversation_id", "title", "created_at", "updated_at",
                       "message_count")
_MESSAGE_ATTRS = ("message_id", "conversation_id", "seq_no", "role", "text",
                  "tool_calls_json", "guardrail_tag", "guardrail_confidence",
                  "reasoning_steps_json", "latency_ms", "tokens_in", "tokens_out",
                  "est_cost_usd", "created_at")

_EDGE_ENTRY = {
    "kind": "edge",
    "target": MESSAGE_IN_CONVERSATION_EDGE,
    "from_type": MESSAGE_VERTEX,
    "to_type": CONVERSATION_VERTEX,
    "from_column": "from_id",
    "to_column": "to_id",
    "file": f"runtime:{MESSAGE_IN_CONVERSATION_EDGE}",
    "columns": {},
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _entry(target: str, id_column: str, attrs: tuple[str, ...]) -> dict:
    return {"kind": "vertex", "target": target, "id_column": id_column,
            "file": f"runtime:{target}",
            "columns": {name: name for name in attrs if name != id_column}}


class ChatStore:
    """Durable conversation store: SQLite write-through + graph mirror."""

    def __init__(self, persistence: ChatPersistence | None = None) -> None:
        self._lock = threading.RLock()
        self.conversations: dict[str, dict] = {}
        self.messages: dict[str, list[dict]] = {}  # conversation_id -> rows
        # Task 4 — durable layer; rehydrate-on-construction so a restart keeps
        # every conversation reopenable with full context (Task 5).
        self._persist = persistence or ChatPersistence()
        self._rehydrate()

    def _rehydrate(self) -> None:
        conv_rows, msg_rows = self._persist.load_all()
        for row in conv_rows:
            cid = row["conversation_id"]
            self.conversations[cid] = row
            self.messages[cid] = msg_rows.get(cid, [])
            if row.get("message_count") != len(self.messages[cid]):
                _log.warning(
                    "conversation %s rehydrated with message_count=%s but %d "
                    "message rows — trusting the rows", cid,
                    row.get("message_count"), len(self.messages[cid]))
                row["message_count"] = len(self.messages[cid])
        orphans = set(msg_rows) - set(self.conversations)
        if orphans:
            _log.warning("ignoring %d message group(s) with no conversation "
                         "header: %s", len(orphans), sorted(orphans))
        if self.conversations:
            _log.info("rehydrated %d conversation(s), %d message(s) from %s",
                      len(self.conversations),
                      sum(len(m) for m in self.messages.values()),
                      self._persist.db.db_path)

    # -------------------------------------------------------------- graph mirror

    def _graph(self):
        from app.graph.client import get_graph_client

        return get_graph_client()

    def _mirror(self, target: str, id_column: str, attrs: tuple[str, ...],
                row: dict) -> None:
        clean = {name: ("" if row.get(name) is None else row.get(name))
                 for name in attrs}
        try:
            self._graph().upsert(_entry(target, id_column, attrs), [clean])
        except Exception as exc:  # noqa: BLE001 — store stays authoritative; log loudly
            _log.error("graph mirror of %s %s failed: %s",
                       target, row.get(id_column), exc)

    def _mirror_edge(self, message_id: str, conversation_id: str) -> None:
        try:
            self._graph().upsert(_EDGE_ENTRY,
                                 [{"from_id": message_id, "to_id": conversation_id}])
        except Exception as exc:  # noqa: BLE001
            _log.error("graph mirror of %s %s->%s failed: %s",
                       MESSAGE_IN_CONVERSATION_EDGE, message_id,
                       conversation_id, exc)

    # ------------------------------------------------------------ conversations

    def create_conversation(self, title: str = "") -> dict:
        with self._lock:
            cid = f"C{uuid.uuid4().hex[:12]}"
            row = {"conversation_id": cid, "title": title or "New conversation",
                   "created_at": _now(), "updated_at": _now(), "message_count": 0}
            self.conversations[cid] = row
            self.messages[cid] = []
            self._persist.save_conversation(row)
            self._mirror(CONVERSATION_VERTEX, "conversation_id",
                         _CONVERSATION_ATTRS, row)
            return dict(row)

    def conversation(self, conversation_id: str) -> dict | None:
        with self._lock:
            row = self.conversations.get(conversation_id)
            return dict(row) if row else None

    def list_conversations(self) -> list[dict]:
        with self._lock:
            out = []
            for cid, row in self.conversations.items():
                msgs = self.messages.get(cid, [])
                preview = ""
                for m in reversed(msgs):
                    if m.get("text"):
                        preview = m["text"][:120]
                        break
                out.append({**row, "last_message_preview": preview})
            out.sort(key=lambda r: r["updated_at"], reverse=True)
            return out

    def set_title(self, conversation_id: str, title: str) -> dict | None:
        with self._lock:
            row = self.conversations.get(conversation_id)
            if row is None:
                return None
            row["title"] = str(title).strip() or row["title"]
            row["updated_at"] = _now()
            self._persist.save_conversation(row)
            self._mirror(CONVERSATION_VERTEX, "conversation_id",
                         _CONVERSATION_ATTRS, row)
            return dict(row)

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock:
            if conversation_id not in self.conversations:
                return False
            message_ids = [m["message_id"]
                           for m in self.messages.get(conversation_id, [])]
            del self.conversations[conversation_id]
            self.messages.pop(conversation_id, None)
            # durable rows go with it (Task 5) …
            self._persist.delete_conversation(conversation_id)
            # … and the graph mirror follows, best-effort (edges go with their
            # endpoint vertices — precedent DocumentGraphWriter.delete_document).
            try:
                if message_ids:
                    self._graph().delete_vertices(MESSAGE_VERTEX, message_ids)
                self._graph().delete_vertices(CONVERSATION_VERTEX, [conversation_id])
            except Exception as exc:  # noqa: BLE001
                _log.error("graph delete of conversation %s failed: %s",
                           conversation_id, exc)
            return True

    # ----------------------------------------------------------------- messages

    def add_message(self, conversation_id: str, role: str, text: str, *,
                    tool_calls: list[dict] | None = None,
                    guardrail: dict | None = None,
                    reasoning_steps: list[dict] | None = None,
                    latency_ms: int = 0, tokens_in: int = 0,
                    tokens_out: int = 0, est_cost_usd: float = 0.0,
                    extra: dict | None = None) -> dict:
        with self._lock:
            conv = self.conversations.get(conversation_id)
            if conv is None:
                raise KeyError(f"unknown conversation '{conversation_id}'")
            seq_no = len(self.messages[conversation_id]) + 1
            row = {
                "message_id": f"{conversation_id}|{seq_no}",
                "conversation_id": conversation_id, "seq_no": seq_no,
                "role": role, "text": text,
                "tool_calls_json": json.dumps(tool_calls or [], default=str),
                "guardrail_tag": (guardrail or {}).get("tag", ""),
                "guardrail_confidence": float((guardrail or {}).get("confidence") or 0.0),
                "guardrail_json": json.dumps(guardrail or {}, default=str),
                "reasoning_steps_json": json.dumps(reasoning_steps or [], default=str),
                "latency_ms": int(latency_ms),
                "tokens_in": int(tokens_in), "tokens_out": int(tokens_out),
                "est_cost_usd": round(float(est_cost_usd), 6),
                "created_at": _now(),
                "extra_json": json.dumps(extra or {}, default=str),
            }
            self.messages[conversation_id].append(row)
            conv["message_count"] = seq_no
            conv["updated_at"] = _now()
            # title auto-generated from the first user message (editable)
            if role == "user" and conv["title"] == "New conversation":
                conv["title"] = (text or "").strip()[:60] or conv["title"]
            # write-through: message + updated header in one transaction
            self._persist.save_message(conv, row)
            self._mirror(MESSAGE_VERTEX, "message_id", _MESSAGE_ATTRS, row)
            self._mirror_edge(row["message_id"], conversation_id)
            self._mirror(CONVERSATION_VERTEX, "conversation_id",
                         _CONVERSATION_ATTRS, conv)
            return dict(row)

    def conversation_messages(self, conversation_id: str) -> list[dict]:
        with self._lock:
            return [dict(m) for m in self.messages.get(conversation_id, [])]

    # ----------------------------------------------------- guardrail trace feed

    def guardrail_log(self) -> list[dict]:
        """Every classification ever made, blocked or not — the Guardrail tab's
        feed (Task 7). One row per USER message, with the tools-called count of
        the assistant reply that served it (0 for anything blocked outright)."""
        with self._lock:
            rows = []
            for cid, msgs in self.messages.items():
                for i, m in enumerate(msgs):
                    if m["role"] != "user":
                        continue
                    guardrail = json.loads(m.get("guardrail_json") or "{}")
                    if not guardrail:
                        continue
                    tools_called = 0
                    for later in msgs[i + 1:]:
                        if later["role"] == "assistant":
                            tools_called = len(json.loads(
                                later.get("tool_calls_json") or "[]"))
                            break
                    rows.append({
                        "when": m.get("created_at"),
                        "conversation_id": cid,
                        "message_id": m["message_id"],
                        "message": (m.get("text") or "")[:2000],
                        "tag": guardrail.get("tag", "CLEAN"),
                        "confidence": guardrail.get("confidence", 0.0),
                        "action": guardrail.get("action", "ALLOWED"),
                        "tools_called": tools_called,
                    })
            rows.sort(key=lambda r: r["when"] or "", reverse=True)
            return rows


_store: ChatStore | None = None
_store_lock = threading.Lock()


def get_chat_store() -> ChatStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = ChatStore()
        return _store
