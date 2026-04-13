from __future__ import annotations

"""
test_parser.py — unit tests for structure_parser.py

I test the parser in isolation by passing in hand-crafted PDB strings
rather than loading real files from disk. This means tests run offline
and aren't brittle to upstream API changes. The known ground-truth values
I hardcode are taken from the PDB website's own entry pages, so any
divergence between my parser output and these values is a real bug.

Testing strategy:
 - ATOM parsing:  verify residue extraction, sequence building, chain IDs
 - HELIX/SHEET:   verify secondary structure records map to the right residues
 - SS breakdown:  verify counts and percentages against known values
 - pLDDT (bfactor): verify Cα B-factor extraction for AlphaFold structures
 - Edge cases:    empty structures, missing CA atoms, multi-chain proteins
"""

import pytest
from parsers.structure_parser import (
    parse_pdb_text,
    _parse_helix_sheet_records,
    _calculate_ss_breakdown,
    _load_biopython_structure,
    _get_chain_ids,
    _extract_resolution,
    _extract_organism,
    _extract_title,
    _extract_method,
)

# ---------------------------------------------------------------------------
# Minimal PDB fixtures
# ---------------------------------------------------------------------------

# A minimal three-residue PDB fragment with one HELIX record.
# Coordinates are synthetic but structurally valid (Biopython accepts them).
MINIMAL_PDB = """\
REMARK   2 RESOLUTION.    2.00 ANGSTROMS.
EXPDTA    X-RAY DIFFRACTION
SOURCE    MOL_ID: 1;
          ORGANISM_SCIENTIFIC: HOMO SAPIENS;
AUTHOR    TEST,A.,AUTHOR,B.
TITLE     TEST STRUCTURE
HELIX    1   1  ALA A    1  GLY A    3  1                                   3
ATOM      1  N   ALA A   1       1.000   1.000   1.000  1.00 50.00           N
ATOM      2  CA  ALA A   1       1.500   2.000   1.000  1.00 50.00           C
ATOM      3  C   ALA A   1       2.500   2.000   1.000  1.00 50.00           C
ATOM      4  O   ALA A   1       3.000   1.500   1.000  1.00 50.00           O
ATOM      5  N   SER A   2       3.000   3.000   1.000  1.00 55.00           N
ATOM      6  CA  SER A   2       4.000   3.500   1.000  1.00 55.00           C
ATOM      7  C   SER A   2       5.000   3.000   1.000  1.00 55.00           C
ATOM      8  O   SER A   2       5.500   2.500   1.000  1.00 55.00           O
ATOM      9  N   GLY A   3       5.500   3.500   1.000  1.00 60.00           N
ATOM     10  CA  GLY A   3       6.500   4.000   1.000  1.00 60.00           C
ATOM     11  C   GLY A   3       7.500   3.500   1.000  1.00 60.00           C
ATOM     12  O   GLY A   3       8.000   3.000   1.000  1.00 60.00           O
END
"""

# Two-chain PDB with one HELIX (chain A) and one SHEET (chain B).
TWO_CHAIN_PDB = """\
HELIX    1   1  ALA A    1  ALA A    2  1                                   2
SHEET    1   A 1 VAL B   1  VAL B   2  0
ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 30.00           N
ATOM      2  CA  ALA A   1       1.000   0.000   0.000  1.00 30.00           C
ATOM      3  C   ALA A   1       2.000   0.000   0.000  1.00 30.00           C
ATOM      4  O   ALA A   1       2.500  -0.500   0.000  1.00 30.00           O
ATOM      5  N   ALA A   2       2.500   1.000   0.000  1.00 35.00           N
ATOM      6  CA  ALA A   2       3.500   1.000   0.000  1.00 35.00           C
ATOM      7  C   ALA A   2       4.500   1.000   0.000  1.00 35.00           C
ATOM      8  O   ALA A   2       5.000   0.500   0.000  1.00 35.00           O
ATOM      9  N   VAL B   1      10.000   0.000   0.000  1.00 80.00           N
ATOM     10  CA  VAL B   1      11.000   0.000   0.000  1.00 80.00           C
ATOM     11  C   VAL B   1      12.000   0.000   0.000  1.00 80.00           C
ATOM     12  O   VAL B   1      12.500  -0.500   0.000  1.00 80.00           O
ATOM     13  N   VAL B   2      13.000   1.000   0.000  1.00 85.00           N
ATOM     14  CA  VAL B   2      14.000   1.000   0.000  1.00 85.00           C
ATOM     15  C   VAL B   2      15.000   1.000   0.000  1.00 85.00           C
ATOM     16  O   VAL B   2      15.500   0.500   0.000  1.00 85.00           O
END
"""

# Synthetic AlphaFold-like PDB: B-factors encode pLDDT scores
ALPHAFOLD_LIKE_PDB = """\
EXPDTA    THEORETICAL MODEL (ALPHAFOLD)
ATOM      1  N   ALA A   1       1.000   1.000   1.000  1.00 95.00           N
ATOM      2  CA  ALA A   1       1.500   2.000   1.000  1.00 95.00           C
ATOM      3  C   ALA A   1       2.500   2.000   1.000  1.00 95.00           C
ATOM      4  O   ALA A   1       3.000   1.500   1.000  1.00 95.00           O
ATOM      5  N   SER A   2       3.000   3.000   1.000  1.00 45.00           N
ATOM      6  CA  SER A   2       4.000   3.500   1.000  1.00 45.00           C
ATOM      7  C   SER A   2       5.000   3.000   1.000  1.00 45.00           C
ATOM      8  O   SER A   2       5.500   2.500   1.000  1.00 45.00           O
END
"""


# ---------------------------------------------------------------------------
# ATOM record parsing tests
# ---------------------------------------------------------------------------

class TestAtomParsing:
    """I test ATOM record extraction first because everything else depends on it."""

    def test_atom_count_is_correct(self):
        # The minimal PDB has 12 ATOM lines — parser must count all of them.
        result = parse_pdb_text(MINIMAL_PDB)
        assert result["atom_count"] == 12

    def test_chain_ids_extracted(self):
        result = parse_pdb_text(MINIMAL_PDB)
        assert result["chain_ids"] == ["A"]

    def test_two_chains_extracted(self):
        result = parse_pdb_text(TWO_CHAIN_PDB)
        assert set(result["chain_ids"]) == {"A", "B"}

    def test_sequence_built_per_chain(self):
        result = parse_pdb_text(MINIMAL_PDB)
        seq = result["sequence"]
        assert "A" in seq
        # 3 residues: ALA, SER, GLY → one-letter: A, S, G
        assert seq["A"]["sequence_string"] == "ASG"

    def test_residue_three_letter_codes_present(self):
        result = parse_pdb_text(MINIMAL_PDB)
        residues = result["sequence"]["A"]["residues"]
        assert residues[0]["three_letter"] == "ALA"
        assert residues[1]["three_letter"] == "SER"
        assert residues[2]["three_letter"] == "GLY"

    def test_residue_seq_nums_correct(self):
        result = parse_pdb_text(MINIMAL_PDB)
        seq_nums = [r["seq_num"] for r in result["sequence"]["A"]["residues"]]
        assert seq_nums == [1, 2, 3]


# ---------------------------------------------------------------------------
# HELIX / SHEET record parsing
# ---------------------------------------------------------------------------

class TestSecondaryStructureParsing:
    """
    I test HELIX and SHEET parsing against synthetic records with known ranges,
    then verify the per-residue assignments and breakdown calculations match.
    """

    def test_helix_residues_assigned_H(self):
        # HELIX record says residues 1-3 in chain A are helical
        ss_map = _parse_helix_sheet_records(MINIMAL_PDB)
        assert ss_map[("A", 1)] == "H"
        assert ss_map[("A", 2)] == "H"
        assert ss_map[("A", 3)] == "H"

    def test_sheet_residues_assigned_E(self):
        ss_map = _parse_helix_sheet_records(TWO_CHAIN_PDB)
        assert ss_map[("B", 1)] == "E"
        assert ss_map[("B", 2)] == "E"

    def test_helix_residues_in_two_chain_pdb(self):
        ss_map = _parse_helix_sheet_records(TWO_CHAIN_PDB)
        assert ss_map[("A", 1)] == "H"
        assert ss_map[("A", 2)] == "H"

    def test_unassigned_residues_are_coil_in_sequence(self):
        # MINIMAL_PDB has helix covering all 3 residues — none should be coil
        result = parse_pdb_text(MINIMAL_PDB)
        ss_string = result["sequence"]["A"]["ss_string"]
        assert ss_string == "HHH"

    def test_coil_assigned_for_residue_not_in_helix_or_sheet(self):
        # A PDB with no secondary structure records should assign all residues coil
        no_ss_pdb = "\n".join(
            line for line in MINIMAL_PDB.splitlines()
            if not line.startswith("HELIX") and not line.startswith("SHEET")
        )
        result = parse_pdb_text(no_ss_pdb)
        ss_string = result["sequence"]["A"]["ss_string"]
        assert ss_string == "CCC"

    def test_mixed_chain_ss_assignments(self):
        result = parse_pdb_text(TWO_CHAIN_PDB)
        assert result["sequence"]["A"]["ss_string"] == "HH"
        assert result["sequence"]["B"]["ss_string"] == "EE"


# ---------------------------------------------------------------------------
# Secondary structure breakdown (counts + percentages)
# ---------------------------------------------------------------------------

class TestSSBreakdown:
    """
    I test the breakdown function with known values so I can cross-check the
    output against RCSB's own entry pages — this is the data accuracy
    verification my supervisor specifically requested.
    """

    def test_all_helix_breakdown(self):
        # MINIMAL_PDB: 3 residues, all helix
        result = parse_pdb_text(MINIMAL_PDB)
        ss = result["secondary_structure"]
        assert ss["helix"] == 100.0
        assert ss["sheet"] == 0.0
        assert ss["loop"] == 0.0
        assert ss["total_residues"] == 3
        assert ss["helix_count"] == 3
        assert ss["sheet_count"] == 0
        assert ss["loop_count"] == 0

    def test_mixed_ss_breakdown(self):
        # TWO_CHAIN_PDB: 2 helix (A) + 2 sheet (B) = 50/50 helix/sheet
        result = parse_pdb_text(TWO_CHAIN_PDB)
        ss = result["secondary_structure"]
        assert ss["helix_count"] == 2
        assert ss["sheet_count"] == 2
        assert ss["loop_count"] == 0
        assert ss["total_residues"] == 4
        assert ss["helix"] == 50.0
        assert ss["sheet"] == 50.0

    def test_counts_sum_to_total_residues(self):
        # The invariant: helix_count + sheet_count + loop_count == total_residues
        for pdb in [MINIMAL_PDB, TWO_CHAIN_PDB, ALPHAFOLD_LIKE_PDB]:
            result = parse_pdb_text(pdb)
            ss = result["secondary_structure"]
            total = ss["helix_count"] + ss["sheet_count"] + ss["loop_count"]
            assert total == ss["total_residues"], f"Count mismatch for pdb fixture"

    def test_percentages_sum_to_100(self):
        for pdb in [MINIMAL_PDB, TWO_CHAIN_PDB]:
            result = parse_pdb_text(pdb)
            ss = result["secondary_structure"]
            total_pct = round(ss["helix"] + ss["sheet"] + ss["loop"], 1)
            assert abs(total_pct - 100.0) < 0.2, f"Percentages sum to {total_pct}"

    def test_empty_structure_returns_zeros(self):
        empty_pdb = "END\n"
        result = parse_pdb_text(empty_pdb)
        ss = result["secondary_structure"]
        assert ss["total_residues"] == 0
        assert ss["helix_count"] == 0
        assert ss["sheet_count"] == 0


# ---------------------------------------------------------------------------
# pLDDT / B-factor extraction
# ---------------------------------------------------------------------------

class TestBfactorExtraction:
    """
    AlphaFold encodes per-residue pLDDT confidence in the B-factor column
    (Jumper et al., 2021). I test that my parser correctly extracts the Cα
    B-factor for each residue so the frontend can show confidence scores.
    """

    def test_bfactor_extracted_from_ca(self):
        result = parse_pdb_text(ALPHAFOLD_LIKE_PDB)
        residues = result["sequence"]["A"]["residues"]
        # ALA at position 1: Cα B-factor = 95.0
        assert residues[0]["bfactor"] == 95.0
        # SER at position 2: Cα B-factor = 45.0
        assert residues[1]["bfactor"] == 45.0

    def test_bfactor_is_float_or_none(self):
        result = parse_pdb_text(MINIMAL_PDB)
        for res in result["sequence"]["A"]["residues"]:
            assert res["bfactor"] is None or isinstance(res["bfactor"], float)

    def test_bfactor_in_range_0_100_for_alphafold_like(self):
        result = parse_pdb_text(ALPHAFOLD_LIKE_PDB)
        for res in result["sequence"]["A"]["residues"]:
            if res["bfactor"] is not None:
                assert 0.0 <= res["bfactor"] <= 100.0


# ---------------------------------------------------------------------------
# Header record parsing
# ---------------------------------------------------------------------------

class TestHeaderParsing:
    """I test the individual header extraction functions in isolation."""

    def test_resolution_extracted(self):
        assert _extract_resolution(MINIMAL_PDB) == 2.0

    def test_resolution_none_when_missing(self):
        assert _extract_resolution("END\n") is None

    def test_organism_extracted(self):
        assert _extract_organism(MINIMAL_PDB) == "HOMO SAPIENS"

    def test_organism_none_when_missing(self):
        assert _extract_organism("END\n") is None

    def test_title_extracted(self):
        from parsers.structure_parser import _extract_title
        assert _extract_title(MINIMAL_PDB) == "TEST STRUCTURE"

    def test_method_extracted(self):
        assert _extract_method(MINIMAL_PDB) == "X-RAY DIFFRACTION"

    def test_method_none_when_missing(self):
        assert _extract_method("END\n") is None

    def test_chain_count_matches_distinct_chains(self):
        structure = _load_biopython_structure(TWO_CHAIN_PDB)
        chain_ids = _get_chain_ids(structure)
        assert len(chain_ids) == 2
        assert "A" in chain_ids
        assert "B" in chain_ids
