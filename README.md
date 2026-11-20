# cheaprecords

Compare JB Hi-Fi vinyl record prices against the Discogs marketplace.

```console
$ cheaprecords fleetwood mac rumours
Record                                          In stock  JB Hi-Fi  Discogs low  Median  For sale  Pressings       Rating  Difference
Fleetwood Mac - Rumours (Vinyl) (2025 Reissue)       yes     69.99        28.31   42.41       346     5 of 5  4.75 (2216)      +41.68
FLEETWOOD MAC - Rumours Live (Vinyl)                 yes    105.00        47.47   51.44       127     4 of 4   4.62 (289)      +57.53

Discogs prices are the lowest asking price in AUD, in any condition, before postage.
Rating is the Discogs community's average out of 5 for the most collected pressing, with the number of votes.
Difference is JB Hi-Fi minus Discogs low; negative means JB Hi-Fi is cheaper.
```

## Usage

Requires [uv](https://docs.astral.sh/uv/) and Google Chrome.

Nothing about the two sites is built in. Tell the tool where they are with
environment variables:

| Variable                   | Value                                                         |
| -------------------------- | ------------------------------------------------------------- |
| `CHEAPRECORDS_JBHIFI_URL`  | address of the JB Hi-Fi storefront, as in your browser's address bar, without a path |
| `CHEAPRECORDS_DISCOGS_URL` | address of the Discogs API, from the Discogs developer documentation |
| `CHEAPRECORDS_JBHIFI_DEALS_URL` | only for `--deals`: address of a JB Hi-Fi page listing discounted vinyl, such as its vinyl clearance page |
| `DISCOGS_TOKEN`            | optional: a Discogs personal access token (see below)         |

An `.envrc` (for direnv) or `.env` file in the
checkout is a handy place for them; both are gitignored, so addresses and
tokens stay out of the repository.

```bash
uv sync
uv run cheaprecords                           # the newest additions to JB Hi-Fi's vinyl
uv run cheaprecords --deals                   # the records on JB Hi-Fi's deals page
uv run cheaprecords coltrane love supreme     # search JB Hi-Fi's vinyl range
uv run cheaprecords radiohead --limit 25      # compare more records (default 10)
uv run cheaprecords <product page address>    # compare a JB Hi-Fi product page
uv run cheaprecords coltrane --json           # machine-readable output
uv run cheaprecords --help
```

There are three views, each listed with JB Hi-Fi's best prices relative to
Discogs first:

- **Newest** (no arguments): the records most recently added to JB Hi-Fi's
  range. New releases are rarely cheaper than Discogs, so this is more
  "what's new" than a bargain finder.
- **Best deals** (`--deals`): the records on JB Hi-Fi's deals page. These
  are already discounted, so this is where JB Hi-Fi most often beats
  Discogs. Only the records the page shows when first opened are read
  (about 36), not those behind its "load more" button.
- **Search** (words or product page addresses): words are matched against
  JB Hi-Fi's product URLs, which hold the artist and title, so every word
  has to appear there.

| Column      | Meaning                                                                  |
| ----------- | ------------------------------------------------------------------------ |
| JB Hi-Fi    | JB Hi-Fi's current price for a new copy                                  |
| Discogs low | cheapest Discogs listing among the pressings checked                     |
| Median      | median of each checked pressing's cheapest listing                       |
| For sale    | copies listed on Discogs across the pressings checked                    |
| Pressings   | Discogs pressings priced, of those sharing the barcode (`--max-pressings`) |
| Rating      | Discogs community's average rating out of 5 for the most collected pressing, with the number of votes |
| Difference  | JB Hi-Fi minus Discogs low; negative means JB Hi-Fi is cheaper           |

Set `DISCOGS_TOKEN` to a Discogs personal access token (created under
Developers in your Discogs account settings) to raise the Discogs rate
limit from 25 to 60 requests a minute. When the limit runs out the tool
waits a minute and carries on.

### How it works

1. **Find records.** The first search or newest view downloads JB Hi-Fi's
   public sitemap (about a minute) and keeps a list of its vinyl product
   URLs for a week; `--reindex` rebuilds it. The deals view reads the
   record links from the deals page instead.
2. **Read JB Hi-Fi.** Each matching product page is loaded in headless
   Chrome, one at a time with a pause between pages, and the price and
   barcode are read from the page's structured data. JB Hi-Fi turns away
   plain HTTP clients, which is why a real browser is used.
3. **Price on Discogs.** The barcode is looked up with the Discogs API and
   the marketplace's lowest price fetched for each matching pressing, plus
   the community rating of the pressing most collectors own.

JB Hi-Fi prices are cached for 6 hours and Discogs prices for 24, under
`~/.cache/cheaprecords` (or `$XDG_CACHE_HOME/cheaprecords`); `--refresh`
ignores both.

### Things to know

- **It compares new with mostly second-hand.** Discogs prices are the
  lowest asking price in any condition, from sellers anywhere, before
  postage. Treat a big difference as a prompt to look, not as a saving.
- **One barcode, many pressings.** A barcode often matches several Discogs
  pressings with quite different prices; only the first `--max-pressings`
  are priced, so compare the low and the median.
- **No match** means Discogs has no vinyl release with JB Hi-Fi's barcode.
- **Keep it small and personal.** Every record costs a page load at JB
  Hi-Fi and several Discogs requests. Both sites have terms of use that
  restrict automated access and reuse of their data; this is meant for
  checking a handful of records for yourself, not for mirroring a catalogue.

## Development

A fully-typed Python project wired up with the [Astral](https://astral.sh)
toolchain:

- **[uv](https://docs.astral.sh/uv/)** — packaging, virtualenv, and dependency management
- **[ruff](https://docs.astral.sh/ruff/)** — linting and formatting
- **[ty](https://docs.astral.sh/ty/)** — type checking
- **[pytest](https://docs.pytest.org/)** + **[pytest-cov](https://pytest-cov.readthedocs.io/)** — testing and coverage
- **[pre-commit](https://pre-commit.com/)** — runs the checks on every commit

### Layout

```
.
├── .copier-answers.yml     # template answers, used by `copier update` (don't edit)
├── .gitignore
├── .pre-commit-config.yaml # file hygiene + lint/format/type-check hooks (also used by CI)
├── .python-version         # dev interpreter, pinned to the minimum supported (3.12)
├── LICENSE                 # GPL-3.0-or-later
├── pyproject.toml          # project metadata + tool config (ruff, ty, pytest, coverage)
├── uv.lock                 # locked dependency versions (commit this)
├── scripts/
│   └── ci.sh               # everything CI runs; also runnable locally
├── src/
│   └── cheaprecords/
│       ├── __init__.py
│       ├── __main__.py     # CLI entry point
│       ├── browser.py      # loads JB Hi-Fi pages in headless Chrome
│       ├── cache.py        # on-disk cache for the index and prices
│       ├── compare.py      # sets the two prices side by side; table and JSON
│       ├── config.py       # site addresses and token, from the environment
│       ├── discogs.py      # Discogs API: barcode lookup and marketplace prices
│       ├── jbhifi.py       # JB Hi-Fi: sitemap index and product page parsing
│       └── py.typed        # marks the package as typed (PEP 561)
└── tests/                  # run offline; the network and browser are faked
```

A `src/` layout is used so that tests run against the installed package
rather than the working directory, catching packaging mistakes early.

### Getting started

```bash
git init                        # if needed: pre-commit only works inside a git repo
uv sync                         # create .venv (and uv.lock) and install everything
uv run pre-commit install       # run the checks automatically on every commit
uv run cheaprecords --help      # see Usage above
uv run python -m cheaprecords   # the same CLI, run as a module
```

`uv sync` reads `pyproject.toml` + `uv.lock` and builds a reproducible
environment in `.venv`. You never need to activate it manually — prefix
commands with `uv run`. The first `uv sync` creates `uv.lock`; commit it,
because CI runs `uv sync --locked`, which fails without it.

### Common tasks

```bash
uv run pre-commit run --all-files   # all static checks: hygiene, lock, lint, format, types
uv run ruff check .
uv run ruff format .
uv run ty check                     # warnings fail too (set in pyproject.toml)
uv run pytest                       # tests only; pass a path or -k to run a subset
uv run pytest --cov                 # tests + coverage (fails below 90%)
uv audit                            # check uv.lock for known vulnerabilities
scripts/ci.sh                       # everything CI runs (see below)
```

### Continuous integration

The checks live in the repo, not in any CI provider's config, so any CI
system (GitLab CI, Bitbucket Pipelines, Forgejo/Gitea Actions, Jenkins, …)
only needs [uv](https://docs.astral.sh/uv/getting-started/installation/)
installed and to run:

```bash
scripts/ci.sh
```

The script runs, in order:

1. `uv sync --locked` — fails if `uv.lock` is missing or out of date
2. `pre-commit run --all-files` — file hygiene, lockfile, lint, format, types
3. `pytest --cov` on every supported Python version (3.12, 3.13, 3.14), each
   in a throwaway `--isolated` environment so `.venv` is left untouched
4. `uv audit` — checks the locked dependencies against the
   [OSV](https://osv.dev) vulnerability database (needs network access;
   `uv audit` is still marked experimental by uv)

When adding or dropping a Python version, update the list at the top of
`scripts/ci.sh` along with `requires-python` and the classifiers in
`pyproject.toml`.

### Managing dependencies

```bash
uv add requests            # add a runtime dependency
uv add --dev mypy          # add a dev-only dependency
uv remove requests         # remove one
uv lock --upgrade          # refresh the lockfile
```

### Configuration

All tool configuration lives in `pyproject.toml`:

- `[tool.ruff]` / `[tool.ruff.lint]` / `[tool.ruff.format]`
- `[tool.ty.environment]` / `[tool.ty.src]` / `[tool.ty.rules]` / `[tool.ty.terminal]`
- `[tool.pytest]` (pytest's native TOML config, with `strict = true`)
- `[tool.coverage.run]` / `[tool.coverage.report]`

Adjust the selected ruff rule set and ty rule severities there to match
your team's preferences.

### Updating from the template

This project was generated with [Copier](https://copier.readthedocs.io/),
and your answers are recorded in `.copier-answers.yml`. To pull in later
improvements to the template:

```bash
uvx copier update               # needs a clean git working tree
```

Copier merges the template changes into your files; review the diff (and
resolve any conflicts) before committing.
