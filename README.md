# ProteinVis

**Interactive 3D Protein Structure Visualisation**
COMP1682 Final Year Project - University of Greenwich

---

## What is this?

ProteinVis is a browser-based tool for visualising and exploring protein structures
in 3D - without installing any desktop software. It fetches structure data from two
public databases (RCSB PDB and AlphaFold EBI), renders them using WebGL via the NGL
Viewer library, and provides interactive controls for representation, colour scheme,
chain visibility, sequence browsing, and distance measurement.

The tool is designed for students and novice researchers who need to explore protein
structures for coursework or research, but lack the technical background to use
professional tools like UCSF ChimeraX or PyMOL. It is a complement to those tools,
not a replacement.

---

## Running the application

**Requirements:** Python 3.8+, pip, a modern web browser (Chrome, Firefox, Edge).
Internet connection required (fetches structures from RCSB and AlphaFold).

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

The Flask server serves both the API (`/api/...`) and the frontend HTML/CSS/JS from
the same port. No separate frontend server is needed.

---

## Project structure

```
protein_visualisation_prototype/
├── backend/
│   ├── app.py                      Flask entry point, manual CORS, static serving
│   ├── requirements.txt
│   ├── routes/
│   │   └── protein_routes.py       HTTP interface only - validation, JSON formatting
│   ├── services/
│   │   └── protein_service.py      Business logic, orchestration, no Flask
│   ├── parsers/
│   │   └── structure_parser.py     PDB text parsing only, no network
│   └── utils/
│       └── pdb_fetcher.py          All HTTP calls, in-memory cache, retries
├── frontend/
│   ├── index.html                  Three-panel layout, ARIA labels
│   ├── styles.css                  Dark scientific theme
│   └── main.js                     ProteinAPI / ViewerManager / UIController
├── TEST_PLAN.md
└── README.md
```

---

## Architecture decisions

**Four-layer backend:** Each layer has exactly one responsibility. `routes/` knows about
HTTP. `services/` knows about business logic. `parsers/` knows about PDB format.
`utils/` knows about network I/O. No layer reaches into another's domain. This
separation means each component can be tested in isolation and swapped independently -
if RCSB changed their API, only `pdb_fetcher.py` would need updating.

**Three-object frontend:** `ProteinAPI`, `ViewerManager`, and `UIController` match the
same separation-of-concerns principle. `UIController` never calls NGL directly;
`ProteinAPI` never touches the DOM. Communication between objects uses the DOM's
`CustomEvent` system as a lightweight event bus.

**Manual CORS:** Implemented via Flask's `after_request` hook rather than `flask-cors`
so the headers being set are visible and explainable, not hidden behind a decorator.

**In-memory cache with 1-hour TTL:** Chosen over Redis or a file cache because this
is a local prototype - the overhead of an external cache service isn't justified.
The TTL of one hour covers any realistic user session without risk of stale data
(PDB entries are updated weekly at most).

**Vanilla JS, no build step:** No React, Vue, or bundler. The frontend can be read
and understood in full by opening three files. Adding a build system would introduce
toolchain complexity that obscures the actual logic.

---

## Features

| Feature | Details |
|---|---|
| Load PDB structure | 4-character identifier, fetched from RCSB |
| Load AlphaFold structure | UniProt accession, fetched from AlphaFold EBI |
| Full-text search | RCSB PDB Search API v2 |
| 6 representations | Cartoon, surface, ball+stick, licorice, backbone, spacefill |
| 5 colour schemes | By chain, secondary structure, B-factor, hydrophobicity, element |
| Chain visibility | Per-chain toggle wired to NGL selection strings |
| Secondary structure | % helix / sheet / loop calculated from HELIX/SHEET PDB records |
| Sequence viewer | Per-residue one-letter codes, coloured by SS type, clickable |
| Atom pick tooltip | Hover shows residue name, chain, atom name |
| Distance measurement | Two-click measurement in Å, line drawn in 3D viewport |
| Screenshot export | 2× resolution PNG download |
| Metadata export | JSON download with full structural metadata |
| AlphaFold disclaimer | Shown in viewport banner and metadata panel for predicted structures |
| In-memory cache | 1-hour TTL; repeated loads never hit the remote API twice |
| ARIA accessibility | Labels on all interactive elements; full keyboard navigation |
| Quick-load examples | 1CRN (Crambin), 4HHB (Oxyhaemoglobin), 1TIM (TIM barrel), 2HHB (Deoxyhaemoglobin) |

---

## Data sources and licensing

**RCSB Protein Data Bank**
Structure files and metadata are retrieved from `files.rcsb.org` and
`data.rcsb.org`. The RCSB PDB is an open-access resource. All data retrieved
through this application is subject to the wwPDB terms of use:
https://www.wwpdb.org/about/privacy

Berman, H.M., Westbrook, J., Feng, Z., Gilliland, G., Bhat, T.N., Weissig, H.,
Shindyalov, I.N., Bourne, P.E. (2000). The Protein Data Bank.
*Nucleic Acids Research*, 28(1), 235–242. https://doi.org/10.1093/nar/28.1.235

**AlphaFold Database (EMBL-EBI)**
Predicted structures are retrieved from `alphafold.ebi.ac.uk`. The AlphaFold
Database is freely available under a Creative Commons Attribution 4.0
(CC BY 4.0) licence.

Jumper, J., Evans, R., Pritzel, A., et al. (2021). Highly accurate protein
structure prediction with AlphaFold. *Nature*, 596, 583–589.
https://doi.org/10.1038/s41586-021-03819-2

---

## Third-party software attribution

**NGL Viewer**
NGL Viewer is used under the MIT Licence.
Rose, A.S., Bradley, A.R., Valasatava, Y., Duarte, J.M., Prlić, A., Rose, P.W.
(2018). NGL viewer: web-based molecular graphics for large complexes.
*Bioinformatics*, 34(21), 3755–3758. https://doi.org/10.1093/bioinformatics/bty419
Repository: https://github.com/nglviewer/ngl

**Flask**
Flask is used under the BSD 3-Clause Licence.
Ronacher, A. et al. Flask. https://flask.palletsprojects.com/
Repository: https://github.com/pallets/flask

**Biopython**
Biopython is used under the Biopython Licence Agreement (permissive open source).
Cock, P.J.A., et al. (2009). Biopython: freely available Python tools for
computational molecular biology and bioinformatics.
*Bioinformatics*, 25(11), 1422–1423. https://doi.org/10.1093/bioinformatics/btp163
Repository: https://github.com/biopython/biopython

**Requests**
The Requests library is used under the Apache 2.0 Licence.
Reitz, K. et al. Requests: HTTP for Humans. https://requests.readthedocs.io/
Repository: https://github.com/psf/requests

**Google Fonts**
Syne (Bonjour Monde), Inter (Rasmus Andersson), DM Mono (Colophon Foundry)
are served via Google Fonts and used under the SIL Open Font Licence 1.1.
https://fonts.google.com/

---

## Academic references

Berman, H.M. et al. (2000). The Protein Data Bank. *Nucleic Acids Research*, 28(1), 235–242.

Goddard, T.D. et al. (2018). UCSF ChimeraX: Meeting modern challenges in
visualization and analysis. *Protein Science*, 27, 14–25.

Jumper, J. et al. (2021). Highly accurate protein structure prediction with AlphaFold.
*Nature*, 596, 583–589.

Meyer, M., Dykes, J. (2020). Criteria for Rigor in Visualization Design Study.
*IEEE Transactions on Visualization and Computer Graphics*, 26(1), 87–97.

Rose, A.S. et al. (2018). NGL viewer: web-based molecular graphics for large complexes.
*Bioinformatics*, 34(21), 3755–3758.

Schrödinger, LLC (2023). The PyMOL Molecular Graphics System, Version 3.0.
https://www.pymol.org/

---

## Ethical considerations

**No personal data is collected or stored.** Users enter only public PDB identifiers
and UniProt accessions. No user accounts, no logging of queries beyond the local
Flask process, no cookies.

**Open data.** All structure data is publicly available under open licences. The
application does not redistribute data - it fetches it on demand and holds it in
a short-lived local cache.

**Responsible API use.** A descriptive `User-Agent` header is sent with all requests
to RCSB and AlphaFold so they can identify the client. The in-memory cache ensures
the same structure is never fetched more than once per server session, minimising
load on the remote APIs. Rate limiting is documented in `pdb_fetcher.py`.

**Accessibility.** ARIA labels are present on all interactive elements. All controls
are keyboard-navigable. Colour is never used as the only means of conveying
information (e.g. the sequence viewer uses both colour and letter codes).

---

## Limitations

See `TEST_PLAN.md` (Known Limitations section) for a full list of current limitations
and areas identified for future improvement.
