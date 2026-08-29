import argparse
import pandas as pd
import sys
import hashlib
import json
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional
from openai import OpenAI


def get_cache_key(target_symbol: str, indication_name: str, mesh: str) -> str:
    """Generate a hash key for caching based on input parameters."""
    input_str = f"{target_symbol}|{indication_name}|{mesh}"
    return hashlib.sha256(input_str.encode()).hexdigest()


def get_expected_files(target: str, indication: str, mesh: str, output_dir: str) -> tuple[Path, Path]:
    """Get expected cache and output file paths."""
    output_path = Path(output_dir)

    # Cache file: output_dir/.cache/{cache_key}.json
    cache_key = get_cache_key(target, indication, mesh)
    cache_file = output_path / ".cache" / f"{cache_key}.json"

    # Output file: output_dir/{safe_target}-{safe_mesh}.json
    safe_target = "".join(c for c in target if c.isalnum() or c in ('-', '_'))
    safe_mesh = "".join(c for c in mesh if c.isalnum() or c in ('-', '_'))
    output_file = output_path / f"{safe_target}-{safe_mesh}.json"

    return cache_file, output_file


def replace_template_variables(template: str, target_symbol: str, indication_name: str, mesh: str) -> str:
    """Replace template variables in the prompt."""
    return (template
            .replace("**{{target_symbol}}**", target_symbol)
            .replace("{{target_symbol}}", target_symbol)
            .replace("**{{indication_name}}**", indication_name)
            .replace("{{indication_name}}", indication_name)
            .replace("**{{mesh}}**", mesh)
            .replace("{{mesh}}", mesh))


def get_output_filepath(output_dir: str, target_symbol: str, mesh: str) -> Path:
    """Get the output file path based on target and mesh."""
    output_path = Path(output_dir)
    safe_target = "".join(c for c in target_symbol if c.isalnum() or c in ('-', '_'))
    safe_mesh = "".join(c for c in mesh if c.isalnum() or c in ('-', '_'))
    filename = f"{safe_target}-{safe_mesh}.json"
    return output_path / filename


def save_response(response_data: dict, output_dir: str, target_symbol: str, mesh: str) -> Optional[str]:
    """Save the response to output directory with pattern {target_symbol}-{mesh}.json."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    output_file = get_output_filepath(output_dir, target_symbol, mesh)

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(response_data, f, indent=2, ensure_ascii=False)
        return str(output_file)
    except Exception as e:
        print(f"   ✗ Error saving response: {e}")
        return None


def create_api_request(client: OpenAI, target_symbol: str, indication_name: str, mesh: str,
                       reasoning_effort: str = "high", verbosity: str = "high"):
    """Create and send the API request with replaced template variables."""

    # Developer prompt template
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

    # User prompt template
    user_prompt_template = """
Identify and summarize **causal, human-relevant biological relationship** by integrating all relevant evidence from human genetics, functional studies, and animal models for the following **Target-Indication** (T-I) pair:

* **Target (HGNC symbol or protein): **{{target_symbol}}**
* **Indication (disease or phenotype): **{{indication_name}}**
"""

    # Replace template variables
    developer_content = replace_template_variables(
        developer_prompt_template, target_symbol, indication_name, mesh
    )
    user_content = replace_template_variables(
        user_prompt_template, target_symbol, indication_name, mesh
    )

    # JSON Schema
    json_schema = {
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

    # Make API request
    response = client.responses.create(
        model="gpt-5",
        input=[
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
        text={
            "format": json_schema,
            "verbosity": verbosity
        },
        reasoning={
            "effort": reasoning_effort,
            "summary": "auto"
        },
        tools=[],
        store=True
    )

    return response


def run_single_query(client: OpenAI, row: pd.Series, output_dir: str, index: int, total: int,
                     reasoning_effort: str = "high", verbosity: str = "high") -> Dict:
    """Run a single query using the OpenAI API directly."""
    target = row['gene']
    indication = row['indication_mesh_term']
    mesh = row['indication_mesh_id']

    print(f"\n[{index}/{total}] Processing: {target} - {indication} ({mesh})")

    try:
        # Check if output file already exists
        output_file = get_output_filepath(output_dir, target, mesh)

        if output_file.exists():
            print(f"   ⏭️  Output file already exists, skipping")
            return {
                'status': 'skipped',
                'target': target,
                'indication': indication,
                'mesh': mesh,
                'message': 'Output file already exists'
            }

        # Make API request
        print(f"   ⏳ Making API request...")
        response = create_api_request(client, target, indication, mesh, reasoning_effort, verbosity)

        # Extract response data
        response_data = {
            "metadata": {
                "target_symbol": target,
                "indication_name": indication,
                "mesh": mesh,
                "timestamp": datetime.now().isoformat()
            },
            "response": response.model_dump() if hasattr(response, 'model_dump') else dict(response)
        }

        # Save response
        saved_file = save_response(response_data, output_dir, target, mesh)

        if saved_file:
            print(f"   ✓ Success: {target} - {mesh}")
            return {
                'status': 'success',
                'target': target,
                'indication': indication,
                'mesh': mesh,
                'output_file': saved_file
            }
        else:
            print(f"   ✗ Failed: {target} - {mesh} (save error)")
            return {
                'status': 'failed',
                'target': target,
                'indication': indication,
                'mesh': mesh,
                'error': 'Failed to save output file'
            }

    except Exception as e:
        print(f"   ❌ Exception: {target} - {mesh}: {str(e)}")
        return {
            'status': 'error',
            'target': target,
            'indication': indication,
            'mesh': mesh,
            'error': str(e)
        }


def load_data(data_path: str) -> pd.DataFrame:
    """Load TSV file."""
    print(f"\n📂 Loading data from: {data_path}")

    # Read TSV file
    df = pd.read_csv(data_path, sep='\t')
    total_rows = len(df)

    print(f"   Total rows in dataset: {total_rows}")

    return df


def run_batch_queries(df: pd.DataFrame, output_dir: str, n_workers: int,
                      reasoning_effort: str = "high", verbosity: str = "high"):
    """Run queries concurrently using ThreadPoolExecutor with shared OpenAI client."""
    total = len(df)
    results = []

    print(f"\n🚀 Starting processing with {n_workers} workers...")
    print(f"   Total queries: {total}")

    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Create shared OpenAI client
    client = OpenAI()

    # Run queries concurrently
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        # Submit all tasks
        future_to_row = {
            executor.submit(run_single_query, client, row, output_dir, idx + 1, total,
                          reasoning_effort, verbosity): (idx, row)
            for idx, row in df.iterrows()
        }

        # Collect results as they complete
        for future in as_completed(future_to_row):
            idx, row = future_to_row[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"\n❌ Unexpected error processing row {idx}: {str(e)}")
                results.append({
                    'status': 'error',
                    'target': row['gene'],
                    'indication': row['indication_mesh_term'],
                    'mesh': row['indication_mesh_id'],
                    'error': str(e)
                })

    return results


def print_summary(results: List[Dict], output_dir: str):
    """Print summary statistics of the batch run."""
    total = len(results)
    success = sum(1 for r in results if r['status'] == 'success')
    failed = sum(1 for r in results if r['status'] == 'failed')
    skipped = sum(1 for r in results if r['status'] == 'skipped')
    error = sum(1 for r in results if r['status'] == 'error')

    print("\n" + "="*60)
    print("BATCH PROCESSING SUMMARY")
    print("="*60)
    print(f"\n📊 Results:")
    print(f"   Total queries:    {total}")
    print(f"   ✓ Successful:     {success} ({success/total*100:.1f}%)")
    print(f"   ⏭️  Skipped:        {skipped} ({skipped/total*100:.1f}%)")
    print(f"   ✗ Failed:         {failed} ({failed/total*100:.1f}%)")
    print(f"   ❌ Errors:         {error} ({error/total*100:.1f}%)")
    print(f"\n📁 Output directory: {output_dir}")

    # Save summary to file
    summary_file = Path(output_dir) / "batch_summary.txt"
    with open(summary_file, 'w') as f:
        f.write("BATCH PROCESSING SUMMARY\n")
        f.write("="*60 + "\n\n")
        f.write(f"Total queries:    {total}\n")
        f.write(f"Successful:       {success} ({success/total*100:.1f}%)\n")
        f.write(f"Skipped:          {skipped} ({skipped/total*100:.1f}%)\n")
        f.write(f"Failed:           {failed} ({failed/total*100:.1f}%)\n")
        f.write(f"Errors:           {error} ({error/total*100:.1f}%)\n\n")

        if failed > 0 or error > 0:
            f.write("\nFailed/Error queries:\n")
            f.write("-"*60 + "\n")
            for r in results:
                if r['status'] in ['failed', 'error']:
                    f.write(f"\n{r['status'].upper()}: {r['target']} - {r['mesh']}\n")
                    f.write(f"  Error: {r.get('error', 'Unknown')}\n")

    print(f"   Summary saved to: {summary_file}")


def parse_arguments():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="POOLED TARGET-INDICATION QUERY RUNNER - Self-sustainable batch processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process with 5 workers using test data file
  python query_gpt5.py -w 5 -o result/gpt5 --data data/test.tsv

  # Single query mode without MeSH ID (uses indication name as identifier)
  python query_gpt5.py --single --target TP53 --indication "Lung adenocarcinoma" -o result/gpt5

  # Single query with custom reasoning effort and verbosity
  python query_gpt5.py --single --target BRCA1 --indication "Breast cancer" -o result/gpt5 --reasoning-effort medium --verbosity low
        """
    )

    parser.add_argument(
        '-w', '--workers',
        type=int,
        default=1,
        help='Number of concurrent workers for parallel processing (default: 1)'
    )

    parser.add_argument(
        '-o', '--output',
        type=str,
        required=True,
        help='Output directory path for all results [REQUIRED]'
    )

    parser.add_argument(
        '--data',
        type=str,
        default='data/pp_13k.tsv',
        help='Path to the input TSV file (default: data/pp_13k.tsv)'
    )

    # Single query mode arguments
    parser.add_argument(
        '--single',
        action='store_true',
        help='Run a single query instead of processing a data file'
    )

    parser.add_argument(
        '--target',
        type=str,
        help='Target gene symbol (required with --single)'
    )

    parser.add_argument(
        '--indication',
        type=str,
        help='Indication name (required with --single)'
    )

    parser.add_argument(
        '--mesh',
        type=str,
        default='',
        help='MeSH ID for the indication (optional with --single)'
    )

    # GPT-5 specific arguments
    parser.add_argument(
        '--reasoning-effort',
        type=str,
        choices=['low', 'medium', 'high'],
        default='high',
        help='Reasoning effort level for GPT-5 (default: high)'
    )

    parser.add_argument(
        '--verbosity',
        type=str,
        choices=['low', 'medium', 'high'],
        default='high',
        help='Output verbosity level (default: high)'
    )

    args = parser.parse_args()

    # Validate single query mode arguments
    if args.single:
        if not args.target or not args.indication:
            parser.error('--single requires --target and --indication')

    return args


def main():
    """Main execution function."""
    try:
        # Parse arguments
        args = parse_arguments()

        # Convert hyphenated argument name to underscore
        reasoning_effort = args.reasoning_effort

        print("\n" + "="*60)
        print("POOLED TARGET-INDICATION QUERY RUNNER")
        print("="*60)

        if args.single:
            # Single query mode
            print(f"\n📋 Single Query Mode:")
            print(f"   Target:           {args.target}")
            print(f"   Indication:       {args.indication}")
            print(f"   MeSH ID:          {args.mesh or '(not provided)'}")
            print(f"   Output directory: {args.output}")
            print(f"   Reasoning effort: {reasoning_effort}")
            print(f"   Verbosity:        {args.verbosity}")

            # Use indication name (with spaces replaced by underscores) as MeSH ID if not provided
            mesh_id = args.mesh if args.mesh else args.indication.replace(' ', '_')

            # Create a single-row DataFrame
            df = pd.DataFrame([{
                'gene': args.target,
                'indication_mesh_term': args.indication,
                'indication_mesh_id': mesh_id
            }])

            # Run with 1 worker
            results = run_batch_queries(df, args.output, n_workers=1,
                                       reasoning_effort=reasoning_effort,
                                       verbosity=args.verbosity)
        else:
            # Multi-query mode
            print(f"\n📋 Configuration:")
            print(f"   Data file:        {args.data}")
            print(f"   Workers:          {args.workers}")
            print(f"   Output directory: {args.output}")
            print(f"   Reasoning effort: {reasoning_effort}")
            print(f"   Verbosity:        {args.verbosity}")

            # Load data
            df = load_data(args.data)

            # Run queries
            results = run_batch_queries(df, args.output, args.workers,
                                       reasoning_effort=reasoning_effort,
                                       verbosity=args.verbosity)

        # Print summary
        print_summary(results, args.output)

        print("\n✅ Processing complete!")

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
