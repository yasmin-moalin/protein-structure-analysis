from __future__ import annotations

# unit tests for protein_service.py, network calls mocked out

import pytest
from unittest.mock import patch, MagicMock


# minimal pdb text sufficient for the parser to run without error
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

    @patch("services.protein_service.fetch_pdb_structure", return_value=_MINI_PDB)
    @patch("services.protein_service.fetch_pdb_metadata", return_value=_MOCK_REST_META)
    def test_returns_expected_fields(self, mock_meta, mock_struct):
        from services.protein_service import get_protein_info
        result = get_protein_info("1HHO")
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
        # rest api title should win over the title record from the pdb file
        assert result["title"] == "STRUCTURE OF HAEMOGLOBIN"

    @patch("services.protein_service.fetch_pdb_structure", return_value=_MINI_PDB)
    @patch("services.protein_service.fetch_pdb_metadata", side_effect=RuntimeError("API down"))
    def test_fallback_to_parsed_title_when_rest_fails(self, mock_meta, mock_struct):
        from services.protein_service import get_protein_info
        result = get_protein_info("1HHO")
        assert result is not None
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

    @patch("services.protein_service.fetch_alphafold_structure", return_value=_MINI_PDB)
    def test_returns_disclaimer(self, mock_struct):
        from services.protein_service import get_alphafold_info
        result = get_alphafold_info("P68871")
        assert "disclaimer" in result
        assert len(result["disclaimer"]) > 50

    @patch("services.protein_service.fetch_alphafold_structure", return_value=_MINI_PDB)
    def test_is_predicted_flag_true(self, mock_struct):
        from services.protein_service import get_alphafold_info
        result = get_alphafold_info("P68871")
        assert result["is_predicted"] is True

    @patch("services.protein_service.fetch_alphafold_structure", return_value=_MINI_PDB)
    def test_resolution_is_none(self, mock_struct):
        from services.protein_service import get_alphafold_info
        # alphafold structures have no crystallographic resolution
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
