import argparse
import pandas as pd
import json
import hashlib
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict
from openai import OpenAI

def get_output_file_path(target: str, mesh: str, output_dir: str) -> Path:
    """Get expected output file path."""
    output_path = Path(output_dir)

    # Output file: output_dir/{safe_target}-{safe_mesh}.json
    safe_target = "".join(c for c in target if c.isalnum() or c in ('-', '_'))
    safe_mesh = "".join(c for c in mesh if c.isalnum() or c in ('-', '_'))
    output_file = output_path / f"{safe_target}-{safe_mesh}.json"

    return output_file


def check_existing_results(target: str, mesh: str, output_dir: str) -> bool:
    """Check if output file already exists."""
    output_file = get_output_file_path(target, mesh, output_dir)
    return output_file.exists()


def replace_template_variables(template: str, target_symbol: str, indication_name: str, mesh: str) -> str:
    """Replace template variables in the prompt."""
    return (template
            .replace("**{{target_symbol}}**", target_symbol)
            .replace("{{target_symbol}}", target_symbol)
            .replace("**{{indication_name}}**", indication_name)
            .replace("{{indication_name}}", indication_name)
            .replace("**{{mesh}}**", mesh)
            .replace("{{mesh}}", mesh))


def get_prompt_templates():
    """Return the developer and user prompt templates."""

    developer_prompt_template = """
## ROLE AND OBJECTIVE
You are an expert in human genetics, functional genomics, systems biology, model organism genetics with domain knowledge in **{{indication_name}}**. Your task is to determine whether a given Target-Indication (T-I) pair reflects a **causal, human-relevant biological relationship** by integrating all relevant evidence from human genetics, functional studies, and animal models.

**Downstream use**: we will use your causal, human-relevant calls to **evaluate whether genetic evidence improves clinical-trial success prediction**. To avoid leakage/circularity, **do not consult, use, or mention any information about drugs, drug classes, therapeutic modalities, or clinical-trial design/results/endpoints/approvals** anywhere in your reasoning, evidence gathering, scoring, or summaries.

## FOCUS T-I PAIR
* Target (gene or protein): **{{target_symbol}}**
* Indication (disease or phenotype): **{{indication_name}}**

## EVIDENCE UNIVERSE (GATHER AND SUMMARIZE)
Synthesize evidence from broad literature and data sources (**prioritize curated/peer-reviewed sources; among curated sources, prefer the latest releases**). **Summarize what each source claims with identifiers/accessions.**

* **(A) Human genetics:** GWAS Catalog and summary statistics; **Open Targets Genetics credible sets**; Gene Burden (e.g., whole genome sequence and exome sequence such as  GeneBass); Cancer Gene Census; IntOGen; fine-mapping; **colocalization with molecular QTLs** (eQTLs, sQTLs, pQTLs, caQTLs, mQTLs); transcriptome-wide association study (**TWAS**); proteome-wide association study (**PWAS**); phenome-wide association (**PheWAS**); Mendelian randomization; **rare variant burden/LoF ("human knockouts")**; mutational constraint.
* **(B) Functional genomics:** tissue or cell type expression (e.g., **GTEx**, Expression Atlas/Single Cell Expression Atlas, **Human Protein Atlas**); regulatory and epigenomic context; perturbation data (e.g., **CRISPR** or **Perturb-seq**), **MPRA**; pathway or process membership (e.g., **Reactome / GO**); protein-protein and genetic interaction networks (e.g., **STRING / BioGRID**); Variant-to-Gene (V2G) links (e.g., promoter capture Hi-C/HiChIP/PLAC-seq, enhancer-promoter models, allele-specific chromatin, and CRISPRi/a enhancer tiling that connect noncoding signals to **{{target_symbol}}**).
* **(C) Animal and model organisms:** knockout or knock-in phenotypes; **require orthology quality (Ensembl Compara) and uPheno/Monarch phenotype alignment before counting as supportive**; otherwise mark **non-informative**.
* **(D) Literature-mined knowledge for breadth:** **Europe PMC / PubMed / PMC** for primaries; **Crossref** for metadata; **LitVar 2.0** for variant-literature linking; **SemMedDB** for mined predicates. **Always verify mined claims with primary sources.**

**Deduplication:** Count each finding once per unique primary study/accession; mark mirrored databases in notes.

## REASONING REQUIREMENTS
* **Direction of Effect (DoE):** infer whether **increased or decreased target activity/expression** is linked to **increased or decreased indication risk/severity**, **prioritizing convergent human lines of evidence** (fine-mapped loci, colocalized QTLs, rare LoF or missense, PheWAS).
* **Cells of action:** infer the most plausible tissues or cell types using **ct-eQTL**, **sc-eQTL**, expression, **ATAC-seq**, and related data.
* **Gene-gene context:** consider **paralogs**, functional redundancy, **network neighbors**, pathway role, and potential **synthetic/epistatic interactions**.
* **Functional and animal work:** use as **support only when orthology is strong**, phenotype class maps via **uPheno/Monarch**, and **DoE and tissue context align with human evidence**; otherwise mark **non-informative**. Only when orthology is strong and the uPheno/Monarch phenotype class is discordant should animal evidence be treated as refuting.
* **Conflict handling:** if credible studies disagree (e.g., alternative causal gene at locus, discordant DoE across tissues, assay artifacts), **present both sides and justify which is stronger** based on design, replication, and relevance.
* **Cross-ancestry replication:** **ancestry-specific effects are expected** for many T-I pairs. Record ancestry-specific effects in HGC (with notes). Do **not** count heterogeneity as inconsistency or include it in CONSISTENCY unless a study explicitly refutes causality.
* **Leakage control (canonical):** Exclude all interventional or treatment-stratified findings and **do not consult, use, or cite** any drug/clinical-trial sources (e.g., ClinicalTrials.gov, FDA/EMA labels, DrugBank, ChEMBL **drug-response** entries, Open Targets Drugs module, trial papers, company press releases). Use only non-interventional human genetics and aligned functional/model evidence.
* **Causality:** make a **carefully considered call only when multiple, orthogonal lines of evidence converge**. **Prioritize coherent, mutually reinforcing findings** indicating a truly causal, human-relevant relationship and **justify the assigned score**.

## EVIDENCE LEDGER
* The JSON field "evidence_register" is the canonical evidence ledger. Every claim asserted in any section of the JSON must have >=1 supporting entry in "evidence_register".
* **Evidence:** human genetic anchors (fine-mapped + QTL colocalization; replicated rare variant associations; coherent PheWAS), functional assays, animal phenotypes aligned via uPheno/Monarch, null findings, alternative gene at the locus, platform artifacts (e.g., pQTL epitope binding), tissue mismatch, credible animal models showing discordant phenotypes.

## SCORING (**QUALITATIVE ONLY; NO NEW COMPUTATIONS**)
Assign **conservative 0--6 scores** with one decimal place. **Report what sources claim; do not compute new statistics.**
* **HGC (Human Genetic Causality, 0--6):** strength and replication of human genetic anchors; clarity of causal gene; **cross-ancestry support**; clarity of **DoE**.
* **BIO_COH (Biological Coherence, 0--6):** tissue/cell relevance, pathway placement, **network proximity**; consistency of mechanism with observed phenotypes.
* **FUNC_ANIMAL (Functional and Animal, 0--6):** rigor and **human alignment** of functional and animal evidence; **penalize discordance or weak orthology**.
* **CONSISTENCY (Consistency of Evidence, 0--6):** agreement across different studies and across the HGC, BIO_COH, and FUNC_ANIMAL categories. **Higher means greater consistency**; 0 = severe, replicated contradictions; 3 = mixed/unclear; 6 = highly coherent across lines. Cross-ancestry heterogeneity is not inconsistency.
* **ICES (Integrated Causal Evidence Score, 0--6):** a **brief (2--10 sentence) rationale** integrating the above.

**Verdict is determined solely from ICES:**
* **0.0--1.9** Insufficient
* **2.0--2.9** Weak
* **3.0--3.9** Moderate
* **4.0--4.9** Strong
* **5.0--6.0** Very Strong.
Do not average other sub-scores to set the verdict.

# LLM MODE QUALITY GUARDS
- **Cite or omit rule**: do not assert facts (effects, directions, replication) without a citation to a primary or curated source such as GWAS Catalog, GTEx or eQTL Catalogue, pQTL resources, ClinGen or GenCC, IMPC or MGI, Reactome or GO, STRING or BioGRID, PubMed or PMC.
- **Two-source confirmation for major claims**: for the **main causal claim** and **DoE**, cite at least two independent sources or one large multi-cohort source.
- **Refutation duty**: actively search for counterevidence (null findings, alternative gene at locus, discordant functional or animal results) and record it in the summarized evidence.
- **Do not compute**: report statistics as stated in sources (for example PP4, p values, effect sizes). Do not run coloc, MR, or TWAS yourself.
- **Assay and platform caveats**: flag potential pQTL assay artifacts, including epitope-binding and platform discordance (Olink vs SomaScan). Prefer cis pQTL replicated across platforms.
- **Cross-species mapping**: treat animal phenotypes as supportive only if **orthology is strong** and **phenotype class aligns** via **uPheno or Monarch**; otherwise mark as **non-informative**. With strong orthology but discordant phenotype class after uPheno/Monarch mapping, mark as refuting.
- **Source credibility and freshness**: prefer **peer-reviewed primary studies with high citations or well-curated databases**; label preprints and mined triples (i.e., LitVar/SemMedDB) clearly and verify them with primaries.

## OUTPUT (**STRICT JSON BY SUB-CATEGORY**)
**Return a single JSON object**. For transparency and traceability, organize all evidence by scoring sub-category (HGC, BIO_COH, FUNC_ANIMAL, CONSISTENCY, ICES) with the following structure. For each sub-category, provide a summarized evidence list (no distinction between supporting and refuting). If there is no evidence for a sub-category, please state no available evidence identified. Include context links to evidence in all categories. Furthermore, scores must be based **only** on genetics/functional/model evidence above; **do not** use drug/trial information to raise or lower scores. Wrap the object in a fenced code block labeled `json`:

{
    "target": "{{target_symbol}}",
    "indication": "{{indication_name}}",
    "verdict": "Very Strong | Strong | Moderate | Weak | Insufficient",
    "scores": {
        "HGC": x.x,
        "BIO_COH": x.x,
        "FUNC_ANIMAL": x.x,
        "CONSISTENCY": x.x,
        "ICES": x.x
    },
    "evidence": {
        "HGC": [
            {"summary": "Summary of evidence for HGC", "citation": "PMID or DOI or URL"}
        ],
        "BIO_COH": [
            {"summary": "Summary of evidence for BIO_COH", "citation": "PMID or DOI or URL"}
        ],
        "FUNC_ANIMAL": [
            {"summary": "Summary of evidence for FUNC_ANIMAL", "citation": "PMID or DOI or URL"}
        ],
        "CONSISTENCY": [
            {"summary": "Synthesis of agreement/discordance across different studies and across the HGC, BIO_COH, and FUNC_ANIMAL categories; note any explicit refutations.", "citation": "PMID or DOI or URL"}
        ],
        "ICES": {
            "integration_summary": "2--10 sentence rationale integrating the above evidence with clear citations."
        }
    },
    "evidence_register": [
        {
            "source_type": "Human genetics | Functional genomics | Animal model | Literature-mined | Review",
            "id_or_url": "...",
            "trait_or_tissue": "...",
            "notes": "..."
        }
    ],
    "notes": "Maximum 500 words. Concise synthesis explaining why ICES and verdict are appropriate; cite 1 to 10 key sources."
}
```
"""

    user_prompt_template = """
Identify and summarize **causal, human-relevant biological relationship** by integrating all relevant evidence from human genetics, functional studies, and animal models for the following **Target-Indication** (T-I) pair:

* **Target (HGNC symbol or protein): **{{target_symbol}}**
* **Indication (disease or phenotype): **{{indication_name}}**
"""

    return developer_prompt_template, user_prompt_template


def get_json_schema():
    """Return the JSON schema for structured output."""
    return {
        "type": "json_schema",
        "name": "target_indication_evidence_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Gene or target symbol."
                },
                "indication": {
                    "type": "string",
                    "description": "Name of the disease or phenotype under investigation."
                },
                "verdict": {
                    "type": "string",
                    "description": "Overall verdict based solely on available evidence (not drugs/trials).",
                    "enum": [
                        "Very Strong",
                        "Strong",
                        "Moderate",
                        "Weak",
                        "Insufficient"
                    ]
                },
                "scores": {
                    "type": "object",
                    "properties": {
                        "HGC": {
                            "type": "number",
                            "description": "Score for Human Genetic Correlation sub-category."
                        },
                        "BIO_COH": {
                            "type": "number",
                            "description": "Score for Biochemical Cohort sub-category."
                        },
                        "FUNC_ANIMAL": {
                            "type": "number",
                            "description": "Score for Functional/Animal model sub-category."
                        },
                        "CONSISTENCY": {
                            "type": "number",
                            "description": "Score for Consistency/Agreement sub-category."
                        },
                        "ICES": {
                            "type": "number",
                            "description": "Integrated Combined Evidence Score."
                        }
                    },
                    "required": [
                        "HGC",
                        "BIO_COH",
                        "FUNC_ANIMAL",
                        "CONSISTENCY",
                        "ICES"
                    ],
                    "additionalProperties": False
                },
                "evidence": {
                    "type": "object",
                    "properties": {
                        "HGC": {
                            "type": "array",
                            "description": "Summarized evidence list for Human Genetics (HGC). State no available evidence if empty.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "summary": {
                                        "type": "string",
                                        "description": "Summary of supporting or refuting evidence."
                                    },
                                    "citation": {
                                        "type": "string",
                                        "description": "Context link or reference (PMID, DOI, or URL)."
                                    }
                                },
                                "required": [
                                    "summary",
                                    "citation"
                                ],
                                "additionalProperties": False
                            }
                        },
                        "BIO_COH": {
                            "type": "array",
                            "description": "Summarized evidence list for Biochemical Cohorts (BIO_COH). State no available evidence if empty.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "summary": {
                                        "type": "string",
                                        "description": "Summary of supporting or refuting evidence."
                                    },
                                    "citation": {
                                        "type": "string",
                                        "description": "Context link or reference (PMID, DOI, or URL)."
                                    }
                                },
                                "required": [
                                    "summary",
                                    "citation"
                                ],
                                "additionalProperties": False
                            }
                        },
                        "FUNC_ANIMAL": {
                            "type": "array",
                            "description": "Summarized evidence list for Functional/Animal models (FUNC_ANIMAL). State no available evidence if empty.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "summary": {
                                        "type": "string",
                                        "description": "Summary of supporting or refuting evidence."
                                    },
                                    "citation": {
                                        "type": "string",
                                        "description": "Context link or reference (PMID, DOI, or URL)."
                                    }
                                },
                                "required": [
                                    "summary",
                                    "citation"
                                ],
                                "additionalProperties": False
                            }
                        },
                        "CONSISTENCY": {
                            "type": "array",
                            "description": "Summarized synthesis of agreement or discordance, including explicit refutations. State no available evidence if empty.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "summary": {
                                        "type": "string",
                                        "description": "Synthesis of (dis)agreement across evidence lines; explicit refutations noted."
                                    },
                                    "citation": {
                                        "type": "string",
                                        "description": "Context link or reference (PMID, DOI, or URL)."
                                    }
                                },
                                "required": [
                                    "summary",
                                    "citation"
                                ],
                                "additionalProperties": False
                            }
                        },
                        "ICES": {
                            "type": "object",
                            "properties": {
                                "integration_summary": {
                                    "type": "string",
                                    "description": "2--10 sentence narrative integrating all above evidence and context links."
                                }
                            },
                            "required": [
                                "integration_summary"
                            ],
                            "additionalProperties": False
                        }
                    },
                    "required": [
                        "HGC",
                        "BIO_COH",
                        "FUNC_ANIMAL",
                        "CONSISTENCY",
                        "ICES"
                    ],
                    "additionalProperties": False
                },
                "evidence_register": {
                    "type": "array",
                    "description": "Register of indexed primary evidence sources for full transparency.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_type": {
                                "type": "string",
                                "description": "Type of evidence source.",
                                "enum": [
                                    "Human genetics",
                                    "Functional genomics",
                                    "Animal model",
                                    "Literature-mined",
                                    "Review"
                                ]
                            },
                            "id_or_url": {
                                "type": "string",
                                "description": "Identifier or URL of the evidence item."
                            },
                            "trait_or_tissue": {
                                "type": "string",
                                "description": "Trait or tissue context for the evidence."
                            },
                            "notes": {
                                "type": "string",
                                "description": "Evidence-specific notes."
                            }
                        },
                        "required": [
                            "source_type",
                            "id_or_url",
                            "trait_or_tissue",
                            "notes"
                        ],
                        "additionalProperties": False
                    }
                },
                "notes": {
                    "type": "string",
                    "description": "Concise synthesis and rationale for ICES and verdict, max 500 words."
                }
            },
            "required": [
                "target",
                "indication",
                "verdict",
                "scores",
                "evidence",
                "evidence_register",
                "notes"
            ],
            "additionalProperties": False
        }
    }


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="BATCH API QUERY RUNNER - Submit queries to OpenAI Batch API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Submit batch job with full dataset
  python query_type_A_batch_V20.py --submit --output results --data data/pp_13k.tsv

  # Submit batch job, skipping existing results
  python query_type_A_batch_V20.py --submit --output results --skip-existing

  # Check status of existing batch job
  python query_type_A_batch_V20.py --check-status batch_abc123

  # Retrieve results from completed batch
  python query_type_A_batch_V20.py --retrieve-results batch_abc123 --output results
        """
    )

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        '--submit',
        action='store_true',
        help='Submit full dataset as batch job'
    )
    mode_group.add_argument(
        '--check-status',
        type=str,
        metavar='BATCH_ID',
        help='Check status of an existing batch job'
    )
    mode_group.add_argument(
        '--retrieve-results',
        type=str,
        metavar='BATCH_ID',
        help='Retrieve and process results from completed batch job'
    )

    # Common arguments
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output directory path [REQUIRED for --submit and --retrieve-results]'
    )

    parser.add_argument(
        '--data',
        type=str,
        default='data/pp_13k.tsv',
        help='Path to the input TSV file (default: data/pp_13k.tsv)'
    )

    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='Skip queries that already have output files'
    )

    return parser.parse_args()


def load_data(data_path: str) -> pd.DataFrame:
    """Load TSV file."""
    print(f"\n📂 Loading data from: {data_path}")

    # Read TSV file
    df = pd.read_csv(data_path, sep='\t')
    total_rows = len(df)

    print(f"   Total rows in dataset: {total_rows}")

    return df


def create_batch_request(row: pd.Series, custom_id: str) -> dict:
    """Create a single batch request in the format required by OpenAI Batch API."""
    target = row['gene']
    indication = row['indication_mesh_term']
    mesh = row['indication_mesh_id']

    # Get templates
    developer_template, user_template = get_prompt_templates()

    # Replace variables
    developer_content = replace_template_variables(developer_template, target, indication, mesh)
    user_content = replace_template_variables(user_template, target, indication, mesh)

    # Get JSON schema
    json_schema = get_json_schema()

    # Create batch request
    batch_request = {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/responses",
        "body": {
            "model": "gpt-5",
            "input": [
                {
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": developer_content
                        }
                    ]
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": user_content
                        }
                    ]
                }
            ],
            "text": {
                "format": json_schema,
                "verbosity": "high"
            },
            "reasoning": {
                "effort": "high",
                "summary": "auto"
            },
            "tools": [],
            "store": True
        }
    }

    return batch_request


def generate_batch_jsonl(df: pd.DataFrame, output_dir: str, skip_existing: bool = False) -> tuple[Path, Dict]:
    """Generate JSONL file for batch API submission."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Create batch metadata
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_name = f"batch_{timestamp}"
    jsonl_file = output_path / f"{batch_name}.jsonl"

    # Track metadata
    metadata = {
        "batch_name": batch_name,
        "timestamp": timestamp,
        "total_queries": len(df),
        "queries": []
    }

    print(f"\n📝 Generating batch JSONL file...")
    print(f"   Output file: {jsonl_file}")

    skipped_count = 0
    included_count = 0

    # Create JSONL file
    with open(jsonl_file, 'w', encoding='utf-8') as f:
        for idx, row in df.iterrows():
            target = row['gene']
            indication = row['indication_mesh_term']
            mesh = row['indication_mesh_id']

            # Check if results already exist
            if skip_existing and check_existing_results(target, mesh, output_dir):
                skipped_count += 1
                print(f"   ⏭️  Skipping existing: {target} - {mesh}")
                continue

            # Generate custom_id
            custom_id = f"{target}|{indication}|{mesh}"

            # Create batch request
            batch_request = create_batch_request(row, custom_id)

            # Write to JSONL
            f.write(json.dumps(batch_request) + '\n')
            included_count += 1

            # Add to metadata
            metadata['queries'].append({
                "custom_id": custom_id,
                "target": target,
                "indication": indication,
                "mesh": mesh
            })

    metadata['included_queries'] = included_count
    metadata['skipped_queries'] = skipped_count

    print(f"   ✓ Generated {included_count} batch requests")
    if skip_existing:
        print(f"   ⏭️  Skipped {skipped_count} existing results")

    # Save metadata
    metadata_file = output_path / f"{batch_name}_metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)
    print(f"   ✓ Metadata saved to: {metadata_file}")

    return jsonl_file, metadata


def submit_batch_job(jsonl_file: Path, metadata: Dict) -> str:
    """Submit batch job to OpenAI API."""
    print(f"\n🚀 Submitting batch job to OpenAI...")

    client = OpenAI()

    # Upload file
    print(f"   📤 Uploading JSONL file...")
    with open(jsonl_file, 'rb') as f:
        batch_input_file = client.files.create(
            file=f,
            purpose="batch"
        )
    print(f"   ✓ File uploaded: {batch_input_file.id}")

    # Create batch
    print(f"   📋 Creating batch job...")
    batch = client.batches.create(
        input_file_id=batch_input_file.id,
        endpoint="/v1/responses",
        completion_window="24h",
        metadata={
            "batch_name": metadata['batch_name'],
            "total_queries": str(metadata['included_queries'])
        }
    )

    print(f"   ✓ Batch job created!")
    print(f"   Batch ID: {batch.id}")
    print(f"   Status: {batch.status}")
    print(f"   Total requests: {batch.request_counts.total if batch.request_counts else 'N/A'}")

    # Save batch ID to metadata
    metadata['batch_id'] = batch.id
    metadata['input_file_id'] = batch_input_file.id
    metadata['status'] = batch.status

    metadata_file = jsonl_file.parent / f"{metadata['batch_name']}_metadata.json"
    with open(metadata_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2)

    return batch.id


def check_batch_status(batch_id: str):
    """Check the status of a batch job."""
    print(f"\n🔍 Checking batch status: {batch_id}")

    client = OpenAI()
    batch = client.batches.retrieve(batch_id)

    print(f"\n📊 Batch Status:")
    print(f"   ID: {batch.id}")
    print(f"   Status: {batch.status}")
    print(f"   Created at: {datetime.fromtimestamp(batch.created_at).isoformat()}")

    if batch.request_counts:
        print(f"\n📈 Request Counts:")
        print(f"   Total: {batch.request_counts.total}")
        print(f"   Completed: {batch.request_counts.completed}")
        print(f"   Failed: {batch.request_counts.failed}")

    if batch.status == "completed":
        print(f"\n✅ Batch completed!")
        print(f"   Output file ID: {batch.output_file_id}")
        if batch.error_file_id:
            print(f"   Error file ID: {batch.error_file_id}")
    elif batch.status == "failed":
        print(f"\n❌ Batch failed!")
        if batch.errors:
            print(f"   Errors: {batch.errors}")
    elif batch.status in ["validating", "in_progress", "finalizing"]:
        print(f"\n⏳ Batch is still processing...")
        if batch.request_counts and batch.request_counts.total > 0:
            completed_pct = (batch.request_counts.completed / batch.request_counts.total) * 100
            print(f"   Progress: {completed_pct:.1f}%")
    elif batch.status == "cancelling" or batch.status == "cancelled":
        print(f"\n🚫 Batch was cancelled")

    return batch


def save_response_files(target: str, indication: str, mesh: str, response_data: dict, output_dir: str):
    """Save response to output file."""
    output_path = Path(output_dir)

    # Create response with metadata
    full_response = {
        "metadata": {
            "target_symbol": target,
            "indication_name": indication,
            "mesh": mesh,
            "timestamp": datetime.now().isoformat(),
            "source": "batch_api"
        },
        "response": response_data
    }

    # Save output file
    output_file = get_output_file_path(target, mesh, output_dir)

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(full_response, f, indent=2, ensure_ascii=False)

    return output_file


def retrieve_and_process_results(batch_id: str, output_dir: str):
    """Retrieve results from completed batch and process into output files."""
    print(f"\n📥 Retrieving results for batch: {batch_id}")

    client = OpenAI()

    # Get batch info
    batch = client.batches.retrieve(batch_id)

    if batch.status != "completed":
        print(f"❌ Batch is not completed yet. Current status: {batch.status}")
        return

    print(f"   ✓ Batch completed")
    print(f"   Output file ID: {batch.output_file_id}")

    # Download output file
    print(f"\n📥 Downloading results...")
    output_content = client.files.content(batch.output_file_id)
    output_data = output_content.read().decode('utf-8')

    # Parse JSONL results
    results = []
    for line in output_data.strip().split('\n'):
        if line:
            results.append(json.loads(line))

    print(f"   ✓ Retrieved {len(results)} results")

    # Process each result
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    success_count = 0
    error_count = 0

    print(f"\n💾 Processing results...")

    for result in results:
        try:
            custom_id = result['custom_id']
            # Parse custom_id: {target}|{indication}|{mesh}
            parts = custom_id.split('|')
            target = parts[0]
            indication = parts[1]
            mesh = parts[2]

            # Get response
            response = result.get('response', {})

            if response.get('status_code') == 200:
                body = response.get('body', {})

                # Extract the structured output
                response_data = body

                # Save file
                output_file = save_response_files(
                    target, indication, mesh, response_data, output_dir
                )

                print(f"   ✓ {target} - {mesh}")
                success_count += 1
            else:
                print(f"   ✗ Failed: {custom_id} (status: {response.get('status_code')})")
                error_count += 1

        except Exception as e:
            print(f"   ❌ Error processing result: {e}")
            error_count += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"   Total processed: {len(results)}")
    print(f"   ✓ Successful:    {success_count}")
    print(f"   ✗ Failed:        {error_count}")
    print(f"\n📁 Output directory: {output_dir}")

    # Download error file if exists
    if batch.error_file_id:
        print(f"\n⚠️  Downloading error file...")
        error_content = client.files.content(batch.error_file_id)
        error_file = output_path / f"batch_{batch_id}_errors.jsonl"
        with open(error_file, 'wb') as f:
            f.write(error_content.read())
        print(f"   ✓ Errors saved to: {error_file}")


def main():
    """Main execution function."""
    try:
        args = parse_arguments()

        print("\n" + "="*60)
        print("OPENAI BATCH API QUERY RUNNER")
        print("="*60)

        # Mode 1: Submit new batch job
        if args.submit:
            if not args.output:
                print("❌ Error: --output is required when using --submit")
                sys.exit(1)

            print(f"\n📋 Mode: Submit Batch Job")
            print(f"   Data file: {args.data}")
            print(f"   Output directory: {args.output}")
            print(f"   Skip existing: {args.skip_existing}")

            # Load full dataset
            df = load_data(args.data)

            # Generate JSONL
            jsonl_file, metadata = generate_batch_jsonl(
                df, args.output, args.skip_existing
            )

            if metadata['included_queries'] == 0:
                print(f"\n⚠️  No queries to submit (all results already exist)")
                print(f"✅ Done!")
                return

            # Submit batch job
            batch_id = submit_batch_job(jsonl_file, metadata)

            print(f"\n{'='*60}")
            print(f"BATCH JOB SUBMITTED")
            print(f"{'='*60}")
            print(f"\n📋 Batch ID: {batch_id}")
            print(f"\n⏳ The batch is now processing. This may take up to 24 hours.")
            print(f"\nTo check status:")
            print(f"   python {sys.argv[0]} --check-status {batch_id}")
            print(f"\nTo retrieve results when completed:")
            print(f"   python {sys.argv[0]} --retrieve-results {batch_id} --output {args.output}")

        # Mode 2: Check batch status
        elif args.check_status:
            print(f"\n📋 Mode: Check Batch Status")
            check_batch_status(args.check_status)

        # Mode 3: Retrieve results
        elif args.retrieve_results:
            if not args.output:
                print("❌ Error: --output is required when using --retrieve-results")
                sys.exit(1)

            print(f"\n📋 Mode: Retrieve Results")
            print(f"   Batch ID: {args.retrieve_results}")
            print(f"   Output directory: {args.output}")

            retrieve_and_process_results(args.retrieve_results, args.output)

        print(f"\n✅ Done!")

    except KeyboardInterrupt:
        print("\n\n❌ Operation cancelled by user")
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
