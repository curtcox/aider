#!/usr/bin/env python3
"""Convenience wrapper for reproducible Aider Polyglot benchmark runs."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "runs"
DEFAULT_SMOKE_TESTS = 3
DEFAULT_EXERCISES_DIR = None
DEFAULT_EXERCISES_DIR_NAME = "polyglot-benchmark"
SMOKE_EXERCISES_PARENT = "smoke-exercises"
HOST_EXECUTION_WARNING = "benchmarking runs unvetted code from GPT, run in a docker container"


def benchmark_dir():
    return Path(os.environ.get("AIDER_BENCHMARK_DIR", "tmp.benchmarks"))


def candidate_exercises_dirs():
    return [
        Path(DEFAULT_EXERCISES_DIR_NAME),
        Path("benchmark") / DEFAULT_EXERCISES_DIR_NAME,
        Path("tmp.benchmarks") / DEFAULT_EXERCISES_DIR_NAME,
        Path("/benchmarks") / DEFAULT_EXERCISES_DIR_NAME,
    ]


def resolve_exercises_dir(exercises_dir=None):
    """Return the path to pass to benchmark.py and the existing source root."""
    if exercises_dir:
        path = Path(exercises_dir).expanduser()
        resolved = path if path.is_absolute() else Path.cwd() / path
        if resolved.exists() and resolved.is_dir():
            return str(resolved), resolved
        raise FileNotFoundError(exercises_dir_missing_message([resolved], explicit=True))

    checked = []
    for candidate in candidate_exercises_dirs():
        checked.append(candidate)
        if candidate.exists() and candidate.is_dir():
            resolved = candidate.resolve()
            return str(resolved), resolved

    raise FileNotFoundError(exercises_dir_missing_message(checked, explicit=False))


def exercises_dir_missing_message(checked_paths, explicit=False):
    checked = "\n".join(f"  - {path}" for path in checked_paths)
    supplied = (
        "The configured --exercises-dir was not found."
        if explicit
        else "No polyglot-benchmark directory was found."
    )
    return (
        f"{supplied}\n"
        "\n"
        "Checked paths:\n"
        f"{checked}\n"
        "\n"
        "Prepare the Polyglot benchmark data with:\n"
        "  python3 benchmark/prepare_polyglot.py\n"
        "\n"
        "Pass an explicit path with --exercises-dir, for example:\n"
        "  python3 benchmark/run_baseline.py --dry-run --run-name smoke "
        "--smoke --exercises-dir tmp.benchmarks/polyglot-benchmark\n"
        "\n"
        "Inside Docker, benchmark/docker.sh mounts host tmp.benchmarks at /benchmarks, "
        "so /benchmarks/polyglot-benchmark should exist when the host checkout exists.\n"
        "\n"
        "No API call was made because the exercises directory was missing."
    )


def discover_exercise_paths(exercises_root):
    """Return deterministic language/exercise paths for a polyglot exercises tree."""
    exercises_root = Path(exercises_root)
    paths = []
    for language_dir in sorted((p for p in exercises_root.iterdir() if p.is_dir()), key=lambda p: p.name):
        practice_dir = language_dir / "exercises" / "practice"
        if not practice_dir.exists():
            continue
        for exercise_dir in sorted((p for p in practice_dir.iterdir() if p.is_dir()), key=lambda p: p.name):
            paths.append(exercise_dir.relative_to(exercises_root))
    return paths


def validate_discoverable_exercises(exercises_root, languages=None):
    """Validate a tree using benchmark.py's exercise discovery layout.

    benchmark.py discovers tasks by looking for language directories directly
    under --exercises-dir, then for <language>/exercises/practice/<exercise>
    directories. It does not require README files or metadata for discovery.
    """
    exercises_root = Path(exercises_root)
    problems = []
    if not exercises_root.exists():
        return [], [f"exercises directory does not exist: {exercises_root}"]
    if not exercises_root.is_dir():
        return [], [f"exercises path is not a directory: {exercises_root}"]

    language_dirs = sorted((p for p in exercises_root.iterdir() if p.is_dir()), key=lambda p: p.name)
    if languages:
        requested = {lang.strip().lower() for lang in languages.split(",") if lang.strip()}
        language_dirs = [p for p in language_dirs if p.name.lower() in requested]
        if not language_dirs:
            problems.append(f"no matching language directories found for: {languages}")

    exercise_paths = []
    for language_dir in language_dirs:
        practice_dir = language_dir / "exercises" / "practice"
        if not practice_dir.exists():
            problems.append(f"missing practice directory: {practice_dir}")
            continue
        if not practice_dir.is_dir():
            problems.append(f"practice path is not a directory: {practice_dir}")
            continue
        exercise_paths.extend(
            exercise_dir.relative_to(exercises_root)
            for exercise_dir in sorted((p for p in practice_dir.iterdir() if p.is_dir()), key=lambda p: p.name)
        )

    if not exercise_paths:
        problems.append(
            "no discoverable exercises found; expected "
            "<language>/exercises/practice/<exercise> directories"
        )
    return exercise_paths, problems


def smoke_exercises_name(run_name):
    return f"{SMOKE_EXERCISES_PARENT}/{run_name}"


def prepare_smoke_exercises(args, run_dir, exercises_dir, source_root, dry_run=False):
    """Copy a small deterministic subset without mutating the source benchmark."""
    source_name = exercises_dir
    smoke_name = smoke_exercises_name(args.run_name)
    smoke_root = benchmark_dir() / smoke_name
    smoke_root_for_benchmark = smoke_root.resolve()
    smoke_size = args.smoke_size

    metadata = {
        "strategy": "copy-first-sorted-language-exercise-paths",
        "source_exercises_dir": source_name,
        "source_root": str(source_root),
        "smoke_exercises_dir": smoke_name,
        "smoke_root": str(smoke_root),
        "smoke_root_for_benchmark": str(smoke_root_for_benchmark),
        "smoke_size": str(smoke_size),
        "expected_tasks": str(smoke_size),
        "tasks": [],
    }

    selected = discover_exercise_paths(source_root)[:smoke_size]
    metadata["tasks"] = [path.as_posix() for path in selected]

    if not dry_run:
        if not selected:
            raise ValueError(f"No smoke exercises found under: {source_root}")
        if smoke_root.exists():
            shutil.rmtree(smoke_root)
        for rel_path in selected:
            src = source_root / rel_path
            dst = smoke_root / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)

    return str(smoke_root_for_benchmark), metadata


def build_benchmark_command(args, passthrough, exercises_dir=None):
    exercises_dir = exercises_dir or args.exercises_dir
    cmd = [
        sys.executable,
        "benchmark/benchmark.py",
        args.run_name,
        "--model",
        args.model,
        "--edit-format",
        args.edit_format,
        "--threads",
        str(args.threads),
        "--exercises-dir",
        exercises_dir,
        "--new",
    ]

    if args.limit:
        cmd.extend(["--num-tests", str(args.limit)])

    cmd.extend(passthrough)
    return cmd


def quote_command(cmd):
    return " ".join(subprocess.list2cmdline([part]) for part in cmd)


def git_metadata():
    def run_git(*args):
        try:
            return subprocess.check_output(
                ["git", *args],
                cwd=REPO_ROOT,
                stderr=subprocess.STDOUT,
                text=True,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError) as err:
            return f"unavailable: {err}"

    status = run_git("status", "--short")
    return {
        "branch": run_git("branch", "--show-current"),
        "commit": run_git("rev-parse", "HEAD"),
        "dirty": "yes" if status else "no",
        "status": status or "clean",
    }


def env_metadata(args):
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "model": args.model,
        "edit_format": args.edit_format,
        "threads": str(args.threads),
        "exercises_dir": getattr(args, "resolved_exercises_dir", None)
        or args.exercises_dir
        or DEFAULT_EXERCISES_DIR_NAME,
        "smoke": "yes" if args.smoke else "no",
        "smoke_size": str(args.smoke_size) if args.smoke else "",
        "limit": str(args.limit or ""),
        "benchmark_dir": str(benchmark_dir()),
        "aider_docker": "yes" if os.environ.get("AIDER_DOCKER") else "no",
        "openai_api_key_set": "yes" if os.environ.get("OPENAI_API_KEY") else "no",
    }


def write_key_values(path, values):
    lines = [f"{key}: {value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n")


def write_run_metadata(run_dir, cmd, args):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "command.txt").write_text(quote_command(cmd) + "\n")
    write_key_values(run_dir / "git.txt", git_metadata())
    write_key_values(run_dir / "env.txt", env_metadata(args))


def write_smoke_metadata(run_dir, smoke_metadata):
    lines = [
        f"strategy: {smoke_metadata['strategy']}",
        f"source_exercises_dir: {smoke_metadata['source_exercises_dir']}",
        f"source_root: {smoke_metadata['source_root']}",
        f"smoke_exercises_dir: {smoke_metadata['smoke_exercises_dir']}",
        f"smoke_root: {smoke_metadata['smoke_root']}",
        f"smoke_root_for_benchmark: {smoke_metadata['smoke_root_for_benchmark']}",
        f"smoke_size: {smoke_metadata['smoke_size']}",
        f"expected_tasks: {smoke_metadata['expected_tasks']}",
        "tasks:",
    ]
    lines.extend(f"- {task}" for task in smoke_metadata["tasks"])
    (run_dir / "smoke_tasks.txt").write_text("\n".join(lines) + "\n")
    (run_dir / "smoke_tasks.json").write_text(json.dumps(smoke_metadata, indent=2) + "\n")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Run a reproducible Aider Polyglot benchmark baseline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--run-name", required=True, help="Stable name for this benchmark run")
    parser.add_argument("--model", default="gpt-4.1-mini", help="Aider model name")
    parser.add_argument("--edit-format", default="diff", help="Aider edit format")
    parser.add_argument("--threads", type=int, default=1, help="Benchmark worker threads")
    parser.add_argument(
        "--exercises-dir",
        default=DEFAULT_EXERCISES_DIR,
        help=(
            "Polyglot exercises directory. Relative paths are resolved from the current "
            "working directory. If omitted, common host and Docker locations are searched."
        ),
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a deterministic copied subset of the exercises",
    )
    parser.add_argument("--smoke-size", type=int, default=DEFAULT_SMOKE_TESTS, help="Smoke task count")
    parser.add_argument("--limit", type=int, help="Pass --num-tests to benchmark.py")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write metadata and print the command without running benchmark.py",
    )
    parser.add_argument(
        "--validate-smoke",
        action="store_true",
        help="Validate the smoke exercise tree with benchmark.py discovery semantics",
    )
    return parser.parse_known_args(argv)


def write_child_metadata(run_dir, values):
    write_key_values(run_dir / "child.txt", values)
    json_values = {key: str(value) for key, value in values.items()}
    (run_dir / "child.json").write_text(json.dumps(json_values, indent=2) + "\n")


def result_files(path):
    return sorted(Path(path).glob("*/exercises/practice/*/.aider.results.json"))


def exercise_dirs(path):
    return [p for p in Path(path).glob("*/exercises/practice/*") if p.is_dir()]


def candidate_run_artifact_dirs(run_name, started_at):
    dirs = []
    for path in benchmark_dir().glob(f"*--{run_name}"):
        try:
            if path.is_dir() and path.stat().st_mtime >= started_at:
                dirs.append(path)
        except OSError:
            continue
    return sorted(dirs, key=lambda path: path.stat().st_mtime, reverse=True)


def warn_if_zero_tasks(run_name, started_at):
    artifact_dirs = candidate_run_artifact_dirs(run_name, started_at)
    completed = sum(len(result_files(path)) for path in artifact_dirs)
    total = sum(len(exercise_dirs(path)) for path in artifact_dirs)

    if completed:
        return artifact_dirs, completed, total

    print()
    if artifact_dirs:
        print(
            "Warning: benchmark.py exited zero, but no completed result artifacts were found "
            f"for {run_name}. Artifact dirs: {', '.join(str(path) for path in artifact_dirs)}"
        )
    else:
        print(
            "Warning: benchmark.py exited zero, but no run artifact directory was found "
            f"for {run_name} under {benchmark_dir()}. The benchmark appears to have run zero tasks."
        )
    return artifact_dirs, completed, total


def print_validation_report(exercises_root, languages=None, expected_count=None):
    paths, problems = validate_discoverable_exercises(exercises_root, languages=languages)
    print()
    print(f"Smoke validation: {exercises_root}")
    print(f"Discoverable tasks: {len(paths)}")
    for path in paths[:10]:
        print(f"  {path.as_posix()}")
    if len(paths) > 10:
        print(f"  ... {len(paths) - 10} more")
    if problems:
        print("Validation problems:")
        for problem in problems:
            print(f"  - {problem}")
    if expected_count is not None and len(paths) != expected_count:
        problems.append(f"expected {expected_count} discoverable tasks, found {len(paths)}")
        print(f"Validation count mismatch: expected {expected_count}, found {len(paths)}")
    return not problems, paths, problems


def print_log_tail(label, path, max_lines=40):
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError as err:
        print(f"{label}: unavailable: {err}")
        return
    if not lines:
        print(f"{label}: empty")
        return
    print(f"{label} tail:")
    for line in lines[-max_lines:]:
        print(f"  {line}")


def main(argv=None):
    args, passthrough = parse_args(argv)
    if args.smoke_size < 1:
        raise SystemExit("--smoke-size must be at least 1")

    run_dir = RUNS_DIR / args.run_name
    smoke_metadata = None
    exercises_dir = args.exercises_dir or DEFAULT_EXERCISES_DIR_NAME
    args.resolved_exercises_dir = exercises_dir

    if args.smoke or not args.dry_run:
        try:
            exercises_dir, source_root = resolve_exercises_dir(args.exercises_dir)
        except FileNotFoundError as err:
            raise SystemExit(str(err))
        args.resolved_exercises_dir = exercises_dir

    if args.smoke:
        exercises_dir, smoke_metadata = prepare_smoke_exercises(
            args,
            run_dir,
            exercises_dir,
            source_root,
            dry_run=args.dry_run and not args.validate_smoke,
        )

    cmd = build_benchmark_command(args, passthrough, exercises_dir=exercises_dir)

    write_run_metadata(run_dir, cmd, args)
    if smoke_metadata:
        write_smoke_metadata(run_dir, smoke_metadata)

    print("Benchmark command:")
    print(quote_command(cmd))
    print(f"Run metadata: {run_dir}")
    if smoke_metadata:
        print(
            "Smoke strategy: copy first "
            f"{args.smoke_size} sorted language/exercise paths from "
            f"{smoke_metadata['source_root']} to {smoke_metadata['smoke_root']}"
        )
        if smoke_metadata["tasks"]:
            print("Smoke tasks:")
            for task in smoke_metadata["tasks"]:
                print(f"  {task}")
        else:
            print("Smoke tasks: unavailable until source exercises are present")

    if args.validate_smoke:
        if not args.smoke:
            raise SystemExit("--validate-smoke requires --smoke")
        validation_ok, _, _ = print_validation_report(
            exercises_dir, expected_count=args.smoke_size
        )
        if not validation_ok:
            raise SystemExit(
                f"Smoke validation failed; expected {args.smoke_size} discoverable tasks. "
                "No API call was made."
            )

    if args.dry_run:
        print("Dry run only; benchmark.py was not executed.")
        return 0

    if args.smoke:
        validation_ok, validation_paths, validation_problems = print_validation_report(
            exercises_dir, expected_count=args.smoke_size
        )
        if not validation_ok:
            write_child_metadata(
                run_dir,
                {
                    "command": quote_command(cmd),
                    "exit_code": 1,
                    "stdout": "",
                    "stderr": "",
                    "selected_smoke_directory": smoke_metadata["smoke_root_for_benchmark"],
                    "artifact_dirs": "",
                    "completed_tests": 0,
                    "total_tests": len(validation_paths),
                    "expected_tests": args.smoke_size,
                    "error": "smoke validation failed before benchmark.py; "
                    + "; ".join(validation_problems),
                },
            )
            print("Smoke validation failed before invoking benchmark.py.")
            print("No API call was made.")
            return 1

    if not os.environ.get("AIDER_DOCKER"):
        print()
        print(f"Refusing to invoke benchmark.py on the host: {HOST_EXECUTION_WARNING}.")
        print("No API call was made.")
        write_child_metadata(
            run_dir,
            {
                "command": quote_command(cmd),
                "exit_code": 1,
                "stdout": "",
                "stderr": "",
                "selected_smoke_directory": (
                    smoke_metadata["smoke_root_for_benchmark"] if smoke_metadata else ""
                ),
                "artifact_dirs": "",
                "completed_tests": 0,
                "total_tests": 0,
                "expected_tests": args.smoke_size if args.smoke else "",
                "error": "host execution refused; set AIDER_DOCKER inside the benchmark container",
            },
        )
        return 1

    stdout_path = run_dir / "benchmark.stdout.log"
    stderr_path = run_dir / "benchmark.stderr.log"
    started_at = time.time()
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, stdout=stdout, stderr=stderr)

    if proc.returncode == 0:
        artifact_dirs, completed, total = warn_if_zero_tasks(args.run_name, started_at)
    else:
        artifact_dirs = candidate_run_artifact_dirs(args.run_name, started_at)
        completed = sum(len(result_files(path)) for path in artifact_dirs)
        total = sum(len(exercise_dirs(path)) for path in artifact_dirs)
    write_child_metadata(
        run_dir,
        {
            "command": quote_command(cmd),
            "exit_code": proc.returncode,
            "stdout": stdout_path,
            "stderr": stderr_path,
            "selected_smoke_directory": (
                smoke_metadata["smoke_root_for_benchmark"] if smoke_metadata else ""
            ),
            "artifact_dirs": ", ".join(str(path) for path in artifact_dirs),
            "completed_tests": completed,
            "total_tests": total,
            "expected_tests": args.smoke_size if args.smoke else "",
        },
    )

    print(f"benchmark.py exit code: {proc.returncode}")
    print(f"benchmark.py stdout: {stdout_path}")
    print(f"benchmark.py stderr: {stderr_path}")
    if proc.returncode == 0 and completed == 0:
        print_log_tail("benchmark.py stdout", stdout_path)
        print_log_tail("benchmark.py stderr", stderr_path)
    if proc.returncode == 0 and args.smoke and completed != args.smoke_size:
        print()
        print(
            "Smoke benchmark task-count mismatch: "
            f"expected {args.smoke_size} completed result artifacts, found {completed}."
        )
        print("Treating this as a failed smoke run so zero-task behavior cannot look successful.")
        return 1

    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
