# TigerAI

Supplementary files for **TigerAI: An AI-powered genetic evidence platform to support clinical development**.

- TigerAI platform: <https://tigerai.bio/>
- Drug development and human expert-curated genetic evidence data: <https://github.com/ericminikel/genetic_support/>

## Supplementary files

| Path | Description |
|------|-------------|
| [`supplementary-file-1/`](supplementary-file-1/) | Supplementary code to run our prompt and replicate our results with the associated datasets. See its [readme](supplementary-file-1/readme.md) for setup and usage. |
| [`supplementary-file-2.md`](supplementary-file-2.md) | Safeguarding report for drug and trial information leakage during LLM inference. We provide detailed methodology and findings from our safety evaluation of the results. |

### Contents of `supplementary-file-1/`

| Path | Description |
|------|-------------|
| `code/query_gpt4o.py` | Query script for GPT-4o |
| `code/query_gpt5.py` | Query script for GPT-5 (configurable reasoning effort and verbosity) |
| `code/query_gpt5_batch.py` | Query script for GPT-5 via the OpenAI Batch API |
| `data/pp_13k.tsv` | 13,022 target-indication pairs used in the study |
| `data/test.tsv` | 5 target-indication pairs for testing |
| `prompt-and-schema.md` | The verbatim developer prompt and JSON schema |
| `requirements` | Python dependencies |

To download all files as a single archive, use **Code → Download ZIP** on this repository page.
