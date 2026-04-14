# ProteinVis — Manual Acceptance Test Table
**Module:** COMP1682 Final Year Project
**Tester:** [Your name]
**Environment:** Windows 11, Chrome 124+, Python 3.8, Flask backend at http://127.0.0.1:5000
**Date of test:** _______________

> **How to use this table:** Complete each test in order. Record the actual output observed and mark Pass/Fail. Any Fail should be investigated and resolved before submission. For network-dependent tests, ensure the backend is running (`cd backend && python app.py`) and you have an active internet connection.

---

## Section 1 — Loading Valid and Invalid Structures

| Test ID | Feature Tested | Input | Steps | Expected Output | Actual Output | Pass/Fail |
|---------|---------------|-------|-------|-----------------|---------------|-----------|
| TC-01 | Empty state on first load | (none — fresh page load) | Open index.html in browser | Empty state panel visible, DNA animation playing, no error overlay | | |
| TC-02 | Load valid PDB — 1CRN (Crambin) | PDB ID: `1CRN` | Enter `1CRN` in PDB input, click Load | DNA loading animation shown, then 3D structure appears; metadata panel shows "CRAMBIN"; 46 residues, 1 chain (A), X-ray method | | |
| TC-03 | Load valid PDB — 4HHB (Haemoglobin) | PDB ID: `4HHB` | Enter `4HHB`, click Load | Structure loads with 4 chains (A, B, C, D); metadata shows organism *Homo sapiens*; chain toggles appear for all 4 chains | | |
| TC-04 | Invalid PDB ID — too short | PDB ID: `1C` | Enter `1C`, click Load | Error overlay appears: "Please enter a 4-character PDB identifier (e.g. 1CRN)" | | |
| TC-05 | Invalid PDB ID — starts with letter | PDB ID: `ABCD` | Enter `ABCD`, click Load | Error message explains format: PDB IDs start with a digit (route returns 400) | | |
| TC-06 | Non-existent PDB ID | PDB ID: `1ZZZ` | Enter `1ZZZ`, click Load | Error overlay: "PDB entry '1ZZZ' was not found. Please check the identifier" | | |
| TC-07 | Load valid AlphaFold — P68871 | UniProt: `P68871` | Enter `P68871` in AlphaFold input, click Load | Structure loads; AlphaFold disclaimer banner visible in viewport; metadata shows "Predicted structure"; pLDDT-related text in disclaimer section | | |
| TC-08 | Invalid UniProt accession | UniProt: `XY` | Enter `XY`, click Load | Error overlay with message explaining UniProt format (6 or 10 characters) | | |
| TC-09 | Non-existent UniProt ID | UniProt: `A99999` | Enter `A99999`, click Load | Error: "No AlphaFold prediction found" | | |

---

## Section 2 — Metadata Accuracy (supervisor's key requirement)

| Test ID | Feature Tested | Input | Steps | Expected Output | Actual Output | Pass/Fail |
|---------|---------------|-------|-------|-----------------|---------------|-----------|
| TC-10 | Metadata fields for 1CRN | PDB: `1CRN` | Load 1CRN; examine metadata panel | Title visible; Organism: *Crambe hispanica*; Method: X-RAY DIFFRACTION; Resolution: 0.54 Å; Residues: 46; Chains: A | | |
| TC-11 | Metadata fields for 4HHB | PDB: `4HHB` | Load 4HHB; examine metadata panel | Organism: *Homo sapiens*; 4 chains shown; Method: X-RAY DIFFRACTION; Resolution shown | | |
| TC-12 | SS breakdown counts — 1CRN | PDB: `1CRN` | Load 1CRN; inspect Secondary Structure section | Helix %, Sheet %, Loop % sum to 100%; residue counts shown (e.g. "14 res" helix); total matches Residues field | | |
| TC-13 | Data verified indicator | PDB: `1CRN` | Load 1CRN; scroll to bottom of metadata panel | Green "Data verified — residue count and chain count match parsed structure" badge visible | | |
| TC-14 | pLDDT scores visible on AlphaFold click | UniProt: `P68871` | Load P68871; click any atom in the 3D viewer | Residue info panel appears; pLDDT score shown with confidence label (Very High / Confident / Low / Very Low) | | |

---

## Section 3 — 3D Viewer Interactions

| Test ID | Feature Tested | Input | Steps | Expected Output | Actual Output | Pass/Fail |
|---------|---------------|-------|-------|-----------------|---------------|-----------|
| TC-15 | Residue click → info panel | PDB: `1CRN` (load first) | Click any atom in the viewport | Residue info panel appears in metadata column showing residue name (3-letter), position number, chain ID, and secondary structure type | | |
| TC-16 | Residue info matches sequence data | PDB: `1CRN` | Click a helix residue (orange in sequence strip) | Info panel shows "α-Helix" for SS type; one-letter + three-letter codes correct | | |
| TC-17 | Atom hover tooltip | PDB: `1CRN` | Hover mouse over atoms in viewport | Small tooltip appears near cursor showing residue name, number, chain, atom name | | |
| TC-18 | Distance measurement — two click | PDB: `1CRN` | Click "Measure", click atom 1, click atom 2 | Orange cylinder drawn between atoms; distance in Ångströms shown below Measure button | | |
| TC-19 | Zoom to residue — from sequence strip | PDB: `4HHB` | Load 4HHB; click a residue in the sequence strip | Camera animates to centre on clicked residue; gold ball+stick highlight appears; sequence strip span highlighted | | |
| TC-20 | 3D click syncs sequence strip | PDB: `1CRN` | Click an atom in the 3D viewer | Corresponding residue in sequence strip scrolls into view and gets white outline highlight | | |

---

## Section 4 — Representation and Colour Controls

| Test ID | Feature Tested | Input | Steps | Expected Output | Actual Output | Pass/Fail |
|---------|---------------|-------|-------|-----------------|---------------|-----------|
| TC-21 | Representation — Cartoon | PDB: `4HHB` | Load 4HHB; select "Cartoon (ribbon)" | Ribbon representation shown; secondary structure visible as ribbons and tubes | | |
| TC-22 | Representation — Surface | PDB: `1CRN` | Select "Molecular surface" | Smooth molecular surface rendered; structure looks like a solid shape | | |
| TC-23 | Representation — Ball+Stick | PDB: `1CRN` | Select "Ball and stick" | Every atom shown as sphere, bonds as sticks | | |
| TC-24 | Representation — Spacefill | PDB: `1CRN` | Select "Spacefill (CPK)" | Atoms shown at van der Waals radii; no visible gaps | | |
| TC-25 | Representation tooltip description updates | PDB: `1CRN` | Change representation select | Small description text below select updates to explain what the selected view reveals | | |
| TC-26 | Colour scheme — by secondary structure | PDB: `4HHB` | Select "Secondary structure" colour | Helices in one colour, sheets in another, loops distinct; matches sequence strip colours | | |
| TC-27 | Colour scheme — by B-factor/pLDDT | UniProt: `P68871` | Load P68871; select "B-factor / confidence" | High-confidence regions (blue/green) and low-confidence regions (red/yellow) clearly visible | | |

---

## Section 5 — Chain Visibility and Isolation

| Test ID | Feature Tested | Input | Steps | Expected Output | Actual Output | Pass/Fail |
|---------|---------------|-------|-------|-----------------|---------------|-----------|
| TC-28 | Chain visibility toggle — hide | PDB: `4HHB` | Load 4HHB; uncheck Chain A checkbox | Chain A disappears from the 3D view; chains B, C, D remain | | |
| TC-29 | Chain visibility toggle — restore | PDB: `4HHB` | After TC-28, re-check Chain A | Chain A reappears | | |
| TC-30 | Chain isolate button | PDB: `4HHB` | Click "Isolate" next to Chain B | Only Chain B visible; other chain checkboxes uncheck automatically | | |
| TC-31 | Show all chains button | PDB: `4HHB` | After TC-30, click "Show all chains" | All four chains reappear; all checkboxes checked | | |

---

## Section 6 — Search and Search History

| Test ID | Feature Tested | Input | Steps | Expected Output | Actual Output | Pass/Fail |
|---------|---------------|-------|-------|-----------------|---------------|-----------|
| TC-32 | Free-text search | Query: `insulin` | Type "insulin" in Search input, click Go | List of matching PDB IDs appears below search box with relevance scores | | |
| TC-33 | Search result loads structure | Query: `crambin` | Search for "crambin"; click first result | PDB input populated with result ID; structure loads automatically | | |
| TC-34 | Search history — chips appear | PDB: `1CRN`, then `4HHB` | Load 1CRN then 4HHB | "Recent" row with clickable chips `1CRN` and `4HHB` appears in the Load section | | |
| TC-35 | Search history — chip reloads | After TC-34 | Click the `1CRN` history chip | 1CRN structure reloads without re-typing | | |
| TC-36 | Search history — persists across reload | After TC-34 | Refresh the browser page | History chips still show `1CRN` and `4HHB` (persisted in localStorage) | | |

---

## Section 7 — Comparison Mode

| Test ID | Feature Tested | Input | Steps | Expected Output | Actual Output | Pass/Fail |
|---------|---------------|-------|-------|-----------------|---------------|-----------|
| TC-37 | Enter comparison mode | PDB: `4HHB` loaded | Click "Split-screen Compare" button | Viewport splits into two panes side by side; second pane empty; controls for "Second PDB ID" appear | | |
| TC-38 | Load second structure | PDB A: `4HHB`, PDB B: `2HHB` | After TC-37, enter `2HHB` in second PDB input, click "Load B" | Deoxy haemoglobin (2HHB) loads in right pane; both structures independently rotatable | | |
| TC-39 | Exit comparison mode | (after TC-38) | Click "Exit Comparison" button | Second pane hides; primary viewport returns to full width; primary structure still visible | | |

---

## Section 8 — Additional Usability and Accessibility

| Test ID | Feature Tested | Input | Steps | Expected Output | Actual Output | Pass/Fail |
|---------|---------------|-------|-------|-----------------|---------------|-----------|
| TC-40 | Screenshot export | PDB: `1CRN` | Load 1CRN; click Screenshot button | PNG file downloaded (≥2× viewport resolution) | | |
| TC-41 | Metadata JSON export | PDB: `4HHB` | Load 4HHB; click "Export Metadata (JSON)" | JSON file downloads containing pdb_id, title, organism, chains, secondary_structure | | |
| TC-42 | Quick-load buttons work | (quick-load section) | Click "1TIM" quick-load button | TIM barrel structure loads directly | | |
| TC-43 | Auto-spin toggle | PDB: any loaded | Click "Spin" button | Structure rotates continuously; clicking again stops rotation | | |
| TC-44 | Background colour change | PDB: any loaded | Change Background to "White" | Viewport background turns white; structure visible | | |
| TC-45 | Centre button resets view | PDB: any loaded, rotated manually | Click "Centre" | Camera animates back to default centred position | | |
| TC-46 | Keyboard navigation — sequence strip | PDB: `1CRN` | Focus sequence strip, use arrow keys / Tab | Residue spans are Tab-focusable; Enter activates highlight + zoom | | |
| TC-47 | Error dismiss button | Any error state | Trigger an error; click "Dismiss" | Error overlay hides; page returns to previous state | | |

---

## Test Summary

| Section | Total Tests | Passed | Failed | Notes |
|---------|------------|--------|--------|-------|
| 1 — Loading | 9 | | | |
| 2 — Metadata Accuracy | 5 | | | |
| 3 — 3D Interactions | 6 | | | |
| 4 — Representation | 7 | | | |
| 5 — Chain Controls | 4 | | | |
| 6 — Search & History | 5 | | | |
| 7 — Comparison Mode | 3 | | | |
| 8 — Usability/A11y | 8 | | | |
| **Total** | **47** | | | |

---

## Known Limitations (pre-filled)

- TC-38: Independent rotation of pane B works by creating a separate NGL Stage; performance may degrade on older GPUs with two stages active simultaneously.
- TC-27: B-factor colour scheme shows B-factor for experimental structures, not pLDDT — meaningful colouring only for AlphaFold structures. A warning note is shown in the metadata panel.
- TC-46: Keyboard navigation in the sequence strip requires the display div to have focus first (click once, then use keyboard).
- Structures with >500,000 atoms (large cryo-EM assemblies) will be slow; ProteinVis is designed for typical research-scale structures (<50,000 atoms).
