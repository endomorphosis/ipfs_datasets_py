"""MCP/CLI-friendly APIs for legal dataset scraping.

Core scraping implementations live in the individual scraper modules. This file
provides parameter-driven helper functions so thin wrappers (MCP tools, CLI
commands, SDK calls) can share the same orchestration, defaults, and error
shapes.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, Iterable, List

import anyio

logger = logging.getLogger(__name__)


def _get_repo_root() -> Path:
    """Resolve repository root from this module path."""
    return Path(__file__).resolve().parents[3]


def _venv_python(venv_dir: str = ".venv") -> Path:
    """Return interpreter path for the target virtual environment."""
    root = _get_repo_root()
    return root / venv_dir / "bin" / "python"


def _ensure_venv(
    *,
    venv_dir: str = ".venv",
    packages: Iterable[str],
    upgrade_pip: bool = True,
) -> Dict[str, Any]:
    """Create/update a project venv and install required packages."""
    root = _get_repo_root()
    python_path = _venv_python(venv_dir)
    venv_path = root / venv_dir

    created = False
    if not python_path.exists():
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_path)],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
        created = True

    if upgrade_pip:
        subprocess.run(
            [str(python_path), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )

    pkg_list = [p for p in packages if p]
    if pkg_list:
        subprocess.run(
            [str(python_path), "-m", "pip", "install", *pkg_list],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )

    return {
        "venv_path": str(venv_path),
        "python_path": str(python_path),
        "created": created,
        "installed_packages": pkg_list,
    }


def _run_cap_vector_operation_in_venv(
    *,
    operation: str,
    payload: Dict[str, Any],
    venv_dir: str = ".venv",
) -> Dict[str, Any]:
    """Run CAP vector operations in the project venv and return parsed JSON."""
    root = _get_repo_root()
    python_path = _venv_python(venv_dir)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["CAP_VECTOR_PAYLOAD"] = json.dumps(payload)
    env["CAP_VECTOR_MODULE_PATH"] = str(
        root
        / "ipfs_datasets_py"
        / "processors"
        / "legal_scrapers"
        / "caselaw_access_program"
        / "vector_search_integration.py"
    )

    script = r'''
import asyncio
import importlib.util
import json
import os
import sys
import time

module_path = os.environ["CAP_VECTOR_MODULE_PATH"]
spec = importlib.util.spec_from_file_location("cap_vector_search_integration", module_path)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Failed to load CAP module spec from {module_path}")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
create_caselaw_access_vector_search = module.create_caselaw_access_vector_search


async def _main() -> None:
    payload = json.loads(os.environ.get("CAP_VECTOR_PAYLOAD", "{}"))
    cap = create_caselaw_access_vector_search()
    op = payload.get("operation")

    if op == "ingest":
        result = await cap.ingest_embeddings(
            collection_name=payload["collection_name"],
            store_type=payload.get("store_type", "faiss"),
            parquet_file=payload.get("parquet_file"),
            model_hint=payload.get("model_hint"),
            max_rows=int(payload.get("max_rows", 10000)),
            batch_size=int(payload.get("batch_size", 512)),
            distance_metric=payload.get("distance_metric", "cosine"),
        )
        print(json.dumps({
            "status": "success",
            "operation": op,
            "result": {
                "collection_name": result.collection_name,
                "store_type": result.store_type,
                "source_file": result.source_file,
                "ingested_count": result.ingested_count,
                "vector_dimension": result.vector_dimension,
            },
        }))
        return

    if op == "search":
        results = await cap.search_by_vector(
            collection_name=payload["collection_name"],
            query_vector=payload["query_vector"],
            store_type=payload.get("store_type", "faiss"),
            top_k=int(payload.get("top_k", 10)),
            filter_dict=payload.get("filter_dict"),
        )
        output = []
        for r in results:
            output.append(
                {
                    "chunk_id": r.chunk_id,
                    "content": r.content,
                    "score": r.score,
                    "metadata": r.metadata,
                }
            )
        print(json.dumps({"status": "success", "operation": op, "results": output}))
        return

    if op == "search_cases":
        from huggingface_hub import hf_hub_url
        import duckdb

        results = await cap.search_by_vector(
            collection_name=payload["collection_name"],
            query_vector=payload["query_vector"],
            store_type=payload.get("store_type", "faiss"),
            top_k=int(payload.get("top_k", 10)),
            filter_dict=payload.get("filter_dict"),
        )

        cid_field = payload.get("cid_metadata_field", "cid")
        cid_column = payload.get("cid_column", "cid")
        text_candidates = payload.get("text_field_candidates") or ["head_matter", "text"]
        snippet_chars = int(payload.get("snippet_chars", 320))
        chunk_lookup_enabled = bool(payload.get("chunk_lookup_enabled", True))

        cid_order = []
        for hit in results:
            metadata = hit.metadata or {}
            cid = metadata.get(cid_field) or hit.chunk_id
            cid_str = str(cid).strip() if cid is not None else ""
            if cid_str and cid_str not in cid_order:
                cid_order.append(cid_str)

        case_rows = {}
        case_source = None
        chunk_source = None
        chunk_lookup_error = None
        chunk_rows_by_chunk_cid = {}
        chunk_rows_by_source_cid = {}
        if cid_order:
            dataset_id = payload.get("hf_dataset_id", "justicedao/ipfs_caselaw_access_project")
            parquet_file = payload.get(
                "hf_parquet_file",
                "embeddings/ipfs_TeraflopAI___Caselaw_Access_Project.parquet",
            )
            hf_url = hf_hub_url(repo_id=dataset_id, repo_type="dataset", filename=parquet_file)
            local_parquet = payload.get("local_case_parquet_file")
            con = duckdb.connect()

            def _execute_with_retries(query_text, params=None, retries=4):
                last_exc = None
                for attempt in range(retries):
                    try:
                        if params is None:
                            return con.execute(query_text)
                        return con.execute(query_text, params)
                    except Exception as exc:
                        last_exc = exc
                        message = str(exc)
                        if "HTTP 429" in message and attempt < retries - 1:
                            # Simple exponential backoff for transient HF rate limits.
                            time.sleep(1.5 * (2 ** attempt))
                            continue
                        raise
                if last_exc is not None:
                    raise last_exc

            sources = [("hf", hf_url)]
            if local_parquet and os.path.exists(local_parquet):
                sources.append(("local", local_parquet))

            last_exc = None
            for source_name, source_ref in sources:
                try:
                    schema_rows = _execute_with_retries(
                        f"DESCRIBE SELECT * FROM read_parquet('{source_ref}')"
                    ).fetchall()
                    schema_cols = {row[0] for row in schema_rows}

                    selected_text_field = None
                    for candidate in text_candidates:
                        if candidate in schema_cols:
                            selected_text_field = candidate
                            break

                    optional_fields = [
                        "name",
                        "court",
                        "decision_date",
                        "jurisdiction",
                        "docket_number",
                        "citations",
                    ]
                    present_optionals = [f for f in optional_fields if f in schema_cols]

                    select_parts = [f"{cid_column} AS cid"]
                    for field in present_optionals:
                        select_parts.append(field)
                    if selected_text_field:
                        select_parts.append(
                            f"substr({selected_text_field}, 1, {snippet_chars}) AS snippet"
                        )

                    placeholders = ", ".join(["?"] * len(cid_order))
                    query = (
                        f"SELECT {', '.join(select_parts)} "
                        f"FROM read_parquet('{source_ref}') "
                        f"WHERE {cid_column} IN ({placeholders})"
                    )
                    rows = _execute_with_retries(query, cid_order).fetchall()
                    col_names = [p.split(" AS ")[-1] for p in select_parts]
                    for row in rows:
                        row_obj = dict(zip(col_names, row))
                        case_rows[str(row_obj.get("cid"))] = row_obj
                    case_source = source_name
                    break
                except Exception as exc:
                    last_exc = exc
                    continue

            if not case_rows and last_exc is not None:
                raise last_exc

            if chunk_lookup_enabled:
                chunk_dataset_id = payload.get("chunk_hf_dataset_id", dataset_id)
                chunk_parquet_file = payload.get(
                    "chunk_hf_parquet_file",
                    "embeddings/sparse_chunks.parquet",
                )
                chunk_hf_url = hf_hub_url(
                    repo_id=chunk_dataset_id,
                    repo_type="dataset",
                    filename=chunk_parquet_file,
                )
                local_chunk_parquet = payload.get("local_chunk_parquet_file")
                chunk_snippet_chars = int(payload.get("chunk_snippet_chars", 1000))

                chunk_sources = [("hf", chunk_hf_url)]
                if local_chunk_parquet and os.path.exists(local_chunk_parquet):
                    chunk_sources.append(("local", local_chunk_parquet))

                last_chunk_exc = None
                for source_name, source_ref in chunk_sources:
                    try:
                        chunk_schema_rows = _execute_with_retries(
                            f"DESCRIBE SELECT * FROM read_parquet('{source_ref}')"
                        ).fetchall()
                        chunk_schema_cols = {row[0] for row in chunk_schema_rows}

                        where_clauses = []
                        if "items" in chunk_schema_cols:
                            where_clauses.append("items.cid")
                        if "source_file_cid" in chunk_schema_cols:
                            where_clauses.append("source_file_cid")

                        if not where_clauses:
                            continue

                        placeholders = ", ".join(["?"] * len(cid_order))
                        where_sql = " OR ".join(
                            [f"{field} IN ({placeholders})" for field in where_clauses]
                        )
                        query = (
                            "SELECT "
                            "source_file_cid, "
                            "source_filename, "
                            "items.cid AS chunk_cid, "
                            f"substr(items.content, 1, {chunk_snippet_chars}) AS chunk_snippet "
                            f"FROM read_parquet('{source_ref}') "
                            f"WHERE {where_sql}"
                        )

                        params = []
                        for _ in where_clauses:
                            params.extend(cid_order)

                        rows = _execute_with_retries(query, params).fetchall()
                        for row in rows:
                            source_file_cid, source_filename, chunk_cid, chunk_snippet = row
                            source_file_cid_str = (
                                str(source_file_cid).strip() if source_file_cid is not None else ""
                            )
                            chunk_cid_str = str(chunk_cid).strip() if chunk_cid is not None else ""
                            chunk_obj = {
                                "chunk_cid": chunk_cid_str,
                                "source_file_cid": source_file_cid_str,
                                "source_filename": source_filename,
                                "snippet": chunk_snippet,
                            }
                            if chunk_cid_str and chunk_cid_str not in chunk_rows_by_chunk_cid:
                                chunk_rows_by_chunk_cid[chunk_cid_str] = chunk_obj
                            if (
                                source_file_cid_str
                                and source_file_cid_str not in chunk_rows_by_source_cid
                            ):
                                chunk_rows_by_source_cid[source_file_cid_str] = chunk_obj

                        chunk_source = source_name
                        break
                    except Exception as exc:
                        last_chunk_exc = exc
                        continue
                if chunk_source is None and last_chunk_exc is not None:
                    chunk_lookup_error = str(last_chunk_exc)

        output = []
        for hit in results:
            metadata = hit.metadata or {}
            cid = metadata.get(cid_field) or hit.chunk_id
            cid_str = str(cid).strip() if cid is not None else ""
            hit_chunk_id = str(hit.chunk_id).strip() if hit.chunk_id is not None else ""
            file_chunk = None
            for candidate in (hit_chunk_id, cid_str):
                if candidate and candidate in chunk_rows_by_chunk_cid:
                    file_chunk = chunk_rows_by_chunk_cid[candidate]
                    break
            if file_chunk is None:
                for candidate in (cid_str, hit_chunk_id):
                    if candidate and candidate in chunk_rows_by_source_cid:
                        file_chunk = chunk_rows_by_source_cid[candidate]
                        break
            output.append(
                {
                    "chunk_id": hit.chunk_id,
                    "content": hit.content,
                    "score": hit.score,
                    "metadata": metadata,
                    "cid": cid_str,
                    "case": case_rows.get(cid_str),
                    "file_chunk": file_chunk,
                }
            )

        print(
            json.dumps(
                {
                    "status": "success",
                    "operation": op,
                    "results": output,
                    "case_source": case_source,
                    "chunk_source": chunk_source,
                    "chunk_lookup_error": chunk_lookup_error,
                }
            )
        )
        return

    if op == "list_files":
        result = cap.describe_dataset_files(model_hint=payload.get("model_hint"))
        print(json.dumps({"status": "success", "operation": op, "result": result}))
        return

    if op == "centroid_search":
        plan = await cap.search_with_centroid_routing(
            target_collection_name=payload["target_collection_name"],
            centroid_collection_name=payload["centroid_collection_name"],
            query_vector=payload["query_vector"],
            store_type=payload.get("store_type", "faiss"),
            centroid_top_k=int(payload.get("centroid_top_k", 5)),
            per_cluster_top_k=int(payload.get("per_cluster_top_k", 20)),
            final_top_k=int(payload.get("final_top_k", 10)),
            cluster_metadata_field=payload.get("cluster_metadata_field", "cluster_id"),
            cluster_cids_parquet_file=payload.get("cluster_cids_parquet_file"),
            cid_metadata_field=payload.get("cid_metadata_field", "cid"),
            cid_list_field=payload.get("cid_list_field", "cids"),
            cluster_id_field_in_cid_map=payload.get("cluster_id_field_in_cid_map", "cluster_id"),
            cid_candidate_multiplier=int(payload.get("cid_candidate_multiplier", 20)),
            base_filter_dict=payload.get("base_filter_dict"),
        )
        print(
            json.dumps(
                {
                    "status": "success",
                    "operation": op,
                    "plan": {
                        "centroid_collection_name": plan.centroid_collection_name,
                        "target_collection_name": plan.target_collection_name,
                        "selected_cluster_ids": plan.selected_cluster_ids,
                        "centroid_candidates": [
                            {
                                "chunk_id": r.chunk_id,
                                "score": r.score,
                                "metadata": r.metadata,
                                "content": r.content,
                            }
                            for r in plan.centroid_candidates
                        ],
                        "retrieved_results": [
                            {
                                "chunk_id": r.chunk_id,
                                "content": r.content,
                                "score": r.score,
                                "metadata": r.metadata,
                            }
                            for r in plan.retrieved_results
                        ],
                    },
                }
            )
        )
        return

    if op == "ingest_bundle":
        target = await cap.ingest_embeddings(
            collection_name=payload["target_collection_name"],
            store_type=payload.get("store_type", "faiss"),
            parquet_file=payload.get("target_parquet_file"),
            model_hint=payload.get("target_model_hint"),
            max_rows=int(payload.get("target_max_rows", 10000)),
            batch_size=int(payload.get("batch_size", 512)),
            distance_metric=payload.get("distance_metric", "cosine"),
        )

        centroid = await cap.ingest_embeddings(
            collection_name=payload["centroid_collection_name"],
            store_type=payload.get("store_type", "faiss"),
            parquet_file=payload.get("centroid_parquet_file"),
            model_hint=payload.get("centroid_model_hint") or payload.get("target_model_hint"),
            max_rows=int(payload.get("centroid_max_rows", 0)),
            batch_size=int(payload.get("batch_size", 512)),
            distance_metric=payload.get("distance_metric", "cosine"),
        )

        print(
            json.dumps(
                {
                    "status": "success",
                    "operation": op,
                    "result": {
                        "target": {
                            "collection_name": target.collection_name,
                            "store_type": target.store_type,
                            "source_file": target.source_file,
                            "ingested_count": target.ingested_count,
                            "vector_dimension": target.vector_dimension,
                        },
                        "centroid": {
                            "collection_name": centroid.collection_name,
                            "store_type": centroid.store_type,
                            "source_file": centroid.source_file,
                            "ingested_count": centroid.ingested_count,
                            "vector_dimension": centroid.vector_dimension,
                        },
                    },
                }
            )
        )
        return

    raise ValueError(f"Unsupported CAP vector operation: {op}")


asyncio.run(_main())
'''

    completed = subprocess.run(
        [str(python_path), "-c", script],
        cwd=str(root),
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        return {
            "status": "error",
            "operation": operation,
            "error": "CAP vector subprocess failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }

    stdout = completed.stdout.strip()
    if not stdout:
        return {"status": "error", "error": "No output from CAP vector operation"}

    # Some imports in this repository emit warnings to stdout. Parse the last JSON line.
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue

    return {
        "status": "error",
        "error": "Could not parse JSON output from CAP vector operation",
        "raw_stdout": stdout,
    }


async def scrape_recap_archive_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .recap_archive_scraper import scrape_recap_archive

        return await scrape_recap_archive(
            courts=parameters.get("courts"),
            document_types=parameters.get("document_types"),
            filed_after=parameters.get("filed_after"),
            filed_before=parameters.get("filed_before"),
            case_name_pattern=parameters.get("case_name_pattern"),
            output_format="json",
            include_text=parameters.get("include_text", True),
            include_metadata=parameters.get("include_metadata", True),
            rate_limit_delay=parameters.get("rate_limit_delay", 1.0),
            max_documents=parameters.get("max_documents"),
            job_id=parameters.get("job_id"),
            resume=parameters.get("resume", False),
        )

    except Exception as e:
        logger.error("RECAP Archive scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def search_recap_documents_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .recap_archive_scraper import search_recap_documents

        return await search_recap_documents(
            query=parameters.get("query"),
            court=parameters.get("court"),
            case_name=parameters.get("case_name"),
            filed_after=parameters.get("filed_after"),
            filed_before=parameters.get("filed_before"),
            document_type=parameters.get("document_type"),
            limit=parameters.get("limit", 100),
        )

    except Exception as e:
        logger.error("RECAP Archive search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "documents": [],
            "count": 0,
        }


async def scrape_state_laws_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .state_laws_scraper import scrape_state_laws

        result = await scrape_state_laws(
            states=parameters.get("states"),
            legal_areas=parameters.get("legal_areas"),
            output_format=parameters.get("output_format", "json"),
            include_metadata=parameters.get("include_metadata", True),
            rate_limit_delay=parameters.get("rate_limit_delay", 2.0),
            max_statutes=parameters.get("max_statutes"),
            output_dir=parameters.get("output_dir"),
            write_jsonld=parameters.get("write_jsonld", True),
            strict_full_text=parameters.get("strict_full_text", False),
            min_full_text_chars=parameters.get("min_full_text_chars", 300),
        )

        # For forward compatibility with resumable orchestration, include job_id when provided.
        job_id = parameters.get("job_id")
        if job_id:
            result["job_id"] = job_id

        return result

    except Exception as e:
        logger.error("State laws scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def list_scraping_jobs_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .scraping_state import list_scraping_jobs

        jobs = await anyio.to_thread.run_sync(list_scraping_jobs)

        status_filter = parameters.get("status_filter", "all")
        job_type = parameters.get("job_type", "all")

        filtered_jobs = jobs
        if status_filter != "all":
            filtered_jobs = [j for j in filtered_jobs if j.get("status") == status_filter]

        if job_type != "all":
            filtered_jobs = [
                j for j in filtered_jobs if str(j.get("job_id", "")).startswith(job_type)
            ]

        return {
            "status": "success",
            "jobs": filtered_jobs,
            "total_count": len(filtered_jobs),
            "filters": {"status": status_filter, "job_type": job_type},
        }

    except Exception as e:
        logger.error("Failed to list scraping jobs: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "jobs": [],
        }


async def scrape_us_code_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .federal_scrapers.us_code_scraper import scrape_us_code

        titles = parameters.get("titles")
        if titles is None and parameters.get("title"):
            titles = [str(parameters.get("title"))]

        return await scrape_us_code(
            titles=titles,
            output_format=parameters.get("output_format", "json"),
            include_metadata=parameters.get("include_metadata", True),
            rate_limit_delay=parameters.get("rate_limit_delay", 1.0),
            max_sections=parameters.get("max_sections"),
            year=parameters.get("year"),
            cache_dir=parameters.get("cache_dir"),
            force_download=parameters.get("force_download", False),
            output_dir=parameters.get("output_dir"),
            keep_zip_cache=parameters.get("keep_zip_cache", False),
        )

    except Exception as e:
        logger.error("US Code scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def scrape_municipal_codes_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    try:
        from .municipal_codes_api import initialize_municipal_codes_job

        return initialize_municipal_codes_job(parameters, tool_version=tool_version)

    except Exception as e:
        logger.error("Municipal code scraping failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "data": [],
            "metadata": {},
        }


async def setup_legal_tools_venv_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Create/update project venv and install legal vector dependencies."""
    try:
        venv_dir = parameters.get("venv_dir", ".venv")
        packages: List[str] = parameters.get(
            "packages",
            [
                "datasets",
                "huggingface_hub",
                "pyarrow",
                "numpy",
                "faiss-cpu",
                "anyio",
            ],
        )
        setup_info = await anyio.to_thread.run_sync(
            lambda: _ensure_venv(
                venv_dir=venv_dir,
                packages=packages,
                upgrade_pip=bool(parameters.get("upgrade_pip", True)),
            )
        )
        return {
            "status": "success",
            "tool_version": tool_version,
            "venv": setup_info,
        }
    except Exception as e:
        logger.error("Legal tools venv setup failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "tool_version": tool_version,
        }


async def ingest_caselaw_access_vectors_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Ingest CAP embeddings into configured vector store.

    By default this operation bootstraps and executes in ``.venv``.
    """
    try:
        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        ["datasets", "huggingface_hub", "pyarrow", "numpy", "faiss-cpu", "anyio"],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "ingest",
            "collection_name": parameters["collection_name"],
            "store_type": parameters.get("store_type", "faiss"),
            "parquet_file": parameters.get("parquet_file"),
            "model_hint": parameters.get("model_hint"),
            "max_rows": int(parameters.get("max_rows", 10000)),
            "batch_size": int(parameters.get("batch_size", 512)),
            "distance_metric": parameters.get("distance_metric", "cosine"),
        }
        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="ingest",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP vector ingestion failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "ingest",
            "tool_version": tool_version,
        }


async def search_caselaw_access_vectors_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search CAP vectors by precomputed query vector using the project venv."""
    try:
        if "query_vector" not in parameters:
            return {
                "status": "error",
                "error": "query_vector is required",
                "operation": "search",
                "tool_version": tool_version,
            }

        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        ["datasets", "huggingface_hub", "pyarrow", "numpy", "faiss-cpu", "anyio"],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "search",
            "collection_name": parameters["collection_name"],
            "store_type": parameters.get("store_type", "faiss"),
            "query_vector": parameters["query_vector"],
            "top_k": int(parameters.get("top_k", 10)),
            "filter_dict": parameters.get("filter_dict"),
        }
        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="search",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP vector search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "search",
            "tool_version": tool_version,
        }


async def search_caselaw_access_cases_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Search CAP vectors and enrich matches with caselaw fields by CID from HF parquet."""
    try:
        if "query_vector" not in parameters:
            return {
                "status": "error",
                "error": "query_vector is required",
                "operation": "search_cases",
                "tool_version": tool_version,
            }
        if not parameters.get("collection_name"):
            return {
                "status": "error",
                "error": "collection_name is required",
                "operation": "search_cases",
                "tool_version": tool_version,
            }

        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        [
                            "datasets",
                            "huggingface_hub",
                            "pyarrow",
                            "numpy",
                            "faiss-cpu",
                            "duckdb",
                            "anyio",
                        ],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "search_cases",
            "collection_name": parameters["collection_name"],
            "store_type": parameters.get("store_type", "faiss"),
            "query_vector": parameters["query_vector"],
            "top_k": int(parameters.get("top_k", 10)),
            "filter_dict": parameters.get("filter_dict"),
            "hf_dataset_id": parameters.get("hf_dataset_id", "justicedao/ipfs_caselaw_access_project"),
            "hf_parquet_file": parameters.get(
                "hf_parquet_file",
                "embeddings/ipfs_TeraflopAI___Caselaw_Access_Project.parquet",
            ),
            "cid_metadata_field": parameters.get("cid_metadata_field", "cid"),
            "cid_column": parameters.get("cid_column", "cid"),
            "text_field_candidates": parameters.get("text_field_candidates", ["head_matter", "text"]),
            "snippet_chars": int(parameters.get("snippet_chars", 320)),
            "local_case_parquet_file": parameters.get("local_case_parquet_file"),
            "chunk_lookup_enabled": bool(parameters.get("chunk_lookup_enabled", True)),
            "chunk_hf_dataset_id": parameters.get(
                "chunk_hf_dataset_id",
                parameters.get("hf_dataset_id", "justicedao/ipfs_caselaw_access_project"),
            ),
            "chunk_hf_parquet_file": parameters.get(
                "chunk_hf_parquet_file",
                "embeddings/sparse_chunks.parquet",
            ),
            "local_chunk_parquet_file": parameters.get("local_chunk_parquet_file"),
            "chunk_snippet_chars": int(parameters.get("chunk_snippet_chars", 1000)),
        }
        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="search_cases",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP caselaw-enriched vector search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "search_cases",
            "tool_version": tool_version,
        }


async def list_caselaw_access_vector_files_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """List CAP dataset files/models via the project venv."""
    try:
        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        ["datasets", "huggingface_hub", "pyarrow", "numpy", "anyio"],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "list_files",
            "model_hint": parameters.get("model_hint"),
        }
        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="list_files",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP vector file listing failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "list_files",
            "tool_version": tool_version,
        }


async def search_caselaw_access_vectors_with_centroids_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Run centroid-first retrieval over CAP vectors using the project venv."""
    try:
        if "query_vector" not in parameters:
            return {
                "status": "error",
                "error": "query_vector is required",
                "operation": "centroid_search",
                "tool_version": tool_version,
            }

        missing_required = [
            key
            for key in ("target_collection_name", "centroid_collection_name")
            if not parameters.get(key)
        ]
        if missing_required:
            return {
                "status": "error",
                "error": f"Missing required parameters: {', '.join(missing_required)}",
                "operation": "centroid_search",
                "tool_version": tool_version,
            }

        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        ["datasets", "huggingface_hub", "pyarrow", "numpy", "faiss-cpu", "anyio"],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "centroid_search",
            "target_collection_name": parameters["target_collection_name"],
            "centroid_collection_name": parameters["centroid_collection_name"],
            "query_vector": parameters["query_vector"],
            "store_type": parameters.get("store_type", "faiss"),
            "centroid_top_k": int(parameters.get("centroid_top_k", 5)),
            "per_cluster_top_k": int(parameters.get("per_cluster_top_k", 20)),
            "final_top_k": int(parameters.get("final_top_k", 10)),
            "cluster_metadata_field": parameters.get("cluster_metadata_field", "cluster_id"),
            "cluster_cids_parquet_file": parameters.get("cluster_cids_parquet_file"),
            "cid_metadata_field": parameters.get("cid_metadata_field", "cid"),
            "cid_list_field": parameters.get("cid_list_field", "cids"),
            "cluster_id_field_in_cid_map": parameters.get("cluster_id_field_in_cid_map", "cluster_id"),
            "cid_candidate_multiplier": int(parameters.get("cid_candidate_multiplier", 20)),
            "base_filter_dict": parameters.get("base_filter_dict"),
        }
        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="centroid_search",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP centroid-first vector search failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "centroid_search",
            "tool_version": tool_version,
        }


async def ingest_caselaw_access_vector_bundle_from_parameters(
    parameters: Dict[str, Any],
    *,
    tool_version: str = "1.0.0",
) -> Dict[str, Any]:
    """Ingest both target vectors and centroid vectors in one call."""
    try:
        missing_required = [
            key
            for key in ("target_collection_name", "centroid_collection_name")
            if not parameters.get(key)
        ]
        if missing_required:
            return {
                "status": "error",
                "error": f"Missing required parameters: {', '.join(missing_required)}",
                "operation": "ingest_bundle",
                "tool_version": tool_version,
            }

        auto_setup_venv = bool(parameters.get("auto_setup_venv", True))
        venv_dir = parameters.get("venv_dir", ".venv")
        if auto_setup_venv:
            await setup_legal_tools_venv_from_parameters(
                {
                    "venv_dir": venv_dir,
                    "packages": parameters.get(
                        "venv_packages",
                        ["datasets", "huggingface_hub", "pyarrow", "numpy", "faiss-cpu", "anyio"],
                    ),
                    "upgrade_pip": parameters.get("upgrade_pip", True),
                },
                tool_version=tool_version,
            )

        operation_payload = {
            "operation": "ingest_bundle",
            "target_collection_name": parameters["target_collection_name"],
            "centroid_collection_name": parameters["centroid_collection_name"],
            "store_type": parameters.get("store_type", "faiss"),
            "target_parquet_file": parameters.get("target_parquet_file"),
            "target_model_hint": parameters.get("target_model_hint"),
            "target_max_rows": int(parameters.get("target_max_rows", 10000)),
            "centroid_parquet_file": parameters.get("centroid_parquet_file"),
            "centroid_model_hint": parameters.get("centroid_model_hint"),
            "centroid_max_rows": int(parameters.get("centroid_max_rows", 0)),
            "batch_size": int(parameters.get("batch_size", 512)),
            "distance_metric": parameters.get("distance_metric", "cosine"),
        }

        result = await anyio.to_thread.run_sync(
            lambda: _run_cap_vector_operation_in_venv(
                operation="ingest_bundle",
                payload=operation_payload,
                venv_dir=venv_dir,
            )
        )
        result["tool_version"] = tool_version
        return result
    except Exception as e:
        logger.error("CAP bundle ingestion failed: %s", e)
        return {
            "status": "error",
            "error": str(e),
            "operation": "ingest_bundle",
            "tool_version": tool_version,
        }
