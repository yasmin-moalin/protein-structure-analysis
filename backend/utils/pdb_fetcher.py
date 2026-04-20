from __future__ import annotations

# all outbound http calls go through here
# requests.Session with 1 hour in-memory cache so same structure is never fetched twice

import time
import logging
import concurrent.futures
from typing import Optional

import requests

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600  # 1 hour

# simple dict cache: { key: (data, timestamp) }
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
    if key in _cache:
        data, timestamp = _cache[key]
        if time.time() - timestamp < CACHE_TTL_SECONDS:
            logger.debug("Cache hit for key: %s", key)
            return data
        del _cache[key]
        logger.debug("Cache expired for key: %s", key)
    return None


def _set_cached(key: str, data: object) -> None:
    _cache[key] = (data, time.time())


def fetch_pdb_structure(pdb_id: str) -> str:
    """download pdb file from rcsb, checks cache first"""
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
    """fetch structured metadata from rcsb data api - cleaner json for title and resolution"""
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
    """download alphafold structure from ebi, longer timeout for large files"""
    uniprot_id = uniprot_id.upper().strip()
    cache_key = f"alphafold_structure_{uniprot_id}"

    cached = _get_cached(cache_key)
    if cached:
        return cached

    meta = fetch_alphafold_metadata(uniprot_id)
    url = meta.get('pdbUrl') or f"{ALPHAFOLD_FILES_BASE}/AF-{uniprot_id}-F1-model_v4.pdb"

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
    """fetch organism, gene, description from alphafold ebi api
    pdb header alone doesn't include these, returns empty dict on failure"""
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
        # api returns a list, first entry is the standard isoform
        result: dict = data[0] if isinstance(data, list) and data else {}
        _set_cached(cache_key, result)
        return result
    except Exception as exc:
        logger.warning("AlphaFold EBI annotation fetch failed for %s: %s", uniprot_id, exc)
        empty: dict = {}
        _set_cached(cache_key, empty)
        return empty


def search_rcsb(query: str, max_results: int = 25) -> list[dict]:
    """full-text search against rcsb, top 8 titles fetched in parallel"""
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
            "paginate": {"start": 0, "rows": max_results}
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
                "pdb_id": item.get("identifier"),
                "score": item.get("score", 0),
                "title": None,
            })

        # fetch titles for top 8 in parallel - serial would be slow
        top8 = results[:8]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            future_to_result = {
                pool.submit(fetch_pdb_metadata, r["pdb_id"]): r
                for r in top8
            }
            for future, r in future_to_result.items():
                try:
                    meta = future.result()
                    r["title"] = (meta.get("struct") or {}).get("title")
                except Exception:
                    pass  # title stays none, frontend shows pdb id alone

        _set_cached(cache_key, results)
        logger.info("Search for '%s' returned %d results", query, len(results))
        return results
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"RCSB search failed with HTTP {e.response.status_code}.")
    except requests.exceptions.Timeout:
        raise RuntimeError("Search request to RCSB timed out.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to RCSB search API.")
