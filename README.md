# geo-tracker

geo-tracker shows which URLs Perplexity, ChatGPT, Claude and Gemini cite when they answer the questions that your audience asks. You run it weekly and compare the results.

## What it does

For each prompt in your list, geo-tracker does these steps:

1. It sends the question to four answer engines.
2. It records the response and its citations.
3. It tags each cited host as `self` (yours) or not.
4. It writes all of it to an append-only SQLite ledger.

One OpenRouter key covers all four engines. A sweep of forty prompts across four engines (160 cells) usually costs less than five dollars. Provider and search pricing varies, so see [Cost](docs/details.md#cost).

```text
$ geo-tracker init && geo-tracker run --label baseline && geo-tracker summary

Self-citations per engine:
  perplexity        3
  openai            1

Top 10 cited domains:
  github.com                                 17
  example.com                                 4 *
  docs.example.com                            2 *
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

All four return citations in the same field, so one parser handles every engine. OpenRouter is moving away from the `:online` suffix. [Grounding and OpenRouter drift](docs/details.md#grounding-and-openrouter-drift) explains the effect.

## Install

The package is not on PyPI yet. Install it from source (Python 3.10 or newer):

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
geo-tracker reparse                    # re-extract citations from stored raw responses
```

Get an OpenRouter key at <https://openrouter.ai/keys>. [geo-tracker in detail](docs/details.md) gives all flags, a weekly cron entry, the schema and the reasons for the append-only design.

## Layout

```text
geo_tracker/   CLI, engine adapters, parser, storage, summary
examples/      sample prompts.yaml and self_domains.yaml
tests/         tests
docs/          details for readers
```

## What this is not

It does not write content. It is not a dashboard. It cannot game the engines. The output is a SQLite file for your own tools.

## License

MIT. See [LICENSE](LICENSE).
