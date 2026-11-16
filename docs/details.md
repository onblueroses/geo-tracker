# geo-tracker in detail

This file keeps the detail from the earlier README. The [README](../README.md) gives the short version.

## Why GEO

SEO measured which page Google linked to. GEO measures which page the answer itself names. It is a different game with a different feedback loop. You can run a tool against the new game, and this is one.

## Grounding

The `:online` suffix tells OpenRouter to add its web plugin to the request. For OpenAI, Anthropic, Google and Perplexity models, the plugin uses the native search of the provider. Perplexity Sonar searches on its own, so it needs no suffix.

All four engines return citations in the same normalized field (`choices[0].message.annotations[].url_citation`). Thus one parser handles every engine.

OpenRouter documents `:online` as a shortcut for the request field `plugins: [{"id": "web"}]`. The annotation shape is the same for both. If the shortcut goes away, we will change the transport. Open an issue if you see it break.

## Models

We checked the model IDs against the [OpenRouter model list](https://openrouter.ai/api/v1/models) on 2026-11-16. For OpenAI, Anthropic and Google, we chose the current fast, low-cost model. Perplexity Sonar Pro is still current:

| Engine | Model | Released on OpenRouter | Replaces |
|--------|-------|------------------------|----------|
| Perplexity | `perplexity/sonar-pro` | 2025-03-07 | (no change) |
| OpenAI | `openai/gpt-6-luna:online` | 2026-09-22 | `openai/gpt-4o-mini:online` |
| Anthropic | `anthropic/claude-haiku-5.5:online` | 2026-10-07 | `anthropic/claude-3.5-haiku:online` |
| Gemini | `google/gemini-4-hydrogen:online` | 2026-11-12 | `google/gemini-2.5-flash:online` |

The model list no longer has `anthropic/claude-3.5-haiku`. To change a model, edit `ENGINES` in `geo_tracker/adapters/engines.py`. Each event row stores the model it used, so a model change stays visible in the ledger.

## Bedrock

`--provider bedrock` sends each prompt to the Bedrock Converse API through boto3. It does not use OpenRouter or `OPENROUTER_API_KEY`. Install it with `pip install -e '.[bedrock]'`. The extra asks for boto3 1.44 or newer. 1.44 is the version we tested, not a measured minimum.

- bedrock-anthropic (`us.anthropic.claude-haiku-5-5`) and bedrock-openai (`us.openai.gpt-6-luna`) get no search tool. They answer from model memory. A memory answer has no citations. Its mention count tells you if the model knows your brand without a search. It does not tell you what a search engine finds.
- bedrock-nova (`us.amazon.nova-2-lite-v1:0`) gets the `nova_grounding` system tool. Nova decides when to search. The citations come back as `citationsContent` blocks, and the parser reads them (`PARSER_VERSION` 2).
- The answer text is the text blocks of the answer, in order. Reasoning, tool and citation blocks are not answer text.
- A stop reason other than `end_turn`, `stop_sequence` or `max_tokens` is an error row. Examples are `guardrail_intervened`, `content_filtered` and `tool_use`.
- An empty answer is an error row, as for OpenRouter.

boto3 finds credentials and the region with its usual chain. `run` stops with exit code 2 if it finds no credentials or no region. Timeouts and retries are the [botocore defaults](https://docs.aws.amazon.com/botocore/latest/reference/config.html). A read timeout is a `timeout` row.

The model IDs are US cross-region inference profiles. We checked them with `aws bedrock list-foundation-models` and `list-inference-profiles` in us-east-2 on 2026-11-16. To change a model, edit `ENGINES` in `geo_tracker/adapters/engines.py`. Bedrock bills by token, and web grounding can have its own fee. Check the [Bedrock pricing page](https://aws.amazon.com/bedrock/pricing/) before a large sweep.

## Cost

One API key (OpenRouter) covers all four engines. The model list gives these search fees for each request on 2026-11-16:

| Engine | Search fee |
|--------|------------|
| Perplexity | $0.005 |
| OpenAI | $0.01 |
| Anthropic | $0.01 |
| Gemini | $0.014 |

Thus the search fees for one prompt on all four engines are about $0.04. A sweep of forty prompts (160 cells) has about $1.56 in search fees. Token cost comes on top and depends on the length of each answer. Check the current prices on OpenRouter before a large sweep.

## Full sample output

```
$ geo-tracker init && geo-tracker run --label baseline && geo-tracker summary

=== Run 1 (baseline) ===
started_at: 2026-11-16T06:00:04+00:00
parse: 1 (parser_version 1)
brands: Acme, Acme Labs

Cells per engine:
  anthropic       error           1
  anthropic       ok              7
  gemini          ok              8
  openai          ok              8
  perplexity      ok              8

Per engine, ok cells only (cells citing you, citations, cells mentioning you):
  engine             cite you  cites  mention you
  anthropic          0 / 7         0     2 / 7     (1 failed, not counted)
  gemini             0 / 8         0     1 / 8
  openai             1 / 8         1     3 / 8
  perplexity         3 / 8         4     5 / 8

Top 4 cited domains:
  github.com                                  17
  example.com                                  4 *
  docs.example.com                             2 *
  postgresql.org                               2
```

`*` flags hosts from your `self_domains.yaml`. A "cell" is one call for one (prompt, engine) pair. The per-engine table counts only `ok` cells. It shows the failed cells next to the counts, so a failure never looks like "not cited" or "not mentioned".

"mention you" counts the `ok` cells whose answer text names one or more of your brands. A cell that names a brand three times counts once. A dash means that the parse did not measure mentions, because it had no `brands.yaml`.

## Brand mentions

List your brand names in `brands.yaml`. An entry is a name, or a name with aliases:

```yaml
- name: Acme
  aliases:
    - Acme Cloud
    - acme.example
- Acme Labs
```

geo-tracker counts each brand apart. The aliases of a brand count for that brand. These rules apply:

- The match ignores letter case. "ACME" and "acme" match "Acme".
- The name must be a whole word. The character before and after it must not be a letter, a digit or an underscore. This applies to letters in all scripts.
- Thus "Acme" matches "Acme's", "(acme)" and "Acme-based". It does not match "Acmeville", "MyAcme" or "acme2".
- A dot or space in a name matches only that dot or space. "Acme Cloud" does not match "Acme  Cloud" with two spaces.
- geo-tracker normalizes the text and the names to Unicode NFC first. Thus a composed and a decomposed "é" are the same letter.
- If two names of one brand overlap, the longer name wins. "Acme Cloud" is one mention, not two.

geo-tracker reads only the answer text, not the cited URLs or their titles. A cited host from your domain is a citation, not a mention.

By default, `run` and `reparse` read `./brands.yaml`. Use `--brands PATH` to give a different file. If you give a path that does not exist, geo-tracker stops with exit code 2. If `./brands.yaml` does not exist and you give no path, geo-tracker does not measure mentions. It prints a note and records the parse as "not measured". An empty brands file is an error.

If you change the matching rule, increase `geo_tracker/mentions.MATCHER_VERSION`. Each mention row stores the version that made it.

## Flags

```
geo-tracker run --engines perplexity,openai     # subset
geo-tracker run --concurrent 10                 # parallel cells (default 5)
geo-tracker summary --run-id 3                  # specific run
geo-tracker reparse                             # re-extract citations from old raw responses
geo-tracker reparse --run-id 3                  # ...for one run only
geo-tracker run --brands brands/acme.yaml       # brands file (default ./brands.yaml)
geo-tracker run --provider bedrock              # Bedrock engines (default: openrouter)
geo-tracker run --provider bedrock --engines bedrock-nova
```

`--engines` rejects a name that it does not know. It does not skip the name. It also rejects an engine of a different provider.

Run `reparse` after you edit `self_domains.yaml` or `brands.yaml`, or increase `parser.PARSER_VERSION`. It reads the stored responses and runs the current parser and matcher. Then it appends one new parse with its citation and mention rows. The old rows stay. `summary` always uses the latest parse of a run, so it does not count a citation or a mention twice.

`reparse` also adds mentions to runs from before v0.3, because their answer text is in the ledger.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success. |
| 1 | A run had one or more failed cells, or a runtime error occurred. |
| 2 | Bad input: a flag, a config file or a missing API key. |

A cron job or a CI step can use the exit code to find a sweep with failures.

## Failures

geo-tracker fails closed. It records a failure as a failure, never as an answer that cites nothing. Each cell gets exactly one event row with one of these `fetch_status` values:

- `ok`: the engine returned answer text.
- `timeout`: the call did not finish in time.
- `error`: the API call failed, the response had an error, or the answer text was empty.
- `parse_error`: the parser or the brand matcher failed. The row keeps the raw response for inspection.

The OpenAI SDK retries connection errors, rate limits and server errors with its default policy. geo-tracker sets no timeout of its own. A request to OpenRouter times out after the [OpenAI SDK default](https://github.com/openai/openai-python#timeouts) of 10 minutes. For Bedrock, botocore retries and times out with its [defaults](https://docs.aws.amazon.com/botocore/latest/reference/config.html). geo-tracker does not retry a cell after that. Re-run to retry.

`reparse` also fails closed. If one stored response does not decode or parse, the whole reparse rolls back.

## Run it weekly

Cron entry:

```cron
0 6 * * 0  cd /opt/geo-tracker && /opt/geo-tracker/.venv/bin/geo-tracker run --label "$(date -u +%Y-W%V)"
```

This runs one sweep at Sunday 06:00 UTC, with the ISO week as label. Every run is its own row. You can compare any two weeks by `run_id`.

## Schema

SQLite has five tables (`geo_tracker/storage.py`):

- `runs`: one row per invocation. Columns: id, started_at, label, config_json.
- `events`: one row per (run, prompt, engine) call. A failure also makes a row, with its `fetch_status` and the error text. The ledger never has gaps.
- `parses`: one row per parse pass. A run makes its first parse. Each `reparse` adds one more. `run_id` is empty when a reparse covers all runs. `brands_json` holds the brands of the parse. It is empty when the parse did not measure mentions.
- `citations`: one row per cited URL in one parse. It includes `parse_id` and `parser_version`, so historical rows survive a parser upgrade.
- `mentions`: one row per brand that one answer names, in one parse. It holds the brand, the number of matches, the first matched text, `parse_id` and `matcher_version`.

If you change the citation extractor, increase `geo_tracker/parser.PARSER_VERSION` and run `geo-tracker reparse`. Old citation rows keep their original interpretation. New rows go next to them with the new parse. `summary` uses the latest parse per run.

A ledger from v0.1 gets the `parses` table and the `citations.parse_id` column the next time geo-tracker opens it. A ledger from v0.1 or v0.2 also gets the `mentions` table and the brand columns of `parses`. Its old rows do not change. Until you run `reparse`, `summary` reads an old run by its highest `parser_version` and shows its mentions as not measured.

## Why append-only

There are two reasons:

1. You will change `self_domains.yaml` or `brands.yaml` and want to re-classify last month's data without paying OpenRouter again. The raw responses are in the ledger, and `geo-tracker reparse` does this.
2. A comparison of week N to week N+4 works only if both rows are exactly what came back at the time. An overwrite removes the comparison.

## What this is not

- It is not a content generator. It tells you which URLs the engines cite. It does not write the content that gets cited.
- It is not a dashboard. The output is a SQLite file. Point Metabase, Datasette or a notebook at it.
- It cannot game the engines. Treat the output as ground truth about your current visibility. Then improve the content that the engines should cite.
