"use client";

/** Round E 6.1 / 6.8 — mounts the chat on every page (layout.tsx).
 *
 * Flag `global.chat` OFF renders NEITHER the panel NOR the floating pill
 * (the backend 409s independently — 6.8's hard gate). Open/closed and the
 * current conversation persist in localStorage so reopening restores the
 * conversation. A `?chat=<conversation_id>` URL param (Subagent C's trace
 * screen links here) opens the panel on that conversation.
 */

import { useEffect, useState } from "react";
import { useFlag } from "@/lib/flags";
import ChatPanel from "@/components/chat/ChatPanel";

const LS_OPEN = "chat.open";
const LS_CONV = "chat.conversation_id";

export default function ChatDock() {
  const chatOn = useFlag("global.chat");
  const [ready, setReady] = useState(false); // after localStorage/url read
  const [open, setOpen] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);

  // Restore persisted state, then honour ?chat=<id> (deep link wins).
  useEffect(() => {
    try {
      const storedOpen = window.localStorage.getItem(LS_OPEN) === "1";
      const storedConv = window.localStorage.getItem(LS_CONV);
      const deepLink = new URLSearchParams(window.location.search).get("chat");
      if (deepLink) {
        setConversationId(deepLink);
        setOpen(true);
        window.localStorage.setItem(LS_CONV, deepLink);
        window.localStorage.setItem(LS_OPEN, "1");
      } else {
        setConversationId(storedConv || null);
        setOpen(storedOpen);
      }
    } catch {
      /* storage unavailable — session-only state */
    }
    setReady(true);
  }, []);

  // Page content shifts left while the panel is docked.
  useEffect(() => {
    const on = Boolean(open && chatOn === true);
    document.body.classList.toggle("chat-open", on);
    return () => document.body.classList.remove("chat-open");
  }, [open, chatOn]);

  const setOpenPersist = (v: boolean) => {
    setOpen(v);
    try {
      window.localStorage.setItem(LS_OPEN, v ? "1" : "0");
    } catch {
      /* ignore */
    }
  };
  const setConvPersist = (id: string | null) => {
    setConversationId(id);
    try {
      if (id) window.localStorage.setItem(LS_CONV, id);
      else window.localStorage.removeItem(LS_CONV);
    } catch {
      /* ignore */
    }
  };

  // Flag off (or still loading) → nothing at all, panel or pill (6.8).
  if (chatOn !== true || !ready) return null;

  if (!open) {
    return (
      <button type="button" className="chat-dock" onClick={() => setOpenPersist(true)}>
        💬 Ask Connect Coach
      </button>
    );
  }
  return (
    <ChatPanel
      conversationId={conversationId}
      onConversationChange={setConvPersist}
      onClose={() => setOpenPersist(false)}
    />
  );
}
