# Aider Polyglot benchmark baseline

This is a lightweight workflow for running Aider's existing Polyglot benchmark
with hosted models and collecting reproducible run metadata. It does not change
the benchmark harness, scoring, or exercise semantics.

## One-time setup

From the repo root on the host:

```bash
python3 benchmark/prepare_polyglot.py
./benchmark/docker_build.sh
```

Enter the Docker benchmark environment:

```bash
./benchmark/docker.sh
```

Inside Docker, install this checkout in editable/dev mode:

```bash
pip install -e '.[dev]'
```

Set your API key inside Docker without committing it anywhere:

```bash
export OPENAI_API_KEY=...
```

`benchmark/docker.sh` mounts host `tmp.benchmarks/` at `/benchmarks` and sets
`AIDER_BENCHMARK_DIR=/benchmarks`, so the same checkout is visible inside
Docker as `/benchmarks/polyglot-benchmark`.

## Resume checklist

After pulling this work on a different computer, resume from the baseline smoke
benchmark. Do not start the full benchmark or any Fleshwound implementation
until the smoke run records three completed tasks.

Current plan status:

- Fork Aider: done.
- Prepare pinned Polyglot data tooling: done.
- Add baseline run wrapper and summarizer: done.
- Run real `gpt-4.1-mini` smoke test: next.
- Run full `gpt-4.1-mini` Polyglot baseline: blocked on smoke success.
- Stronger hosted model, non-OpenAI hosted model, Ollama smoke/full local,
  `EditSystem`, `NoopEditSystem`, `FleshwoundEditSystem`, Fleshwound
  benchmarks, and comparison report: not started.

Fresh-machine resume commands from the repo root:

```bash
git pull
python3 benchmark/prepare_polyglot.py
./benchmark/docker_build.sh
./benchmark/docker.sh
```

Inside Docker:

```bash
pip install -e '.[dev]'
export OPENAI_API_KEY=...
python3 benchmark/run_baseline.py \
  --run-name real-smoke-gpt41mini \
  --model gpt-4.1-mini \
  --edit-format diff \
  --threads 1 \
  --smoke \
  --smoke-size 3 \
  --exercises-dir /benchmarks/polyglot-benchmark
python3 benchmark/summarize_runs.py
```

The smoke step is successful only if
`runs/real-smoke-gpt41mini/child.txt` shows `completed_tests: 3` and
`expected_tests: 3`, and `runs/summary.csv` contains the corresponding
benchmark row. If it fails before model calls, fix Docker, the mounted
`/benchmarks/polyglot-benchmark` directory, or `OPENAI_API_KEY` first.

## Prepare Polyglot benchmark data

The Polyglot exercises are not bundled with this repo. Prepare the pinned
checkout from the host repo root:

```bash
python3 benchmark/prepare_polyglot.py
```

The script fetches `https://github.com/Aider-AI/polyglot-benchmark.git` at
commit `7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`, writes it to
`tmp.benchmarks/polyglot-benchmark`, and records provenance in
`tmp.benchmarks/polyglot-benchmark/.aider-polyglot-provenance.json`.

Inside Docker, use the host-prepared data through the benchmark mount:

```bash
test -d /benchmarks/polyglot-benchmark
```

Verify the host directory exists before starting a smoke run:

```bash
test -d tmp.benchmarks/polyglot-benchmark
```

Then run a no-cost smoke validation after preparation:

```bash
python3 benchmark/run_baseline.py \
  --dry-run \
  --run-name real-smoke-gpt41mini \
  --model gpt-4.1-mini \
  --edit-format diff \
  --threads 1 \
  --smoke \
  --smoke-size 3 \
  --validate-smoke
```

Do not paste API keys into terminal transcripts or logs. Prefer exporting
`OPENAI_API_KEY` in your shell, or loading it from a local `.env`-style shell
setup that is not committed.

## Real smoke benchmark

The wrapper creates a tiny deterministic exercises directory from the existing
Polyglot benchmark, then runs the normal `benchmark.py` harness against that
copy. It selects the first `N` sorted `language/exercises/practice/exercise`
paths, so the default smoke set is stable across runs and the original
`polyglot-benchmark` checkout is never mutated.

Run it inside Docker when you are ready for hosted model calls:

```bash
python3 benchmark/run_baseline.py \
  --run-name real-smoke-gpt41mini \
  --model gpt-4.1-mini \
  --edit-format diff \
  --threads 1 \
  --smoke \
  --smoke-size 3
```

To make the Docker exercise path explicit:

```bash
python3 benchmark/run_baseline.py \
  --run-name real-smoke-gpt41mini \
  --model gpt-4.1-mini \
  --edit-format diff \
  --threads 1 \
  --smoke \
  --smoke-size 3 \
  --exercises-dir /benchmarks/polyglot-benchmark
```

From the host repo root, use the host path when validating without cost:

```bash
python3 benchmark/run_baseline.py \
  --dry-run \
  --run-name smoke-gpt41mini-explicit \
  --smoke \
  --smoke-size 3 \
  --validate-smoke \
  --exercises-dir tmp.benchmarks/polyglot-benchmark
```

Pass `OPENAI_API_KEY` as an environment variable inside Docker, for example
with `export OPENAI_API_KEY=...`. The wrapper records only whether the variable
is set, never the key value.

Use `--threads 1` for smoke validation. A single worker makes setup failures,
model authentication errors, and per-exercise artifacts easier to inspect before
spending more on parallel requests.

The smoke exercises are created under the benchmark mount:
`tmp.benchmarks/smoke-exercises/<run-name>/` on the host, or
`/benchmarks/smoke-exercises/<run-name>/` inside Docker when
`AIDER_BENCHMARK_DIR=/benchmarks` is set. The real benchmark artifacts are still
written by `benchmark.py` under
`tmp.benchmarks/YYYY-MM-DD-HH-MM-SS--<run-name>/`.

`benchmark.py --exercises-dir` joins relative values to `AIDER_BENCHMARK_DIR`.
For smoke runs the wrapper passes the copied smoke directory as an absolute
path, so the harness reads the exact subset created for that run instead of
looking for a relative path under the benchmark directory.

Non-dry-run wrapper invocations fail before invoking `benchmark.py` unless
`AIDER_DOCKER` is set. This mirrors `benchmark.py`'s own host-safety guard,
which prints "benchmarking runs unvetted code from GPT, run in a docker
container" and returns before task discovery.

Summarize the result:

```bash
python3 benchmark/summarize_runs.py
```

For 1 to 5 `gpt-4.1-mini` smoke tasks, expect a small hosted-model charge,
typically cents or less, depending on retries, prompt size, and whether tests
pass on the first attempt. Check `runs/summary.csv` for the actual captured
cost when the benchmark emits it.

Delete smoke artifacts when you are done:

```bash
rm -rf tmp.benchmarks/smoke-exercises/real-smoke-gpt41mini
rm -rf tmp.benchmarks/*--real-smoke-gpt41mini
rm -rf runs/real-smoke-gpt41mini
```

## Full run

Run the full gpt-4.1-mini diff baseline:

```bash
python3 benchmark/run_baseline.py \
  --run-name full-gpt41mini-diff \
  --model gpt-4.1-mini \
  --edit-format diff \
  --threads 1
```

On a 16GB M1 Mac, start with one thread. Increase `--threads` only after a
smoke run confirms Docker, dependencies, model access, and test commands are
working reliably.

You can pass through additional `benchmark.py` flags after the wrapper flags,
for example:

```bash
python3 benchmark/run_baseline.py --run-name python-smoke --smoke --languages python
```

## Metadata and results

For each wrapper run, `runs/<run-name>/` contains:

- `command.txt`: the exact `benchmark/benchmark.py` command.
- `child.txt`: for non-dry-runs, the child command, exit code, stdout/stderr
  log paths, artifact dirs discovered after exit, and completed/total counts.
- `benchmark.stdout.log` and `benchmark.stderr.log`: captured child output.
- `git.txt`: branch, commit SHA, dirty status, and short status output.
- `env.txt`: Python/platform details, model, edit format, threads, exercise
  directory, Docker marker, and whether `OPENAI_API_KEY` is set. The key value
  is never written.
- `smoke_tasks.txt`: for smoke runs, the deterministic selection strategy,
  source directory, smoke directory, and selected task paths.

The benchmark harness writes raw artifacts under `tmp.benchmarks/`. Each
completed exercise normally has a `.aider.results.json` file with outcomes,
cost, timing, token counts, and error counters.

## Summaries

Create or refresh a CSV summary:

```bash
python3 benchmark/summarize_runs.py
```

This scans `tmp.benchmarks/`, prints a small table, and writes
`runs/summary.csv`. You can point it at explicit directories:

```bash
python3 benchmark/summarize_runs.py tmp.benchmarks/2026-05-26-12-00-00--smoke-gpt41mini
```

The summarizer supports the current Polyglot artifact layout,
`<run>/<language>/exercises/practice/<exercise>/.aider.results.json`, and falls
back to finding `.aider.results.json` anywhere under a run directory. Incomplete
runs and missing fields are included with blank or zero values where needed.

## Success and failure

A successful smoke run creates a dated benchmark directory, writes at least one
`.aider.results.json`, and the summary shows completed tests with pass rates,
cost, and seconds per case.

A failed setup usually looks like one of these:

- `AIDER_DOCKER` warning: enter the benchmark Docker container before running.
- Missing Polyglot exercises: the wrapper checks `polyglot-benchmark`,
  `benchmark/polyglot-benchmark`, `tmp.benchmarks/polyglot-benchmark`, and
  `/benchmarks/polyglot-benchmark`, in that order. Clone the exercises into
  `tmp.benchmarks/polyglot-benchmark` on the host before starting Docker, or
  pass `--exercises-dir` explicitly. If smoke setup fails at this point, no
  model or API call has happened yet.
- Model authentication errors: confirm `OPENAI_API_KEY` is set inside Docker.
- Incomplete summaries: inspect the raw exercise directories and rerun with
  `--cont` passed through if appropriate.

## No-cost validation

These commands do not call hosted models:

```bash
python3 benchmark/run_baseline.py --dry-run --run-name smoke-gpt41mini --smoke --smoke-size 3
python3 benchmark/summarize_runs.py --help
```
