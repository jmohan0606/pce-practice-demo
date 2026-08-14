"use client";

/** Round E 6.1 — the conversation history drawer inside the chat panel:
 * title / last-message preview / timestamp, click to open, delete with a
 * confirm. Fetches on every open so it always shows the live list.
 */

import { useCallback, useEffect, useState } from "react";
import {
  ChatApiError,
  type ConversationSummary,
  deleteConversation,
  listConversations,
} from "@/lib/chatApi";

function when(ts: string | undefined): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function ChatHistory({
  currentId,
  onOpen,
  onDeleted,
  onClose,
}: {
  currentId: string | null;
  onOpen: (id: string) => void;
  onDeleted: (id: string) => void;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<ConversationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listConversations()
      .then((r) => setRows(r.conversations))
      .catch((e) => setError(e instanceof ChatApiError ? e.message : String(e)));
  }, []);
  useEffect(load, [load]);

  const remove = (row: ConversationSummary) => {
    if (!window.confirm(`Delete "${row.title || "Untitled conversation"}"? Its messages go with it.`))
      return;
    deleteConversation(row.conversation_id)
      .then(() => {
        setRows((r) => (r ? r.filter((x) => x.conversation_id !== row.conversation_id) : r));
        onDeleted(row.conversation_id);
      })
      .catch((e) => setError(e instanceof ChatApiError ? e.message : String(e)));
  };

  return (
    <div className="chat-hist">
      <div className="chat-hist-h">
        <b>Conversations</b>
        <button type="button" className="iconbtn" onClick={onClose} title="Back to the conversation">
          ×
        </button>
      </div>
      {error ? <div className="chat-note">{error}</div> : null}
      {rows && rows.length === 0 ? <div className="chat-note">No conversations yet.</div> : null}
      {rows === null && !error ? <div className="chat-note">Loading…</div> : null}
      {rows?.map((row) => (
        <div
          key={row.conversation_id}
          className={`chat-hist-row${row.conversation_id === currentId ? " cur" : ""}`}
        >
          <button type="button" className="open" onClick={() => onOpen(row.conversation_id)}>
            <span className="t">{row.title || "Untitled conversation"}</span>
            {row.last_message_preview ? <span className="p">{row.last_message_preview}</span> : null}
            <span className="w">
              {when(row.updated_at)} · {row.message_count} {row.message_count === 1 ? "message" : "messages"}
            </span>
          </button>
          <button type="button" className="iconbtn" title="Delete conversation" onClick={() => remove(row)}>
            🗑
          </button>
        </div>
      ))}
    </div>
  );
}
