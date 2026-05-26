#!/usr/bin/env python3
"""Prepare the Polyglot benchmark exercises for Aider benchmark runs."""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = REPO_ROOT / "tmp.benchmarks" / "polyglot-benchmark"
DEFAULT_SOURCE_URL = "https://github.com/Aider-AI/polyglot-benchmark.git"
DEFAULT_REF = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
METADATA_NAME = ".aider-polyglot-provenance.json"


def metadata_path(dest):
    return Path(dest) / METADATA_NAME


def source_kind(source_url):
    return "local-directory" if Path(source_url).expanduser().exists() else "git"


def write_metadata(dest, source_url, ref, resolved_commit=None, command_used=None):
    dest = Path(dest).resolve()
    metadata = {
        "source_url": source_url,
        "source_description": (
            "Local directory copied without .git metadata"
            if source_kind(source_url) == "local-directory"
            else "Git repository cloned at the pinned ref"
        ),
        "source_kind": source_kind(source_url),
        "ref": ref,
        "resolved_commit": resolved_commit or ref,
        "destination_path": str(dest),
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command_used": command_used,
    }
    metadata_path(dest).write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return metadata


def read_metadata(dest):
    path = metadata_path(dest)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def is_prepared(dest):
    dest = Path(dest)
    return dest.is_dir() and metadata_path(dest).exists() and has_exercises(dest)


def has_exercises(dest):
    dest = Path(dest)
    if not dest.is_dir():
        return False
    for language_dir in dest.iterdir():
        if (language_dir / "exercises" / "practice").is_dir():
            return True
    return False


def validate_prepared(dest):
    if not has_exercises(dest):
        raise RuntimeError(
            "Prepared Polyglot data does not contain any "
            "language/exercises/practice directories. Check the source and ref."
        )


def copy_local_source(source, dest, ref, command_used=None):
    source = Path(source).expanduser().resolve()
    if not source.is_dir():
        raise RuntimeError(f"Local source directory does not exist: {source}")

    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(".git"))
    validate_prepared(dest)
    return write_metadata(dest, str(source), ref, resolved_commit=ref, command_used=command_used)


def run_git(args, cwd=None):
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=cwd,
            stderr=subprocess.STDOUT,
            text=True,
        ).strip()
    except FileNotFoundError as err:
        raise RuntimeError("git is required to prepare the Polyglot benchmark data.") from err
    except subprocess.CalledProcessError as err:
        output = err.output.strip()
        detail = f"\n\nGit output:\n{output}" if output else ""
        raise RuntimeError(
            "Unable to fetch the Polyglot benchmark data. Check network access, "
            f"the source URL, and the requested ref.{detail}"
        ) from err


def clone_source(source_url, dest, ref, command_used=None):
    with tempfile.TemporaryDirectory(prefix="aider-polyglot-") as tmp:
        checkout = Path(tmp) / "polyglot-benchmark"
        run_git(["clone", "--no-checkout", source_url, str(checkout)])
        run_git(["checkout", ref], cwd=checkout)
        resolved_commit = run_git(["rev-parse", "HEAD"], cwd=checkout)
        shutil.rmtree(checkout / ".git", ignore_errors=True)
        shutil.copytree(checkout, dest)
    validate_prepared(dest)
    return write_metadata(
        dest,
        source_url,
        ref,
        resolved_commit=resolved_commit,
        command_used=command_used,
    )


def prepare_polyglot(
    dest=DEFAULT_DEST,
    source_url=DEFAULT_SOURCE_URL,
    ref=DEFAULT_REF,
    force=False,
    command_used=None,
):
    dest = Path(dest).expanduser()
    if not dest.is_absolute():
        dest = Path.cwd() / dest

    if is_prepared(dest) and not force:
        return dest, read_metadata(dest), False

    if dest.exists():
        if any(dest.iterdir()):
            if not force:
                raise RuntimeError(
                    f"Destination already exists and is not an empty prepared directory: {dest}\n"
                    f"Remove it, pass --dest elsewhere, or rerun with --force."
                )
            shutil.rmtree(dest)
        else:
            dest.rmdir()

    dest.parent.mkdir(parents=True, exist_ok=True)
    source_path = Path(source_url).expanduser()
    if source_path.exists():
        metadata = copy_local_source(source_path, dest, ref, command_used=command_used)
    else:
        metadata = clone_source(source_url, dest, ref, command_used=command_used)
    return dest, metadata, True


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Prepare the Aider Polyglot benchmark exercises.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--dest", default=str(DEFAULT_DEST), help="Destination exercises directory")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL, help="Git URL or local source dir")
    parser.add_argument("--ref", default=DEFAULT_REF, help="Git commit, tag, or local provenance ref")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing destination instead of reusing prepared data",
    )
    return parser.parse_args(argv)


def main(argv=None):
    raw_argv = sys.argv[1:] if argv is None else argv
    args = parse_args(argv)
    command_used = " ".join(
        subprocess.list2cmdline([part]) for part in [sys.executable, sys.argv[0], *raw_argv]
    )
    try:
        dest, metadata, created = prepare_polyglot(
            args.dest,
            args.source_url,
            args.ref,
            args.force,
            command_used=command_used,
        )
    except RuntimeError as err:
        raise SystemExit(f"Error: {err}")

    action = "Prepared" if created else "Already prepared"
    print(f"{action} Polyglot benchmark exercises: {dest}")
    print(f"Source URL: {metadata['source_url']}")
    print(f"Source kind: {metadata['source_kind']}")
    print(f"Ref: {metadata['ref']}")
    print(f"Resolved commit: {metadata['resolved_commit']}")
    print(f"Destination path: {metadata['destination_path']}")
    print(f"Provenance metadata: {metadata_path(dest)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
