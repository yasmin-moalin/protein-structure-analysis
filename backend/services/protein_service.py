from __future__ import annotations

# business logic layer - no flask, no http, just python

import logging
from typing import Optional

from utils.pdb_fetcher import (
    fetch_pdb_structure,
    fetch_pdb_metadata,
    fetch_alphafold_structure,
    fetch_alphafold_metadata,
    search_rcsb,
)
from parsers.structure_parser import parse_pdb_text

logger = logging.getLogger(__name__)

# disclaimer lives here not in the route because it's about the data source
ALPHAFOLD_DISCLAIMER = (
    "This is a computationally predicted structure from the AlphaFold Database "
    "(Jumper et al., 2021), not an experimentally determined structure. "
    "Per-residue confidence scores (pLDDT) are encoded in the B-factor column. "
    "Scores above 90 indicate high confidence; below 50 indicate low confidence. "
    "Use caution when interpreting structural details in low-confidence regions."
)


def get_protein_info(pdb_id: str) -> dict:
    """merge rcsb rest metadata with parsed pdb data, falls back to pdb header if rest fails"""
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
        "ligands": parsed.get("ligands", {"count": 0, "unique_names": []}),
        "rcsb_url": f"https://www.rcsb.org/structure/{pdb_id}",
        "is_predicted": False,
        "source": "RCSB PDB",
    }


def get_protein_structure_text(pdb_id: str) -> str:
    """return raw pdb text for ngl to load"""
    return fetch_pdb_structure(pdb_id.upper().strip())


def get_alphafold_info(uniprot_id: str) -> dict:
    """build metadata dict for an alphafold prediction, ebi api fills in organism and gene"""
    uniprot_id = uniprot_id.upper().strip()
    logger.info("Building AlphaFold info package for UniProt: %s", uniprot_id)

    pdb_text = fetch_alphafold_structure(uniprot_id)
    parsed = parse_pdb_text(pdb_text)

    af_meta = fetch_alphafold_metadata(uniprot_id)

    # mean plddt calculated here because it spans all chains
    mean_plddt = _calculate_mean_plddt(parsed.get("sequence", {}))

    return {
        "uniprot_id": uniprot_id,
        "title": (
            af_meta.get("uniprotDescription")
            or parsed.get("title")
            or f"AlphaFold prediction for {uniprot_id}"
        ),
        "organism": (
            af_meta.get("organismScientificName")
            or parsed.get("organism")
            or "Unknown organism"
        ),
        "gene": af_meta.get("gene"),
        "method": "Computational prediction (AlphaFold v4, DeepMind)",
        "resolution": None,
        "authors": ["Jumper et al. (2021)", "DeepMind / Google"],
        "atom_count": parsed.get("atom_count", 0),
        "chain_ids": parsed.get("chain_ids", []),
        "chains": parsed.get("chains", []),
        "sequence": parsed.get("sequence", {}),
        "secondary_structure": parsed.get("secondary_structure", {}),
        "ligands": parsed.get("ligands", {"count": 0, "unique_names": []}),
        "alphafold_url": f"https://alphafold.ebi.ac.uk/entry/{uniprot_id}",
        "is_predicted": True,
        "mean_plddt": mean_plddt,
        "disclaimer": ALPHAFOLD_DISCLAIMER,
        "source": "AlphaFold Database (EBI)",
    }


def get_alphafold_structure_text(uniprot_id: str) -> str:
    """return raw alphafold pdb text for ngl to load"""
    return fetch_alphafold_structure(uniprot_id.upper().strip())


def search_proteins(query: str) -> list[dict]:
    """search rcsb and return pdb_id, score, title - full details loaded on demand"""
    query = query.strip()
    if len(query) < 2:
        raise ValueError("Search query must be at least 2 characters.")

    logger.info("Searching RCSB for: '%s'", query)
    raw = search_rcsb(query)

    return [
        {
            "pdb_id": result["pdb_id"],
            "score": round(result.get("score", 0), 3),
            "title": result.get("title") or "",
        }
        for result in raw
    ]


def _fetch_rest_metadata_safe(pdb_id: str) -> dict:
    """fetch rest metadata, return empty dict on failure so structure still loads"""
    try:
        raw = fetch_pdb_metadata(pdb_id)
        return _extract_rest_fields(raw)
    except Exception as exc:
        logger.warning("REST metadata failed for %s: %s", pdb_id, exc)
        return {}


def _calculate_mean_plddt(sequence: dict) -> Optional[float]:
    """average plddt scores across all chains - stored in b-factor column by alphafold"""
    scores = [
        r["bfactor"]
        for chain_data in sequence.values()
        for r in chain_data.get("residues", [])
        if r.get("bfactor") is not None
    ]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)


def _extract_rest_fields(raw: dict) -> dict:
    """pull the fields i need from the nested rcsb rest api response"""
    result: dict = {}

    struct = raw.get("struct", {})
    result["title"] = struct.get("title")

    refine = raw.get("refine", [{}])
    if isinstance(refine, list) and refine:
        result["resolution"] = refine[0].get("ls_d_res_high")

    exptl = raw.get("exptl", [{}])
    if isinstance(exptl, list) and exptl:
        result["method"] = exptl[0].get("method")

    # organism not available at entry level from rcsb rest, fall back to parser
    result["organism"] = None

    return result
