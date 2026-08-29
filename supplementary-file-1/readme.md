# TigerAI Query script implementation with tutorial

## Setup

First, set up Python venv:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements
```

Second, make sure that your API keys are in the secrets file:

```bash
# secrets file format (only include the key(s) you need):
export OPENAI_API_KEY=your_openai_key    # for GPT-4o, GPT-5
export GOOGLE_API_KEY=your_google_key    # for Gemini 3 Pro
```

> **Note:** You don't need both keys. Only provide the API key for the service you plan to use.

Then source it:

```bash
source secrets
```

> ⚠️ **Important:** Always activate the virtual environment (`source venv/bin/activate`) before running any query scripts!

---

## Common Configuration

All scripts share the same input format, core arguments, and output structure.

### Input File Format

The input TSV file must contain these columns (see `data/pp_13k.tsv`):

| Column | Description |
|--------|-------------|
| `gene` | Target gene symbol |
| `indication_mesh_term` | Indication/disease name |
| `indication_mesh_id` | MeSH identifier (used for output file naming only) |

> **Note:** The `indication_mesh_id` column only affects output file naming (`{target}-{mesh}.json`), not inference.

### Core CLI Arguments

| Argument | Description |
|----------|-------------|
| `-w, --workers` | Concurrent workers (default: 1) ¹ |
| `-o, --output` | Output directory **(required)** |
| `--data` | Input TSV file (default: `data/pp_13k.tsv`) |
| `--single` | Single query mode (alternative to batch file processing) |
| `--target` | Target gene symbol (required with `--single`) |
| `--indication` | Indication name (required with `--single`) |
| `--mesh` | MeSH ID (optional with `--single`, defaults to indication name) |

¹ Not available for `query_gpt5_batch.py`

### Output

- Results saved as `{target}-{mesh}.json` in the output directory
- `batch_summary.txt` generated with processing statistics
- Existing output files are skipped (enables resumable processing)

> **Note:** To force re-run a query, delete the existing output file first.

---

## Scripts

> ⚠️ **Caution:** `data/pp_13k.tsv` contains 13,022 T-I pairs. Running the full dataset incurs high API costs! Use `data/test.tsv` (5 pairs) for testing. ⚠️

### Quick Reference

| Script | Model | Provider | Key Feature |
|--------|-------|----------|-------------|
| `query_gpt4o.py` | GPT-4o | OpenAI | Standard inference |
| `query_gpt5.py` | GPT-5 | OpenAI | Configurable reasoning |
| `query_gpt5_batch.py` | GPT-5 | OpenAI | Batch API (50% cost savings) |
| `query_gemini3pro.py` | Gemini 3 Pro | Google | Thinking mode |

---

### query_gpt4o.py

Standard GPT-4o inference with no additional configuration.

```bash
python code/query_gpt4o.py -w 5 -o result/gpt4o --data data/test.tsv
```

---

### query_gpt5.py

GPT-5 with configurable reasoning mode.

**Additional Arguments:**

| Argument | Description |
|----------|-------------|
| `--reasoning-effort` | `low`, `medium`, `high` (default: `high`) |
| `--verbosity` | `low`, `medium`, `high` (default: `high`) |

```bash
# Default (high reasoning, high verbosity)
python code/query_gpt5.py -w 5 -o result/gpt5 --data data/test.tsv

# Custom settings
python code/query_gpt5.py --single --target BRCA1 --indication "Breast cancer" -o result/gpt5 --reasoning-effort medium --verbosity low
```

---

### query_gpt5_batch.py

Batch API for GPT-5 with 50% cost savings. Suitable for non-time-sensitive workloads (up to 24h processing).

**Mode Arguments** (mutually exclusive):

| Argument | Description |
|----------|-------------|
| `--submit` | Submit a new batch job |
| `--check-status BATCH_ID` | Check status of existing job |
| `--retrieve-results BATCH_ID` | Download results from completed job |
| `--skip-existing` | Skip queries with existing output files (with `--submit`) |

**Workflow:**

```bash
# 1. Submit batch job
python code/query_gpt5_batch.py --submit -o result/gpt5_batch --data data/test.tsv
# Returns: batch_abc123

# 2. Check status
python code/query_gpt5_batch.py --check-status batch_abc123

# 3. Retrieve results when complete
python code/query_gpt5_batch.py --retrieve-results batch_abc123 -o result/gpt5_batch
```

> **Note:** Reasoning effort and verbosity are fixed at `high` for batch jobs (to reduce moving parts). You can revise them manually (line 510-517).

---

### query_gemini3pro.py

Gemini 3 Pro with thinking mode enabled.

```bash
python code/query_gemini3pro.py -w 5 -o result/gemini3pro --data data/test.tsv
```
