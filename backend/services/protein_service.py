from __future__ import annotations

"""
protein_service.py — business logic and orchestration

This layer sits between the routes and the fetcher/parser. It has no
knowledge of Flask or HTTP — it just accepts plain Python values, decides
which combination of data sources to use, and returns structured dicts.
That separation means I can test the business logic independently of Flask
and without making network calls (by mocking the fetcher).

The main decision this layer makes is how to combine RCSB REST metadata
(which has cleaner title and method fields in structured JSON) with the
parsed PDB file data (which has actual structural information). For PDB
entries, both sources contribute; for AlphaFold entries, only the parsed
file is available, supplemented with known constants.
"""

import logging
from typing import Optional

from utils.pdb_fetcher import (
    fetch_pdb_structure,
    fetch_pdb_metadata,
    fetch_alphafold_structure,
    search_rcsb,
)
from parsers.structure_parser import parse_pdb_text

logger = logging.getLogger(__name__)

# The AlphaFold disclaimer text. I define it here rather than in the route
# or frontend because it's a factual statement about the data source that
# belongs with the business logic — not with HTTP formatting or DOM updates.
# The pLDDT explanation is included because students need to know that the
# B-factor column encodes confidence, not temperature factors as in
# crystallographic structures (Jumper et al., 2021).
ALPHAFOLD_DISCLAIMER = (
    "This is a computationally predicted structure from the AlphaFold Database "
    "(Jumper et al., 2021), not an experimentally determined structure. "
    "Per-residue confidence scores (pLDDT) are encoded in the B-factor column. "
    "Scores above 90 indicate high confidence; below 50 indicate low confidence. "
    "Use caution when interpreting structural details in low-confidence regions."
)


def get_protein_info(pdb_id: str) -> dict:
    """
    Return combined structural and metadata info for a PDB entry.

    I fetch the RCSB REST metadata separately from the PDB file because
    the REST API gives me clean JSON fields for title and method — much
    nicer than parsing the fixed-column HEADER records. I then merge the
    REST fields with the parser output so the frontend gets everything in
    one response and doesn't need to make two API calls.

    If the REST metadata call fails, I fall back gracefully to the parsed
    PDB header fields. The structure still loads; the user just sees slightly
    less polished metadata text.
    """
    pdb_id = pdb_id.upper().strip()
    logger.info("Building protein info package for: %s", pdb_id)

    pdb_text = fetch_pdb_structure(pdb_id)
    parsed = parse_pdb_text(pdb_text)
    rest_meta = _fetch_rest_metadata_safe(pdb_id)

    return {
        "pdb_id": pdb_id,
        "title": rest_meta.get("title") or parsed.get("title") or "Title not available",
        "organism": rest_meta.get("organism") or parsed.get("organism") or "Unknown organism",
        "method": rest_meta.get("method") or parsed.get("method") or "Unknown method",
        "resolution": rest_meta.get("resolution") or parsed.get("resolution"),
        "authors": parsed.get("authors", []),
        "atom_count": parsed.get("atom_count", 0),
        "chain_ids": parsed.get("chain_ids", []),
        "chains": parsed.get("chains", []),
        "sequence": parsed.get("sequence", {}),
        "secondary_structure": parsed.get("secondary_structure", {}),
        "rcsb_url": f"https://www.rcsb.org/structure/{pdb_id}",
        "is_predicted": False,
        "source": "RCSB PDB",
    }


def get_protein_structure_text(pdb_id: str) -> str:
    """
    Return the raw PDB file text for NGL Viewer to load.

    Routing the structure file through the backend (rather than having the
    frontend fetch directly from RCSB) means the cache is shared — loading
    metadata and then the structure file for the same protein only hits RCSB
    once. The file content is served as plain text by the route layer.
    """
    return fetch_pdb_structure(pdb_id.upper().strip())


def get_alphafold_info(uniprot_id: str) -> dict:
    """
    Return structural info for an AlphaFold predicted structure.

    AlphaFold structures don't carry all the same metadata as experimental
    PDB entries — no crystallographic resolution, no depositing authors, no
    experimental method. I populate what I can from the parsed PDB file
    (title, organism if present, sequences, SS breakdown) and fill in
    known constants for the rest. The disclaimer field is mandatory and must
    be displayed prominently by the frontend.
    """
    uniprot_id = uniprot_id.upper().strip()
    logger.info("Building AlphaFold info package for UniProt: %s", uniprot_id)

    pdb_text = fetch_alphafold_structure(uniprot_id)
    parsed = parse_pdb_text(pdb_text)

    return {
        "uniprot_id": uniprot_id,
        "title": parsed.get("title") or f"AlphaFold prediction for {uniprot_id}",
        "organism": parsed.get("organism") or "Unknown organism",
        "method": "Computational prediction (AlphaFold v4, DeepMind)",
        "resolution": None,
        "authors": ["Jumper et al. (2021)", "DeepMind / Google"],
        "atom_count": parsed.get("atom_count", 0),
        "chain_ids": parsed.get("chain_ids", []),
        "chains": parsed.get("chains", []),
        "sequence": parsed.get("sequence", {}),
        "secondary_structure": parsed.get("secondary_structure", {}),
        "alphafold_url": f"https://alphafold.ebi.ac.uk/entry/{uniprot_id}",
        "is_predicted": True,
        "disclaimer": ALPHAFOLD_DISCLAIMER,
        "source": "AlphaFold Database (EBI)",
    }


def get_alphafold_structure_text(uniprot_id: str) -> str:
    """Return the raw AlphaFold PDB text for NGL Viewer to load."""
    return fetch_alphafold_structure(uniprot_id.upper().strip())


def search_proteins(query: str) -> list[dict]:
    """
    Search RCSB PDB by free text and return a simplified result list.

    I return only { pdb_id, score } rather than the full RCSB response
    because the search results are displayed as a clickable list — the user
    selects one to load it, at which point get_protein_info() fetches all
    the detail. Fetching full metadata for 25 results upfront would be
    extremely wasteful and slow.
    """
    query = query.strip()
    if len(query) < 2:
        raise ValueError("Search query must be at least 2 characters.")

    logger.info("Searching RCSB for: '%s'", query)
    raw = search_rcsb(query)

    return [
        {
            "pdb_id": result["identifier"],
            "score": round(result.get("score", 0), 3),
        }
        for result in raw
    ]


def _fetch_rest_metadata_safe(pdb_id: str) -> dict:
    """
    Attempt to fetch REST metadata, returning an empty dict on failure.

    I wrap the REST call in a broad except because it's supplementary —
    the parsed PDB file contains enough information to render the structure
    even if this call fails. A transient API hiccup shouldn't break the
    whole structure load.
    """
    try:
        raw = fetch_pdb_metadata(pdb_id)
        return _extract_rest_fields(raw)
    except Exception as exc:
        logger.warning("REST metadata failed for %s: %s", pdb_id, exc)
        return {}


def _extract_rest_fields(raw: dict) -> dict:
    """
    Pull the specific fields I need from the RCSB REST API response.

    The REST response is a deeply nested dict. I extract only what I need
    into a flat dict so the rest of the service layer never has to traverse
    the tree structure — that coupling would make future API changes painful.
    """
    result: dict = {}

    # Title — most reliably found in raw["struct"]["title"]
    struct = raw.get("struct", {})
    result["title"] = struct.get("title")

    # Resolution — in the refine list for X-ray structures
    refine = raw.get("refine", [{}])
    if isinstance(refine, list) and refine:
        result["resolution"] = refine[0].get("ls_d_res_high")

    # Experimental method — in exptl list
    exptl = raw.get("exptl", [{}])
    if isinstance(exptl, list) and exptl:
        result["method"] = exptl[0].get("method")

    # Organism — RCSB puts this in entity-level data, not entry-level.
    # The entry endpoint doesn't include it directly, so we fall back to
    # the PDB parser's SOURCE record extraction for organism.
    result["organism"] = None

    return result
