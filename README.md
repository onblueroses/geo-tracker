# geo-tracker

Measure how often LLM answer engines (Perplexity, ChatGPT search, Claude search, Gemini search) cite *your* URLs when users ask the questions your audience would ask.

GEO (Generative Engine Optimization) is what SEO became when the destination stopped being the search-results page and became the answer itself. You can't optimize what you don't measure. This is a small tool that measures it.

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

`*` = matches your `self_domains.yaml`.

## How it works

For every prompt × every engine, geo-tracker fires one query through OpenRouter (so you only need one API key for all four), captures the response + the citation list, classifies each cited domain as `self` or other, and writes everything to an append-only SQLite ledger. Re-run weekly to track movement.

The four engines:

| Engine | OpenRouter model |
|--------|------------------|
| Perplexity | `perplexity/sonar-pro` |
| OpenAI (web search) | `openai/gpt-4o-mini:online` |
| Anthropic (web search) | `anthropic/claude-3.5-haiku:online` |
| Gemini (web search) | `google/gemini-2.5-flash:online` |

The `:online` suffix activates OpenRouter's web-search augmentation; citations come back in a normalized shape (`choices[0].message.annotations[].url_citation`) so one parser handles all four.

## Install

```bash
pip install geo-tracker
```

Or from source:

```bash
git clone https://github.com/onblueroses/geo-tracker
cd geo-tracker
pip install -e .
```

## Usage

```bash
# 1. Scaffold prompts.yaml, self_domains.yaml, .env, and an empty SQLite DB
geo-tracker init

# 2. Edit the YAML files with your prompts + domains
# 3. Put OPENROUTER_API_KEY in .env (get a key at https://openrouter.ai/keys)

# 4. Run one full sweep
geo-tracker run --label "2026-W21-baseline"

# 5. See the citation rollup
geo-tracker summary
```

A run with 10 prompts × 4 engines costs roughly $0.05 in OpenRouter credits and takes about 30 seconds with the default `--concurrent 5`.

## Run it weekly

Drop it in cron:

```cron
0 6 * * 0  cd /opt/geo-tracker && /opt/geo-tracker/.venv/bin/geo-tracker run --label "$(date -u +%Y-W%V)"
```

The ledger is append-only, so every run is its own row in `runs` with all events + citations attached. Compare any two weeks by their `run_id`.

## Schema

The SQLite DB has three tables (see `geo_tracker/storage.py`):

- `runs(id, started_at, label, config_json)` — one row per invocation
- `events(id, run_id, prompt, engine, model, fetch_status, response_text, raw_response_json, latency_ms, ...)` — one row per (run, prompt, engine) call. Failures still produce a row (`fetch_status` = `error` or `timeout`) so the ledger never has gaps.
- `citations(id, event_id, parser_version, cited_url, cited_domain, rank, snippet, is_self)` — one row per cited URL.

Bump `geo_tracker/parser.PARSER_VERSION` when you change the citation extractor; old citation rows keep their original version tag.

## Why an append-only ledger?

Two reasons. First, you'll want to re-parse historical raw responses when you tweak classification (new self-domain? add it and re-run the parser). Second, comparing week N to week N+4 only works if you trust both as-recorded — overwriting kills longitudinal analysis.

## What this is not

- Not a content generator. It tells you which URLs the engines cite; it doesn't write the content that gets cited.
- Not an alerting system. It gives you a ledger; build the dashboard you want on top.
- Not a way to game the engines. Treat its output as ground truth about your current visibility, then improve your underlying content.

## License

MIT. See [LICENSE](./LICENSE).
