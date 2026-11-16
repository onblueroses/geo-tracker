# geo-tracker

geo-tracker shows which URLs Perplexity, ChatGPT, Claude and Gemini cite when they answer the questions that your audience asks. It also counts the answers that name your brand. You run it weekly and compare the results.

## What it does

For each prompt in your list, geo-tracker does these steps:

1. It sends the question to four answer engines.
2. It records the response and its citations.
3. It tags each cited host as `self` (yours) or not.
4. It finds the names from your `brands.yaml` in the answer text.
5. It writes all of it to an append-only SQLite ledger.

A failed call gets its own row with the error. geo-tracker never counts a failed call as an answer that does not cite you.

The output below is an illustration with example domains, not a real run.

```text
$ geo-tracker init && geo-tracker run --label baseline && geo-tracker summary

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

`*` flags hosts from your `self_domains.yaml`. "mention you" counts the answers that name a brand from your `brands.yaml`.

A name matches as a whole word, in any letter case. Thus "Acme" matches "acme's" but not "Acmeville". [Brand mentions](docs/details.md#brand-mentions) gives the full rule.

## The four engines

| Engine | OpenRouter model | Grounding |
|--------|------------------|-----------|
| Perplexity | `perplexity/sonar-pro` | native |
| OpenAI | `openai/gpt-6-luna:online` | OpenRouter web plugin |
| Anthropic | `anthropic/claude-haiku-5.5:online` | OpenRouter web plugin |
| Gemini | `google/gemini-4-hydrogen:online` | OpenRouter web plugin |

We checked these IDs against the [OpenRouter model list](https://openrouter.ai/api/v1/models) on 2026-11-16. For OpenAI, Anthropic and Google, each is the current fast, low-cost model. Perplexity keeps Sonar Pro. For these providers, the web plugin uses the native search of the provider. All four return citations in the same field, so one parser handles every engine. [Grounding](docs/details.md#grounding) gives more detail.

One OpenRouter key covers all four engines. [Cost](docs/details.md#cost) gives the search fees.

## Bedrock engines

OpenRouter is the default provider. `--provider bedrock` uses AWS Bedrock instead:

| Engine | Bedrock model | Grounding |
|--------|---------------|-----------|
| bedrock-anthropic | `us.anthropic.claude-haiku-5-5` | none (model memory) |
| bedrock-openai | `us.openai.gpt-6-luna` | none (model memory) |
| bedrock-nova | `us.amazon.nova-2-lite-v1:0` | Nova web grounding |

bedrock-anthropic and bedrock-openai do not search the web. They measure what the model knows from its training data, not what a search finds. Thus they give mention counts but no citations. Do not compare their citation counts with the search engines. bedrock-nova uses the `nova_grounding` web search tool of Bedrock and gives citations.

The IDs are US cross-region inference profiles, so call them from a US region. We checked them with `aws bedrock list-inference-profiles` in us-east-2 on 2026-11-16. Your AWS account must have access to each model. [Bedrock](docs/details.md#bedrock) gives more detail.

## Install

The package is not on PyPI yet. Install it from source (Python 3.11 or newer):

```bash
git clone https://github.com/onblueroses/geo-tracker
cd geo-tracker
pip install -e .        # or: uv sync
pip install -e '.[bedrock]'   # only for the Bedrock engines (adds boto3)
```

## Usage

```bash
geo-tracker init                       # scaffold prompts.yaml, self_domains.yaml, brands.yaml, .env, empty DB
$EDITOR prompts.yaml                   # the questions your audience would type
$EDITOR self_domains.yaml              # your hosts
$EDITOR brands.yaml                    # your brand names and aliases
$EDITOR .env                           # OPENROUTER_API_KEY=...
geo-tracker run --label baseline       # query all engines for all prompts
geo-tracker summary                    # citation and mention rollup for the latest run
geo-tracker reparse                    # re-extract citations and mentions from stored responses
geo-tracker run --provider bedrock     # the Bedrock engines, with your AWS credentials
```

`run` exits with code 1 if one or more cells failed. The failed cells are in the ledger with their error. Re-run to retry them.

Get an OpenRouter key at <https://openrouter.ai/keys>. The Bedrock engines need no key in `.env`. boto3 finds your AWS credentials and region with its usual chain (environment, `~/.aws` files, instance role). [geo-tracker in detail](docs/details.md) gives all flags, a weekly cron entry, the schema and the reasons for the append-only design.

## Development

```bash
uv sync --extra dev
uv run pytest
```

The tests make no network calls and use no API key. One live Bedrock test runs only with `GEO_TRACKER_LIVE_BEDROCK=1` and AWS credentials. `pytest -rs` shows why it skipped.

## Layout

```text
geo_tracker/   CLI, engine adapters, parser, mention matcher, storage, summary
examples/      sample prompts.yaml, self_domains.yaml and brands.yaml
tests/         tests
docs/          details for readers
```

## What this is not

It does not write content. It is not a dashboard. It cannot game the engines. The output is a SQLite file for your own tools.

## License

MIT. See [LICENSE](LICENSE).
