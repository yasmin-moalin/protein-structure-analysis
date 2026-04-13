from __future__ import annotations

"""
protein_routes.py: HTTP interface only

Flask, status codes, JSON formatting, nothing else. Business logic stays in
the service layer. I validate ID format here but leave semantic checks (does
this entry exist?) to the fetcher, which would make the same network call anyway.
"""

import re
import logging
from typing import Optional

from flask import Blueprint, request, jsonify, make_response, Response

from services.protein_service import (
    get_protein_info,
    get_protein_structure_text,
    get_alphafold_info,
    get_alphafold_structure_text,
    search_proteins,
)

logger = logging.getLogger(__name__)

protein_bp = Blueprint("protein", __name__, url_prefix="/api")

# PDB IDs are exactly 4 characters: a digit followed by three alphanumerics.
_PDB_PATTERN = re.compile(r"^[0-9][A-Z0-9]{3}$")

# UniProt accession format covers both legacy 6-char (e.g. P68871) and
# the newer 10-char format (e.g. A0A000AB12), per UniProt documentation.
_UNIPROT_PATTERN = re.compile(
    r"^[OPQ][0-9][A-Z0-9]{3}[0-9]([A-Z][A-Z0-9]{2}[0-9])?$"
    r"|^[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}$"
)


def _validate_pdb_id(pdb_id: str) -> Optional[str]:
    """Return an error string if the PDB ID is invalid, else None."""
    if not pdb_id or not pdb_id.strip():
        return "PDB ID is required."
    if not _PDB_PATTERN.match(pdb_id.upper().strip()):
        return (
            f"'{pdb_id}' is not a valid PDB identifier. "
            "PDB IDs are 4 characters: a digit followed by three alphanumeric characters "
            "(e.g. 1CRN, 4HHB, 1TIM)."
        )
    return None


def _validate_uniprot_id(uniprot_id: str) -> Optional[str]:
    """Return an error string if the UniProt accession is invalid, else None."""
    if not uniprot_id or not uniprot_id.strip():
        return "UniProt accession is required."
    cleaned = uniprot_id.upper().strip()
    # A relaxed length check covers accessions the regex might miss while
    # still catching obvious garbage input. UniProt accessions are 6 or 10 chars.
    if len(cleaned) not in (6, 10) or not cleaned[0].isalpha():
        return (
            f"'{uniprot_id}' does not look like a valid UniProt accession. "
            "UniProt accessions are 6 or 10 characters and start with a letter "
            "(e.g. P68871, Q5VSL9, A0A000A0A0)."
        )
    return None


def _error(message: str, code: int) -> Response:
    """Format a consistent JSON error response."""
    return make_response(jsonify({"error": message, "status": code}), code)


def _ok(data: dict) -> Response:
    """Format a consistent JSON success response."""
    return make_response(jsonify({"data": data, "status": 200}), 200)


@protein_bp.route("/protein/<pdb_id>", methods=["GET"])
def get_protein(pdb_id: str) -> Response:
    """Return metadata and structural analysis for a PDB entry."""
    err = _validate_pdb_id(pdb_id)
    if err:
        return _error(err, 400)

    try:
        data = get_protein_info(pdb_id.upper().strip())
        logger.info("Served /api/protein/%s", pdb_id.upper())
        return _ok(data)
    except ValueError as exc:
        return _error(str(exc), 404)
    except RuntimeError as exc:
        return _error(str(exc), 502)
    except Exception:
        logger.exception("Unexpected error in get_protein(%s)", pdb_id)
        return _error("An unexpected error occurred. Please try again.", 500)


@protein_bp.route("/protein/<pdb_id>/structure", methods=["GET"])
def get_protein_structure(pdb_id: str) -> Response:
    """Serve the raw PDB file as plain text for NGL Viewer to load."""
    err = _validate_pdb_id(pdb_id)
    if err:
        return _error(err, 400)

    try:
        pdb_text = get_protein_structure_text(pdb_id.upper().strip())
        resp = make_response(pdb_text, 200)
        resp.headers["Content-Type"] = "text/plain; charset=utf-8"
        return resp
    except ValueError as exc:
        return _error(str(exc), 404)
    except RuntimeError as exc:
        return _error(str(exc), 502)
    except Exception:
        logger.exception("Unexpected error in get_protein_structure(%s)", pdb_id)
        return _error("Could not retrieve structure file.", 500)


@protein_bp.route("/alphafold/<uniprot_id>", methods=["GET"])
def get_alphafold(uniprot_id: str) -> Response:
    """Return metadata and structural info for an AlphaFold predicted structure."""
    err = _validate_uniprot_id(uniprot_id)
    if err:
        return _error(err, 400)

    try:
        data = get_alphafold_info(uniprot_id.upper().strip())
        logger.info("Served /api/alphafold/%s", uniprot_id.upper())
        return _ok(data)
    except ValueError as exc:
        return _error(str(exc), 404)
    except RuntimeError as exc:
        return _error(str(exc), 502)
    except Exception:
        logger.exception("Unexpected error in get_alphafold(%s)", uniprot_id)
        return _error("An unexpected error occurred. Please try again.", 500)


@protein_bp.route("/alphafold/<uniprot_id>/structure", methods=["GET"])
def get_alphafold_structure(uniprot_id: str) -> Response:
    """Serve raw AlphaFold PDB text for NGL Viewer."""
    err = _validate_uniprot_id(uniprot_id)
    if err:
        return _error(err, 400)

    try:
        pdb_text = get_alphafold_structure_text(uniprot_id.upper().strip())
        resp = make_response(pdb_text, 200)
        resp.headers["Content-Type"] = "text/plain; charset=utf-8"
        return resp
    except ValueError as exc:
        return _error(str(exc), 404)
    except RuntimeError as exc:
        return _error(str(exc), 502)
    except Exception:
        logger.exception("Unexpected error in get_alphafold_structure(%s)", uniprot_id)
        return _error("Could not retrieve AlphaFold structure file.", 500)


@protein_bp.route("/search", methods=["GET"])
def search() -> Response:
    """Search RCSB PDB by free text. GET because it's a read-only, idempotent operation."""
    query = request.args.get("q", "").strip()

    if not query:
        return _error("Search query parameter 'q' is required.", 400)
    if len(query) < 2:
        return _error("Search query must be at least 2 characters.", 400)

    try:
        results = search_proteins(query)
        return _ok({"results": results, "query": query, "count": len(results)})
    except ValueError as exc:
        return _error(str(exc), 400)
    except RuntimeError as exc:
        return _error(str(exc), 502)
    except Exception:
        logger.exception("Unexpected error in search(q='%s')", query)
        return _error("Search failed. Please try again.", 500)
