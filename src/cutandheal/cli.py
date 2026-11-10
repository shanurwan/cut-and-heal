"""Command line. Orchestration shells out to kubectl, so a run uses whatever cluster and
credentials the operator already has; nothing here needs a kubeconfig of its own."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .model import load_scenario
from .render import RenderOptions, render, to_yaml

DEFAULT_CONTROLLER_IMAGE = f"ghcr.io/shanurwan/cut-and-heal:{__version__}"


def _kubectl(*args: str, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["kubectl", *args], input=stdin, text=True, capture_output=True, check=check)


def _options(args: argparse.Namespace) -> RenderOptions:
    return RenderOptions(
        namespace=args.namespace,
        run_id=args.run_id,
        seed=args.seed,
        controller_image=args.controller_image,
        metrics=not args.no_metrics,
    )


def cmd_validate(args: argparse.Namespace) -> int:
    scn = load_scenario(args.scenario)
    print(f"{scn.name}: {scn.total_nodes} nodes in {len(scn.regions)} regions, {scn.duration_s}s")
    for phase in scn.timeline:
        state = ", ".join(
            f"{b}: {scn.open_count(phase, b)}/{scn.regions[scn.borders[b].gated].nodes} open" for b in scn.borders
        )
        print(f"  {phase.name:<16} {phase.duration_s:>5}s  {state}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    scn = load_scenario(args.scenario)
    sys.stdout.write(to_yaml(render(scn, _options(args), Path(args.scenario).read_text(encoding="utf-8"))))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    scn = load_scenario(args.scenario)
    out = Path(args.out) / args.run_id
    if out.exists():
        print(f"{out} already exists; a run never overwrites another run's evidence", file=sys.stderr)
        return 2
    manifests = to_yaml(render(scn, _options(args), Path(args.scenario).read_text(encoding="utf-8")))
    ns = args.namespace
    if _kubectl("get", "namespace", ns, check=False).returncode == 0:
        print(f"namespace {ns} exists; delete it or pick another, runs do not share state", file=sys.stderr)
        return 2
    _kubectl("apply", "-f", "-", stdin=manifests)
    budget = scn.duration_s + 1800
    deadline = time.monotonic() + budget
    stage = ""
    status = ""
    while time.monotonic() < deadline:
        done = _kubectl("exec", "-n", ns, "controller", "--", "cat", "/results/DONE", check=False)
        if done.returncode == 0:
            status = done.stdout.strip()
            break
        st = _kubectl(
            "exec",
            "-n",
            ns,
            "controller",
            "--",
            "python",
            "-c",
            "import urllib.request as u;print(u.urlopen('http://127.0.0.1:8080/v1/status').read().decode())",
            check=False,
        )
        now = st.stdout.strip() if st.returncode == 0 else "controller not up yet"
        if now != stage:
            stage = now
            print(time.strftime("%H:%M:%S"), stage, flush=True)
        time.sleep(10)
    else:
        print(f"no result after {budget}s; leaving namespace {ns} in place for inspection", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    _kubectl("cp", f"{ns}/controller:/results", str(out))
    (out / "manifests.yaml").write_text(manifests, encoding="utf-8")
    print(f"run {args.run_id}: {status}; evidence in {out}")
    if not args.keep:
        _kubectl("delete", "namespace", ns, "--wait=true", check=False)
        _kubectl("delete", "clusterrole,clusterrolebinding", f"cut-and-heal-{ns}", check=False)
    return 0 if status == "completed" else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    from .analyze import Params, cells, delivery_series, summarise
    from .evidence import load_run
    from .validity import as_dicts, judge

    run = load_run(args.run)
    params = Params()
    summary = summarise(run, params)
    verdicts = judge(run, cells(run, params))
    summary["verdicts"] = as_dicts(verdicts)
    summary["valid"] = all(v.passed for v in verdicts)
    out = Path(args.run) / "analysis"
    out.mkdir(exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    series = delivery_series(run, params)
    if series:
        with (out / "delivery.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(series[0]))
            writer.writeheader()
            writer.writerows(series)
    for v in verdicts:
        print(f"{'pass' if v.passed else 'FAIL'}  {v.rule}  {v.title}\n      {v.detail}")
    print(f"\n{'VALID' if summary['valid'] else 'INVALID'}: {len(run.messages)} messages")
    if summary["valid"] or args.show_invalid:
        for c in summary["cells"]:
            if c["window"] == "steady" and c["pairs"]:
                ci = f"[{c['ci_low']:.3f}, {c['ci_high']:.3f}]" if c["ci_low"] is not None else ""
                print(
                    f"  {c['phase']:<16} {c['src']:>6} -> {c['dst']:<6} {'path' if c['path_exists'] else 'none':<5}"
                    f" {c['ratio']:.4f} {ci:<16} p50 {c['p50_ms']} ms  p99 {c['p99_ms']} ms"
                )
    return 0 if summary["valid"] else 1


def cmd_report(args: argparse.Namespace) -> int:
    from .report import write_report

    print(write_report([Path(r) for r in args.runs], Path(args.out)))
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    from .trace import fetch_ioda, segment

    series = fetch_ioda(args.country, args.start, args.end, args.baseline_days)
    for seg in segment(series, levels=tuple(args.levels)):
        print(json.dumps(asdict(seg)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cah", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def scenario_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("scenario")
        p.add_argument("--namespace", default="cah")
        p.add_argument("--run-id", default=time.strftime("%Y%m%dT%H%M%S"))
        p.add_argument("--seed", type=int, default=1)
        p.add_argument("--controller-image", default=DEFAULT_CONTROLLER_IMAGE)
        p.add_argument("--no-metrics", action="store_true")

    p = sub.add_parser("validate", help="check a scenario and print its timeline")
    p.add_argument("scenario")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("render", help="print the Kubernetes manifests for a run")
    scenario_args(p)
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("run", help="deploy, run the timeline, copy the evidence out, clean up")
    scenario_args(p)
    p.add_argument("--out", default="runs")
    p.add_argument("--keep", action="store_true", help="leave the namespace in place afterwards")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("analyze", help="judge a run's validity and compute its results")
    p.add_argument("run")
    p.add_argument("--show-invalid", action="store_true", help="print numbers even if the run is invalid")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("report", help="write a report across replicate runs")
    p.add_argument("runs", nargs="+")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("trace", help="segment a public outage signal into availability levels")
    p.add_argument("--country", required=True, help="ISO 3166-1 alpha-2, e.g. IR")
    p.add_argument("--start", required=True, help="UTC, e.g. 2019-11-14")
    p.add_argument("--end", required=True)
    p.add_argument("--baseline-days", type=int, default=2)
    p.add_argument("--levels", type=float, nargs="+", default=[0.0, 0.02, 0.1, 0.5, 1.0])
    p.set_defaults(fn=cmd_trace)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
