#!/usr/bin/env python3
"""Summarize Aider benchmark result artifacts into runs/summary.csv."""

import argparse
import csv
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO_ROOT / "runs"
BENCHMARK_DIR = REPO_ROOT / "tmp.benchmarks"
RESULT_GLOB = "*/exercises/practice/*/.aider.results.json"
RUN_DIR_RE = re.compile(r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}--")
SOURCE_PROVENANCE = ".aider-polyglot-provenance.json"

CSV_FIELDS = [
    "run_name",
    "benchmark_dir",
    "raw_artifacts_path",
    "completed_tests",
    "total_tests",
    "passed_count",
    "failed_count",
    "pass_rate",
    "pass_rate_1",
    "pass_rate_2",
    "pass_num_1",
    "pass_num_2",
    "model",
    "edit_format",
    "commit_hash",
    "total_cost",
    "wall_clock_seconds",
    "seconds_per_case",
    "test_timeouts",
    "error_outputs",
    "num_malformed_responses",
    "prompt_tokens",
    "completion_tokens",
]


def run_name_from_benchmark_dir(path):
    name = path.name
    if len(name) > 21 and name[19:21] == "--":
        return name[21:]
    return name


def safe_number(value, default=0):
    return value if isinstance(value, (int, float)) else default


def load_result(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def find_result_files(path):
    """Find benchmark result artifacts.

    Supported layouts:
    - Current Polyglot benchmark runs:
      <run>/<language>/exercises/practice/<exercise>/.aider.results.json
    - Defensive fallback for copied or future artifacts anywhere below <run>.
    """
    path = Path(path)
    files = sorted(path.glob(RESULT_GLOB))
    if files:
        return files
    return sorted(path.rglob(".aider.results.json"))


def is_dated_run_dir(path):
    return bool(RUN_DIR_RE.match(Path(path).name))


def is_prepared_source_dataset(path):
    path = Path(path)
    return path.name == "polyglot-benchmark" or (path / SOURCE_PROVENANCE).exists()


def is_benchmark_result_dir(path):
    path = Path(path)
    if is_prepared_source_dataset(path):
        return False
    return bool(find_result_files(path))


def count_exercise_dirs(path):
    path = Path(path)
    exercise_dirs = list(path.glob("*/exercises/practice/*"))
    if exercise_dirs:
        return len([p for p in exercise_dirs if p.is_dir()])
    result_files = find_result_files(path)
    return len({result_file.parent for result_file in result_files})


def summarize_benchmark_dir(path):
    path = Path(path)
    result_files = find_result_files(path)
    results = [result for result in (load_result(fname) for fname in result_files) if result]
    total_tests = count_exercise_dirs(path)
    tries = max((len(result.get("tests_outcomes", [])) for result in results), default=0)

    row = {
        "run_name": run_name_from_benchmark_dir(path),
        "benchmark_dir": str(path),
        "raw_artifacts_path": str(path),
        "completed_tests": len(results),
        "total_tests": total_tests,
        "passed_count": 0,
        "failed_count": 0,
        "pass_rate": "",
        "pass_rate_1": "",
        "pass_rate_2": "",
        "pass_num_1": "",
        "pass_num_2": "",
        "model": "",
        "edit_format": "",
        "commit_hash": "",
        "total_cost": 0,
        "wall_clock_seconds": 0,
        "seconds_per_case": "",
        "test_timeouts": 0,
        "error_outputs": 0,
        "num_malformed_responses": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }

    if not results:
        return row

    passed_by_try = [0] * tries
    duration = 0
    variants = {"model": set(), "edit_format": set(), "commit_hash": set()}

    for result in results:
        outcomes = result.get("tests_outcomes", [])
        if outcomes and outcomes[-1]:
            row["passed_count"] += 1
            for index in range(len(outcomes) - 1, tries):
                passed_by_try[index] += 1
        else:
            row["failed_count"] += 1

        row["total_cost"] += safe_number(result.get("cost"))
        duration += safe_number(result.get("duration"))
        row["test_timeouts"] += safe_number(result.get("test_timeouts"))
        row["error_outputs"] += safe_number(result.get("num_error_outputs"))
        row["num_malformed_responses"] += safe_number(result.get("num_malformed_responses"))
        row["prompt_tokens"] += safe_number(result.get("prompt_tokens"))
        row["completion_tokens"] += safe_number(result.get("completion_tokens"))

        for key in variants:
            value = result.get(key)
            if value:
                variants[key].add(str(value))

    for index, passed in enumerate(passed_by_try[:2], start=1):
        row[f"pass_num_{index}"] = passed
        row[f"pass_rate_{index}"] = f"{100 * passed / len(results):.1f}"

    for key, values in variants.items():
        row[key] = ", ".join(sorted(values))

    row["total_cost"] = f"{row['total_cost']:.4f}"
    row["wall_clock_seconds"] = f"{duration:.1f}"
    row["seconds_per_case"] = f"{duration / len(results):.1f}"
    row["pass_rate"] = f"{100 * row['passed_count'] / len(results):.1f}"
    return row


def discover_benchmark_dirs(paths):
    seen = set()
    dirs = []
    for path in paths:
        path = Path(path)
        if not path.exists():
            continue
        if is_benchmark_result_dir(path):
            candidates = [path]
        else:
            candidates = sorted(p for p in path.iterdir() if p.is_dir())
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            if is_benchmark_result_dir(candidate):
                seen.add(resolved)
                dirs.append(candidate)
    return dirs


def write_csv(rows, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def print_table(rows):
    if not rows:
        print("No benchmark result directories found.")
        return

    columns = [
        "run_name",
        "completed_tests",
        "total_tests",
        "pass_rate_1",
        "pass_rate_2",
        "total_cost",
    ]
    widths = {
        column: max(len(column), *(len(str(row.get(column, ""))) for row in rows))
        for column in columns
    }
    print("  ".join(column.ljust(widths[column]) for column in columns))
    print("  ".join("-" * widths[column] for column in columns))
    for row in rows:
        print("  ".join(str(row.get(column, "")).ljust(widths[column]) for column in columns))


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        default=[BENCHMARK_DIR],
        help="Benchmark directories or parent directories to scan",
    )
    parser.add_argument("--output", default=RUNS_DIR / "summary.csv", type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    dirs = discover_benchmark_dirs(args.paths)
    rows = [summarize_benchmark_dir(path) for path in dirs]
    write_csv(rows, args.output)
    print_table(rows)
    print(f"\nWrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
