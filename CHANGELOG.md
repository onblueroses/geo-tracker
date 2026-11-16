# Changelog

## 0.3.0 (not released yet)

Brand mentions:

- `brands.yaml` lists your brand names and aliases. `init` writes a sample.
- Each answer gets mention rows per brand: the count and the first matched text. The match is a whole word in any letter case.
- `summary` shows "mention you" per engine. `reparse` adds mentions to older runs from their stored answer text.
- Without `./brands.yaml` and without `--brands`, the run does not measure mentions. It prints a note and records the parse as "not measured".

AWS Bedrock provider:

- `--provider bedrock` runs three Bedrock engines through the Converse API: `bedrock-anthropic` (Claude Haiku 5.5), `bedrock-openai` (GPT-6 Luna) and `bedrock-nova` (Nova 2 Lite).
- bedrock-anthropic and bedrock-openai do not search. They measure model memory, not search citations. bedrock-nova uses the `nova_grounding` web search tool and gives citations.
- OpenRouter stays the default provider.
- The parser reads Bedrock citations (`PARSER_VERSION` 2).
- The `bedrock` extra installs boto3.

Other changes:

- The OpenRouter client uses the timeouts of the OpenAI SDK, not its own values.
- `summary` widens the engine column for long engine names.
