# geo-tracker

When someone asks Perplexity or ChatGPT or Claude or Gemini a question your audience cares about, which URLs does the model actually cite? This tells you. Weekly. With receipts.

SEO measured which page Google linked to. GEO measures which page got named inside the answer. Different game, different feedback loop. You can run a tool against the new game; this is one.

## What it does

For every prompt in your list, geo-tracker fires the question at four answer engines, captures the response and the citation set, tags each cited host as `self` (yours) or not, and writes everything to an append-only SQLite ledger. Re-run on Sundays; diff this week against last week.

One API key (OpenRouter) covers all four engines. A cell typically costs a few cents (provider + search pricing varies); a sweep of forty prompts across four engines (160 cells) usually lands under five dollars and finishes in a couple of minutes.

```
$ geo-tracker init && geo-tracker run --label baseline && geo-tracker summary

Cells per engine:
  perplexity      ok        8
  openai          ok        8
  anthropic       ok        7
  anthropic       error     1
  gemini          ok        8

Self-citations per engine:
  perplexity        3
  openai            1

Top 10 cited domains:
  github.com                                 17
  example.com                                 4 *
  docs.example.com                            2 *
  postgresql.org                              2
  ...
```

`*` flags hosts from your `self_domains.yaml`.

## The four engines

| Engine | OpenRouter model | Grounding |
|--------|------------------|-----------|
| Perplexity | `perplexity/sonar-pro` | native |
| OpenAI | `openai/gpt-4o-mini:online` | OpenRouter web search |
| Anthropic | `anthropic/claude-3.5-haiku:online` | OpenRouter web search |
| Gemini | `google/gemini-2.5-flash:online` | OpenRouter web search |

The `:online` suffix tells OpenRouter to wrap a web-search loop around the model. All four return citations in the same normalized field (`choices[0].message.annotations[].url_citation`), so one parser handles every engine.

> **Note on OpenRouter drift.** OpenRouter is migrating from the `:online` suffix to a `plugins: [{id: web}]` request field. The annotation shape is the same, so this parser keeps working, but if the shortcut goes away in a future release we'll switch transports. Open an issue if you see it break.

## Install

From source (the package isn't on PyPI yet):

```bash
git clone https://github.com/onblueroses/geo-tracker
cd geo-tracker
pip install -e .
```

## Usage

```bash
geo-tracker init                       # scaffold prompts.yaml, self_domains.yaml, .env, empty DB
$EDITOR prompts.yaml                   # the questions your audience would type
$EDITOR self_domains.yaml              # your hosts
$EDITOR .env                           # OPENROUTER_API_KEY=...
geo-tracker run --label baseline       # query all engines for all prompts
geo-tracker summary                    # citation rollup for the latest run
```

Useful flags:

```
geo-tracker run --engines perplexity,openai     # subset
geo-tracker run --concurrent 10                 # parallel cells (default 5)
geo-tracker summary --run-id 3                  # specific run
geo-tracker reparse                             # re-extract citations from old raw responses
geo-tracker reparse --run-id 3                  # ...for one run only
```

`reparse` is what you run after editing `self_domains.yaml` or bumping `parser.PARSER_VERSION`. It walks the stored raw responses, runs the current parser, and appends new citation rows tagged with the current version. The old rows stay; `summary` always uses the latest parser_version per run, so no double-counting.

Get an OpenRouter key at <https://openrouter.ai/keys>.

## Run it weekly

Cron entry:

```cron
0 6 * * 0  cd /opt/geo-tracker && /opt/geo-tracker/.venv/bin/geo-tracker run --label "$(date -u +%Y-W%V)"
```

Sunday 06:00 UTC, one sweep, ISO-week-tagged. Every run is its own row; compare any two weeks by `run_id`.

## Schema

Three tables in SQLite (`geo_tracker/storage.py`):

- `runs`: one row per invocation. id, started_at, label, config_json.
- `events`: one row per (run, prompt, engine) call. Failures still produce a row with `fetch_status` set to `error` or `timeout` and the raw exception text captured. The ledger never has gaps.
- `citations`: one row per cited URL. Includes `parser_version` so historical rows survive a parser upgrade.

If you change the citation extractor, bump `geo_tracker/parser.PARSER_VERSION` and run `geo-tracker reparse`. Old citation rows keep their original interpretation; new rows land alongside them tagged with the new version. `summary` uses the latest version per run.

## Why append-only

Two reasons. First, because you'll tweak `self_domains.yaml` and want to re-classify last month's data without re-paying OpenRouter, and the raw responses are right there (`geo-tracker reparse` does this). Second, comparing week N to week N+4 only works if both rows are exactly what came back at the time. Overwriting throws away the comparison.

## What this is not

Not a content generator. It tells you which URLs the engines cite; it doesn't write the content that gets cited.

It's not a dashboard either. The output is a SQLite file; point Metabase or Datasette or a notebook at it.

And it can't game the engines. Treat the output as ground truth about your current visibility, then go improve the content the engines should have been citing.

## License

MIT. See [LICENSE](./LICENSE).
