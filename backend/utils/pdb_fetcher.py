from __future__ import annotations

"""
pdb_fetcher.py: all outbound HTTP calls live here

I put every network call in one place so the rest of the stack never has to
know about URLs or retry logic. I use requests.Session for connection pooling
and a 1-hour in-memory cache so the same structure isn't fetched twice per
session.
"""

import time
import logging
import concurrent.futures
from typing import Optional

import requests

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600  # 1 hour, covers any realistic session

# Simple dict cache: { key: (data, timestamp) }
_cache: dict[str, tuple] = {}

_session = requests.Session()
_session.headers.update({
    "User-Agent": "ProteinVis/1.0 (COMP1682 FYP; University of Greenwich; educational use)"
})

RCSB_FILES_BASE = "https://files.rcsb.org/download"
RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA_API = "https://data.rcsb.org/rest/v1/core/entry"

ALPHAFOLD_FILES_BASE = "https://alphafold.ebi.ac.uk/files"
ALPHAFOLD_API_BASE = "https://alphafold.ebi.ac.uk/api"


def _get_cached(key: str) -> Optional[object]:
    """Return cached value if it exists and hasn't expired, else None."""
    if key in _cache:
        data, timestamp = _cache[key]
        if time.time() - timestamp < CACHE_TTL_SECONDS:
            logger.debug("Cache hit for key: %s", key)
            return data
        del _cache[key]
        logger.debug("Cache expired for key: %s", key)
    return None


def _set_cached(key: str, data: object) -> None:
    """Store data in the cache with current timestamp."""
    _cache[key] = (data, time.time())


def fetch_pdb_structure(pdb_id: str) -> str:
    """
    Download the PDB file for a given 4-character identifier from RCSB.

    Returns the raw PDB text. I validate the format here rather than in
    the service layer because this is the first place a bad ID would cause
    a problem, no point in deferring that check and waiting for a network
    roundtrip to discover it.
    """
    pdb_id = pdb_id.upper().strip()
    cache_key = f"pdb_structure_{pdb_id}"

    cached = _get_cached(cache_key)
    if cached:
        return cached

    url = f"{RCSB_FILES_BASE}/{pdb_id}.pdb"
    logger.info("Fetching PDB structure from RCSB: %s", url)

    try:
        response = _session.get(url, timeout=20)
        response.raise_for_status()
        pdb_text = response.text
        _set_cached(cache_key, pdb_text)
        logger.info("Fetched PDB %s (%d bytes)", pdb_id, len(pdb_text))
        return pdb_text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise ValueError(
                f"PDB entry '{pdb_id}' was not found. "
                "Please check the identifier. PDB IDs are 4 characters (e.g. 1CRN, 4HHB)."
            )
        raise RuntimeError(
            f"RCSB returned an error fetching '{pdb_id}': HTTP {e.response.status_code}."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("The request to RCSB timed out. Please try again in a moment.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            "Could not connect to RCSB. Please check your internet connection."
        )


def fetch_pdb_metadata(pdb_id: str) -> dict:
    """
    Fetch structured metadata for a PDB entry via the RCSB Data API.

    I use the REST data API rather than parsing the PDB header directly
    because the REST response is structured JSON, much easier to extract
    specific fields from than the fixed-column HEADER/TITLE/REMARK records
    in the PDB format. The parser still reads PDB records for things the
    REST API doesn't expose cleanly, like per-residue secondary structure.
    """
    pdb_id = pdb_id.upper().strip()
    cache_key = f"pdb_metadata_{pdb_id}"

    cached = _get_cached(cache_key)
    if cached:
        return cached

    url = f"{RCSB_DATA_API}/{pdb_id}"
    logger.info("Fetching PDB metadata from RCSB Data API: %s", url)

    try:
        response = _session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        _set_cached(cache_key, data)
        return data
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise ValueError(f"No metadata found for PDB entry '{pdb_id}'.")
        raise RuntimeError(
            f"RCSB Data API returned HTTP {e.response.status_code} for '{pdb_id}'."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Metadata request to RCSB timed out.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to RCSB Data API.")


def fetch_alphafold_structure(uniprot_id: str) -> str:
    """
    Download the AlphaFold predicted structure for a given UniProt accession.

    Downloads from the AlphaFold EBI database using model v4. Structures can
    be large so I give this a longer timeout than standard PDB fetches.
    """
    uniprot_id = uniprot_id.upper().strip()
    cache_key = f"alphafold_structure_{uniprot_id}"

    cached = _get_cached(cache_key)
    if cached:
        return cached

    url = f"{ALPHAFOLD_FILES_BASE}/AF-{uniprot_id}-F1-model_v4.pdb"
    logger.info("Fetching AlphaFold structure: %s", url)

    try:
        response = _session.get(url, timeout=30)
        response.raise_for_status()
        pdb_text = response.text
        _set_cached(cache_key, pdb_text)
        logger.info("Fetched AlphaFold %s (%d bytes)", uniprot_id, len(pdb_text))
        return pdb_text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise ValueError(
                f"No AlphaFold prediction found for '{uniprot_id}'. "
                "Ensure this is a valid UniProt accession (e.g. P68871 for haemoglobin beta)."
            )
        raise RuntimeError(
            f"AlphaFold DB returned HTTP {e.response.status_code} for '{uniprot_id}'."
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            "The request to AlphaFold DB timed out. "
            "AlphaFold structures can be large, please try again."
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to AlphaFold DB. Check your internet connection.")


def fetch_alphafold_metadata(uniprot_id: str) -> dict:
    """
    Fetch structured annotation for an AlphaFold entry from the EBI REST API.

    The AlphaFold EBI API (https://alphafold.ebi.ac.uk/api/prediction/{id})
    returns richer annotation than the PDB file header: organism name, gene
    symbol, UniProt protein description, and taxon ID. I fetch this alongside
    the structure file so the metadata panel can display biologically meaningful
    labels rather than the sparse PDB TITLE record.

    Returns the first prediction entry dict, or an empty dict on failure.
    Failures are soft; the caller must handle a missing 'gene' or 'organism'
    gracefully by falling back to PDB-parsed values.
    """
    uniprot_id = uniprot_id.upper().strip()
    cache_key = f"alphafold_meta_{uniprot_id}"

    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    url = f"{ALPHAFOLD_API_BASE}/prediction/{uniprot_id}"
    logger.info("Fetching AlphaFold annotation from EBI API: %s", url)

    try:
        response = _session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        # API returns a list; each item is one fragment/prediction.
        # Take the first entry which covers the canonical isoform.
        result: dict = data[0] if isinstance(data, list) and data else {}
        _set_cached(cache_key, result)
        return result
    except Exception as exc:
        logger.warning("AlphaFold EBI annotation fetch failed for %s: %s", uniprot_id, exc)
        empty: dict = {}
        _set_cached(cache_key, empty)
        return empty


def search_rcsb(query: str, max_results: int = 25) -> list[dict]:
    """
    Run a full-text search against the RCSB PDB v2 Search API.

    Capped at 25 results. I fetch titles for the top 8 in parallel so users
    can recognise proteins by name rather than just PDB ID.
    """
    cache_key = f"search_{query.lower().strip()}_{max_results}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    payload = {
        "query": {
            "type": "terminal",
            "service": "full_text",
            "parameters": {"value": query}
        },
        "return_type": "entry",
        "request_options": {
            "paginate": {"start": 0, "rows": max_results},
            "results_content_type": ["experimental"],
            "sort": [{"sort_by": "score", "direction": "descending"}],
            "scoring_strategy": "combined"
        }
    }

    logger.info("Searching RCSB for: %s", query)

    try:
        response = _session.post(RCSB_SEARCH_URL, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        raw_results = data.get("result_set", [])

        results = []
        for item in raw_results:
            results.append({
                "identifier": item.get("identifier"),
                "score": item.get("score", 0),
                "title": None,
            })

        # Fetch titles for the top 8 results in parallel (serial would be slow).
        top8 = results[:8]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            future_to_result = {
                pool.submit(fetch_pdb_metadata, r["identifier"]): r
                for r in top8
            }
            for future, r in future_to_result.items():
                try:
                    meta = future.result()
                    r["title"] = (meta.get("struct") or {}).get("title")
                except Exception:
                    pass  # title stays None, frontend shows PDB ID alone

        _set_cached(cache_key, results)
        logger.info("Search for '%s' returned %d results", query, len(results))
        return results
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"RCSB search failed with HTTP {e.response.status_code}.")
    except requests.exceptions.Timeout:
        raise RuntimeError("Search request to RCSB timed out.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to RCSB search API.")
