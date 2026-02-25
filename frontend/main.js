/**
 * main.js — ProteinVis frontend
 *
 * Three-object architecture matching the four-layer backend:
 *
 *   ProteinAPI      — all fetch calls to the Flask backend
 *   ViewerManager   — all NGL Viewer interactions (WebGL, representations,
 *                     picking, measurement, screenshot)
 *   UIController    — all DOM manipulation and event handling; owns the
 *                     other two objects and orchestrates them
 *
 * No layer does another's job. UIController never touches NGL directly.
 * ProteinAPI never touches the DOM. ViewerManager never fetches anything.
 *
 * I chose vanilla JS over React/Vue because the project doesn't have a build
 * step and adding a framework would require bundling infrastructure that would
 * obscure the actual logic. The three-object split gives me the same separation
 * of concerns as a component framework without the toolchain dependency.
 */

'use strict';

/* ============================================================
   ProteinAPI — all network calls to the Flask backend
   ============================================================ */

class ProteinAPI {
  /**
   * @param {string} baseUrl - Flask backend URL, e.g. 'http://127.0.0.1:5000'
   *
   * I keep the base URL as a constructor parameter so switching between
   * development and a hypothetical deployed backend only requires changing
   * one string at the instantiation site, not hunting through fetch() calls.
   */
  constructor(baseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, ''); // strip trailing slash
  }

  /**
   * Fetch metadata and structural analysis for a PDB entry.
   * @returns {Promise<object>} The data payload from the backend.
   */
  async fetchProteinInfo(pdbId) {
    return this._get(`/api/protein/${encodeURIComponent(pdbId.toUpperCase())}`);
  }

  /**
   * Fetch the raw PDB file text for NGL to load.
   * I return the raw text rather than JSON here because NGL expects
   * a string or Blob — wrapping it in JSON and unwrapping it would
   * be pointless overhead.
   */
  async fetchProteinStructure(pdbId) {
    const url = `${this.baseUrl}/api/protein/${encodeURIComponent(pdbId.toUpperCase())}/structure`;
    const response = await fetch(url);
    if (!response.ok) {
      const json = await response.json().catch(() => ({}));
      throw new Error(json.error || `Failed to fetch structure for ${pdbId}`);
    }
    return response.text();
  }

  /**
   * Fetch metadata and structural analysis for an AlphaFold prediction.
   */
  async fetchAlphaFoldInfo(uniprotId) {
    return this._get(`/api/alphafold/${encodeURIComponent(uniprotId.toUpperCase())}`);
  }

  /**
   * Fetch the raw AlphaFold PDB file text.
   */
  async fetchAlphaFoldStructure(uniprotId) {
    const url = `${this.baseUrl}/api/alphafold/${encodeURIComponent(uniprotId.toUpperCase())}/structure`;
    const response = await fetch(url);
    if (!response.ok) {
      const json = await response.json().catch(() => ({}));
      throw new Error(json.error || `Failed to fetch AlphaFold structure for ${uniprotId}`);
    }
    return response.text();
  }

  /**
   * Search RCSB PDB by free text.
   */
  async searchProteins(query) {
    return this._get(`/api/search?q=${encodeURIComponent(query)}`);
  }

  /**
   * Shared GET helper — handles the response envelope { data, status }
   * that all backend endpoints return.
   */
  async _get(path) {
    const response = await fetch(`${this.baseUrl}${path}`);
    const json = await response.json();
    if (!response.ok) {
      throw new Error(json.error || `Request failed with status ${response.status}`);
    }
    return json.data;
  }
}


/* ============================================================
   ViewerManager — all NGL Viewer interactions
   ============================================================ */

class ViewerManager {
  /**
   * @param {string} containerId - ID of the div NGL should render into.
   *
   * I initialise NGL here rather than lazily because the Stage constructor
   * sets up the WebGL context and resize observer immediately — if I deferred
   * it, the first load would feel slower due to WebGL context creation.
   */
  constructor(containerId) {
    this._containerId = containerId;
    this._stage = null;
    this._component = null;          // current loaded structure component
    this._highlightRepr = null;      // temporary highlight for sequence picker
    this._measureShape = null;       // NGL shape component for distance line
    this._visibleChains = new Set(); // chains currently visible
    this._allChains = [];            // all chains in current structure

    // Current rendering state — maintained so re-applying is idempotent
    this._currentRepr = 'cartoon';
    this._currentColor = 'chainid';

    // Measurement state
    this._measureMode = false;
    this._measureAtom1 = null;

    // Mouse position for tooltip placement (tracked via mousemove)
    this._mouseX = 0;
    this._mouseY = 0;

    this._initStage();
  }

  _initStage() {
    // NGL Stage — I disable the built-in tooltip because I want a custom-styled
    // one that matches the dark theme and shows more information.
    this._stage = new NGL.Stage(this._containerId, {
      backgroundColor: '#070b14',
      tooltip: false,
      quality: 'medium', // balance between detail and performance
    });

    // Track mouse position for tooltip placement
    const container = document.getElementById(this._containerId);
    container.addEventListener('mousemove', (e) => {
      const rect = container.getBoundingClientRect();
      this._mouseX = e.clientX - rect.left;
      this._mouseY = e.clientY - rect.top;
    });

    // Hover signal — show atom info tooltip
    this._stage.signals.hovered.add((proxy) => {
      if (proxy && proxy.atom) {
        this._emit('atomHovered', { atom: proxy.atom, x: this._mouseX, y: this._mouseY });
      } else {
        this._emit('atomHovered', null);
      }
    });

    // Click signal — used for measure mode and residue selection
    this._stage.signals.clicked.add((proxy) => {
      if (proxy && proxy.atom) {
        this._handleAtomClick(proxy.atom);
      } else if (this._measureMode) {
        // Clicked empty space during measure — provide feedback
        this._emit('measureStatus', 'Click directly on an atom in the structure.');
      }
    });

    // Handle container resize — NGL doesn't auto-resize in some setups
    const resizeObserver = new ResizeObserver(() => {
      if (this._stage) this._stage.handleResize();
    });
    resizeObserver.observe(container);
  }

  /**
   * Load a PDB text string into the viewer.
   * Replaces any currently loaded structure.
   *
   * @param {string} pdbText  - Raw PDB file content
   * @param {string} name     - Identifier used in NGL internals (PDB ID or UniProt)
   * @param {string[]} chainIds - Chain IDs for visibility state initialisation
   */
  async loadStructure(pdbText, name, chainIds) {
    // Remove the previous structure before loading a new one so memory
    // isn't accumulated. NGL holds WebGL buffers per component.
    if (this._component) {
      this._stage.removeAllComponents();
      this._component = null;
      this._highlightRepr = null;
      this._measureShape = null;
    }

    const blob = new Blob([pdbText], { type: 'text/plain' });

    // NGL infers format from the 'ext' option — without it, it tries to
    // guess from the blob's filename, which doesn't exist for blobs.
    this._component = await this._stage.loadFile(blob, {
      ext: 'pdb',
      defaultRepresentation: false,
      name: name,
    });

    this._allChains = chainIds || [];
    this._visibleChains = new Set(this._allChains);

    this._applyRepresentation();
    this._component.autoView();
  }

  /**
   * Set the representation type (cartoon, surface, ball+stick, etc.).
   * Re-applies current colour scheme automatically.
   */
  setRepresentation(reprType) {
    this._currentRepr = reprType;
    this._applyRepresentation();
  }

  /**
   * Set the colour scheme (chainid, sstruc, bfactor, hydrophobicity, element).
   */
  setColorScheme(scheme) {
    this._currentColor = scheme;
    this._applyRepresentation();
  }

  /**
   * Set chain visibility. Rebuilds the NGL selection string from the
   * set of visible chains and re-applies the representation.
   */
  setChainVisibility(chainId, visible) {
    if (visible) {
      this._visibleChains.add(chainId);
    } else {
      this._visibleChains.delete(chainId);
    }
    this._applyRepresentation();
  }

  /**
   * Set the viewport background colour.
   */
  setBackground(color) {
    if (this._stage) {
      this._stage.setParameters({ backgroundColor: color });
    }
  }

  /**
   * Toggle auto-rotation. Uses NGL's setSpin API if available,
   * which internally uses requestAnimationFrame.
   */
  toggleSpin(enabled) {
    if (!this._stage) return;
    try {
      if (enabled) {
        this._stage.setSpin([0, 1, 0], 0.008);
      } else {
        this._stage.setSpin(false);
      }
    } catch (e) {
      // setSpin not available in this NGL build — no-op gracefully
      console.warn('NGL setSpin not available:', e.message);
    }
  }

  /**
   * Capture a high-resolution screenshot and trigger a browser download.
   *
   * factor: 2 gives a 2× resolution image — good enough for publications
   * without being so large it freezes the browser on typical hardware.
   */
  async screenshot(filename) {
    if (!this._stage) return;
    try {
      const blob = await this._stage.makeImage({ factor: 2, antialias: true, trim: false });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || 'protein_screenshot.png';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error('Screenshot failed:', e);
    }
  }

  /**
   * Animate the camera to fit the current structure in the viewport.
   */
  centre() {
    if (this._component) {
      this._component.autoView(500); // 500ms animation
    }
  }

  /**
   * Enter distance measurement mode. The next two atom clicks will be used
   * to calculate the distance between those atoms.
   */
  startMeasure() {
    this._measureMode = true;
    this._measureAtom1 = null;
    this._emit('measureStatus', 'Click the first atom…');
  }

  /**
   * Exit measurement mode and remove any measurement shape from the viewport.
   */
  clearMeasure() {
    this._measureMode = false;
    this._measureAtom1 = null;
    if (this._measureShape) {
      this._stage.removeComponent(this._measureShape);
      this._measureShape = null;
    }
    this._emit('measureCleared', null);
  }

  /**
   * Highlight a specific residue in the 3D view.
   * Used by the sequence viewer to show the selected residue.
   *
   * @param {string} chainId - Chain identifier
   * @param {number} resno   - Residue sequence number
   */
  highlightResidue(chainId, resno) {
    if (!this._component) return;

    // Remove previous highlight representation
    if (this._highlightRepr) {
      this._component.removeRepresentation(this._highlightRepr);
      this._highlightRepr = null;
    }

    // Add a ball+stick overlay for just this residue — NGL selection syntax
    // is '{resno}:{chainId}' for a specific residue in a specific chain.
    const sele = `${resno}:${chainId}`;
    this._highlightRepr = this._component.addRepresentation('ball+stick', {
      sele,
      colorValue: '#ffd700', // gold highlight
      radius: 0.25,
      opacity: 1,
    });
  }

  /**
   * Clear the residue highlight from the 3D view.
   */
  clearHighlight() {
    if (this._highlightRepr && this._component) {
      this._component.removeRepresentation(this._highlightRepr);
      this._highlightRepr = null;
    }
  }

  isLoaded() {
    return this._component !== null;
  }

  // ---- Private methods ----

  /**
   * Rebuild the NGL representation from current state.
   *
   * I call this on every representation/colour/chain change rather than
   * mutating an existing representation because NGL's representation update
   * API is less reliable across versions than just removing and re-adding.
   * The performance difference is negligible for typical structure sizes.
   */
  _applyRepresentation() {
    if (!this._component) return;

    // Remove existing representations (but not the highlight)
    const reprs = this._component.reprList.slice();
    reprs.forEach((r) => {
      if (r !== this._highlightRepr) {
        this._component.removeRepresentation(r);
      }
    });

    // Build NGL selection string from visible chains.
    // If all chains are visible, '*' is more efficient than a long OR expression.
    let sele = '*';
    if (this._visibleChains.size > 0 && this._visibleChains.size < this._allChains.length) {
      sele = [...this._visibleChains].map((c) => `:${c}`).join(' or ');
    } else if (this._visibleChains.size === 0) {
      sele = 'none';
    }

    this._component.addRepresentation(this._currentRepr, {
      sele,
      colorScheme: this._currentColor,
    });
  }

  /**
   * Handle a click on an atom — either for measurement or general picking info.
   */
  _handleAtomClick(atom) {
    if (this._measureMode) {
      this._handleMeasureClick(atom);
    }
    // Always emit so UIController can update the tooltip / highlight display
    this._emit('atomClicked', { atom });
  }

  /**
   * Two-click distance measurement.
   * First click stores atom 1. Second click calculates distance, draws a line
   * in the viewport using NGL's Shape API, and emits the result.
   */
  _handleMeasureClick(atom) {
    if (!this._measureAtom1) {
      this._measureAtom1 = atom;
      this._emit('measureStatus', `Atom 1: ${atom.resname} ${atom.resno}:${atom.chainname} — now click second atom…`);
      return;
    }

    const a1 = this._measureAtom1;
    const a2 = atom;

    // Euclidean distance in Ångströms (PDB coordinates are in Å)
    const dx = a2.x - a1.x;
    const dy = a2.y - a1.y;
    const dz = a2.z - a1.z;
    const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);

    // Draw a visible line between the two atoms using NGL's Shape primitive.
    // I use a thin cylinder rather than a line because NGL renders lines at
    // a fixed 1px width regardless of depth — cylinders scale correctly.
    if (this._measureShape) {
      this._stage.removeComponent(this._measureShape);
    }

    const shape = new NGL.Shape('measurement');
    shape.addCylinder(
      [a1.x, a1.y, a1.z],
      [a2.x, a2.y, a2.z],
      [1, 0.8, 0],   // orange-ish colour (RGB 0–1)
      0.1            // radius in Å — thin enough to not obscure the structure
    );
    shape.addSphere([a1.x, a1.y, a1.z], [1, 0.8, 0], 0.25);
    shape.addSphere([a2.x, a2.y, a2.z], [1, 0.8, 0], 0.25);

    this._measureShape = this._stage.addComponentFromObject(shape);
    this._measureShape.addRepresentation('buffer');

    // Exit measure mode and report result
    this._measureMode = false;
    this._measureAtom1 = null;
    this._emit('measureComplete', {
      atom1: { resname: a1.resname, resno: a1.resno, chain: a1.chainname },
      atom2: { resname: a2.resname, resno: a2.resno, chain: a2.chainname },
      distance: distance.toFixed(2),
    });
  }

  /**
   * Emit a custom event on document so UIController can listen without
   * ViewerManager needing a direct reference to UIController.
   * Using document as the event bus avoids tight coupling between the two.
   */
  _emit(eventName, detail) {
    document.dispatchEvent(new CustomEvent(`pv:${eventName}`, { detail }));
  }
}


/* ============================================================
   UIController — all DOM manipulation and event handling
   ============================================================ */

class UIController {
  /**
   * @param {ProteinAPI}    api    - Network layer
   * @param {ViewerManager} viewer - 3D rendering layer
   */
  constructor(api, viewer) {
    this.api = api;
    this.viewer = viewer;
    this._currentMetadata = null; // stored for JSON export
    this._sequenceData = {};       // per-chain sequence + SS data from last load
    this._selectedResSpan = null;  // currently highlighted residue span in DOM
  }

  /**
   * Wire up all event listeners. Called once on DOMContentLoaded.
   * I put all event binding here rather than inline in the HTML so the
   * JS logic stays in one place and the HTML stays semantic.
   */
  init() {
    // Load PDB
    this._el('load-pdb-btn').addEventListener('click', () => {
      this._loadPDB(this._el('pdb-input').value);
    });
    this._el('pdb-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._loadPDB(this._el('pdb-input').value);
    });

    // Load AlphaFold
    this._el('load-af-btn').addEventListener('click', () => {
      this._loadAlphaFold(this._el('af-input').value);
    });
    this._el('af-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._loadAlphaFold(this._el('af-input').value);
    });

    // PDB ID auto-uppercase
    this._el('pdb-input').addEventListener('input', (e) => {
      const pos = e.target.selectionStart;
      e.target.value = e.target.value.toUpperCase();
      e.target.setSelectionRange(pos, pos);
    });

    // Search
    this._el('search-btn').addEventListener('click', () => {
      this._search(this._el('search-input').value);
    });
    this._el('search-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._search(this._el('search-input').value);
    });

    // Quick-load buttons (in controls panel)
    document.querySelectorAll('.btn--quick[data-pdb]').forEach((btn) => {
      btn.addEventListener('click', () => this._loadPDB(btn.dataset.pdb));
    });

    // Empty state CTA buttons
    document.querySelectorAll('.btn--outline-mono[data-pdb]').forEach((btn) => {
      btn.addEventListener('click', () => this._loadPDB(btn.dataset.pdb));
    });

    // Representation select
    this._el('representation-select').addEventListener('change', (e) => {
      this.viewer.setRepresentation(e.target.value);
    });

    // Colour scheme select
    this._el('colour-select').addEventListener('change', (e) => {
      this.viewer.setColorScheme(e.target.value);
    });

    // Background colour
    this._el('bg-select').addEventListener('change', (e) => {
      this.viewer.setBackground(e.target.value);
    });

    // View control buttons
    this._el('centre-btn').addEventListener('click', () => this.viewer.centre());

    this._el('spin-btn').addEventListener('click', () => {
      const btn = this._el('spin-btn');
      const active = btn.getAttribute('aria-pressed') === 'true';
      btn.setAttribute('aria-pressed', String(!active));
      this.viewer.toggleSpin(!active);
    });

    this._el('screenshot-btn').addEventListener('click', () => {
      const id = this._currentMetadata?.pdb_id || this._currentMetadata?.uniprot_id || 'protein';
      this.viewer.screenshot(`${id}_screenshot.png`);
    });

    // Measurement
    this._el('measure-btn').addEventListener('click', () => {
      const btn = this._el('measure-btn');
      const active = btn.getAttribute('aria-pressed') === 'true';
      if (active) {
        this.viewer.clearMeasure();
        btn.setAttribute('aria-pressed', 'false');
        this._el('measure-status').hidden = true;
        this._el('clear-measure-btn').hidden = true;
      } else {
        btn.setAttribute('aria-pressed', 'true');
        this._el('measure-status').hidden = false;
        this._el('clear-measure-btn').hidden = false;
        this.viewer.startMeasure();
      }
    });

    this._el('clear-measure-btn').addEventListener('click', () => {
      this.viewer.clearMeasure();
      this._el('measure-btn').setAttribute('aria-pressed', 'false');
      this._el('measure-status').hidden = true;
      this._el('measure-result').hidden = true;
      this._el('clear-measure-btn').hidden = true;
    });

    // Error dismiss
    this._el('error-close-btn').addEventListener('click', () => this._hideError());

    // Sequence chain selector
    this._el('sequence-chain-select').addEventListener('change', (e) => {
      this._renderSequenceChain(e.target.value);
    });

    // Sequence panel collapse
    this._el('seq-collapse-btn').addEventListener('click', () => {
      const panel = this._el('sequence-panel');
      const btn = this._el('seq-collapse-btn');
      const expanded = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!expanded));
      panel.classList.toggle('collapsed', expanded);
      // Rotate the chevron icon via CSS class
      btn.classList.toggle('rotated', expanded);
    });

    // Export metadata
    this._el('export-btn').addEventListener('click', () => this._exportMetadata());

    // ViewerManager events (emitted on document)
    document.addEventListener('pv:atomHovered', (e) => this._onAtomHovered(e.detail));
    document.addEventListener('pv:atomClicked', (e) => this._onAtomClicked(e.detail));
    document.addEventListener('pv:measureStatus', (e) => {
      const el = this._el('measure-status');
      el.textContent = e.detail;
      el.hidden = false;
    });
    document.addEventListener('pv:measureComplete', (e) => this._onMeasureComplete(e.detail));
    document.addEventListener('pv:measureCleared', () => {
      this._el('measure-result').hidden = true;
      this._el('measure-status').hidden = true;
    });
  }

  // ---- Load flows ----

  async _loadPDB(rawId) {
    const pdbId = rawId?.trim().toUpperCase();
    if (!pdbId || pdbId.length < 4) {
      this._showError('Please enter a 4-character PDB identifier (e.g. 1CRN).');
      return;
    }

    this._showLoading();
    this._hideError();
    this._hideEmpty();

    try {
      // Fetch metadata and structure file in parallel — they're independent
      // requests and this roughly halves the perceived load time.
      const [info, pdbText] = await Promise.all([
        this.api.fetchProteinInfo(pdbId),
        this.api.fetchProteinStructure(pdbId),
      ]);

      await this.viewer.loadStructure(pdbText, pdbId, info.chain_ids);

      this._currentMetadata = info;
      this._sequenceData = info.sequence || {};

      this._updateMetadata(info);
      this._updateChainToggles(info.chains || []);
      this._updateSequenceViewer(info.sequence || {});

      this._el('af-disclaimer').hidden = true;
      this._hideLoading();
    } catch (err) {
      this._hideLoading();
      this._showError(err.message || 'Failed to load structure. Please check the PDB ID and try again.');
    }
  }

  async _loadAlphaFold(rawId) {
    const uniprotId = rawId?.trim().toUpperCase();
    if (!uniprotId || uniprotId.length < 6) {
      this._showError('Please enter a UniProt accession (e.g. P68871).');
      return;
    }

    this._showLoading();
    this._hideError();
    this._hideEmpty();

    try {
      const [info, pdbText] = await Promise.all([
        this.api.fetchAlphaFoldInfo(uniprotId),
        this.api.fetchAlphaFoldStructure(uniprotId),
      ]);

      await this.viewer.loadStructure(pdbText, uniprotId, info.chain_ids);

      this._currentMetadata = info;
      this._sequenceData = info.sequence || {};

      this._updateMetadata(info);
      this._updateChainToggles(info.chains || []);
      this._updateSequenceViewer(info.sequence || {});

      // Show AlphaFold disclaimer — scientific integrity requires making clear
      // this is a prediction, not an experimentally determined structure.
      this._el('af-disclaimer').hidden = false;
      this._hideLoading();
    } catch (err) {
      this._hideLoading();
      this._showError(err.message || 'Failed to load AlphaFold structure. Check the UniProt accession and try again.');
    }
  }

  async _search(query) {
    query = query?.trim();
    if (!query || query.length < 2) return;

    const resultsEl = this._el('search-results');
    resultsEl.hidden = false;
    resultsEl.innerHTML = '<p style="padding:0.5rem;font-size:0.75rem;color:#475569">Searching…</p>';

    try {
      const data = await this.api.searchProteins(query);
      const results = data.results || [];

      if (results.length === 0) {
        resultsEl.innerHTML = '<p style="padding:0.5rem;font-size:0.75rem;color:#475569">No results found.</p>';
        return;
      }

      resultsEl.innerHTML = results.map((r) => `
        <div class="search-result-item" tabindex="0" role="button"
             data-pdb="${r.pdb_id}"
             aria-label="Load ${r.pdb_id} (relevance score ${r.score})">
          <span class="search-result-id">${r.pdb_id}</span>
          <span style="font-size:0.68rem;color:#475569">score ${r.score}</span>
        </div>
      `).join('');

      // Wire up click and keyboard activation on each result
      resultsEl.querySelectorAll('.search-result-item').forEach((item) => {
        const activate = () => {
          this._el('pdb-input').value = item.dataset.pdb;
          resultsEl.hidden = true;
          this._loadPDB(item.dataset.pdb);
        };
        item.addEventListener('click', activate);
        item.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
        });
      });
    } catch (err) {
      resultsEl.innerHTML = `<p style="padding:0.5rem;font-size:0.75rem;color:#ef4444">${err.message}</p>`;
    }
  }

  // ---- Metadata UI ----

  _updateMetadata(info) {
    const show = (id, val) => {
      const el = this._el(id);
      if (el) el.textContent = val ?? '—';
    };

    // Source badge
    const badge = this._el('source-badge');
    if (info.is_predicted) {
      badge.textContent = 'AlphaFold Database (EBI)';
      badge.className = 'source-badge source-badge--alphafold';
    } else {
      badge.textContent = 'RCSB Protein Data Bank';
      badge.className = 'source-badge source-badge--pdb';
    }

    // AlphaFold disclaimer in the metadata panel — shown whenever the loaded
    // structure is a prediction rather than an experimental determination.
    // The disclaimer is required by scientific integrity: a user scrolling
    // through the metadata must see it in context, not just as a viewport banner.
    this._el('meta-af-disclaimer').hidden = !info.is_predicted;

    show('meta-title', info.title);
    show('meta-organism', info.organism);
    show('meta-method', info.method);
    show('meta-resolution', info.resolution ? `${info.resolution} Å` : 'N/A');
    show('meta-atoms', info.atom_count?.toLocaleString());

    const totalResidues = info.secondary_structure?.total_residues;
    show('meta-residues', totalResidues ? totalResidues.toLocaleString() : '—');
    show('meta-chains', info.chain_ids?.join(', ') || '—');

    // Authors
    const authorsEl = this._el('meta-authors');
    if (info.authors?.length) {
      authorsEl.textContent = info.authors.join(', ');
      this._el('authors-section').hidden = false;
    } else {
      this._el('authors-section').hidden = true;
    }

    // Secondary structure breakdown
    const ss = info.secondary_structure || {};
    this._updateSSBar(ss);

    // Chain detail list
    this._updateChainDetailList(info.chains || []);

    // External links
    const rcsbLink = this._el('rcsb-link');
    const afLink = this._el('af-link');
    if (info.rcsb_url) {
      rcsbLink.href = info.rcsb_url;
      rcsbLink.hidden = false;
    } else {
      rcsbLink.hidden = true;
    }
    if (info.alphafold_url) {
      afLink.href = info.alphafold_url;
      afLink.hidden = false;
    } else {
      afLink.hidden = true;
    }

    // Show metadata panel
    this._el('metadata-placeholder').hidden = true;
    this._el('metadata-content').hidden = false;
  }

  _updateSSBar(ss) {
    const helix = ss.helix ?? 0;
    const sheet = ss.sheet ?? 0;
    const loop  = ss.loop ?? 0;

    this._el('ss-bar-helix').style.width = `${helix}%`;
    this._el('ss-bar-sheet').style.width = `${sheet}%`;
    this._el('ss-bar-loop').style.width  = `${loop}%`;

    this._el('ss-helix-pct').textContent = `${helix}%`;
    this._el('ss-sheet-pct').textContent = `${sheet}%`;
    this._el('ss-loop-pct').textContent  = `${loop}%`;
  }

  _updateChainDetailList(chains) {
    const list = this._el('chain-detail-list');
    list.innerHTML = chains.map((c) => `
      <div class="chain-detail-item">
        <span class="chain-id-badge">${c.id}</span>
        <span class="chain-detail-stats">${(c.residue_count || 0).toLocaleString()} residues · ${(c.atom_count || 0).toLocaleString()} atoms</span>
      </div>
    `).join('');
  }

  // ---- Chain toggles ----

  _updateChainToggles(chains) {
    const container = this._el('chain-toggles');
    const section = this._el('chain-section');

    if (!chains.length) {
      section.hidden = true;
      return;
    }

    container.innerHTML = chains.map((c) => `
      <label class="chain-toggle">
        <input type="checkbox" checked data-chain="${c.id}"
               aria-label="Toggle visibility of chain ${c.id}">
        <span class="chain-toggle-label">Chain ${c.id}</span>
        <span class="chain-toggle-count">${(c.residue_count || 0)} res</span>
      </label>
    `).join('');

    container.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.addEventListener('change', () => {
        this.viewer.setChainVisibility(cb.dataset.chain, cb.checked);
      });
    });

    section.hidden = false;
  }

  // ---- Sequence viewer ----

  _updateSequenceViewer(sequence) {
    const panel = this._el('sequence-panel');
    const chainSelect = this._el('sequence-chain-select');
    const chainIds = Object.keys(sequence);

    if (!chainIds.length) {
      panel.hidden = true;
      return;
    }

    // Populate chain selector dropdown
    chainSelect.innerHTML = chainIds.map((id) => `<option value="${id}">Chain ${id}</option>`).join('');

    this._renderSequenceChain(chainIds[0]);
    panel.hidden = false;
  }

  /**
   * Render the amino acid sequence for a single chain as a row of coloured spans.
   * Each span is clickable to highlight the residue in the 3D view.
   *
   * I colour by secondary structure type (helix/sheet/loop) because that
   * provides the most educational value — users can see the correspondence
   * between the sequence and the 3D ribbon representation.
   */
  _renderSequenceChain(chainId) {
    const display = this._el('sequence-display');
    const chainData = this._sequenceData[chainId];
    this._selectedResSpan = null;

    if (!chainData?.residues) {
      display.innerHTML = '<span style="color:#475569;font-size:0.75rem">No sequence data for this chain.</span>';
      return;
    }

    const spans = chainData.residues.map((res) => {
      const ssClass = res.ss === 'H' ? 'res--helix' : res.ss === 'E' ? 'res--sheet' : 'res--loop';
      return `<span class="res ${ssClass}" tabindex="0"
                    data-chain="${chainId}" data-resno="${res.seq_num}"
                    title="${res.three_letter} ${res.seq_num} (${res.ss === 'H' ? 'Helix' : res.ss === 'E' ? 'Sheet' : 'Loop'})"
                    aria-label="Residue ${res.three_letter} ${res.seq_num}, ${res.ss === 'H' ? 'alpha helix' : res.ss === 'E' ? 'beta sheet' : 'loop'}"
                    role="button">${res.one_letter}</span>`;
    }).join('');

    display.innerHTML = spans;

    // Wire click and keyboard activation on each residue span
    display.querySelectorAll('.res').forEach((span) => {
      const activate = () => {
        // Remove selection highlight from previous span
        if (this._selectedResSpan) this._selectedResSpan.classList.remove('res--selected');
        span.classList.add('res--selected');
        this._selectedResSpan = span;
        this.viewer.highlightResidue(span.dataset.chain, parseInt(span.dataset.resno, 10));
      };
      span.addEventListener('click', activate);
      span.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
      });
    });
  }

  // ---- Atom picking events ----

  _onAtomHovered(detail) {
    const tooltip = this._el('atom-tooltip');
    if (!detail) {
      tooltip.hidden = true;
      return;
    }
    const { atom, x, y } = detail;
    tooltip.textContent = `${atom.resname} ${atom.resno} · Chain ${atom.chainname} · ${atom.atomname}`;
    // Position the tooltip near the cursor, nudged so it doesn't overlap the pointer
    const container = this._el('viewport');
    const cw = container.clientWidth;
    const tx = (x + 16 + 200 > cw) ? x - 210 : x + 16;
    tooltip.style.left = `${tx}px`;
    tooltip.style.top = `${Math.max(0, y - 10)}px`;
    tooltip.hidden = false;
  }

  _onAtomClicked(detail) {
    // Currently just for visual feedback — the measurement logic is handled
    // inside ViewerManager._handleAtomClick via its own state machine.
  }

  _onMeasureComplete(detail) {
    const { atom1, atom2, distance } = detail;
    const resultEl = this._el('measure-result');
    resultEl.innerHTML = `
      <div style="font-size:0.7rem;color:#94a3b8;margin-bottom:0.3rem">Distance</div>
      <div style="font-size:1rem;color:#22d3ee">${distance} Å</div>
      <div style="font-size:0.68rem;color:#64748b;margin-top:0.25rem">
        ${atom1.resname}${atom1.resno}:${atom1.chain} → ${atom2.resname}${atom2.resno}:${atom2.chain}
      </div>
    `;
    resultEl.hidden = false;
    this._el('measure-btn').setAttribute('aria-pressed', 'false');
    this._el('measure-status').hidden = true;
  }

  // ---- Export ----

  _exportMetadata() {
    if (!this._currentMetadata) return;

    // Build a clean export object — omit the raw sequence data to keep the
    // file size reasonable. The structural metadata is what researchers actually
    // need to cite or reference.
    const exportData = {
      source: this._currentMetadata.source,
      identifier: this._currentMetadata.pdb_id || this._currentMetadata.uniprot_id,
      title: this._currentMetadata.title,
      organism: this._currentMetadata.organism,
      method: this._currentMetadata.method,
      resolution_angstroms: this._currentMetadata.resolution,
      atom_count: this._currentMetadata.atom_count,
      chains: this._currentMetadata.chains,
      authors: this._currentMetadata.authors,
      secondary_structure: this._currentMetadata.secondary_structure,
      is_predicted: this._currentMetadata.is_predicted,
      exported_at: new Date().toISOString(),
    };

    const json = JSON.stringify(exportData, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const id = exportData.identifier || 'protein';
    a.href = url;
    a.download = `${id}_metadata.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ---- Loading / error state helpers ----

  _showLoading() {
    this._el('loading-overlay').hidden = false;
    this._el('empty-state').hidden = true;
  }

  _hideLoading() {
    this._el('loading-overlay').hidden = true;
  }

  _showError(message) {
    this._el('error-message').textContent = message;
    this._el('error-overlay').hidden = false;
    this._hideLoading();
  }

  _hideError() {
    this._el('error-overlay').hidden = true;
  }

  _hideEmpty() {
    this._el('empty-state').hidden = true;
  }

  // ---- Utility ----

  _el(id) {
    return document.getElementById(id);
  }
}


/* ============================================================
   Bootstrap — wire everything together on DOMContentLoaded
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  // I configure the backend URL here in one place so switching environments
  // (e.g. local dev → deployed server) only requires changing this string.
  const BACKEND_URL = 'http://127.0.0.1:5000';

  const api    = new ProteinAPI(BACKEND_URL);
  const viewer = new ViewerManager('viewport');
  const ui     = new UIController(api, viewer);

  ui.init();
});
