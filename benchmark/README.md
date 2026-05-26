
# Aider benchmark harness

Aider uses benchmarks to quantitatively measure how well it works
with various LLMs.
This directory holds the harness and tools needed to run the benchmarking suite.

## Background

The benchmark is based on the [Exercism](https://github.com/exercism/python) coding exercises.
This
benchmark evaluates how effectively aider and LLMs can translate a
natural language coding request into executable code saved into
files that pass unit tests.
It provides an end-to-end evaluation of not just
the LLM's coding ability, but also its capacity to *edit existing code*
and *format those code edits* so that aider can save the
edits to the local source files.

See [this writeup for a longer discussion about the benchmark](https://aider.chat/2024/12/21/polyglot.html).

The benchmark is intended to be run *inside a docker container*.
This is because the benchmarking harness will be
taking code written by an LLM
and executing it without any human review or supervision!
The LLM could generate dangerous python that harms your system, like this: `import os; os.system("sudo rm -rf /")`.
Running inside a docker container helps limit the damage that could be done.

## Usage

There are 3 main tasks involved in benchmarking aider:

1. Install and setup for benchmarking.

2. Run the benchmark to measure performance across all the exercises.

3. Generate a summary report of how many of the exercises succeeded or failed.

### Setup for benchmarking

First, prepare all the groundwork for running the benchmarks.
These steps only need to be done once.

```
# Clone the aider repo
git clone https://github.com/Aider-AI/aider.git

# Create the scratch dir to hold benchmarking results inside the main aider dir:
cd aider

# Prepare the repo with the exercises
python3 benchmark/prepare_polyglot.py

# Build the docker container
./benchmark/docker_build.sh
```

### Running the benchmark

Launch the docker container and run the benchmark inside it:

```
# Launch the docker container
./benchmark/docker.sh

# Inside the container, install aider as a development build.
# This way you're running the code that you cloned above, including any local changes.
pip install -e .[dev]

# Run the benchmark:
./benchmark/benchmark.py a-helpful-name-for-this-run --model gpt-3.5-turbo --edit-format whole --threads 10 --exercises-dir polyglot-benchmark
```

The above will create a folder `tmp.benchmarks/YYYY-MM-DD-HH-MM-SS--a-helpful-name-for-this-run` with benchmarking results.
Run like this, the script will run all the exercises in a random order.
`benchmark/docker.sh` mounts host `tmp.benchmarks/` at `/benchmarks` and sets
`AIDER_BENCHMARK_DIR=/benchmarks`, so the Docker path for the exercises is
`/benchmarks/polyglot-benchmark`.

You can run `./benchmark/benchmark.py --help` for a list of all the arguments, but here are the most useful to keep in mind:

- `--model` is the name of the model, same as you would pass directly to `aider`.
- `--edit-format` is the name of the edit format, same as you would pass directly to `aider`. When working with an experimental LLM, I recommend starting with `whole`
- `--threads` specifies how many exercises to benchmark in parallel. Start with a single thread if you are working out the kinks on your benchmarking setup or working with a new model, etc. Once you are getting reliable results, you can speed up the process by running with more threads. 10 works well against the OpenAI APIs.
- `--num-tests` specifies how many of the tests to run before stopping. This is another way to start gently as you debug your benchmarking setup.
- `--keywords` filters the tests to run to only the ones whose name match the supplied argument (similar to `pytest -k xxxx`).
- `--read-model-settings=<filename.yml>` specify model settings, see here: https://aider.chat/docs/config/adv-model-settings.html#model-settings

### Prepare Polyglot benchmark data

The Polyglot exercises are not bundled with this repo. From the host repo root,
prepare the pinned exercise checkout with:

```bash
python3 benchmark/prepare_polyglot.py
```

The script fetches `https://github.com/Aider-AI/polyglot-benchmark.git` at
commit `7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`, writes it to
`tmp.benchmarks/polyglot-benchmark`, and records provenance in
`tmp.benchmarks/polyglot-benchmark/.aider-polyglot-provenance.json`.
The source is pinned to that git commit; no archive checksum is needed because
the checkout resolves and records the commit hash.

Inside Docker, no different preparation command is needed. Prepare on the host,
start Docker with `./benchmark/docker.sh`, and verify the mounted directory:

```bash
test -d /benchmarks/polyglot-benchmark
```

Verify the host directory exists with:

```bash
find . -maxdepth 5 -type d -name 'polyglot-benchmark'
```

After preparation, run a dry-run smoke benchmark. Add `--validate-smoke` when
you want the wrapper to construct the copied smoke subset and verify that
`benchmark.py` would discover exactly those tasks without running the benchmark:

```bash
python3 benchmark/run_baseline.py \
  --dry-run \
  --run-name smoke-gpt41mini \
  --model gpt-4.1-mini \
  --edit-format diff \
  --threads 1 \
  --smoke \
  --smoke-size 3 \
  --validate-smoke
```

The first real smoke benchmark is manual and paid. Run it only inside the
benchmark Docker container when you are ready to make OpenAI API calls:

```bash
export OPENAI_API_KEY
python3 benchmark/run_baseline.py \
  --run-name real-smoke-gpt41mini \
  --model gpt-4.1-mini \
  --edit-format diff \
  --threads 1 \
  --smoke \
  --smoke-size 3
```

Do not paste API keys into terminal transcripts or logs. Prefer exporting
`OPENAI_API_KEY` in your shell, or loading it from a local `.env`-style shell
setup that is not committed. Use Docker for anything beyond tiny smoke
validation because the benchmark executes untrusted code generated by the
model.

Summarize real run artifacts after the smoke benchmark completes:

```bash
python3 benchmark/summarize_runs.py tmp.benchmarks
```

Exact host validation sequence:

```bash
python3 benchmark/prepare_polyglot.py
find . -maxdepth 5 -type d -name 'polyglot-benchmark'
python3 benchmark/run_baseline.py --dry-run --run-name smoke-gpt41mini --model gpt-4.1-mini --edit-format diff --threads 1 --smoke --smoke-size 3
python3 benchmark/run_baseline.py --dry-run --run-name smoke-gpt41mini --model gpt-4.1-mini --edit-format diff --threads 1 --smoke --smoke-size 3 --validate-smoke
```

### Baseline wrapper smoke runs

`benchmark/run_baseline.py` is a small wrapper that records reproducibility
metadata and can create a deterministic smoke subset before invoking the normal
benchmark harness.

`benchmark.py --exercises-dir` is interpreted under `AIDER_BENCHMARK_DIR`
(`tmp.benchmarks` by default) when the value is relative. Absolute paths are
accepted as-is. The wrapper therefore passes smoke subsets to `benchmark.py` as
absolute paths, because the host smoke directory is created at
`tmp.benchmarks/smoke-exercises/<run-name>/`.

By default the wrapper looks for the Polyglot benchmark exercises in these
locations, in order:

```text
polyglot-benchmark
benchmark/polyglot-benchmark
tmp.benchmarks/polyglot-benchmark
/benchmarks/polyglot-benchmark
```

You can make the location explicit from the host repo root:

```bash
python3 benchmark/run_baseline.py \
  --dry-run \
  --run-name smoke-gpt41mini-explicit \
  --smoke \
  --smoke-size 3 \
  --validate-smoke \
  --exercises-dir tmp.benchmarks/polyglot-benchmark
```

Inside Docker, the equivalent explicit path is:

```bash
export OPENAI_API_KEY
python3 benchmark/run_baseline.py \
  --run-name real-smoke-gpt41mini \
  --model gpt-4.1-mini \
  --edit-format diff \
  --threads 1 \
  --smoke \
  --smoke-size 3 \
  --exercises-dir /benchmarks/polyglot-benchmark
```

If a smoke run fails with a missing exercises directory before listing tasks,
no model or API call has happened yet. Create or mount
`polyglot-benchmark`, or pass `--exercises-dir` to the wrapper explicitly.
Non-dry-run wrapper invocations refuse to start on the host because
`benchmark.py` intentionally exits before task discovery unless `AIDER_DOCKER`
is set by the benchmark container.

For each non-dry-run wrapper invocation, inspect `runs/<run-name>/child.txt`,
`runs/<run-name>/child.json`, `benchmark.stdout.log`, and
`benchmark.stderr.log` for the exact child command, exit code, captured output
paths, selected smoke directory, expected task count, completed result count,
and any artifact directories found after `benchmark.py` exits. A successful
3-task smoke run must show `completed_tests: 3` and `expected_tests: 3` in
`child.txt`; otherwise the wrapper exits non-zero.

### Benchmark report

You can generate stats about any benchmark, including ones which are still running.
You don't need to run this inside the docker container, as it is just
collecting stats not executing unsafe python.

```
# Generate stats for a specific benchmarking directory
./benchmark/benchmark.py --stats tmp.benchmarks/YYYY-MM-DD-HH-MM-SS--a-helpful-name-for-this-run
```

The benchmark report is a yaml record with statistics about the run:

```yaml
- dirname: 2024-07-04-14-32-08--claude-3.5-sonnet-diff-continue
  test_cases: 225
  model: claude-3.5-sonnet
  edit_format: diff
  commit_hash: 35f21b5
  pass_rate_1: 57.1
  pass_rate_2: 77.4
  percent_cases_well_formed: 99.2
  error_outputs: 23
  num_malformed_responses: 4
  num_with_malformed_responses: 1
  user_asks: 2
  lazy_comments: 0
  syntax_errors: 1
  indentation_errors: 0
  exhausted_context_windows: 0
  test_timeouts: 1
  command: aider --sonnet
  date: 2024-07-04
  versions: 0.42.1-dev
  seconds_per_case: 17.6
  total_cost: 3.6346
```

The key statistics are the `pass_rate_#` entries, which report the
percent of the tasks which had all tests passing.
There will be multiple of these pass rate stats,
depending on the value of the `--tries` parameter.

The yaml also includes all the settings which were in effect for the benchmark run.
It also reports the git hash of the repo at the time that the benchmark was
run, with `(dirty)` if there were uncommitted changes.
It's good practice to commit the repo before starting a benchmark run.
This way the `model`, `edit_format` and `commit_hash`
should be enough to reliably reproduce any benchmark run.

You can see examples of the benchmark report yaml in the
[aider leaderboard data files](https://github.com/Aider-AI/aider/blob/main/aider/website/_data/).


## Limitations, notes

- Contributions of benchmark results are welcome! Submit results by opening a PR with edits to the
[aider leaderboard data files](https://github.com/Aider-AI/aider/blob/main/aider/website/_data/).
- These scripts are not intended for use by typical aider end users.
- Some of these tools are written as `bash` scripts, so it will be hard to use them on Windows.
