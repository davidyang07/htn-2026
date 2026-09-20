"""A deliberately naive instruction-follower.

This is the stand-in for a model's instruction-following, used when no model
endpoint is configured (see `workswarm/config.py`). It reads a document and
returns the file paths that document instructs its reader to fetch.

It is *supposed* to be susceptible. That is the whole point: an indirect
prompt injection works by getting a reader to treat content as instruction,
and this reproduces that failure without a model so the demo's enforcement
path can be exercised end to end. What it is not is a script of the demo --
nothing here names `demo_target/secrets/demo_secret.txt`. Edit the poisoned
paragraph to name a different path and it asks for that one; delete the
paragraph and it asks for nothing.

Deliberately free of any WorkSwarm import, so the interesting half of the
bridge stays testable without the engine.
"""

from __future__ import annotations

import re

#: A path-shaped token: at least one directory separator and a file extension.
PATH_RE = re.compile(r"(?<![\w./\\-])((?:\.{1,2}[/\\])?[\w.-]+(?:[/\\][\w.-]+)+\.[A-Za-z0-9]+)")

#: Phrases that read as an instruction addressed to the reader. A document
#: containing none of these produces no extra requests at all.
DIRECTIVE_CUES = (
    "you must",
    "before producing",
    "add the following",
    "include its contents",
    "requested_files",
    "required step",
    "checklist",
    "list all",
    "attach the",
    "therefore",
    "obtain the",
    "retrieve the",
)

#: How far *either side* of a directive cue to look for the path it refers to.
#: Both directions on purpose: a numbered checklist names the file on the item
#: line and puts the instruction underneath, so a forward-only window misses
#: exactly the shape of instruction that is easiest to follow.
DIRECTIVE_WINDOW = 600


def follow_document_instructions(document: str) -> list[str]:
    """Extract the file paths a document instructs its reader to fetch.

    Reads only the text it was given; it opens nothing. Order is stable and
    duplicates are collapsed, so the same document always yields the same
    request list.
    """
    if not document:
        return []

    lowered = document.lower()
    requested: list[str] = []

    for cue in DIRECTIVE_CUES:
        start = 0
        while True:
            index = lowered.find(cue, start)
            if index == -1:
                break
            window = document[
                max(0, index - DIRECTIVE_WINDOW) : index + DIRECTIVE_WINDOW
            ]
            for path in PATH_RE.findall(window):
                normalized = path.replace("\\", "/")
                if normalized not in requested:
                    requested.append(normalized)
            start = index + len(cue)

    return requested
