"""Deterministic context compression preserving tool-call/result pairing."""

import copy
import json


def message_bytes(messages):
    return len(json.dumps(messages, ensure_ascii=False).encode())


def compact_messages(messages, limit):
    """Bound old tool results, retaining the latest round and the full disk trace.

    This intentionally performs no additional model calls. It is a selectable
    strategy for controlled comparisons, not a claim of improved solve rate.
    """
    compacted = copy.deepcopy(messages)
    before = message_bytes(compacted)
    if before <= limit * 0.7:
        return compacted, {
            "before_bytes": before,
            "after_bytes": before,
            "trimmed_results": 0,
        }
    latest_assistant = max(
        (i for i, message in enumerate(compacted) if message["role"] == "assistant"),
        default=len(compacted),
    )
    trimmed = 0
    for index, message in enumerate(compacted):
        if index >= latest_assistant or message["role"] != "tool":
            continue
        content = message.get("content", "")
        if len(content.encode()) <= 2400:
            continue
        # Preserve the beginning (command/error context) and tail (test summary).
        head = content.encode()[:600].decode(errors="replace")
        tail = content.encode()[-1400:].decode(errors="replace")
        message["content"] = (
            head
            + "\n[older output shortened; rerun source inspection if needed; full controller trace retained for review]\n"
            + tail
        )
        trimmed += 1
    return compacted, {
        "before_bytes": before,
        "after_bytes": message_bytes(compacted),
        "trimmed_results": trimmed,
    }
