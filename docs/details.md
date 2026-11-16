# geo-tracker in detail

This file keeps the detail from the earlier README. The [README](../README.md) gives the short version.

## Why GEO

SEO measured which page Google linked to. GEO measures which page the answer itself names. It is a different game with a different feedback loop. You can run a tool against the new game, and this is one.

## Grounding and OpenRouter drift

The `:online` suffix tells OpenRouter to put a web-search loop around the model. All four engines return citations in the same normalized field (`choices[0].message.annotations[].url_citation`). Thus one parser handles every engine.

OpenRouter is moving from the `:online` suffix to a `plugins: [{id: web}]` request field. The annotation shape is the same, so this parser continues to work. If the shortcut goes away in a future release, we will change the transport. Open an issue if you see it break.

## Cost

One API key (OpenRouter) covers all four engines. A cell typically costs a few cents, because provider and search pricing varies. A sweep of forty prompts across four engines (160 cells) usually costs less than five dollars and finishes in a couple of minutes.

## Full sample output

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

## Flags

```
geo-tracker run --engines perplexity,openai     # subset
geo-tracker run --concurrent 10                 # parallel cells (default 5)
geo-tracker summary --run-id 3                  # specific run
geo-tracker reparse                             # re-extract citations from old raw responses
geo-tracker reparse --run-id 3                  # ...for one run only
```

Run `reparse` after you edit `self_domains.yaml` or increase `parser.PARSER_VERSION`. It reads the stored raw responses and runs the current parser. Then it appends new citation rows with the current version. The old rows stay. `summary` always uses the latest `parser_version` per run, so it does not count a citation twice.

## Run it weekly

Cron entry:

```cron
0 6 * * 0  cd /opt/geo-tracker && /opt/geo-tracker/.venv/bin/geo-tracker run --label "$(date -u +%Y-W%V)"
```

This runs one sweep at Sunday 06:00 UTC, with the ISO week as label. Every run is its own row. You can compare any two weeks by `run_id`.

## Schema

SQLite has three tables (`geo_tracker/storage.py`):

- `runs`: one row per invocation. Columns: id, started_at, label, config_json.
- `events`: one row per (run, prompt, engine) call. A failure also makes a row, with `fetch_status` set to `error` or `timeout` and the raw exception text. The ledger never has gaps.
- `citations`: one row per cited URL. It includes `parser_version`, so historical rows survive a parser upgrade.

If you change the citation extractor, increase `geo_tracker/parser.PARSER_VERSION` and run `geo-tracker reparse`. Old citation rows keep their original interpretation. New rows go next to them with the new version. `summary` uses the latest version per run.

## Why append-only

There are two reasons:

1. You will change `self_domains.yaml` and want to re-classify last month's data without paying OpenRouter again. The raw responses are in the ledger, and `geo-tracker reparse` does this.
2. A comparison of week N to week N+4 works only if both rows are exactly what came back at the time. An overwrite removes the comparison.

## What this is not

- It is not a content generator. It tells you which URLs the engines cite. It does not write the content that gets cited.
- It is not a dashboard. The output is a SQLite file. Point Metabase, Datasette or a notebook at it.
- It cannot game the engines. Treat the output as ground truth about your current visibility. Then improve the content that the engines should cite.
