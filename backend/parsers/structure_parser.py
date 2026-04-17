from __future__ import annotations

"""
structure_parser.py: parses raw PDB text into structured data. I use Biopython for atoms and chains, and manual line parsing for HELIX/SHEET/SOURCE records that Biopython doesn't expose.
"""

import io
import logging
from typing import Optional

from Bio.PDB import PDBParser, PPBuilder
from Bio.PDB.Structure import Structure

logger = logging.getLogger(__name__)

# Standard 3-to-1 amino acid code map. I define it here rather than importing from Biopython to keep the dependency small.
AA_THREE_TO_ONE: dict[str, str] = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "SEC": "U", "PYL": "O",  # selenocysteine and pyrrolysine (uncommon but valid)
    "MSE": "M",              # selenomethionine (common in X-ray structures)
}


def parse_pdb_text(pdb_text: str) -> dict:
    """Parse a PDB file string and return all extracted data in a single dict for the service layer."""
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
        "ligands": _extract_ligands(structure),
    }


def _load_biopython_structure(pdb_text: str) -> Structure:
    """Parse the PDB text into a Biopython Structure object - I use QUIET=True because real PDB files produce a lot of harmless warnings."""
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
    """Build a per-chain summary of residue and atom counts, excluding water and ligands so the count reflects amino acids only."""
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
    """Extract crystallographic resolution from REMARK 2. Returns None for NMR/predicted."""
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
    """Extract the scientific name from SOURCE records by joining the multi-line field and pulling out ORGANISM_SCIENTIFIC."""
    source_parts = []
    for line in pdb_text.splitlines():
        if line.startswith("SOURCE"):
            source_parts.append(line[10:].strip())

    source_text = " ".join(source_parts)

    if "ORGANISM_SCIENTIFIC:" in source_text:
        start = source_text.index("ORGANISM_SCIENTIFIC:") + len("ORGANISM_SCIENTIFIC:")
        end = source_text.find(";", start)
        organism = source_text[start:end].strip() if end != -1 else source_text[start:].strip()
        # PDB sometimes uses title case within this field, strip it
        return organism.strip(" ;") or None

    return None


def _extract_authors(pdb_text: str) -> list[str]:
    """Extract author names from AUTHOR records (comma-separated, may span multiple lines)."""
    author_lines = []
    for line in pdb_text.splitlines():
        if line.startswith("AUTHOR"):
            author_lines.append(line[10:].strip().rstrip(","))

    if not author_lines:
        return []

    combined = ",".join(author_lines)
    return [a.strip() for a in combined.split(",") if a.strip()]


def _extract_title(pdb_text: str) -> Optional[str]:
    """Extract and join TITLE records (they wrap at column 79)."""
    title_parts = []
    for line in pdb_text.splitlines():
        if line.startswith("TITLE"):
            title_parts.append(line[10:].strip())
    return " ".join(title_parts).strip() or None


def _extract_method(pdb_text: str) -> Optional[str]:
    """Extract the experimental method from EXPDTA (e.g. X-RAY DIFFRACTION, NMR)."""
    for line in pdb_text.splitlines():
        if line.startswith("EXPDTA"):
            return line[10:].strip()
    return None


def _parse_helix_sheet_records(pdb_text: str) -> dict[tuple, str]:
    """Parse HELIX and SHEET records into a (chain_id, seq_num) → 'H'/'E' map - I read the fixed-column PDB format directly rather than using DSSP which needs an external binary."""
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
    """Build per-chain sequence data from ATOM records, annotated with secondary structure. I use PPBuilder (not SEQRES) so the sequence matches only what's visible in the 3D view."""
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

                    # I read the Cα B-factor per residue - AlphaFold stores pLDDT here, experimental structures store crystallographic B-factor.
                    try:
                        bfactor = round(residue["CA"].get_bfactor(), 1)
                    except KeyError:
                        atoms_list = list(residue.get_atoms())
                        bfactor = round(atoms_list[0].get_bfactor(), 1) if atoms_list else None

                    residues.append({
                        "one_letter": one_letter,
                        "three_letter": res_name,
                        "seq_num": seq_num,
                        "ss": ss,
                        "bfactor": bfactor,
                    })

            if residues:
                sequences[chain.id] = {
                    "residues": residues,
                    "sequence_string": "".join(r["one_letter"] for r in residues),
                    "ss_string": "".join(r["ss"] for r in residues),
                }
        break  # first model only

    return sequences


def _extract_ligands(structure: Structure) -> dict:
    """Identify non-water ligands (cofactors, ions, small molecules) and return the total count and up to 12 unique names."""
    _WATER_NAMES: frozenset = frozenset({"HOH", "DOD", "WAT", "H2O", "OH2"})
    seen: list[str] = []
    seen_names: list[str] = []

    for model in structure:
        for chain in model:
            for residue in chain:
                hetfield = residue.id[0]
                if hetfield in (" ", "W"):
                    continue
                res_name = residue.get_resname().strip()
                if res_name in _WATER_NAMES:
                    continue
                seen.append(res_name)
                if res_name not in seen_names:
                    seen_names.append(res_name)
        break  # first model only

    return {
        "count": len(seen),
        "unique_names": seen_names[:12],  # cap display at 12 names
    }


def _calculate_ss_breakdown(
    structure: Structure, ss_map: dict[tuple, str]
) -> dict:
    """Calculate the helix/sheet/loop percentage breakdown by cross-referencing each standard residue against the HELIX and SHEET records."""
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
        return {
            "helix": 0.0, "sheet": 0.0, "loop": 0.0,
            "total_residues": 0,
            "helix_count": 0, "sheet_count": 0, "loop_count": 0,
        }

    loop_count = total - helix_count - sheet_count
    return {
        "helix": round(helix_count / total * 100, 1),
        "sheet": round(sheet_count / total * 100, 1),
        "loop": round(loop_count / total * 100, 1),
        "total_residues": total,
        "helix_count": helix_count,
        "sheet_count": sheet_count,
        "loop_count": loop_count,
    }
