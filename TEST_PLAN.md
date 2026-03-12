# ProteinVis — Test Plan
**Module:** COMP1682 Final Year Project
**University of Greenwich**
**Tester:** Yasmin Yahye

---

## Testing Approach

I used manual functional testing against each stated requirement because the
application is a visualisation tool — the correctness of a rendered 3D molecule
cannot be verified by a unit test; it requires a human to confirm that the
representation looks right, that tooltips appear at the correct positions, and
that interactive controls respond as expected.

Where backend logic is deterministic (parsing, caching, search), I also include
API-level tests using the `curl` commands shown, so a marker can reproduce the
exact results without running a browser.

---

## Test Environment

- **OS:** Windows 11
- **Browser:** Google Chrome (latest stable)
- **Python:** 3.8
- **Backend:** `cd backend && python app.py` (server at `http://127.0.0.1:5000`)
- **Frontend:** Served by Flask at `http://127.0.0.1:5000`

---

## Test Scenarios

### TC-01 — Application loads to empty state

**Requirement:** Three-panel layout with empty state animation in the viewport.
**Steps:**
1. Start Flask server (`python app.py`)
2. Open `http://127.0.0.1:5000` in Chrome

**Expected:** Header "ProteinVis · COMP1682" visible. Left controls panel, empty viewport with floating DNA animation, right metadata panel showing "Load a structure to view metadata". No console errors.
**Pass/Fail:** PASS
**Notes:** DNA float animation loads correctly. Sequence viewer and metadata content are hidden as expected.

---

### TC-02 — Load a PDB structure by identifier (1CRN)

**Requirement:** Fetch PDB structure by 4-char identifier; NGL rendering; metadata sidebar populated.
**Steps:**
1. Type `1CRN` into the "PDB Identifier" field
2. Click "Load"

**Expected:** Loading animation appears; 3D cartoon ribbon of crambin renders in the viewport; metadata panel shows title ("CRAMBIN"), organism, method (X-RAY DIFFRACTION), resolution (~1.5 Å), atom count, chain details, and authors. Source badge reads "RCSB Protein Data Bank".
**Pass/Fail:** PASS
**API check:** `curl http://127.0.0.1:5000/api/protein/1CRN` → returns `data.title`, `data.atom_count`, `data.chain_ids`

---

### TC-03 — Quick-load buttons

**Requirement:** Quick-load buttons for 1CRN, 4HHB, 1TIM, 2HHB.
**Steps:**
1. Click each of the four quick-load buttons in turn
2. Observe viewport and metadata for each

**Expected:** Each click triggers a load cycle (loading overlay → structure renders → metadata updates). 4HHB shows four chains (A, B, C, D). 1TIM shows the characteristic (β/α)₈ TIM barrel fold.
**Pass/Fail:** PASS
**Notes:** Subsequent loads correctly replace the previous structure — no component accumulation in WebGL memory.

---

### TC-04 — Load an AlphaFold predicted structure (P68871)

**Requirement:** Fetch AlphaFold prediction by UniProt accession; AlphaFold disclaimer shown; is_predicted flag set.
**Steps:**
1. Enter `P68871` in the "AlphaFold (UniProt)" field
2. Click "Load"

**Expected:** Structure loads. AlphaFold banner appears over viewport ("Predicted structure — not experimentally determined..."). Metadata panel source badge reads "AlphaFold Database (EBI)". Yellow disclaimer block appears in metadata panel with pLDDT explanation and Jumper et al. citation. Resolution shows "N/A". Authors show "Jumper et al. (2021), DeepMind / Google".
**Pass/Fail:** PASS
**API check:** `curl http://127.0.0.1:5000/api/alphafold/P68871` → `data.is_predicted = true`, `data.disclaimer` non-empty

---

### TC-05 — Representation switching

**Requirement:** Six representations: cartoon, surface, ball+stick, licorice, backbone, spacefill.
**Steps:**
1. Load 1CRN
2. Change "Representation" dropdown to each option in turn

**Expected:** Viewport updates after each selection. Cartoon shows ribbon. Surface shows molecular envelope. Ball+stick shows atoms and bonds. Licorice shows bonds only. Backbone shows Cα trace. Spacefill shows van der Waals spheres.
**Pass/Fail:** PASS

---

### TC-06 — Colour scheme switching

**Requirement:** Five colour schemes: by chain, secondary structure, B-factor, hydrophobicity, element.
**Steps:**
1. Load 4HHB (four chains — good for testing chain colouring)
2. Switch through each colour scheme

**Expected:** "By chain" colours each chain distinctly. "Secondary structure" uses standard colouring (helix = orange, sheet = yellow as per sequence viewer legend). "B-factor" shows a heat map. "Hydrophobicity" highlights hydrophobic regions. "By element" uses CPK standard colouring (carbon grey, nitrogen blue, oxygen red).
**Pass/Fail:** PASS

---

### TC-07 — Chain visibility toggling

**Requirement:** Per-chain visibility toggling wired to NGL selection strings.
**Steps:**
1. Load 4HHB (chains A, B, C, D)
2. Uncheck chain A in the "Chain Visibility" section

**Expected:** Chain A disappears from the 3D viewport immediately. The remaining chains (B, C, D) remain visible and unaffected. Re-checking chain A restores it.
**Pass/Fail:** PASS

---

### TC-08 — Secondary structure breakdown

**Requirement:** % helix, sheet, loop calculated from parser and displayed as a bar.
**Steps:**
1. Load 1CRN
2. Observe the "Secondary Structure" section in the metadata panel

**Expected:** Three-segment coloured bar with labelled percentages. For 1CRN (predominantly helical), helix % should be highest. Numbers should sum to approximately 100%.
**Pass/Fail:** PASS
**API check:** `curl http://127.0.0.1:5000/api/protein/1CRN` → `data.secondary_structure.helix`, `.sheet`, `.loop`

---

### TC-09 — Amino acid sequence viewer

**Requirement:** Sequence viewer populated from parsed ATOM records; residues coloured by secondary structure; clickable to highlight in 3D.
**Steps:**
1. Load 1CRN
2. Observe the sequence viewer strip at the bottom of the viewport
3. Click any residue span

**Expected:** Sequence viewer shows one-letter codes in orange (helix), yellow (sheet), or grey (loop). Chain selector is populated. Clicking a residue adds a gold ball-and-stick overlay on that residue in the 3D viewport.
**Pass/Fail:** PASS

---

### TC-10 — Distance measurement

**Requirement:** Distance measurement between two clicked atoms, shown in Ångströms with a line drawn in the viewport.
**Steps:**
1. Load 1CRN
2. Click "Measure" button
3. Click one atom in the viewport (e.g. in the helix)
4. Click a second atom

**Expected:** After first click, status reads "Atom 1: [residue] — now click second atom…". After second click, distance result appears (e.g. "6.23 Å") with residue labels. A yellow-orange cylinder is drawn in the viewport connecting the two atoms. "Clear" button appears.
**Pass/Fail:** PASS

---

### TC-11 — In-memory cache (1-hour TTL)

**Requirement:** Structures cached for 1 hour; repeated loads don't hit RCSB again.
**Steps:**
1. Load 1CRN and observe Flask server log (timestamp of fetch)
2. Click 1CRN quick-load button a second time

**Expected:** On second load, no new HTTP request to `files.rcsb.org` appears in the Flask log — the line "Cache hit for key: pdb_structure_1CRN" is logged instead.
**Pass/Fail:** PASS
**Notes:** Cache is in-memory so it resets on server restart, as expected.

---

### TC-12 — Free-text search

**Requirement:** Search endpoint returns results from RCSB; clicking a result loads the structure.
**Steps:**
1. Type "insulin" in the "Search PDB" field
2. Click "Go"
3. Click the first result

**Expected:** A results list appears showing PDB IDs (e.g. 1MSO, 4INS). Clicking a result populates the PDB ID field, closes the results list, and loads the structure.
**Pass/Fail:** PASS
**API check:** `curl "http://127.0.0.1:5000/api/search?q=insulin"` → `data.results` array non-empty

---

### TC-13 — Export metadata as JSON

**Requirement:** "Export Metadata (JSON)" downloads a structured JSON file.
**Steps:**
1. Load 4HHB
2. Click "Export Metadata (JSON)" in the metadata panel

**Expected:** Browser downloads `4HHB_metadata.json`. File contains: `identifier`, `title`, `organism`, `method`, `resolution_angstroms`, `atom_count`, `chains`, `authors`, `secondary_structure`, `is_predicted`, `exported_at` fields. File is valid JSON.
**Pass/Fail:** PASS

---

### TC-14 — Input validation — invalid PDB ID

**Requirement:** Clear error messages for invalid input; never exposes raw exception text.
**Steps:**
1. Enter `XXXX` in the PDB ID field and click Load
2. Enter `ABC` (too short) and click Load

**Expected:** `XXXX` shows a user-facing error overlay: "PDB entry 'XXXX' was not found. Please check the identifier…". `ABC` shows: "'ABC' is not a valid PDB identifier. PDB IDs are 4 characters…". Neither shows a Python traceback.
**Pass/Fail:** PASS

---

### TC-15 — Screenshot export

**Requirement:** Screenshot saved as PNG from current viewport view.
**Steps:**
1. Load 4HHB, switch to Surface representation
2. Click the Screenshot button

**Expected:** Browser downloads `4HHB_screenshot.png`. File is a valid 2× resolution PNG of the current viewport state.
**Pass/Fail:** PASS

---

### TC-16 — Keyboard navigation and ARIA

**Requirement:** All controls keyboard-accessible; ARIA labels on all interactive elements.
**Steps:**
1. Tab through all interactive elements in the controls panel
2. Activate a quick-load button using Enter key
3. Inspect key elements with browser DevTools accessibility panel

**Expected:** All buttons, inputs, selects, and checkboxes are reachable via Tab. Enter key activates buttons. Focus outline is visible on all focused elements. DevTools accessibility tree shows descriptive ARIA labels (e.g. "Enter 4-character PDB identifier", "Toggle visibility of chain A").
**Pass/Fail:** PASS

---

## Known Limitations

1. **Large cryo-EM structures** (e.g. ribosome, >500,000 atoms) may cause slow load times and reduce rendering performance. The prototype targets typical PDB sizes (< 50,000 atoms).
2. **NMR structures** (e.g. 1D3Z) have multiple models; only model 0 is rendered. A future version could add a model selector.
3. **Resolution field** is absent for NMR and predicted structures — displayed as "N/A". This is correct behaviour, not a bug.
4. **Cache is in-memory per server process.** Restarting Flask clears the cache. A production deployment would use Redis or a persistent cache.
5. **Search results show PDB ID and score only.** A future improvement would fetch titles for all results to give more context before clicking.
6. **AlphaFold structures longer than 2700 residues** are truncated by the AlphaFold API. This is an upstream limitation.
