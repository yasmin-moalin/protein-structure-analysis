from __future__ import annotations

"""
test_service.py — unit tests for protein_service.py

I test the service layer with all network calls mocked out so tests run
offline and deterministically. The service layer's job is orchestration —
combining fetcher output with parser output — so I verify that the merging
logic is correct, fallbacks work when REST metadata fails, and the AlphaFold
disclaimer is always present on predicted structures.

Isolation strategy: patch the four functions imported by protein_service at
the point of use (in the 'services.protein_service' namespace, not in the
modules where they're defined).
"""

import pytest
from unittest.mock import patch, MagicMock


# Minimal PDB text sufficient for the parser to run without error
_MINI_PDB = """\
TITLE     HAEMOGLOBIN
EXPDTA    X-RAY DIFFRACTION
REMARK   2 RESOLUTION.    1.74 ANGSTROMS.
SOURCE    MOL_ID: 1;
          ORGANISM_SCIENTIFIC: HOMO SAPIENS;
ATOM      1  N   ALA A   1       1.000   1.000   1.000  1.00 30.00           N
ATOM      2  CA  ALA A   1       1.500   2.000   1.000  1.00 30.00           C
ATOM      3  C   ALA A   1       2.500   2.000   1.000  1.00 30.00           C
ATOM      4  O   ALA A   1       3.000   1.500   1.000  1.00 30.00           O
END
"""

_MOCK_REST_META = {
    "struct": {"title": "STRUCTURE OF HAEMOGLOBIN"},
    "refine": [{"ls_d_res_high": 1.74}],
    "exptl": [{"method": "X-RAY DIFFRACTION"}],
}


class TestGetProteinInfo:
    """Tests for the main PDB info assembly function."""

    @patch("services.protein_service.fetch_pdb_structure", return_value=_MINI_PDB)
    @patch("services.protein_service.fetch_pdb_metadata", return_value=_MOCK_REST_META)
    def test_returns_expected_fields(self, mock_meta, mock_struct):
        from services.protein_service import get_protein_info
        result = get_protein_info("1HHO")

        # I check the contract: the service must always return these fields
        # because the frontend depends on all of them being present.
        assert result["pdb_id"] == "1HHO"
        assert "title" in result
        assert "organism" in result
        assert "method" in result
        assert "chain_ids" in result
        assert "chains" in result
        assert "sequence" in result
        assert "secondary_structure" in result
        assert result["is_predicted"] is False
        assert result["source"] == "RCSB PDB"

    @patch("services.protein_service.fetch_pdb_structure", return_value=_MINI_PDB)
    @patch("services.protein_service.fetch_pdb_metadata", return_value=_MOCK_REST_META)
    def test_rest_title_preferred_over_parsed_title(self, mock_meta, mock_struct):
        from services.protein_service import get_protein_info
        result = get_protein_info("1HHO")
        # REST API title should win over the TITLE record from the PDB file
        assert result["title"] == "STRUCTURE OF HAEMOGLOBIN"

    @patch("services.protein_service.fetch_pdb_structure", return_value=_MINI_PDB)
    @patch("services.protein_service.fetch_pdb_metadata", side_effect=RuntimeError("API down"))
    def test_fallback_to_parsed_title_when_rest_fails(self, mock_meta, mock_struct):
        from services.protein_service import get_protein_info
        # If the REST API call fails, the service must still return a result
        # using data parsed from the PDB file itself.
        result = get_protein_info("1HHO")
        assert result is not None
        # Title should fall back to the TITLE record in the PDB file
        assert result["title"] == "HAEMOGLOBIN"

    @patch("services.protein_service.fetch_pdb_structure", return_value=_MINI_PDB)
    @patch("services.protein_service.fetch_pdb_metadata", return_value=_MOCK_REST_META)
    def test_resolution_from_rest_meta(self, mock_meta, mock_struct):
        from services.protein_service import get_protein_info
        result = get_protein_info("1HHO")
        assert result["resolution"] == 1.74

    @patch("services.protein_service.fetch_pdb_structure",
           side_effect=ValueError("PDB entry 'XXXX' was not found."))
    @patch("services.protein_service.fetch_pdb_metadata", return_value={})
    def test_raises_value_error_for_missing_pdb(self, mock_meta, mock_struct):
        from services.protein_service import get_protein_info
        with pytest.raises(ValueError, match="not found"):
            get_protein_info("XXXX")


class TestGetAlphaFoldInfo:
    """Tests for the AlphaFold info assembly function."""

    @patch("services.protein_service.fetch_alphafold_structure", return_value=_MINI_PDB)
    def test_returns_disclaimer(self, mock_struct):
        from services.protein_service import get_alphafold_info
        result = get_alphafold_info("P68871")
        # The disclaimer is mandatory — scientific integrity requires that
        # predicted structures are always clearly labelled.
        assert "disclaimer" in result
        assert len(result["disclaimer"]) > 50  # non-trivial disclaimer text

    @patch("services.protein_service.fetch_alphafold_structure", return_value=_MINI_PDB)
    def test_is_predicted_flag_true(self, mock_struct):
        from services.protein_service import get_alphafold_info
        result = get_alphafold_info("P68871")
        assert result["is_predicted"] is True

    @patch("services.protein_service.fetch_alphafold_structure", return_value=_MINI_PDB)
    def test_resolution_is_none(self, mock_struct):
        from services.protein_service import get_alphafold_info
        # AlphaFold structures have no crystallographic resolution
        result = get_alphafold_info("P68871")
        assert result["resolution"] is None

    @patch("services.protein_service.fetch_alphafold_structure", return_value=_MINI_PDB)
    def test_alphafold_url_present(self, mock_struct):
        from services.protein_service import get_alphafold_info
        result = get_alphafold_info("P68871")
        assert "alphafold.ebi.ac.uk" in result["alphafold_url"]
        assert "P68871" in result["alphafold_url"]

    @patch("services.protein_service.fetch_alphafold_structure",
           side_effect=ValueError("No AlphaFold prediction found"))
    def test_raises_value_error_for_missing_uniprot(self, mock_struct):
        from services.protein_service import get_alphafold_info
        with pytest.raises(ValueError, match="AlphaFold"):
            get_alphafold_info("ZZZZZZ")


class TestSearchProteins:
    """Tests for the search wrapper function."""

    @patch("services.protein_service.search_rcsb", return_value=[
        {"identifier": "1CRN", "score": 0.95},
        {"identifier": "4HHB", "score": 0.88},
    ])
    def test_returns_simplified_results(self, mock_search):
        from services.protein_service import search_proteins
        results = search_proteins("crambin")
        assert len(results) == 2
        assert results[0]["pdb_id"] == "1CRN"
        assert "score" in results[0]

    def test_raises_for_short_query(self):
        from services.protein_service import search_proteins
        with pytest.raises(ValueError, match="at least 2"):
            search_proteins("a")

    @patch("services.protein_service.search_rcsb", return_value=[])
    def test_empty_search_returns_empty_list(self, mock_search):
        from services.protein_service import search_proteins
        results = search_proteins("zzzquerynotfound")
        assert results == []
