from __future__ import annotations

# unit tests for protein_routes.py (flask layer), service layer mocked out

import pytest
from unittest.mock import patch
import json
import sys
import os

# backend directory to path so imports resolve when pytest runs from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def app():
    from app import create_app
    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()


class TestGetProteinEndpoint:

    def test_valid_pdb_id_calls_service(self, client):
        mock_data = {
            "pdb_id": "1CRN", "title": "CRAMBIN", "organism": "Crambe hispanica",
            "method": "X-RAY DIFFRACTION", "resolution": 0.54, "authors": [],
            "atom_count": 327, "chain_ids": ["A"], "chains": [],
            "sequence": {}, "secondary_structure": {},
            "rcsb_url": "https://www.rcsb.org/structure/1CRN",
            "is_predicted": False, "source": "RCSB PDB",
        }
        with patch("routes.protein_routes.get_protein_info", return_value=mock_data):
            response = client.get("/api/protein/1CRN")
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body["data"]["pdb_id"] == "1CRN"
        assert body["status"] == 200

    def test_invalid_pdb_format_returns_400(self, client):
        # 'ABC' is only 3 characters - route must reject it
        response = client.get("/api/protein/ABC")
        assert response.status_code == 400
        body = json.loads(response.data)
        assert "error" in body

    def test_pdb_not_starting_with_digit_returns_400(self, client):
        # pdb ids must start with a digit
        response = client.get("/api/protein/ABCD")
        assert response.status_code == 400

    def test_not_found_pdb_returns_404(self, client):
        with patch("routes.protein_routes.get_protein_info",
                   side_effect=ValueError("PDB entry 'ZZZZ' was not found.")):
            response = client.get("/api/protein/1ZZZ")
        assert response.status_code == 404

    def test_remote_api_error_returns_502(self, client):
        with patch("routes.protein_routes.get_protein_info",
                   side_effect=RuntimeError("RCSB returned HTTP 500")):
            response = client.get("/api/protein/1CRN")
        assert response.status_code == 502

    def test_response_envelope_structure(self, client):
        mock_data = {"pdb_id": "4HHB", "title": "HAEMOGLOBIN"}
        with patch("routes.protein_routes.get_protein_info", return_value=mock_data):
            response = client.get("/api/protein/4HHB")
        body = json.loads(response.data)
        # every successful response must use { data: {...}, status: 200 }
        assert "data" in body
        assert "status" in body
        assert body["status"] == 200


class TestGetProteinStructureEndpoint:

    def test_structure_returns_plain_text(self, client):
        with patch("routes.protein_routes.get_protein_structure_text",
                   return_value="ATOM 1 CA ALA A 1\nEND\n"):
            response = client.get("/api/protein/1CRN/structure")
        assert response.status_code == 200
        assert b"ATOM" in response.data
        assert "text/plain" in response.content_type

    def test_invalid_pdb_format_returns_400(self, client):
        response = client.get("/api/protein/XX/structure")
        assert response.status_code == 400

    def test_not_found_returns_404(self, client):
        with patch("routes.protein_routes.get_protein_structure_text",
                   side_effect=ValueError("not found")):
            response = client.get("/api/protein/1ZZZ/structure")
        assert response.status_code == 404


class TestGetAlphaFoldEndpoint:

    def test_valid_uniprot_returns_200_with_disclaimer(self, client):
        mock_data = {
            "uniprot_id": "P68871", "title": "HAEMOGLOBIN BETA",
            "disclaimer": "This is a computationally predicted structure.",
            "is_predicted": True, "source": "AlphaFold Database (EBI)",
            "organism": "Homo sapiens", "method": "Computational prediction",
            "resolution": None, "atom_count": 0, "chain_ids": ["A"],
            "chains": [], "sequence": {}, "secondary_structure": {},
            "alphafold_url": "https://alphafold.ebi.ac.uk/entry/P68871",
            "authors": [],
        }
        with patch("routes.protein_routes.get_alphafold_info", return_value=mock_data):
            response = client.get("/api/alphafold/P68871")
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body["data"]["disclaimer"] != ""
        assert body["data"]["is_predicted"] is True

    def test_invalid_uniprot_format_returns_400(self, client):
        # 'XY' is too short to be a valid uniprot accession
        response = client.get("/api/alphafold/XY")
        assert response.status_code == 400

    def test_not_found_uniprot_returns_404(self, client):
        with patch("routes.protein_routes.get_alphafold_info",
                   side_effect=ValueError("No AlphaFold prediction found")):
            response = client.get("/api/alphafold/P00001")
        assert response.status_code == 404


class TestSearchEndpoint:

    def test_search_returns_results(self, client):
        mock_data = {
            "results": [{"pdb_id": "1CRN", "score": 0.9}],
            "query": "crambin",
            "count": 1,
        }
        with patch("routes.protein_routes.search_proteins", return_value=mock_data["results"]):
            response = client.get("/api/search?q=crambin")
        assert response.status_code == 200
        body = json.loads(response.data)
        assert "results" in body["data"]

    def test_missing_query_returns_400(self, client):
        response = client.get("/api/search")
        assert response.status_code == 400

    def test_single_char_query_returns_400(self, client):
        response = client.get("/api/search?q=a")
        assert response.status_code == 400

    def test_search_runtime_error_returns_502(self, client):
        with patch("routes.protein_routes.search_proteins",
                   side_effect=RuntimeError("RCSB search failed")):
            response = client.get("/api/search?q=haemoglobin")
        assert response.status_code == 502
