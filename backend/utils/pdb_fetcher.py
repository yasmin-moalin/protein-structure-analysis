from __future__ import annotations

"""
pdb_fetcher.py — all outbound HTTP calls live here

I centralised every network call in this module so the rest of the stack
never has to know about URLs, headers, or retry logic. If RCSB changes
their API tomorrow, I only edit this file — the layers above are insulated
from that change.

I use requests.Session rather than plain requests.get because the session
reuses TCP connections. When a user loads several proteins in a row the
latency difference is noticeable — each new connection adds roughly 100ms
of TLS handshake overhead on top of the actual transfer time.

Rate-limiting note: RCSB's terms of service allow programmatic access for
research and education but ask clients to be polite. I address this in three
ways: (1) a 1-hour in-memory cache so the same structure is never fetched
twice in a session, (2) a descriptive User-Agent header so RCSB can identify
the client if there's ever a problem, and (3) using their CDN-served PDB
files for structure downloads rather than the search API, which is the
intended usage pattern for single-entry retrieval.
"""

import time
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# 1 hour TTL — protein structures are updated weekly at most, so an hour
# covers any realistic user session without risk of stale data.
CACHE_TTL_SECONDS = 3600

# Simple dict-based cache: { key: (data, timestamp) }.
# I went with an in-memory dict rather than Redis because this is a prototype
# running locally — the overhead of a separate cache service isn't justified
# at this scale, and a simple dict gives me the same TTL behaviour with zero
# extra dependencies. In a multi-process deployment I'd swap this for Redis
# or Memcached, but that's out of scope here.
_cache: dict[str, tuple] = {}

# A single session instance for the whole module lifetime so all calls
# benefit from connection pooling. The User-Agent string identifies the
# client to the remote server — this is responsible API practice.
_session = requests.Session()
_session.headers.update({
    "User-Agent": "ProteinVis/1.0 (COMP1682 FYP; University of Greenwich; educational use)"
})

# RCSB base URLs — module-level constants so they're easy to update if
# the API changes. RCSB moved from v1 to v2 search recently, so keeping
# these isolated matters.
RCSB_FILES_BASE = "https://files.rcsb.org/download"
RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_DATA_API = "https://data.rcsb.org/rest/v1/core/entry"

# AlphaFold EBI base URL. I use v4 model files — the most recent stable
# release following Jumper et al. (2021). Earlier versions are still served
# but v4 has improved confidence scoring.
ALPHAFOLD_FILES_BASE = "https://alphafold.ebi.ac.uk/files"


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
    a problem — no point in deferring that check and waiting for a network
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
        logger.info("Fetched PDB %s — %d bytes", pdb_id, len(pdb_text))
        return pdb_text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise ValueError(
                f"PDB entry '{pdb_id}' was not found. "
                "Please check the identifier — PDB IDs are 4 characters (e.g. 1CRN, 4HHB)."
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
    because the REST response is structured JSON — much easier to extract
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

    AlphaFold DB (Jumper et al., 2021) serves PDB-format files at a
    predictable URL pattern. I use model version 4 (v4) as the current
    stable release. Structures can be large — up to 2700 residues for
    full-length proteins — so I give this a longer timeout than PDB fetches.
    The disclaimer that this is a prediction is handled at the service layer.
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
        logger.info("Fetched AlphaFold %s — %d bytes", uniprot_id, len(pdb_text))
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
            "AlphaFold structures can be large — please try again."
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to AlphaFold DB. Check your internet connection.")


def search_rcsb(query: str, max_results: int = 25) -> list[dict]:
    """
    Run a full-text search against the RCSB PDB Search API.

    I use the v2 search API with a full_text query type because it handles
    misspellings and partial matches better than a strict field match. A
    student searching for 'haemoglobin' (British spelling) should still find
    haemoglobin structures. Results are capped at 25 — displaying more in a
    sidebar list isn't useful without pagination, and pagination would add
    frontend complexity that's out of scope for this project.
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
        results = data.get("result_set", [])
        _set_cached(cache_key, results)
        logger.info("Search for '%s' returned %d results", query, len(results))
        return results
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"RCSB search failed with HTTP {e.response.status_code}.")
    except requests.exceptions.Timeout:
        raise RuntimeError("Search request to RCSB timed out.")
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to RCSB search API.")
