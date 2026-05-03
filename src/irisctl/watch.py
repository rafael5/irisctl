"""Polling loop for `--watch` flags.

A runner is any callable returning an envelope. Each iteration prints
one envelope on its own line (JSON) or a separator-delimited block
(human). KeyboardInterrupt exits cleanly with the last envelope.
"""

from __future__ import annotations

import sys
import time
from typing import IO, Any, Callable

from irisctl.output import render_human, render_json


def watch_loop(
    runner: Callable[[], dict[str, Any]],
    *,
    interval: float = 5.0,
    max_iters: int | None = None,
    out: IO[str] | None = None,
    render: str = "json",
    pretty: bool = False,
) -> dict[str, Any] | None:
    """Run `runner()` every `interval` seconds, printing the envelope each time.

    Stops after `max_iters` iterations (None = forever) or on
    KeyboardInterrupt. Returns the last envelope produced.
    """
    sink = out if out is not None else sys.stdout
    last: dict[str, Any] | None = None
    i = 0
    try:
        while True:
            i += 1
            try:
                env = runner()
            except KeyboardInterrupt:
                break
            last = env
            if render == "human":
                sink.write(render_human(env) + "\n---\n")
            else:
                sink.write(render_json(env, pretty=pretty) + "\n")
            sink.flush()
            if max_iters is not None and i >= max_iters:
                break
            try:
                time.sleep(interval)
            except KeyboardInterrupt:
                break
    except KeyboardInterrupt:
        pass
    return last
