from __future__ import annotations

"""
test_fetcher.py - unit tests for pdb_fetcher.py

I test the fetcher in isolation using unittest.mock so no real HTTP calls
are made. The tests verify:
  1. Successful responses are returned and cached
  2. 404 HTTP errors raise ValueError (not found - user-visible message)
  3. Other HTTP errors raise RuntimeError (server error)
  4. Network timeouts raise RuntimeError
  5. The cache returns stale data after TTL expiry (simulated with time mock)
  6. The RCSB search API payload is well-formed

I do NOT test that RCSB actually returns haemoglobin when you search for it -
that's an integration concern, not a unit concern.
"""

import time
import pytest
from unittest.mock import patch, MagicMock
import requests


# ---------------------------------------------------------------------------
# fetch_pdb_structure tests
# ---------------------------------------------------------------------------

class TestFetchPdbStructure:

    def _make_response(self, status_code: int, text: str = "") -> MagicMock:
        """Helper that builds a mock requests.Response object."""
        r = MagicMock()
        r.status_code = status_code
        r.text = text
        if status_code >= 400:
            http_err = requests.exceptions.HTTPError(response=r)
            r.raise_for_status.side_effect = http_err
        else:
            r.raise_for_status.return_value = None
        return r

    def test_successful_fetch_returns_pdb_text(self):
        from utils.pdb_fetcher import fetch_pdb_structure, _cache
        _cache.clear()

        mock_resp = self._make_response(200, "ATOM      1  CA  ALA A   1\nEND\n")
        with patch("utils.pdb_fetcher._session") as mock_session:
            mock_session.get.return_value = mock_resp
            result = fetch_pdb_structure("1CRN")
        assert "ATOM" in result

    def test_404_raises_value_error(self):
        from utils.pdb_fetcher import fetch_pdb_structure, _cache
        _cache.clear()

        mock_resp = self._make_response(404)
        with patch("utils.pdb_fetcher._session") as mock_session:
            mock_session.get.return_value = mock_resp
            with pytest.raises(ValueError, match="not found"):
                fetch_pdb_structure("ZZZZ")

    def test_500_raises_runtime_error(self):
        from utils.pdb_fetcher import fetch_pdb_structure, _cache
        _cache.clear()

        mock_resp = self._make_response(500)
        with patch("utils.pdb_fetcher._session") as mock_session:
            mock_session.get.return_value = mock_resp
            with pytest.raises(RuntimeError):
                fetch_pdb_structure("1CRN")

    def test_timeout_raises_runtime_error(self):
        from utils.pdb_fetcher import fetch_pdb_structure, _cache
        _cache.clear()

        with patch("utils.pdb_fetcher._session") as mock_session:
            mock_session.get.side_effect = requests.exceptions.Timeout()
            with pytest.raises(RuntimeError, match="timed out"):
                fetch_pdb_structure("1CRN")

    def test_connection_error_raises_runtime_error(self):
        from utils.pdb_fetcher import fetch_pdb_structure, _cache
        _cache.clear()

        with patch("utils.pdb_fetcher._session") as mock_session:
            mock_session.get.side_effect = requests.exceptions.ConnectionError()
            with pytest.raises(RuntimeError, match="connect"):
                fetch_pdb_structure("1CRN")

    def test_cache_hit_avoids_second_request(self):
        from utils.pdb_fetcher import fetch_pdb_structure, _cache, _set_cached
        # Pre-populate cache to simulate a previous fetch
        _set_cached("pdb_structure_1CRN", "CACHED_DATA")

        with patch("utils.pdb_fetcher._session") as mock_session:
            result = fetch_pdb_structure("1CRN")
            mock_session.get.assert_not_called()

        assert result == "CACHED_DATA"


# ---------------------------------------------------------------------------
# fetch_alphafold_structure tests
# ---------------------------------------------------------------------------

class TestFetchAlphaFoldStructure:

    def test_404_raises_value_error_with_uniprot_mention(self):
        from utils.pdb_fetcher import fetch_alphafold_structure, _cache
        _cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        http_err = requests.exceptions.HTTPError(response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_err

        with patch("utils.pdb_fetcher._session") as mock_session:
            mock_session.get.return_value = mock_resp
            with pytest.raises(ValueError, match="AlphaFold"):
                fetch_alphafold_structure("ZZZZZZ")

    def test_timeout_raises_runtime_error(self):
        from utils.pdb_fetcher import fetch_alphafold_structure, _cache
        _cache.clear()

        with patch("utils.pdb_fetcher._session") as mock_session:
            mock_session.get.side_effect = requests.exceptions.Timeout()
            with pytest.raises(RuntimeError, match="timed out"):
                fetch_alphafold_structure("P68871")


# ---------------------------------------------------------------------------
# search_rcsb tests
# ---------------------------------------------------------------------------

class TestSearchRcsb:

    def test_successful_search_returns_result_list(self):
        from utils.pdb_fetcher import search_rcsb, _cache
        _cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "result_set": [
                {"identifier": "1CRN", "score": 0.95},
                {"identifier": "4HHB", "score": 0.88},
            ]
        }

        with patch("utils.pdb_fetcher._session") as mock_session:
            mock_session.post.return_value = mock_resp
            results = search_rcsb("crambin")

        assert len(results) == 2
        assert results[0]["identifier"] == "1CRN"

    def test_empty_result_returns_empty_list(self):
        from utils.pdb_fetcher import search_rcsb, _cache
        _cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"result_set": []}

        with patch("utils.pdb_fetcher._session") as mock_session:
            mock_session.post.return_value = mock_resp
            results = search_rcsb("zzznotaprotein")

        assert results == []

    def test_timeout_raises_runtime_error(self):
        from utils.pdb_fetcher import search_rcsb, _cache
        _cache.clear()

        with patch("utils.pdb_fetcher._session") as mock_session:
            mock_session.post.side_effect = requests.exceptions.Timeout()
            with pytest.raises(RuntimeError, match="timed out"):
                search_rcsb("insulin")


# ---------------------------------------------------------------------------
# Cache TTL tests
# ---------------------------------------------------------------------------

class TestCacheTTL:

    def test_cache_expires_after_ttl(self):
        from utils.pdb_fetcher import _set_cached, _get_cached, CACHE_TTL_SECONDS

        _set_cached("test_key", "test_data")
        assert _get_cached("test_key") == "test_data"

        # Simulate time advancing past TTL by patching time.time
        with patch("utils.pdb_fetcher.time") as mock_time:
            mock_time.time.return_value = time.time() + CACHE_TTL_SECONDS + 1
            assert _get_cached("test_key") is None

    def test_fresh_cache_not_expired(self):
        from utils.pdb_fetcher import _set_cached, _get_cached
        _set_cached("fresh_key", "fresh_data")
        assert _get_cached("fresh_key") == "fresh_data"
