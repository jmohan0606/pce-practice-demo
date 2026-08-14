"""Round E chat — conversation storage.

Main-thread Task 3 ships the WORKING interface with in-memory storage so the
agent is testable end to end; Task 4 (Subagent A) makes it durable
(SQLite + graph mirror of phx_dm_pce_conversation / phx_dm_pce_chat_message)
behind THIS SAME interface — callers never change.

Global persistence for now — every user sees every conversation (demo
simplification, recorded in DECISIONS.md; per-user scoping comes later).

Message rows carry the full Task-4 field set: message_id, conversation_id,
seq_no, role, text, tool_calls_json, guardrail_tag, guardrail_confidence,
guardrail_json, reasoning_steps_json, latency_ms, tokens_in, tokens_out,
est_cost_usd — token and cost per message feed the Trace screen like every
other agent call (the underlying LLM turns are ALSO turn-logged under the
conversation's ``chat|<conversation_id>`` scope).
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from app.shared.logging import get_logger

_log = get_logger("app.chat.store")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class ChatStore:
    """In-memory conversation store (Task 3 baseline; Task 4 makes it durable)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.conversations: dict[str, dict] = {}
        self.messages: dict[str, list[dict]] = {}  # conversation_id -> rows

    # ------------------------------------------------------------ conversations

    def create_conversation(self, title: str = "") -> dict:
        with self._lock:
            cid = f"C{uuid.uuid4().hex[:12]}"
            row = {"conversation_id": cid, "title": title or "New conversation",
                   "created_at": _now(), "updated_at": _now(), "message_count": 0}
            self.conversations[cid] = row
            self.messages[cid] = []
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
            return dict(row)

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock:
            if conversation_id not in self.conversations:
                return False
            del self.conversations[conversation_id]
            self.messages.pop(conversation_id, None)
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
