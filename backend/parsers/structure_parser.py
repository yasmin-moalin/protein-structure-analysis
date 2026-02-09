from __future__ import annotations

"""
structure_parser.py — PDB file parsing only, no network calls

This module's only job is to read PDB text and extract information from it.
I keep it strictly isolated from network calls and Flask so that it can be
tested independently by passing in a PDB string directly.

PDB format is old — it dates to 1971 and uses fixed-column records, which
makes it tedious to parse manually. I combine Biopython's PDBParser for
structural data (atoms, chains, residues, polypeptide chains) with manual
line parsing for header records like HELIX, SHEET, AUTHOR, SOURCE, and
EXPDTA. Biopython doesn't expose all of these cleanly, and its fixed-column
assumptions sometimes miss edge cases in real-world files.

The hybrid approach means I get reliability from Biopython where it matters
(atom coordinates, residue identity) and flexibility from direct parsing
where Biopython's abstractions get in the way (secondary structure records,
organism extraction).
"""

import io
import logging
from typing import Optional

from Bio.PDB import PDBParser, PPBuilder
from Bio.PDB.Structure import Structure

logger = logging.getLogger(__name__)

# Standard 3-letter to 1-letter amino acid codes. I define this here
# rather than importing from Biopython's seq module because I only need
# it for sequence display. Keeping the dependency surface small makes
# the code easier to explain and test.
AA_THREE_TO_ONE: dict[str, str] = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "SEC": "U", "PYL": "O",  # selenocysteine and pyrrolysine — uncommon but valid
    "MSE": "M",              # selenomethionine — common in X-ray structures
}


def parse_pdb_text(pdb_text: str) -> dict:
    """
    Parse a complete PDB file string and return all extracted data.

    Returns a single dict so the service layer has one thing to deal with
    rather than calling multiple parse functions. Everything the frontend
    needs — metadata, per-chain sequences with secondary structure annotation,
    atom counts, secondary structure breakdown percentages — comes back from
    this one call.
    """
    structure = _load_biopython_structure(pdb_text)
    ss_residues = _parse_helix_sheet_records(pdb_text)
    sequences = _build_sequences(structure, ss_residues)

    return {
        "atom_count": _count_atoms(structure),
        "chain_ids": _get_chain_ids(structure),
        "chains": _get_chain_details(structure),
        "resolution": _extract_resolution(pdb_text),
        "organism": _extract_organism(pdb_text),
        "authors": _extract_authors(pdb_text),
        "title": _extract_title(pdb_text),
        "method": _extract_method(pdb_text),
        "sequence": sequences,
        "secondary_structure": _calculate_ss_breakdown(structure, ss_residues),
    }


def _load_biopython_structure(pdb_text: str) -> Structure:
    """
    Parse the PDB text into a Biopython Structure object.

    QUIET=True suppresses warnings because real-world PDB files are
    notoriously noisy — missing atoms, non-standard residues, duplicate
    chain IDs in biological assemblies. These warnings don't affect the
    data I care about and would flood the logs during normal use.
    """
    parser = PDBParser(QUIET=True)
    return parser.get_structure("protein", io.StringIO(pdb_text))


def _count_atoms(structure: Structure) -> int:
    """Count all atoms in the first model, including HETATM records."""
    return sum(1 for _ in structure.get_atoms())


def _get_chain_ids(structure: Structure) -> list[str]:
    """Return sorted list of chain identifiers from the first model only."""
    chains = []
    for model in structure:
        for chain in model:
            if chain.id.strip() and chain.id not in chains:
                chains.append(chain.id)
        break  # NMR structures have multiple models; model 0 is always representative
    return sorted(chains)


def _get_chain_details(structure: Structure) -> list[dict]:
    """
    Build per-chain summary: chain ID, standard residue count, atom count.

    I filter to residues where hetfield == ' ' (space) to exclude water
    molecules (HOH) and small molecule ligands from the residue count.
    The count I show the user should mean 'amino acid residues', not
    'everything in the chain', which would be misleading.
    """
    details = []
    for model in structure:
        for chain in model:
            std_residues = [r for r in chain if r.id[0] == " "]
            details.append({
                "id": chain.id,
                "residue_count": len(std_residues),
                "atom_count": sum(1 for _ in chain.get_atoms()),
            })
        break
    return sorted(details, key=lambda c: c["id"])


def _extract_resolution(pdb_text: str) -> Optional[float]:
    """
    Extract crystallographic resolution from REMARK 2 records.

    REMARK 2 is the standard location for this value in PDB format.
    NMR and predicted structures don't have resolution — I return None
    and handle it gracefully in the frontend with 'N/A'.
    """
    for line in pdb_text.splitlines():
        if line.startswith("REMARK   2 RESOLUTION."):
            tokens = line.split()
            for i, token in enumerate(tokens):
                if token == "ANGSTROMS." and i > 0:
                    try:
                        return float(tokens[i - 1])
                    except ValueError:
                        pass
    return None


def _extract_organism(pdb_text: str) -> Optional[str]:
    """
    Extract the scientific organism name from SOURCE records.

    SOURCE records use a key: value format with semicolons between fields.
    I look for ORGANISM_SCIENTIFIC because the common name field
    (ORGANISM_COMMON) isn't always present, but scientific name always is.
    SOURCE can span multiple continuation lines, so I concatenate them first.
    """
    source_parts = []
    for line in pdb_text.splitlines():
        if line.startswith("SOURCE"):
            source_parts.append(line[10:].strip())

    source_text = " ".join(source_parts)

    if "ORGANISM_SCIENTIFIC:" in source_text:
        start = source_text.index("ORGANISM_SCIENTIFIC:") + len("ORGANISM_SCIENTIFIC:")
        end = source_text.find(";", start)
        organism = source_text[start:end].strip() if end != -1 else source_text[start:].strip()
        # PDB sometimes uses title case within the field — normalise
        return organism.strip(" ;") or None

    return None


def _extract_authors(pdb_text: str) -> list[str]:
    """
    Extract author names from AUTHOR records.

    AUTHOR records are comma-separated in columns 11–79. Multi-line entries
    are standard for structures with many co-authors, so I concatenate
    continuation lines before splitting on commas.
    """
    author_lines = []
    for line in pdb_text.splitlines():
        if line.startswith("AUTHOR"):
            author_lines.append(line[10:].strip().rstrip(","))

    if not author_lines:
        return []

    combined = ",".join(author_lines)
    return [a.strip() for a in combined.split(",") if a.strip()]


def _extract_title(pdb_text: str) -> Optional[str]:
    """
    Extract and concatenate TITLE records.

    PDB TITLE lines wrap at column 79, so multi-word titles span several
    continuation lines. I join them into a single clean string.
    """
    title_parts = []
    for line in pdb_text.splitlines():
        if line.startswith("TITLE"):
            title_parts.append(line[10:].strip())
    return " ".join(title_parts).strip() or None


def _extract_method(pdb_text: str) -> Optional[str]:
    """
    Extract the experimental method from the EXPDTA record.

    Typical values: X-RAY DIFFRACTION, SOLUTION NMR, ELECTRON MICROSCOPY.
    This tells the user whether they're looking at an experimental structure
    or (in the AlphaFold case) a prediction — an important distinction for
    scientific literacy.
    """
    for line in pdb_text.splitlines():
        if line.startswith("EXPDTA"):
            return line[10:].strip()
    return None


def _parse_helix_sheet_records(pdb_text: str) -> dict[tuple, str]:
    """
    Parse HELIX and SHEET records and return a mapping of (chain_id, seq_num)
    to secondary structure type: 'H' for helix, 'E' for extended/sheet.

    I use HELIX/SHEET records from the PDB header rather than running a DSSP
    calculation because DSSP requires an external binary — adding a system
    dependency to install an executable is not reasonable for a browser-based
    tool aimed at novice users. The PDB author-assigned secondary structure is
    what ChimeraX and PyMOL also use for their ribbon representations by
    default, so my annotations will be consistent with what users see in
    professional tools.

    PDB HELIX column layout (1-indexed):
      col 20: initChainID, cols 22-25: initSeqNum
      col 32: endChainID,  cols 34-37: endSeqNum

    PDB SHEET column layout (1-indexed):
      col 22: initChainID, cols 23-26: initSeqNum
      col 33: endChainID,  cols 34-37: endSeqNum
    """
    ss_map: dict[tuple, str] = {}

    for line in pdb_text.splitlines():
        if line.startswith("HELIX ") and len(line) >= 37:
            try:
                chain = line[19]
                start = int(line[21:25].strip())
                end = int(line[33:37].strip())
                for seq_num in range(start, end + 1):
                    ss_map[(chain, seq_num)] = "H"
            except (ValueError, IndexError):
                continue

        elif line.startswith("SHEET ") and len(line) >= 37:
            try:
                chain = line[21]
                start = int(line[22:26].strip())
                end = int(line[33:37].strip())
                for seq_num in range(start, end + 1):
                    ss_map[(chain, seq_num)] = "E"
            except (ValueError, IndexError):
                continue

    return ss_map


def _build_sequences(structure: Structure, ss_map: dict[tuple, str]) -> dict[str, dict]:
    """
    Build per-chain sequence data from ATOM records, annotated with
    secondary structure assignments from the HELIX/SHEET map.

    I use Biopython's PPBuilder (polypeptide peptide builder) rather than
    SEQRES records because SEQRES lists all residues in the sequence
    regardless of whether they're structurally resolved, whereas PPBuilder
    only includes residues that are actually present in ATOM records. The
    sequence the user sees should match the residues visible in the 3D view,
    not residues that were disordered and missing from the electron density.

    Returns a dict keyed by chain ID, each containing:
      - 'residues': list of { one_letter, three_letter, seq_num, ss } dicts
      - 'sequence_string': concatenated one-letter codes for display
      - 'ss_string': matching SS characters (H/E/C) for colour coding
    """
    ppb = PPBuilder()
    sequences: dict[str, dict] = {}

    for model in structure:
        for chain in model:
            residues = []
            for pp in ppb.build_peptides(chain):
                for residue in pp:
                    res_name = residue.get_resname().strip()
                    seq_num = residue.get_id()[1]
                    one_letter = AA_THREE_TO_ONE.get(res_name, "X")
                    ss = ss_map.get((chain.id, seq_num), "C")
                    residues.append({
                        "one_letter": one_letter,
                        "three_letter": res_name,
                        "seq_num": seq_num,
                        "ss": ss,
                    })

            if residues:
                sequences[chain.id] = {
                    "residues": residues,
                    "sequence_string": "".join(r["one_letter"] for r in residues),
                    "ss_string": "".join(r["ss"] for r in residues),
                }
        break  # first model only

    return sequences


def _calculate_ss_breakdown(
    structure: Structure, ss_map: dict[tuple, str]
) -> dict:
    """
    Calculate percentage breakdown of residues in helix, sheet, and loop.

    I count standard amino acid residues only (hetfield == ' ') and
    cross-reference with the HELIX/SHEET map to assign each residue.
    Anything not explicitly assigned to helix or sheet is considered loop/coil.
    """
    total = 0
    helix_count = 0
    sheet_count = 0

    for model in structure:
        for chain in model:
            for residue in chain:
                if residue.id[0] != " ":
                    continue  # skip HETATM (water, ligands)
                total += 1
                ss = ss_map.get((chain.id, residue.id[1]), "C")
                if ss == "H":
                    helix_count += 1
                elif ss == "E":
                    sheet_count += 1
        break

    if total == 0:
        return {"helix": 0.0, "sheet": 0.0, "loop": 0.0, "total_residues": 0}

    loop_count = total - helix_count - sheet_count
    return {
        "helix": round(helix_count / total * 100, 1),
        "sheet": round(sheet_count / total * 100, 1),
        "loop": round(loop_count / total * 100, 1),
        "total_residues": total,
    }
