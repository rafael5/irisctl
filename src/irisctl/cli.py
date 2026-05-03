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
from pathlib import Path
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
    from irisctl.commands import alerts as cmd_alerts
    from irisctl.commands import exec_cmd as cmd_exec
    from irisctl.commands import health as cmd_health
    from irisctl.commands import license as cmd_license
    from irisctl.commands import logs as cmd_logs
    from irisctl.commands import metrics as cmd_metrics
    from irisctl.commands import namespaces as cmd_namespaces
    from irisctl.commands import ports as cmd_ports
    from irisctl.commands import shell as cmd_shell
    from irisctl.commands import source as cmd_source
    from irisctl.commands import sql as cmd_sql
    from irisctl.commands import status as cmd_status
    from irisctl.commands import version as cmd_version

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

    # exec — Phase 2
    p = _sub("exec", help="Run ObjectScript via iris session (1 LU per call)")
    p.add_argument("script", nargs="?", default=None,
                   help="Inline ObjectScript (omit when using --file or --stdin)")
    p.add_argument("--ns", "--namespace", dest="ns", default="%SYS",
                   help="IRIS namespace (default: %%SYS)")
    p.add_argument("--file", type=Path, default=None,
                   help="Read script from a file")
    p.add_argument("--stdin", action="store_true",
                   help="Read script from standard input")
    p.add_argument("--force", action="store_true",
                   help="Skip the license pre-check")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="Subprocess timeout in seconds (default 60)")
    p.set_defaults(func=lambda a, prof: cmd_exec.run(
        prof,
        namespace=a.ns,
        script=a.script,
        stdin_text=sys.stdin.read() if a.stdin else None,
        file=a.file,
        force=a.force,
        timeout=a.timeout,
    ))

    # sql — Phase 2
    p = _sub("sql", help="Run a SQL statement, return rows as JSON (1 LU per call)")
    p.add_argument("statement", nargs="?", default=None,
                   help="Inline SQL (omit when using --file)")
    p.add_argument("--ns", "--namespace", dest="ns", default="USER",
                   help="IRIS namespace (default: USER)")
    p.add_argument("--file", type=Path, default=None,
                   help="Read SQL from a file")
    p.add_argument("--force", action="store_true",
                   help="Skip the license pre-check")
    p.add_argument("--timeout", type=float, default=60.0,
                   help="Subprocess timeout in seconds (default 60)")
    p.set_defaults(func=lambda a, prof: cmd_sql.run(
        prof,
        namespace=a.ns,
        statement=a.statement,
        file=a.file,
        force=a.force,
        timeout=a.timeout,
    ))

    # shell — Phase 2 (replaces process; --dry-run for inspection)
    p = _sub("shell", help="Open an interactive iris session (consumes 1 LU)")
    p.add_argument("--ns", "--namespace", dest="ns", default="%SYS",
                   help="IRIS namespace (default: %%SYS)")
    p.add_argument("--force", action="store_true",
                   help="Bypass the license pre-check")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the docker-exec argv instead of execing")
    p.set_defaults(func=lambda a, prof: cmd_shell.run(
        prof, namespace=a.ns, force=a.force, dry_run=a.dry_run,
    ))

    # namespaces — Phase 3
    p = _sub("namespaces", help="List IRIS namespaces (Atelier GetServer)")
    p.set_defaults(func=lambda a, prof: cmd_namespaces.run(prof))

    # source — Phase 3 (sub-verbs)
    p_src = _sub("source", help="Source-code CRUD via Atelier")
    src_sub = p_src.add_subparsers(dest="source_sub", required=False,
                                   metavar="ACTION")

    p_list = src_sub.add_parser("list", parents=[globals_parent],
                                help="List documents in a namespace")
    p_list.add_argument("namespace")
    p_list.add_argument("pattern", nargs="?", default=None,
                        help="Filter pattern (Atelier filter syntax)")
    p_list.add_argument("--type", default=None,
                        help="Document type filter (e.g. CLS, MAC, INT)")
    p_list.set_defaults(source_sub="list")

    p_get = src_sub.add_parser("get", parents=[globals_parent],
                               help="Get a document's source")
    p_get.add_argument("namespace")
    p_get.add_argument("doc")
    p_get.set_defaults(source_sub="get")

    p_put = src_sub.add_parser("put", parents=[globals_parent],
                               help="Upsert a document (file or stdin)")
    p_put.add_argument("namespace")
    p_put.add_argument("doc")
    p_put.add_argument("--file", type=Path, default=None)
    p_put.add_argument("--stdin", action="store_true",
                       help="Read content from stdin")
    p_put.set_defaults(source_sub="put")

    p_del = src_sub.add_parser("delete", parents=[globals_parent],
                               help="Delete a document")
    p_del.add_argument("namespace")
    p_del.add_argument("doc")
    p_del.set_defaults(source_sub="delete")

    p_comp = src_sub.add_parser("compile", parents=[globals_parent],
                                help="Compile one or more documents")
    p_comp.add_argument("namespace")
    p_comp.add_argument("docs", nargs="+", help="One or more doc names")
    p_comp.add_argument("--flags", default="ck", help="Compile flags (default ck)")
    p_comp.set_defaults(source_sub="compile")

    def _source_run(a, prof):
        if getattr(a, "source_sub", None) == "put" and a.stdin:
            a.stdin_text = sys.stdin.read()
        return cmd_source.dispatch(a, prof)
    p_src.set_defaults(func=_source_run)

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
