"""Provider-neutral prompt-cache marking (Round H task 3).

Agents never emit a provider-specific cache parameter. A block that is part of
the static prefix carries ``"stable": True`` — a provider-neutral flag — and
each ADAPTER decides what that means on its wire:

- Claude adapter   → ``claude_cache_blocks``: replaces the flag with
  ``cache_control: {"type": "ephemeral"}`` (byte-identical to the pre-Round-H
  wire format, so the Round E two-static-anchor economics are unchanged).
- cdao / Azure OpenAI adapters → ``strip_stable_flags``: removes the flag and
  sends the text untouched. There is no cache parameter on that wire; OpenAI
  prefix caching is AUTOMATIC, so the only requirement is that the stable
  prefix stays byte-identical turn over turn — which stripping a key from the
  block dict (never touching ``text``) preserves.
- Mock adapter     → ignores the flag entirely (single-string path).

The Round E invariant is unchanged: EXACTLY TWO stable blocks (system +
opening), byte-identical every turn — the flag moved, not the anchors.
"""
from __future__ import annotations

STABLE_FLAG = "stable"


def claude_cache_blocks(blocks: list[dict]) -> list[dict]:
    """Claude wire format: each ``stable: True`` block becomes a
    ``cache_control: {"type": "ephemeral"}`` block; other blocks pass through
    unchanged. Always returns new dicts — caller structures are never mutated."""
    out = []
    for block in blocks:
        block = dict(block)
        if block.pop(STABLE_FLAG, False):
            block["cache_control"] = {"type": "ephemeral"}
        out.append(block)
    return out


def claude_wire(system_blocks: list[dict],
                messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Translate a stable-flagged conversation to the exact structures the
    Anthropic SDK is called with (system blocks + messages)."""
    wire_messages = [
        {**m, "content": claude_cache_blocks(m["content"])}
        if isinstance(m.get("content"), list) else dict(m)
        for m in messages
    ]
    return claude_cache_blocks(system_blocks), wire_messages


def strip_stable_flags(blocks: list[dict]) -> list[dict]:
    """OpenAI-shaped wire (cdao / Azure): drop the flag, keep every ``text``
    byte-identical so automatic prefix caching can engage on the stable prefix."""
    out = []
    for block in blocks:
        block = dict(block)
        block.pop(STABLE_FLAG, None)
        out.append(block)
    return out


def openai_chat_messages(system_blocks: list[dict],
                         messages: list[dict]) -> list[dict]:
    """Flatten a stable-flagged conversation to OpenAI chat-completions
    messages. Text blocks within one message join with a fixed separator, so
    as long as the caller's stable prefix is byte-identical each turn, the
    flattened request prefix is too — the condition for OpenAI's automatic
    prefix caching (no cache parameter exists on this wire)."""
    chat: list[dict] = [{
        "role": "system",
        "content": "\n\n".join(b.get("text", "")
                               for b in strip_stable_flags(system_blocks)),
    }]
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            text = "\n\n".join(b.get("text", "")
                               for b in strip_stable_flags(content))
        else:
            text = str(content or "")
        chat.append({"role": message["role"], "content": text})
    return chat
