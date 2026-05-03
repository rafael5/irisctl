"""irisctl CLI entry point.

Usage:
    irisctl [global flags] <subcommand> [subcommand args]

Global flags:
    --profile NAME       Select a profile from ~/.config/irisctl/config.toml
    --json               Force JSON output (default)
    --human              Render envelope as a human-readable table
    --pretty             Pretty-print JSON output

Phase 1 subcommands: license, metrics, alerts, status, version, ports,
logs, health.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Callable

from irisctl import __version__
from irisctl.config import load_profile
from irisctl.output import (
    ErrorCode,
    error_envelope,
    exit_code_for,
    render_human,
    render_json,
)

log = logging.getLogger(__name__)


# Each command exposes a `register` and a `run` function. `register`
# adds its subparser + sets `func`. `run` is what the dispatch calls.
CommandRunner = Callable[..., dict[str, Any]]


def _emit(envelope: dict[str, Any], *, args: argparse.Namespace) -> int:
    if getattr(args, "human", False):
        sys.stdout.write(render_human(envelope) + "\n")
    else:
        sys.stdout.write(render_json(envelope, pretty=args.pretty) + "\n")
    sys.stdout.flush()
    if envelope["ok"]:
        return exit_code_for(ErrorCode.OK)
    code = ErrorCode(envelope["error"]["code"])
    return exit_code_for(code)


def _add_global_flags(p: argparse.ArgumentParser) -> None:
    # default=SUPPRESS so subparsers don't overwrite values set on the
    # top-level parser (and vice-versa). The runtime default lives in
    # main() via getattr(args, name, default).
    p.add_argument("--profile", default=argparse.SUPPRESS,
                   help="Profile name from ~/.config/irisctl/config.toml")
    out = p.add_mutually_exclusive_group()
    out.add_argument("--json", dest="human", action="store_false",
                     default=argparse.SUPPRESS, help="JSON output (default)")
    out.add_argument("--human", dest="human", action="store_true",
                     default=argparse.SUPPRESS,
                     help="Human-readable table output")
    p.add_argument("--pretty", action="store_true",
                   default=argparse.SUPPRESS,
                   help="Pretty-print JSON output")


def _build_parser() -> argparse.ArgumentParser:
    # Parent holding global flags so they can appear on the top-level
    # OR on any subcommand (e.g. `irisctl license --human` is valid).
    globals_parent = argparse.ArgumentParser(add_help=False)
    _add_global_flags(globals_parent)

    parser = argparse.ArgumentParser(
        prog="irisctl",
        description=(
            "Programmer/AI-friendly CLI for "
            "InterSystems IRIS Community Docker containers."
        ),
        parents=[globals_parent],
    )
    parser.add_argument("--version", action="version", version=f"irisctl {__version__}")

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # Lazy import to keep startup fast
    from irisctl.commands import (
        alerts as cmd_alerts,
    )
    from irisctl.commands import (
        health as cmd_health,
    )
    from irisctl.commands import (
        license as cmd_license,
    )
    from irisctl.commands import (
        logs as cmd_logs,
    )
    from irisctl.commands import (
        metrics as cmd_metrics,
    )
    from irisctl.commands import (
        ports as cmd_ports,
    )
    from irisctl.commands import (
        status as cmd_status,
    )
    from irisctl.commands import (
        version as cmd_version,
    )

    def _sub(name: str, **kw):
        p = sub.add_parser(name, parents=[globals_parent], **kw)
        return p

    # license
    p = _sub("license", help="Current license-unit consumption")
    p.set_defaults(func=lambda a, prof: cmd_license.run(prof))

    # metrics
    p = _sub("metrics", help="Read /api/monitor/metrics counters")
    p.add_argument("--prefix", default=None,
                   help="Filter to metrics whose name begins with PREFIX")
    msub = p.add_subparsers(dest="metrics_sub", required=False)
    p_describe = msub.add_parser("describe", parents=[globals_parent],
                                 help="Show one metric in detail")
    p_describe.add_argument("name")
    p_describe.set_defaults(metrics_sub="describe")
    p_scrape = msub.add_parser("scrape", parents=[globals_parent],
                               help="Raw Prometheus text")
    p_scrape.set_defaults(metrics_sub="scrape")
    p.set_defaults(func=lambda a, prof: cmd_metrics.dispatch(a, prof))

    # alerts
    p = _sub("alerts", help="Read /api/monitor/alerts")
    p.set_defaults(func=lambda a, prof: cmd_alerts.run(prof))

    # version
    p = _sub("version", help="IRIS engine + image version info")
    p.set_defaults(func=lambda a, prof: cmd_version.run(prof))

    # ports
    p = _sub("ports", help="Per-listener reachability check")
    p.set_defaults(func=lambda a, prof: cmd_ports.run(prof))

    # logs
    p = _sub("logs", help="Tail messages.log via host helper")
    p.add_argument("--tail", type=int, default=200,
                   help="Lines to return (default 200)")
    p.set_defaults(func=lambda a, prof: cmd_logs.run(prof, tail=a.tail))

    # status
    p = _sub("status", help="Composite container + listener + license check")
    p.set_defaults(func=lambda a, prof: cmd_status.run(prof))

    # health
    p = _sub("health", help="Composite health verdict (status + ports + alerts)")
    p.set_defaults(func=lambda a, prof: cmd_health.run(prof))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    # SUPPRESS-defaults: backfill the runtime defaults here.
    args.profile = getattr(args, "profile", None)
    args.human = getattr(args, "human", False)
    args.pretty = getattr(args, "pretty", False)
    try:
        profile = load_profile(profile=args.profile)
    except KeyError as e:
        env = error_envelope(args.command or "irisctl",
                             code=ErrorCode.USAGE,
                             message=str(e))
        return _emit(env, args=args)

    try:
        envelope = args.func(args, profile)
    except Exception as e:  # pragma: no cover — last-resort safety net
        log.exception("internal error")
        envelope = error_envelope(
            args.command or "irisctl",
            code=ErrorCode.INTERNAL,
            message=f"{type(e).__name__}: {e}",
        )
    return _emit(envelope, args=args)


if __name__ == "__main__":
    sys.exit(main())
