# CLAUDE.md — CrewListr Pro

Operational notes for agentic work in this repo. Keep it tight; it loads every session.

## Don't run more of the suite than the change needs

`python -m pytest -q` is seven test files here, so the full run is cheap and
there is no `ci_scope.py` — the sibling repositories carry one
(`TEST_SCOPE=changed pytest`, from mozaix #962) because their suites are
thousands of tests; this one is not.

What still applies is the machine. `hosted-allowance` and the Linux leg of
`quality` run on the Mac Studio shared by every repository's self-hosted
runners and by every agent session — it has sat at load 50 on 20 cores, and a
container holding a job is capped at 4 CPUs while that lasts. While the hosted
allowance is out, **every** job in `ci.yml` is on that one box. Long local
loops (`mypy` over everything in a watch loop, repeated full builds) cost CI
directly.

## CI

`.github/workflows/ci.yml` runs on pull requests and on pushes to `main`. One
run in flight per ref: a newer commit cancels the older run rather than
queueing behind it.

**Read `hosted-allowance` before touching any `runs-on`.** The account's
included minutes ran out on 2026-09-06, and GitHub does not fail a hosted job
when that happens — it refuses to START it, so the job ends in seconds with no
steps and reads on the checks list exactly like a code regression. That gate
decides whether the hosted legs exist at all, and says so on every run. Adding
a new hosted job outside it reintroduces the confusion it was built to remove.
