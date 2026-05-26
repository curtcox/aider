import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from benchmark import prepare_polyglot, run_baseline, summarize_runs


class TestRunBaseline(unittest.TestCase):
    def test_build_smoke_command(self):
        args = argparse.Namespace(
            run_name="smoke",
            model="gpt-4.1-mini",
            edit_format="diff",
            threads=1,
            exercises_dir="polyglot-benchmark",
            smoke=True,
            smoke_size=3,
            limit=None,
        )

        cmd = run_baseline.build_benchmark_command(
            args, ["--languages", "python"], exercises_dir="smoke-exercises/smoke"
        )

        self.assertIn("benchmark/benchmark.py", cmd)
        self.assertIn("--new", cmd)
        self.assertNotIn("--num-tests", cmd)
        self.assertIn("smoke-exercises/smoke", cmd)
        self.assertEqual(cmd[-2:], ["--languages", "python"])

    @mock.patch("benchmark.run_baseline.RUNS_DIR")
    def test_dry_run_writes_metadata(self, runs_dir):
        with tempfile.TemporaryDirectory() as tempdir:
            runs_dir.__truediv__.side_effect = Path(tempdir).__truediv__

            rc = run_baseline.main(["--dry-run", "--run-name", "smoke"])

            self.assertEqual(rc, 0)
            run_dir = Path(tempdir) / "smoke"
            self.assertTrue((run_dir / "command.txt").exists())
            self.assertTrue((run_dir / "git.txt").exists())
            self.assertTrue((run_dir / "env.txt").exists())

    @mock.patch("benchmark.run_baseline.benchmark_dir")
    def test_prepare_smoke_exercises_copies_deterministic_subset(self, mock_benchmark_dir):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            mock_benchmark_dir.return_value = root
            source = root / "polyglot-benchmark"
            for rel_path in [
                "python/exercises/practice/zebra",
                "python/exercises/practice/hello-world",
                "javascript/exercises/practice/acronym",
            ]:
                exercise = source / rel_path
                exercise.mkdir(parents=True)
                (exercise / "README.md").write_text(rel_path)

            args = argparse.Namespace(
                run_name="smoke",
                smoke_size=2,
                languages=None,
            )

            smoke_name, metadata = run_baseline.prepare_smoke_exercises(
                args,
                root / "runs" / "smoke",
                "polyglot-benchmark",
                source,
                dry_run=False,
            )

            self.assertEqual(Path(smoke_name), (root / "smoke-exercises" / "smoke").resolve())
            self.assertEqual(
                metadata["tasks"],
                [
                    "javascript/exercises/practice/acronym",
                    "python/exercises/practice/hello-world",
                ],
            )
            self.assertTrue(
                (
                    root
                    / "smoke-exercises"
                    / "smoke"
                    / "javascript"
                    / "exercises"
                    / "practice"
                    / "acronym"
                    / "README.md"
                ).exists()
            )
            self.assertFalse((source / "javascript" / "exercises" / "practice" / "zebra").exists())

    @mock.patch("benchmark.run_baseline.benchmark_dir")
    def test_prepare_smoke_exercises_respects_language_filter(self, mock_benchmark_dir):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            mock_benchmark_dir.return_value = root
            source = root / "polyglot-benchmark"
            for rel_path in [
                "cpp/exercises/practice/allergies",
                "python/exercises/practice/bob",
                "python/exercises/practice/hello-world",
            ]:
                exercise = source / rel_path
                exercise.mkdir(parents=True)
                (exercise / "README.md").write_text(rel_path)

            args = argparse.Namespace(
                run_name="python-smoke",
                smoke_size=2,
                languages="python",
            )

            smoke_name, metadata = run_baseline.prepare_smoke_exercises(
                args,
                root / "runs" / "python-smoke",
                "polyglot-benchmark",
                source,
                dry_run=False,
            )

            self.assertEqual(Path(smoke_name), (root / "smoke-exercises" / "python-smoke").resolve())
            self.assertEqual(
                metadata["tasks"],
                [
                    "python/exercises/practice/bob",
                    "python/exercises/practice/hello-world",
                ],
            )
            self.assertEqual(metadata["languages"], "python")
            self.assertTrue(
                (
                    root
                    / "smoke-exercises"
                    / "python-smoke"
                    / "python"
                    / "exercises"
                    / "practice"
                    / "bob"
                    / "README.md"
                ).exists()
            )
            self.assertFalse(
                (
                    root
                    / "smoke-exercises"
                    / "python-smoke"
                    / "cpp"
                    / "exercises"
                    / "practice"
                    / "allergies"
                ).exists()
            )

    @mock.patch("benchmark.run_baseline.benchmark_dir")
    def test_validate_discoverable_exercises_matches_benchmark_layout(self, mock_benchmark_dir):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            mock_benchmark_dir.return_value = root
            exercises_root = root / "smoke-exercises" / "smoke"
            (exercises_root / "cpp" / "exercises" / "practice" / "allergies").mkdir(
                parents=True
            )
            (exercises_root / "notes").mkdir()
            (exercises_root / "README.md").write_text("not a language")

            paths, problems = run_baseline.validate_discoverable_exercises(exercises_root)

            self.assertEqual(
                [path.as_posix() for path in paths],
                ["cpp/exercises/practice/allergies"],
            )
            self.assertIn("missing practice directory", "\n".join(problems))

    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch("benchmark.run_baseline.RUNS_DIR")
    def test_non_dry_run_refuses_host_execution_before_benchmark(self, runs_dir):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runs_dir.__truediv__.side_effect = (root / "runs").__truediv__
            source = root / "polyglot-benchmark"
            (source / "python" / "exercises" / "practice" / "hello-world").mkdir(parents=True)

            with mock.patch("benchmark.run_baseline.subprocess.run") as run:
                rc = run_baseline.main(
                    [
                        "--run-name",
                        "smoke",
                        "--exercises-dir",
                        str(source),
                    ]
                )

            self.assertEqual(rc, 1)
            benchmark_calls = [
                call
                for call in run.call_args_list
                if "benchmark/benchmark.py" in [str(part) for part in call.args[0]]
            ]
            self.assertEqual(benchmark_calls, [])
            child = root / "runs" / "smoke" / "child.txt"
            self.assertIn("host execution refused", child.read_text())

    @mock.patch("benchmark.run_baseline.benchmark_dir")
    @mock.patch("benchmark.run_baseline.RUNS_DIR")
    def test_dry_run_smoke_metadata_records_selected_tasks(
        self, runs_dir, mock_benchmark_dir
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runs_dir.__truediv__.side_effect = (root / "runs").__truediv__
            mock_benchmark_dir.return_value = root / "benchmarks"
            exercise = (
                root
                / "benchmarks"
                / "polyglot-benchmark"
                / "python"
                / "exercises"
                / "practice"
                / "hello-world"
            )
            exercise.mkdir(parents=True)
            (exercise / "README.md").write_text("hello")

            rc = run_baseline.main(
                [
                    "--dry-run",
                    "--run-name",
                    "smoke",
                    "--smoke",
                    "--smoke-size",
                    "1",
                    "--exercises-dir",
                    str(root / "benchmarks" / "polyglot-benchmark"),
                ]
            )

            self.assertEqual(rc, 0)
            smoke_tasks = root / "runs" / "smoke" / "smoke_tasks.txt"
            text = smoke_tasks.read_text()
            self.assertIn("python/exercises/practice/hello-world", text)
            self.assertIn(f"source_exercises_dir: {root / 'benchmarks' / 'polyglot-benchmark'}", text)
            self.assertIn("smoke_exercises_dir: smoke-exercises/smoke", text)
            self.assertIn(
                f"smoke_root_for_benchmark: {(root / 'benchmarks' / 'smoke-exercises' / 'smoke').resolve()}",
                text,
            )
            self.assertIn("expected_tasks: 1", text)
            self.assertTrue((root / "runs" / "smoke" / "smoke_tasks.json").exists())
            self.assertFalse((root / "benchmarks" / "smoke-exercises").exists())

    @mock.patch.dict(os.environ, {"AIDER_DOCKER": "1"}, clear=True)
    @mock.patch("benchmark.run_baseline.benchmark_dir")
    @mock.patch("benchmark.run_baseline.RUNS_DIR")
    def test_smoke_run_fails_if_benchmark_completes_zero_tasks(
        self, runs_dir, mock_benchmark_dir
    ):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            runs_dir.__truediv__.side_effect = (root / "runs").__truediv__
            mock_benchmark_dir.return_value = root / "benchmarks"
            source = root / "benchmarks" / "polyglot-benchmark"
            (source / "python" / "exercises" / "practice" / "hello-world").mkdir(parents=True)
            artifact = root / "benchmarks" / "2026-05-26-12-00-00--smoke"
            (artifact / "python" / "exercises" / "practice" / "hello-world").mkdir(parents=True)

            completed = mock.Mock(returncode=0)
            with mock.patch("benchmark.run_baseline.subprocess.run", return_value=completed):
                rc = run_baseline.main(
                    [
                        "--run-name",
                        "smoke",
                        "--smoke",
                        "--smoke-size",
                        "1",
                        "--exercises-dir",
                        str(source),
                    ]
                )

            self.assertEqual(rc, 1)
            child_text = (root / "runs" / "smoke" / "child.txt").read_text()
            self.assertIn("completed_tests: 0", child_text)
            self.assertIn("expected_tests: 1", child_text)

    def test_resolve_exercises_dir_uses_explicit_path_from_cwd(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            fixture = root / "fixtures" / "polyglot-benchmark"
            fixture.mkdir(parents=True)
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                exercises_dir, source_root = run_baseline.resolve_exercises_dir(
                    "fixtures/polyglot-benchmark"
                )
            finally:
                os.chdir(old_cwd)

            self.assertEqual(Path(exercises_dir), fixture.resolve())
            self.assertEqual(source_root, fixture.resolve())

    def test_resolve_exercises_dir_tries_candidates_in_order(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            second = root / "benchmark" / "polyglot-benchmark"
            third = root / "tmp.benchmarks" / "polyglot-benchmark"
            second.mkdir(parents=True)
            third.mkdir(parents=True)
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                exercises_dir, source_root = run_baseline.resolve_exercises_dir()
            finally:
                os.chdir(old_cwd)

            expected = (root / "benchmark" / "polyglot-benchmark").resolve()
            self.assertEqual(Path(exercises_dir), expected)
            self.assertEqual(source_root, expected)

    def test_missing_exercises_dir_error_is_actionable(self):
        with tempfile.TemporaryDirectory() as tempdir:
            old_cwd = Path.cwd()
            try:
                os.chdir(tempdir)
                with self.assertRaises(FileNotFoundError) as cm:
                    run_baseline.resolve_exercises_dir()
            finally:
                os.chdir(old_cwd)

        message = str(cm.exception)
        self.assertIn("polyglot-benchmark", message)
        self.assertIn("tmp.benchmarks/polyglot-benchmark", message)
        self.assertIn("/benchmarks/polyglot-benchmark", message)
        self.assertIn("python3 benchmark/prepare_polyglot.py", message)
        self.assertIn("--exercises-dir", message)
        self.assertIn("No API call was made", message)


class TestPreparePolyglot(unittest.TestCase):
    def test_prepare_polyglot_copies_local_source_and_writes_metadata(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source"
            exercise = source / "python" / "exercises" / "practice" / "hello-world"
            exercise.mkdir(parents=True)
            (exercise / "README.md").write_text("hello")

            dest, metadata, created = prepare_polyglot.prepare_polyglot(
                dest=root / "tmp.benchmarks" / "polyglot-benchmark",
                source_url=str(source),
                ref="local-test-ref",
            )

            self.assertTrue(created)
            self.assertTrue((dest / "python" / "exercises" / "practice" / "hello-world").is_dir())
            self.assertEqual(metadata["source_url"], str(source.resolve()))
            self.assertEqual(metadata["source_kind"], "local-directory")
            self.assertEqual(metadata["ref"], "local-test-ref")
            self.assertEqual(metadata["resolved_commit"], "local-test-ref")
            self.assertEqual(metadata["destination_path"], str(dest.resolve()))
            self.assertIn("prepared_at_utc", metadata)
            self.assertIn("source_description", metadata)
            self.assertIn("command_used", metadata)
            self.assertTrue((dest / prepare_polyglot.METADATA_NAME).exists())

    def test_prepare_polyglot_is_safe_to_rerun(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source"
            (source / "go" / "exercises" / "practice" / "two-fer").mkdir(parents=True)
            dest = root / "tmp.benchmarks" / "polyglot-benchmark"

            prepare_polyglot.prepare_polyglot(dest=dest, source_url=str(source), ref="local")
            rerun_dest, metadata, created = prepare_polyglot.prepare_polyglot(
                dest=dest, source_url=str(source), ref="local"
            )

            self.assertFalse(created)
            self.assertEqual(rerun_dest, dest)
            self.assertEqual(metadata["ref"], "local")

    def test_prepare_polyglot_existing_unprepared_dir_is_actionable(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source"
            source.mkdir()
            dest = root / "tmp.benchmarks" / "polyglot-benchmark"
            dest.mkdir(parents=True)
            (dest / "README.md").write_text("not provenance-managed")

            with self.assertRaises(RuntimeError) as cm:
                prepare_polyglot.prepare_polyglot(dest=dest, source_url=str(source), ref="local")

            self.assertIn("Destination already exists", str(cm.exception))
            self.assertIn("--force", str(cm.exception))

    def test_prepare_polyglot_rejects_source_without_practice_exercises(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "source"
            source.mkdir()

            with self.assertRaises(RuntimeError) as cm:
                prepare_polyglot.prepare_polyglot(
                    dest=root / "tmp.benchmarks" / "polyglot-benchmark",
                    source_url=str(source),
                    ref="local",
                )

            self.assertIn("language/exercises/practice", str(cm.exception))


class TestSummarizeRuns(unittest.TestCase):
    def test_summarize_benchmark_dir(self):
        with tempfile.TemporaryDirectory() as tempdir:
            run_dir = Path(tempdir) / "2026-05-26-12-00-00--smoke"
            exercise = run_dir / "python" / "exercises" / "practice" / "hello-world"
            exercise.mkdir(parents=True)
            (exercise / ".aider.results.json").write_text(
                json.dumps(
                    {
                        "model": "gpt-4.1-mini",
                        "edit_format": "diff",
                        "commit_hash": "abc1234",
                        "tests_outcomes": [False, True],
                        "cost": 0.0123,
                        "duration": 4.5,
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                    }
                )
            )

            row = summarize_runs.summarize_benchmark_dir(run_dir)

            self.assertEqual(row["run_name"], "smoke")
            self.assertEqual(row["completed_tests"], 1)
            self.assertEqual(row["total_tests"], 1)
            self.assertEqual(row["pass_rate_1"], "0.0")
            self.assertEqual(row["pass_rate_2"], "100.0")
            self.assertEqual(row["passed_count"], 1)
            self.assertEqual(row["failed_count"], 0)
            self.assertEqual(row["pass_rate"], "100.0")
            self.assertEqual(row["total_cost"], "0.0123")
            self.assertEqual(row["wall_clock_seconds"], "4.5")

    def test_summarize_minimal_real_run_artifact(self):
        with tempfile.TemporaryDirectory() as tempdir:
            run_dir = Path(tempdir) / "real-smoke"
            exercise = run_dir / "go" / "exercises" / "practice" / "two-fer"
            exercise.mkdir(parents=True)
            (exercise / ".aider.results.json").write_text(
                json.dumps(
                    {
                        "model": "gpt-4.1-mini",
                        "edit_format": "diff",
                        "tests_outcomes": [False],
                        "cost": 0.001,
                        "duration": 2,
                    }
                )
            )

            row = summarize_runs.summarize_benchmark_dir(run_dir)

            self.assertEqual(row["run_name"], "real-smoke")
            self.assertEqual(row["completed_tests"], 1)
            self.assertEqual(row["total_tests"], 1)
            self.assertEqual(row["passed_count"], 0)
            self.assertEqual(row["failed_count"], 1)
            self.assertEqual(row["pass_rate"], "0.0")
            self.assertEqual(row["total_cost"], "0.0010")
            self.assertEqual(row["raw_artifacts_path"], str(run_dir))

    def test_discover_skips_prepared_source_dataset_without_results(self):
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "polyglot-benchmark"
            (source / "python" / "exercises" / "practice" / "hello-world").mkdir(parents=True)
            (source / ".aider-polyglot-provenance.json").write_text("{}")

            run_dir = root / "2026-05-26-12-00-00--smoke"
            (run_dir / "python" / "exercises" / "practice" / "hello-world").mkdir(parents=True)

            dirs = summarize_runs.discover_benchmark_dirs([root])

            self.assertEqual(dirs, [])

    def test_discover_skips_explicit_prepared_source_dataset(self):
        with tempfile.TemporaryDirectory() as tempdir:
            source = Path(tempdir) / "polyglot-benchmark"
            (source / "python" / "exercises" / "practice" / "hello-world").mkdir(parents=True)
            (source / ".aider-polyglot-provenance.json").write_text("{}")

            self.assertEqual(summarize_runs.discover_benchmark_dirs([source]), [])

    def test_discover_ignores_empty_dated_run_without_results(self):
        with tempfile.TemporaryDirectory() as tempdir:
            run_dir = Path(tempdir) / "2026-05-26-12-00-00--smoke"
            (run_dir / "python" / "exercises" / "practice" / "hello-world").mkdir(parents=True)

            self.assertEqual(summarize_runs.discover_benchmark_dirs([Path(tempdir)]), [])


if __name__ == "__main__":
    unittest.main()
