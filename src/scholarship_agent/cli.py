"""Command line entry points."""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser
from pathlib import Path

from scholarship_agent.agent import RunReport
from scholarship_agent.logging_config import configure_logging
from scholarship_agent.runtime import load_runtime


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="scholarship-agent",
        description="Collect academic opportunities and deliver a separate digest to each person.",
    )
    parser.add_argument("--config", default="config/settings.yaml", help="Path to settings.yaml")
    parser.add_argument("--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Collect, match, and deliver")
    run.add_argument("--dry-run", action="store_true", help="Match and print, then discard the run")
    run.add_argument("--loop", action="store_true", help="Keep running on the configured interval")
    run.add_argument("--interval-hours", type=float, default=None)

    commands.add_parser("check", help="Read each enabled feed and print how many items came back")
    commands.add_parser("profiles", help="Show the configured people and what they receive")
    serve = commands.add_parser("serve", help="Open the saved matches in a local web page")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true", help="Do not open a browser window")

    args = parser.parse_args(argv)
    config_path = Path(args.config)
    runtime = load_runtime(config_path)
    configure_logging(runtime.settings.log_dir, verbose=args.verbose)
    try:
        if args.command == "profiles":
            _print_profiles(runtime)
            return 0
        if args.command == "check":
            return _check(runtime)
        if args.command == "serve":
            return _serve(runtime, args)
        return _run(runtime, args)
    finally:
        runtime.close()


def _run(runtime, args) -> int:
    interval = args.interval_hours or runtime.settings.schedule.interval_hours
    try:
        while True:
            report = runtime.agent.run(dry_run=args.dry_run)
            _print_report(report)
            if not args.loop:
                return 1 if report.source_errors and report.sources_ok == 0 else 0
            print(f"Sleeping for {interval} hours. Stop with Ctrl+C.")
            time.sleep(interval * 3600)
    except KeyboardInterrupt:
        print("Stopped.")
        return 0


def _serve(runtime, args) -> int:
    from scholarship_agent.site import serve

    url = f"http://{args.host}:{args.port}/browse?degree=all&country=all"
    print(f"Matches are at {url}", flush=True)
    print("Stop with Ctrl+C.", flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        serve(runtime.profiles, runtime.repository, runtime.departments, args.host, args.port)
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


def _check(runtime) -> int:
    failed = False
    for source_id, count, error in runtime.agent.check():
        if error:
            failed = True
            print(f"{source_id}: FAILED {error}")
        else:
            print(f"{source_id}: {count} item(s)")
    return 1 if failed else 0


def _print_profiles(runtime) -> None:
    for profile in runtime.profiles:
        countries = ", ".join(profile.countries) or "worldwide"
        disciplines = ", ".join(profile.disciplines) or "all fields"
        routes = []
        if runtime.settings.delivery.write_digest_files:
            routes.append(f"files in {runtime.settings.digests_dir}")
        if runtime.settings.delivery.email.enabled and profile.resolved_email:
            routes.append(f"email {profile.resolved_email}")
        if runtime.settings.delivery.telegram.enabled and profile.resolved_telegram_chat_id:
            routes.append("telegram")
        print(
            f"{profile.display_name} [{profile.id}]\n"
            f"  degrees: {', '.join(profile.degree_levels)}\n"
            f"  types: {', '.join(profile.opportunity_types)}\n"
            f"  places: {countries}\n"
            f"  fields: {disciplines}\n"
            f"  delivery: {', '.join(routes) or 'log only'}"
        )


def _print_report(report: RunReport) -> None:
    label = "Dry run" if report.dry_run else "Run"
    print(
        f"{label}: {report.sources_ok} source(s) ok, {len(report.source_errors)} failed, "
        f"{report.fetched} item(s) read, {report.changed} new or updated, "
        f"{report.delivered} delivered."
    )
    for line in report.previews:
        print(f"  {line}")
    for error in report.source_errors:
        print(f"  error: {error}")


if __name__ == "__main__":
    raise SystemExit(main())
