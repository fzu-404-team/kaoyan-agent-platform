"""Progressive delivery of an already validated answer on the conversation stream."""

import asyncio
import re
from collections.abc import Awaitable, Callable

# Java authorizes every delta with a database read, so the count stays small.
MAX_SEGMENTS = 24
# Total pause across all segments; the stream runs after the task timeout.
REPLAY_SECONDS = 1.0
SLOT = "answer"
# A piece ends after a line break or a sentence-final mark (keeping the mark).
PIECE = re.compile(r"[^\n。！？!?；;]*(?:[\n。！？!?；;]+|$)")

Sink = Callable[[dict], Awaitable[None]]


def segments(text: str, limit: int = MAX_SEGMENTS) -> list[str]:
    """Split at line and sentence ends, then merge into at most ``limit`` pieces.

    Joining the result always reproduces ``text`` exactly; nothing is trimmed.
    """
    pieces = [piece for piece in PIECE.findall(text) if piece]
    if len(pieces) <= limit:
        return pieces
    target = len(text) / limit
    merged: list[str] = []
    current = ""
    for piece in pieces:
        current += piece
        if len(current) >= target and len(merged) < limit - 1:
            merged.append(current)
            current = ""
    if current:
        merged.append(current)
    return merged


async def replay_answer(sink: Sink, text: str, seconds: float = REPLAY_SECONDS) -> int:
    """Send validated text as consecutive ``answer`` deltas; return the delta count.

    Offsets count Unicode code points (Python ``len``), matching the Java
    consumer. Only text that already passed result validation may be passed in.
    """
    parts = segments(text)
    pause = seconds / len(parts) if parts else 0.0
    offset = 0
    for index, part in enumerate(parts):
        if index and pause:
            await asyncio.sleep(pause)
        await sink({"type": "delta", "slot": SLOT, "offset": offset, "text": part})
        offset += len(part)
    return len(parts)
