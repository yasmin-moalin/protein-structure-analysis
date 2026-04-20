// three objects: ProteinAPI (fetch), ViewerManager (ngl), UIController (dom)

'use strict';

/* ProteinAPI */

class ProteinAPI {
  constructor(baseUrl) {
    this.baseUrl = baseUrl.replace(/\/$/, ''); // strip trailing slash
  }

  async fetchProteinInfo(pdbId) {
    return this._get(`/api/protein/${encodeURIComponent(pdbId.toUpperCase())}`);
  }

  async fetchProteinStructure(pdbId) {
    const url = `${this.baseUrl}/api/protein/${encodeURIComponent(pdbId.toUpperCase())}/structure`;
    const response = await fetch(url);
    if (!response.ok) {
      const json = await response.json().catch(() => ({}));
      throw new Error(json.error || `Failed to fetch structure for ${pdbId}`);
    }
    return response.text();
  }

  async fetchAlphaFoldInfo(uniprotId) {
    return this._get(`/api/alphafold/${encodeURIComponent(uniprotId.toUpperCase())}`);
  }

  async fetchAlphaFoldStructure(uniprotId) {
    const url = `${this.baseUrl}/api/alphafold/${encodeURIComponent(uniprotId.toUpperCase())}/structure`;
    const response = await fetch(url);
    if (!response.ok) {
      const json = await response.json().catch(() => ({}));
      throw new Error(json.error || `Failed to fetch AlphaFold structure for ${uniprotId}`);
    }
    return response.text();
  }

  async searchProteins(query) {
    return this._get(`/api/search?q=${encodeURIComponent(query)}`);
  }

  // shared GET helper, unwraps the { data, status } envelope
  async _get(path) {
    const response = await fetch(`${this.baseUrl}${path}`);
    const json = await response.json();
    if (!response.ok) {
      throw new Error(json.error || `Request failed with status ${response.status}`);
    }
    return json.data;
  }
}


/* ViewerManager */

class ViewerManager {
  constructor(containerId) {
    this._containerId = containerId;
    this._stage = null;
    this._component = null;
    this._highlightRepr = null;
    this._measureShape = null;
    this._visibleChains = new Set();
    this._allChains = [];

    this._currentRepr = 'cartoon';
    this._currentColor = 'chainid';

    this._measureMode = false;
    this._measureAtom1 = null;

    this._mouseX = 0;
    this._mouseY = 0;

    this._initStage();
  }

  _initStage() {
    // disable ngl's built-in tooltip so we can show our own styled one
    this._stage = new NGL.Stage(this._containerId, {
      backgroundColor: '#070b14',
      tooltip: false,
      quality: 'medium',
    });

    const container = document.getElementById(this._containerId);
    container.addEventListener('mousemove', (e) => {
      const rect = container.getBoundingClientRect();
      this._mouseX = e.clientX - rect.left;
      this._mouseY = e.clientY - rect.top;
    });

    this._stage.signals.hovered.add((proxy) => {
      if (proxy && proxy.atom) {
        this._emit('atomHovered', { atom: proxy.atom, x: this._mouseX, y: this._mouseY });
      } else {
        this._emit('atomHovered', null);
      }
    });

    this._stage.signals.clicked.add((proxy) => {
      if (proxy && proxy.atom) {
        this._handleAtomClick(proxy.atom);
      } else if (this._measureMode) {
        this._emit('measureStatus', 'Click directly on an atom in the structure.');
      }
    });

    const resizeObserver = new ResizeObserver(() => {
      if (this._stage) this._stage.handleResize();
    });
    resizeObserver.observe(container);

    // intercept wheel so two-finger scroll reaches ngl instead of scrolling the page
    container.addEventListener('wheel', (e) => {
      e.preventDefault();
    }, { passive: false });
  }

  async loadStructure(pdbText, name, chainIds) {
    // clear previous structure to free webgl memory
    if (this._component) {
      this._stage.removeAllComponents();
      this._component = null;
      this._highlightRepr = null;
      this._measureShape = null;
    }

    const blob = new Blob([pdbText], { type: 'text/plain' });

    // ext needed because ngl can't infer format from a blob with no filename
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

  setRepresentation(reprType) {
    this._currentRepr = reprType;
    this._applyRepresentation();
  }

  setColorScheme(scheme) {
    this._currentColor = scheme;
    this._applyRepresentation();
  }

  setChainVisibility(chainId, visible) {
    if (visible) {
      this._visibleChains.add(chainId);
    } else {
      this._visibleChains.delete(chainId);
    }
    this._applyRepresentation();
  }

  setBackground(color) {
    if (this._stage) {
      this._stage.setParameters({ backgroundColor: color });
    }
  }

  toggleSpin(enabled) {
    if (!this._stage) return;
    try {
      if (enabled) {
        this._stage.setSpin([0, 1, 0], 0.008);
      } else {
        this._stage.setSpin(false);
      }
    } catch (e) {
      console.warn('NGL setSpin not available:', e.message);
    }
  }

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

  // dispatch wheel event on canvas so the zoom buttons work for touchpad users
  zoom(direction) {
    if (!this._stage) return;
    const container = document.getElementById(this._containerId);
    const canvas = container?.querySelector('canvas');
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    canvas.dispatchEvent(new WheelEvent('wheel', {
      deltaY: direction * -120,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
      bubbles: true,
      cancelable: true,
    }));
  }

  centre() {
    if (this._component) {
      this._component.autoView(500);
    }
  }

  startMeasure() {
    this._measureMode = true;
    this._measureAtom1 = null;
    // crosshair tells the user they're in a special click mode
    const container = document.getElementById(this._containerId);
    if (container) container.style.cursor = 'crosshair';
    this._emit('measureStatus', 'Click the first atom…');
  }

  clearMeasure() {
    this._measureMode = false;
    this._measureAtom1 = null;
    if (this._measureShape) {
      this._stage.removeComponent(this._measureShape);
      this._measureShape = null;
    }
    const container = document.getElementById(this._containerId);
    if (container) container.style.cursor = '';
    this._emit('measureCleared', null);
  }

  highlightResidue(chainId, resno) {
    if (!this._component) return;

    if (this._highlightRepr) {
      this._component.removeRepresentation(this._highlightRepr);
      this._highlightRepr = null;
    }

    // ngl selection syntax: '{resno}:{chainId}'
    const sele = `${resno}:${chainId}`;
    this._highlightRepr = this._component.addRepresentation('ball+stick', {
      sele,
      colorValue: '#ffd700',
      radius: 0.25,
      opacity: 1,
    });
  }

  clearHighlight() {
    if (this._highlightRepr && this._component) {
      this._component.removeRepresentation(this._highlightRepr);
      this._highlightRepr = null;
    }
  }

  zoomToResidue(chainId, resno) {
    if (!this._component) return;
    const sele = `${resno}:${chainId}`;
    try {
      this._component.autoView(sele, 500);
    } catch (e) {
      this._component.autoView(500);
    }
  }

  isolateChain(chainId) {
    if (chainId === null) {
      this._visibleChains = new Set(this._allChains);
    } else {
      this._visibleChains = new Set([chainId]);
    }
    this._applyRepresentation();
  }

  clearAll() {
    if (this._stage) {
      this._stage.removeAllComponents();
    }
    this._component = null;
    this._highlightRepr = null;
    this._measureShape = null;
    this._visibleChains = new Set();
    this._allChains = [];
    this._measureMode = false;
    this._measureAtom1 = null;
  }

  isLoaded() {
    return this._component !== null;
  }

  // remove and re-add representations rather than mutating - more reliable across ngl versions
  _applyRepresentation() {
    if (!this._component) return;

    const reprs = this._component.reprList.slice();
    reprs.forEach((r) => {
      if (r !== this._highlightRepr) {
        this._component.removeRepresentation(r);
      }
    });

    // '*' is more efficient than a long OR expression when all chains are visible
    let sele = '*';
    if (this._visibleChains.size > 0 && this._visibleChains.size < this._allChains.length) {
      sele = [...this._visibleChains].map((c) => `:${c}`).join(' or ');
    } else if (this._visibleChains.size === 0) {
      sele = 'none';
    }

    if (this._currentColor === 'colorblind') {
      // blue/orange palette safe for deuteranopia and protanopia
      const cbPalette = ['#0072B2', '#E69F00', '#56B4E9', '#D55E00', '#009E73', '#F0E442'];
      const chains = this._allChains.length ? this._allChains : [''];
      chains.forEach((chainId, colourIdx) => {
        const chainSele = chainId
          ? (sele === '*' ? `:${chainId}` : `(${sele}) and :${chainId}`)
          : sele;
        this._component.addRepresentation(this._currentRepr, {
          sele: chainSele,
          colorScheme: 'uniform',
          colorValue: cbPalette[colourIdx % cbPalette.length],
        });
      });
    } else {
      this._component.addRepresentation(this._currentRepr, {
        sele,
        colorScheme: this._currentColor,
      });
    }
  }

  _handleAtomClick(atom) {
    if (this._measureMode) {
      this._handleMeasureClick(atom);
    }
    this._emit('atomClicked', { atom });
  }

  _handleMeasureClick(atom) {
    if (!this._measureAtom1) {
      this._measureAtom1 = atom;
      this._emit('measureStatus', `Atom 1: ${atom.resname} ${atom.resno}:${atom.chainname} - now click second atom…`);
      return;
    }

    const a1 = this._measureAtom1;
    const a2 = atom;

    // euclidean distance in angstroms
    const dx = a2.x - a1.x;
    const dy = a2.y - a1.y;
    const dz = a2.z - a1.z;
    const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);

    // cylinders scale with depth, lines render at fixed 1px regardless
    if (this._measureShape) {
      this._stage.removeComponent(this._measureShape);
    }

    const shape = new NGL.Shape('measurement');
    shape.addCylinder(
      [a1.x, a1.y, a1.z],
      [a2.x, a2.y, a2.z],
      [1, 0.8, 0],
      0.1
    );
    shape.addSphere([a1.x, a1.y, a1.z], [1, 0.8, 0], 0.25);
    shape.addSphere([a2.x, a2.y, a2.z], [1, 0.8, 0], 0.25);

    this._measureShape = this._stage.addComponentFromObject(shape);
    this._measureShape.addRepresentation('buffer');

    this._measureMode = false;
    this._measureAtom1 = null;
    this._emit('measureComplete', {
      atom1: { resname: a1.resname, resno: a1.resno, chain: a1.chainname },
      atom2: { resname: a2.resname, resno: a2.resno, chain: a2.chainname },
      distance: distance.toFixed(2),
    });
  }

  // emit on document so ViewerManager and UIController stay decoupled
  _emit(eventName, detail) {
    document.dispatchEvent(new CustomEvent(`pv:${eventName}`, { detail }));
  }
}


/* UIController */

class UIController {
  constructor(api, viewer) {
    this.api = api;
    this.viewer = viewer;
    this._currentMetadata = null;
    this._sequenceData = {};
    this._selectedResSpan = null;
    this._viewer2 = null;
    this._compareActive = false;
  }

  init() {
    this._el('load-pdb-btn').addEventListener('click', () => {
      this._loadPDB(this._el('pdb-input').value);
    });
    this._el('pdb-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._loadPDB(this._el('pdb-input').value);
    });

    this._el('load-af-btn').addEventListener('click', () => {
      this._loadAlphaFold(this._el('af-input').value);
    });
    this._el('af-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._loadAlphaFold(this._el('af-input').value);
    });

    this._el('pdb-input').addEventListener('input', (e) => {
      const pos = e.target.selectionStart;
      e.target.value = e.target.value.toUpperCase();
      e.target.setSelectionRange(pos, pos);
      e.target.classList.remove('input--pulse');
    });

    this._el('search-btn').addEventListener('click', () => {
      this._search(this._el('search-input').value);
    });
    this._el('search-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._search(this._el('search-input').value);
      if (e.key === 'ArrowDown') {
        const first = this._el('typeahead-list')?.querySelector('[role="option"]');
        if (first) { e.preventDefault(); first.focus(); }
      }
    });

    // live typeahead, debounced 300ms
    this._initTypeahead();

    document.querySelectorAll('.btn--quick[data-pdb]').forEach((btn) => {
      btn.addEventListener('click', () => this._loadPDB(btn.dataset.pdb));
    });

    document.querySelectorAll('.btn--outline-mono[data-pdb]').forEach((btn) => {
      btn.addEventListener('click', () => this._loadPDB(btn.dataset.pdb));
    });

    const reprSelect = this._el('representation-select');
    const reprTip = this._el('repr-description');
    const _updateReprTip = () => {
      const opt = reprSelect.options[reprSelect.selectedIndex];
      if (reprTip && opt) reprTip.textContent = opt.dataset.tip || '';
    };
    reprSelect.addEventListener('change', (e) => {
      this.viewer.setRepresentation(e.target.value);
      _updateReprTip();
    });
    _updateReprTip();

    this._el('colour-select').addEventListener('change', (e) => {
      this.viewer.setColorScheme(e.target.value);
    });

    this._el('bg-select').addEventListener('change', (e) => {
      this.viewer.setBackground(e.target.value);
    });

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

    this._el('compare-toggle-btn').addEventListener('click', () => {
      this._toggleCompareMode();
    });
    this._el('load-compare-btn').addEventListener('click', () => {
      this._loadCompare(this._el('compare-pdb-input').value);
    });
    this._el('compare-pdb-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') this._loadCompare(this._el('compare-pdb-input').value);
    });

    this._el('measure-btn').addEventListener('click', () => {
      const btn = this._el('measure-btn');
      const active = btn.getAttribute('aria-pressed') === 'true';
      if (active) {
        this._exitMeasureMode();
      } else {
        btn.setAttribute('aria-pressed', 'true');
        this._el('measure-status').hidden = true;
        this._el('clear-measure-btn').hidden = false;
        this._el('measure-steps').hidden = false;
        this._setMeasureStep(1);
        this._el('measure-ring').hidden = false;
        this.viewer.startMeasure();
      }
    });

    this._el('clear-measure-btn').addEventListener('click', () => {
      this._exitMeasureMode();
    });

    this._el('error-close-btn').addEventListener('click', () => this._hideError());

    this._el('sequence-chain-select').addEventListener('change', (e) => {
      this._renderSequenceChain(e.target.value);
    });

    this._el('seq-collapse-btn').addEventListener('click', () => {
      const panel = this._el('sequence-panel');
      const btn = this._el('seq-collapse-btn');
      const expanded = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!expanded));
      panel.classList.toggle('collapsed', expanded);
      btn.classList.toggle('rotated', expanded);
    });

    this._el('export-btn').addEventListener('click', () => this._exportMetadata());

    document.addEventListener('pv:atomHovered', (e) => this._onAtomHovered(e.detail));
    document.addEventListener('pv:atomClicked', (e) => this._onAtomClicked(e.detail));
    document.addEventListener('pv:measureStatus', (e) => {
      const el = this._el('measure-status');
      el.textContent = e.detail;
      el.hidden = false;
      if (e.detail && e.detail.includes('now click second')) {
        this._setMeasureStep(2);
      }
    });
    document.addEventListener('pv:measureComplete', (e) => this._onMeasureComplete(e.detail));
    document.addEventListener('pv:measureCleared', () => {
      this._el('measure-result').hidden = true;
      this._el('measure-status').hidden = true;
    });

    this._renderHistoryChips();

    this._el('zoom-in-btn').addEventListener('click',  () => this.viewer.zoom(1));
    this._el('zoom-out-btn').addEventListener('click', () => this.viewer.zoom(-1));

    this._el('clear-viewer-btn').addEventListener('click', () => this._clearViewer());

    // calling _showTour not _setupTour here avoids duplicate listeners on replay
    this._el('replay-tour-btn').addEventListener('click', () => {
      localStorage.removeItem('pv_tour_done');
      this._showTour();
    });

    this._initHelpPopovers();

    // keyboard shortcuts: C centre, M measure, S screenshot, Esc dismiss error
    document.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) return;
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === 'Escape') { this._hideError(); return; }
      if (!this.viewer.isLoaded()) return;
      if (e.key === 'c' || e.key === 'C') this.viewer.centre();
      if (e.key === 'm' || e.key === 'M') this._el('measure-btn').click();
      if (e.key === 's' || e.key === 'S') {
        const id = this._currentMetadata?.pdb_id || this._currentMetadata?.uniprot_id || 'protein';
        this.viewer.screenshot(`${id}_screenshot.png`);
      }
    });

    this._setupTour();
    if (!localStorage.getItem('pv_tour_done')) this._showTour();
  }

  // ---- load flows ----

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
      // fetch metadata and structure in parallel - roughly halves load time
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

      this._saveToHistory(pdbId, info.title);
      this._el('pdb-input').classList.remove('input--pulse');

      this._el('af-disclaimer').hidden = true;
      this._el('clear-viewer-btn').hidden = false;
      this._hideLoading();
    } catch (err) {
      this._hideLoading();
      if (!this._currentMetadata) this._el('empty-state').hidden = false;
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

      this._saveToHistory(`AF:${uniprotId}`, info.title);
      this._el('clear-viewer-btn').hidden = false;

      // show alphafold disclaimer - it's a prediction not experimental
      this._el('af-disclaimer').hidden = false;
      this._hideLoading();
    } catch (err) {
      this._hideLoading();
      if (!this._currentMetadata) this._el('empty-state').hidden = false;
      this._showError(err.message || 'Failed to load AlphaFold structure. Check the UniProt accession and try again.');
    }
  }

  async _search(query) {
    query = query?.trim().toUpperCase();
    if (!query || query.length < 2) return;

    // if it looks like a pdb id just load it directly
    if (/^[0-9][A-Z0-9]{3}$/.test(query)) {
      this._el('pdb-input').value = query;
      this._loadPDB(query);
      return;
    }

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

      resultsEl.innerHTML = results.map((r) => {
        const title = r.title
          ? r.title.charAt(0).toUpperCase() + r.title.slice(1).toLowerCase()
          : '';
        const displayTitle = title.length > 48 ? title.slice(0, 47) + '…' : title;
        return `
          <div class="search-result-item" tabindex="0" role="button"
               data-pdb="${r.pdb_id}"
               aria-label="Load ${r.pdb_id}${title ? ' - ' + title : ''} (score ${r.score})">
            <span class="search-result-id">${r.pdb_id}</span>
            ${displayTitle ? `<span class="search-result-title">${displayTitle}</span>` : ''}
          </div>
        `;
      }).join('');

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

  // ---- metadata ui ----

  _updateMetadata(info) {
    const show = (id, val) => {
      const el = this._el(id);
      if (el) el.textContent = val ?? '-';
    };

    const badge = this._el('source-badge');
    if (info.is_predicted) {
      badge.textContent = 'AlphaFold Database (EBI)';
      badge.className = 'source-badge source-badge--alphafold';
    } else {
      badge.textContent = 'RCSB Protein Data Bank';
      badge.className = 'source-badge source-badge--pdb';
    }

    this._el('meta-af-disclaimer').hidden = !info.is_predicted;

    show('meta-title', info.title);
    show('meta-organism', info.organism);
    show('meta-method', info.method);

    // alphafold: show mean plddt instead of resolution
    const resLabel = this._el('meta-resolution-label');
    if (info.is_predicted && info.mean_plddt != null) {
      if (resLabel) resLabel.textContent = 'Mean pLDDT';
      show('meta-resolution', `${info.mean_plddt} / 100`);
    } else {
      if (resLabel) resLabel.textContent = 'Resolution';
      show('meta-resolution', info.resolution ? `${info.resolution} Å` : 'N/A');
    }
    show('meta-atoms', info.atom_count?.toLocaleString());

    const totalResidues = info.secondary_structure?.total_residues;
    show('meta-residues', totalResidues ? totalResidues.toLocaleString() : '-');
    show('meta-chains', info.chain_ids?.join(', ') || '-');

    const ligands = info.ligands;
    const ligandItem = this._el('meta-ligand-item');
    if (ligands && ligands.count > 0) {
      const names = ligands.unique_names?.join(', ');
      show('meta-ligands', names ? `${ligands.count} (${names})` : String(ligands.count));
      if (ligandItem) ligandItem.hidden = false;
    } else {
      if (ligandItem) ligandItem.hidden = true;
    }

    const geneItem = this._el('meta-gene-item');
    if (info.gene && geneItem) {
      show('meta-gene', info.gene);
      geneItem.hidden = false;
    } else if (geneItem) {
      geneItem.hidden = true;
    }

    const authorsEl = this._el('meta-authors');
    if (info.authors?.length) {
      authorsEl.textContent = info.authors.join(', ');
      this._el('authors-section').hidden = false;
    } else {
      this._el('authors-section').hidden = true;
    }

    const ss = info.secondary_structure || {};
    this._updateSSBar(ss);

    this._updateChainDetailList(info.chains || []);

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

    this._el('metadata-placeholder').hidden = true;
    this._el('metadata-content').hidden = false;

    this._checkDataAccuracy(info);

    this._el('residue-info-section').hidden = true;
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

    const hEl = this._el('ss-helix-count');
    const sEl = this._el('ss-sheet-count');
    const lEl = this._el('ss-loop-count');
    if (ss.helix_count != null && hEl) {
      hEl.textContent = `(${ss.helix_count} res)`;
      sEl.textContent = `(${ss.sheet_count} res)`;
      lEl.textContent = `(${ss.loop_count} res)`;
    }
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

  // ---- chain toggles ----

  _updateChainToggles(chains) {
    const container = this._el('chain-toggles');
    const section = this._el('chain-section');

    if (!chains.length) {
      section.hidden = true;
      return;
    }

    container.innerHTML = chains.map((c) => `
      <div class="chain-toggle-row">
        <label class="chain-toggle">
          <input type="checkbox" checked data-chain="${c.id}"
                 aria-label="Toggle visibility of chain ${c.id}">
          <span class="chain-toggle-label">Chain ${c.id}</span>
          <span class="chain-toggle-count">${(c.residue_count || 0)} res</span>
        </label>
        <button class="btn btn--isolate" data-isolate-chain="${c.id}"
                aria-label="Show only chain ${c.id}">Isolate</button>
      </div>
    `).join('');

    if (chains.length > 1) {
      container.insertAdjacentHTML('beforeend', `
        <button class="btn btn--ghost btn--sm" id="show-all-chains-btn"
                aria-label="Show all chains">Show all chains</button>
      `);
      this._el('show-all-chains-btn').addEventListener('click', () => {
        this.viewer.isolateChain(null);
        container.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
          cb.checked = true;
        });
      });
    }

    container.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
      cb.addEventListener('change', () => {
        this.viewer.setChainVisibility(cb.dataset.chain, cb.checked);
      });
    });

    container.querySelectorAll('.btn--isolate').forEach((btn) => {
      btn.addEventListener('click', () => {
        const chainId = btn.dataset.isolateChain;
        this.viewer.isolateChain(chainId);
        // sync checkboxes after isolate
        container.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
          cb.checked = cb.dataset.chain === chainId;
        });
      });
    });

    section.hidden = false;
  }

  // ---- sequence viewer ----

  _updateSequenceViewer(sequence) {
    const panel = this._el('sequence-panel');
    const chainSelect = this._el('sequence-chain-select');
    const chainIds = Object.keys(sequence);

    if (!chainIds.length) {
      panel.hidden = true;
      return;
    }

    chainSelect.innerHTML = chainIds.map((id) => `<option value="${id}">Chain ${id}</option>`).join('');

    this._renderSequenceChain(chainIds[0]);
    panel.hidden = false;
  }

  // each letter is a clickable span coloured by secondary structure
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

    display.querySelectorAll('.res').forEach((span) => {
      const activate = () => {
        if (this._selectedResSpan) this._selectedResSpan.classList.remove('res--selected');
        span.classList.add('res--selected');
        this._selectedResSpan = span;
        const resno = parseInt(span.dataset.resno, 10);
        this.viewer.highlightResidue(span.dataset.chain, resno);
        this.viewer.zoomToResidue(span.dataset.chain, resno);
        this._showResidueInfo(span.dataset.chain, resno, null);
      };
      span.addEventListener('click', activate);
      span.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
      });
    });
  }

  // ---- atom picking ----

  _onAtomHovered(detail) {
    const tooltip = this._el('atom-tooltip');
    if (!detail) {
      tooltip.hidden = true;
      return;
    }
    const { atom, x, y } = detail;
    tooltip.textContent = `${atom.resname} ${atom.resno} · Chain ${atom.chainname} · ${atom.atomname}`;
    const container = this._el('viewport');
    const cw = container.clientWidth;
    const tx = (x + 16 + 200 > cw) ? x - 210 : x + 16;
    tooltip.style.left = `${tx}px`;
    tooltip.style.top = `${Math.max(0, y - 10)}px`;
    tooltip.hidden = false;
  }

  _onAtomClicked(detail) {
    if (!detail?.atom || this.viewer._measureMode) return;

    const atom = detail.atom;
    const chainId = atom.chainname || atom.chain;
    const resno = atom.resno;

    this._showResidueInfo(chainId, resno, atom);

    const chainSelect = this._el('sequence-chain-select');
    if (chainSelect && chainSelect.value !== chainId) {
      chainSelect.value = chainId;
      this._renderSequenceChain(chainId);
    }

    const display = this._el('sequence-display');
    const targetSpan = display?.querySelector(`[data-chain="${chainId}"][data-resno="${resno}"]`);
    if (targetSpan) {
      if (this._selectedResSpan) this._selectedResSpan.classList.remove('res--selected');
      targetSpan.classList.add('res--selected');
      this._selectedResSpan = targetSpan;
      targetSpan.scrollIntoView({ inline: 'center', behavior: 'smooth', block: 'nearest' });
    }

    this.viewer.highlightResidue(chainId, resno);
  }

  _showResidueInfo(chainId, resno, atom) {
    const section = this._el('residue-info-section');
    const isPredicted = this._currentMetadata?.is_predicted;

    const chainData = this._sequenceData[chainId];
    const resRecord = chainData?.residues?.find(r => r.seq_num === resno);

    const threeLetter = resRecord?.three_letter || atom?.resname || '?';
    const oneLetter = resRecord?.one_letter || '?';
    const ssType = resRecord?.ss || 'C';
    const ssLabel = ssType === 'H' ? 'α-Helix' : ssType === 'E' ? 'β-Sheet' : 'Loop / Coil';
    const bfactor = resRecord?.bfactor;

    this._el('ri-name').textContent = `${threeLetter} (${oneLetter})`;
    this._el('ri-resno').textContent = resno;
    this._el('ri-chain').textContent = chainId;
    this._el('ri-ss').textContent = ssLabel;

    // b-factor = plddt for alphafold structures
    const plddt = this._el('ri-plddt-block');
    if (isPredicted && bfactor != null) {
      this._el('ri-plddt').textContent = bfactor;
      let label = '';
      if (bfactor >= 90) label = 'Very High ≥90';
      else if (bfactor >= 70) label = 'Confident 70–89';
      else if (bfactor >= 50) label = 'Low 50–69';
      else label = 'Very Low <50';
      this._el('ri-plddt-label').textContent = label;
      plddt.hidden = false;
    } else {
      plddt.hidden = true;
    }

    section.hidden = false;
  }

  _onMeasureComplete(detail) {
    const { atom1, atom2, distance } = detail;
    const resultEl = this._el('measure-result');
    resultEl.innerHTML = `
      <div style="font-size:0.7rem;color:#94a3b8;margin-bottom:0.3rem">Distance</div>
      <div style="font-size:1.1rem;color:#22d3ee;font-family:'DM Mono',monospace">${distance} Å</div>
      <div style="font-size:0.68rem;color:#64748b;margin-top:0.25rem">
        ${atom1.resname}${atom1.resno}:${atom1.chain} → ${atom2.resname}${atom2.resno}:${atom2.chain}
      </div>
    `;
    resultEl.hidden = false;
    this._el('measure-btn').setAttribute('aria-pressed', 'false');
    this._el('measure-status').hidden = true;
    this._setMeasureStep(3);
    this._el('measure-ring').hidden = true;
  }

  _setMeasureStep(stepNum) {
    [1, 2, 3].forEach(n => {
      const el = this._el(`measure-step-${n}`);
      if (!el) return;
      el.classList.toggle('measure-step--active', n === stepNum);
      el.classList.toggle('measure-step--done',   n < stepNum);
    });
  }

  _exitMeasureMode() {
    this.viewer.clearMeasure();
    this._el('measure-btn').setAttribute('aria-pressed', 'false');
    this._el('measure-status').hidden = true;
    this._el('measure-result').hidden = true;
    this._el('clear-measure-btn').hidden = true;
    this._el('measure-steps').hidden = true;
    this._el('measure-ring').hidden = true;
  }

  // ---- export ----

  _exportMetadata() {
    if (!this._currentMetadata) return;

    const exportData = {
      source: this._currentMetadata.source,
      identifier: this._currentMetadata.pdb_id || this._currentMetadata.uniprot_id,
      title: this._currentMetadata.title,
      organism: this._currentMetadata.organism,
      gene: this._currentMetadata.gene || undefined,
      method: this._currentMetadata.method,
      resolution_angstroms: this._currentMetadata.resolution,
      atom_count: this._currentMetadata.atom_count,
      chains: this._currentMetadata.chains,
      authors: this._currentMetadata.authors,
      secondary_structure: this._currentMetadata.secondary_structure,
      ligands: this._currentMetadata.ligands,
      is_predicted: this._currentMetadata.is_predicted,
      mean_plddt: this._currentMetadata.mean_plddt || undefined,
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

  // ---- typeahead ----

  _initTypeahead() {
    const input   = this._el('search-input');
    const list    = this._el('typeahead-list');
    const wrapper = list?.parentElement;
    if (!input || !list) return;

    let debounceTimer = null;
    let lastQuery = '';

    const hideList = () => {
      list.hidden = true;
      list.innerHTML = '';
      wrapper?.setAttribute('aria-expanded', 'false');
    };

    const showResults = (results, query) => {
      list.innerHTML = '';
      if (!results.length) {
        list.innerHTML = `<li class="typeahead-empty" role="option" aria-selected="false">No results for "${query}"</li>`;
        list.hidden = false;
        wrapper?.setAttribute('aria-expanded', 'true');
        return;
      }

      results.slice(0, 8).forEach((r) => {
        const title = r.title
          ? r.title.charAt(0).toUpperCase() + r.title.slice(1).toLowerCase()
          : '';
        const displayTitle = title.length > 44 ? title.slice(0, 43) + '…' : title;
        const li = document.createElement('li');
        li.className = 'typeahead-item';
        li.setAttribute('role', 'option');
        li.setAttribute('aria-selected', 'false');
        li.setAttribute('tabindex', '-1');
        li.dataset.pdb = r.pdb_id;
        li.innerHTML = `
          <span class="typeahead-id">${r.pdb_id}</span>
          ${displayTitle ? `<span class="typeahead-title">${displayTitle}</span>` : ''}
        `;

        const activate = () => {
          input.value = r.pdb_id;
          hideList();
          this._loadPDB(r.pdb_id);
        };

        li.addEventListener('click', activate);
        li.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            const next = li.nextElementSibling;
            if (next) next.focus();
          }
          if (e.key === 'ArrowUp') {
            e.preventDefault();
            const prev = li.previousElementSibling;
            if (prev) prev.focus(); else input.focus();
          }
          if (e.key === 'Escape') { hideList(); input.focus(); }
        });

        list.appendChild(li);
      });

      list.hidden = false;
      wrapper?.setAttribute('aria-expanded', 'true');
    };

    input.addEventListener('input', () => {
      const query = input.value.trim();
      clearTimeout(debounceTimer);

      if (/^[0-9][A-Z0-9]{3}$/i.test(query)) {
        hideList();
        return;
      }

      if (query.length < 2) { hideList(); return; }
      if (query === lastQuery) return;
      lastQuery = query;

      list.innerHTML = `<li class="typeahead-empty" role="option" aria-selected="false">Searching…</li>`;
      list.hidden = false;
      wrapper?.setAttribute('aria-expanded', 'true');

      debounceTimer = setTimeout(async () => {
        try {
          const data = await this.api.searchProteins(query);
          const results = data.results || [];
          showResults(results, query);
        } catch {
          list.innerHTML = `<li class="typeahead-empty" role="option" aria-selected="false">Search unavailable - check connection</li>`;
        }
      }, 300);
    });

    document.addEventListener('click', (e) => {
      if (!wrapper?.contains(e.target)) hideList();
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') hideList();
    });
  }

  // ---- onboarding tour ----

  // set up listeners once - separate from _showTour so replay doesn't add duplicate handlers
  _setupTour() {
    this._tourSteps = [
      {
        icon: '🧬',
        title: 'Welcome to ProteinVis',
        body: 'This tool lets you explore real 3D protein structures from the global Protein Data Bank. This short tour shows you the key features - it only takes 30 seconds.',
      },
      {
        icon: '📥',
        title: 'Load a protein structure',
        body: 'Type a 4-character PDB ID (like 4HHB for haemoglobin) in the left panel and click Load - or use a Quick Load button. For AlphaFold predictions, enter a UniProt ID instead.',
      },
      {
        icon: '🖱',
        title: 'Click anything to explore',
        body: 'Click any atom in the 3D view to see its residue name, chain, and secondary structure. For AlphaFold proteins, you\'ll also see the confidence score. Click letters in the sequence strip at the bottom to zoom directly to a residue.',
      },
      {
        icon: '⚖️',
        title: 'Compare two structures',
        body: 'Use "Compare Structures" in the left panel to load two proteins side by side - try haemoglobin (4HHB) vs deoxyhaemoglobin (2HHB). Tip: zoom with the Zoom+/− buttons or two-finger scroll on your trackpad.',
      },
    ];
    this._tourStep = 0;

    const close = () => {
      this._el('tour-overlay').hidden = true;
      localStorage.setItem('pv_tour_done', '1');
    };

    this._el('tour-next-btn').addEventListener('click', () => {
      if (this._tourStep < this._tourSteps.length - 1) {
        this._tourStep++;
        this._renderTour();
      } else {
        close();
      }
    });
    this._el('tour-back-btn').addEventListener('click', () => {
      if (this._tourStep > 0) { this._tourStep--; this._renderTour(); }
    });
    this._el('tour-skip-btn').addEventListener('click', close);
  }

  _showTour() {
    this._tourStep = 0;
    this._renderTour();
    this._el('tour-overlay').hidden = false;
  }

  _renderTour() {
    const steps = this._tourSteps;
    const step  = this._tourStep;
    const s     = steps[step];
    const overlay = this._el('tour-overlay');
    this._el('tour-icon').textContent  = s.icon;
    this._el('tour-title').textContent = s.title;
    this._el('tour-body').textContent  = s.body;
    this._el('tour-step-indicator').textContent = `Step ${step + 1} of ${steps.length}`;
    this._el('tour-next-btn').textContent = step === steps.length - 1 ? 'Get started ✓' : 'Next →';
    this._el('tour-back-btn').hidden = step === 0;
    overlay.querySelectorAll('.tour-dot').forEach((d, i) =>
      d.classList.toggle('tour-dot--active', i === step)
    );
  }

  // ---- help popovers ----

  // one shared popover repositioned when any ? button is clicked
  _initHelpPopovers() {
    const popover   = this._el('help-popover');
    const popText   = this._el('help-popover-text');
    const closeBtn  = this._el('help-popover-close');

    const show = (btn) => {
      popText.textContent = btn.dataset.help || '';
      const rect = btn.getBoundingClientRect();
      popover.style.top  = `${rect.bottom + window.scrollY + 6}px`;
      const left = Math.min(rect.left, window.innerWidth - 280);
      popover.style.left = `${Math.max(8, left)}px`;
      popover.hidden = false;
      closeBtn.focus();
    };

    document.querySelectorAll('.help-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (!popover.hidden && popover._source === btn) {
          popover.hidden = true;
          popover._source = null;
        } else {
          popover._source = btn;
          show(btn);
        }
      });
    });

    closeBtn.addEventListener('click', () => {
      popover.hidden = true;
      popover._source = null;
    });

    document.addEventListener('click', () => {
      popover.hidden = true;
      popover._source = null;
    });
  }

  // ---- data accuracy check ----

  // cross-checks residue and chain counts to confirm what's displayed matches what was parsed
  _checkDataAccuracy(info) {
    const el = this._el('data-verified');
    if (!el) return;

    const ss = info.secondary_structure || {};
    const parsedResidues = ss.total_residues;
    const chainCountFromList = (info.chains || []).length;
    const chainCountFromIds = (info.chain_ids || []).length;

    const sumChainResidues = (info.chains || []).reduce((acc, c) => acc + (c.residue_count || 0), 0);

    const residuesMatch = parsedResidues == null || sumChainResidues === parsedResidues;
    const chainsMatch = chainCountFromList === chainCountFromIds;

    if (residuesMatch && chainsMatch) {
      el.className = 'data-verified data-verified--ok';
      el.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>
        Data verified - residue count and chain count match parsed structure
      `;
    } else {
      el.className = 'data-verified data-verified--warn';
      el.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>
        Count mismatch: chains ${chainCountFromList}/${chainCountFromIds}, residues ${sumChainResidues}/${parsedResidues}
      `;
    }
    el.hidden = false;
  }

  // ---- search history ----

  _saveToHistory(id, title) {
    try {
      const history = this._loadHistory();
      const filtered = history.filter(h => h.id !== id);
      filtered.unshift({ id, title: title || id, ts: Date.now() });
      const trimmed = filtered.slice(0, 5);
      localStorage.setItem('pv_history', JSON.stringify(trimmed));
      this._renderHistoryChips();
    } catch (e) {
      // localStorage may be blocked - history is optional
    }
  }

  _loadHistory() {
    try {
      return JSON.parse(localStorage.getItem('pv_history') || '[]');
    } catch (e) {
      return [];
    }
  }

  _renderHistoryChips() {
    const container = this._el('history-chips');
    const section = this._el('search-history');
    if (!container || !section) return;

    const history = this._loadHistory();
    if (!history.length) {
      section.hidden = true;
      return;
    }

    container.innerHTML = history.map(h => `
      <button class="history-chip" data-id="${h.id}"
              title="${h.title || h.id}"
              aria-label="Reload ${h.id} - ${h.title || ''}">
        ${h.id}
      </button>
    `).join('');

    container.querySelectorAll('.history-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const id = chip.dataset.id;
        if (id.startsWith('AF:')) {
          this._el('af-input').value = id.slice(3);
          this._loadAlphaFold(id.slice(3));
        } else {
          this._el('pdb-input').value = id;
          this._loadPDB(id);
        }
      });
    });

    section.hidden = false;
  }

  // ---- comparison mode ----

  _toggleCompareMode() {
    const btn = this._el('compare-toggle-btn');
    const controls = this._el('compare-controls');
    const vpRow = this._el('viewport-row');
    const vpB = this._el('viewport-b');

    this._compareActive = !this._compareActive;
    btn.setAttribute('aria-pressed', String(this._compareActive));
    btn.textContent = this._compareActive ? 'Exit Comparison' : 'Split-screen Compare';
    controls.hidden = !this._compareActive;

    if (this._compareActive) {
      vpB.hidden = false;
      vpRow.classList.add('comparison-active');

      if (!this._viewer2) {
        this._viewer2 = new ViewerManager('viewport-b');
      }
      // ngl needs a resize call after the container becomes visible
      setTimeout(() => {
        if (this._viewer2?._stage) this._viewer2._stage.handleResize();
        if (this.viewer?._stage) this.viewer._stage.handleResize();
      }, 100);
    } else {
      vpB.hidden = true;
      vpRow.classList.remove('comparison-active');
      this._el('compare-label-b').hidden = true;
      setTimeout(() => {
        if (this.viewer?._stage) this.viewer._stage.handleResize();
      }, 100);
    }
  }

  async _loadCompare(rawId) {
    const pdbId = rawId?.trim().toUpperCase();
    if (!pdbId || pdbId.length < 4) {
      this._showError('Please enter a 4-character PDB ID for comparison.');
      return;
    }
    if (!this._viewer2) {
      this._showError('Enter comparison mode first.');
      return;
    }

    const loadingEl = this._el('compare-loading');
    if (loadingEl) loadingEl.hidden = false;
    const loadBtn = this._el('load-compare-btn');
    if (loadBtn) { loadBtn.disabled = true; loadBtn.textContent = 'Loading…'; }

    try {
      const [info, pdbText] = await Promise.all([
        this.api.fetchProteinInfo(pdbId),
        this.api.fetchProteinStructure(pdbId),
      ]);
      await this._viewer2.loadStructure(pdbText, pdbId, info.chain_ids);

      const labelEl = this._el('compare-label-b');
      labelEl.textContent = `B: ${pdbId} - ${info.title || ''}`;
      labelEl.hidden = false;
    } catch (err) {
      this._showError(err.message || `Failed to load ${pdbId} for comparison.`);
    } finally {
      if (loadingEl) loadingEl.hidden = true;
      if (loadBtn) { loadBtn.disabled = false; loadBtn.textContent = 'Load B'; }
    }
  }

  // ---- clear / reset ----

  _clearViewer() {
    this.viewer.clearAll();
    this._currentMetadata = null;
    this._sequenceData = {};
    this._selectedResSpan = null;

    this._el('metadata-placeholder').hidden = false;
    this._el('metadata-content').hidden = true;
    this._el('chain-section').hidden = true;
    this._el('sequence-panel').hidden = true;
    this._el('af-disclaimer').hidden = true;
    this._el('residue-info-section').hidden = true;
    this._el('data-verified').hidden = true;
    this._el('measure-status').hidden = true;
    this._el('measure-result').hidden = true;
    this._el('clear-measure-btn').hidden = true;
    this._el('measure-steps').hidden = true;
    this._el('measure-btn').setAttribute('aria-pressed', 'false');
    this._el('spin-btn').setAttribute('aria-pressed', 'false');
    this._el('clear-viewer-btn').hidden = true;

    if (this._compareActive) {
      this._compareActive = false;
      this._el('compare-toggle-btn').setAttribute('aria-pressed', 'false');
      this._el('compare-toggle-btn').textContent = 'Split-screen Compare';
      this._el('compare-controls').hidden = true;
      this._el('viewport-b').hidden = true;
      this._el('viewport-row').classList.remove('comparison-active');
      this._el('compare-label-b').hidden = true;
      if (this._viewer2?._stage) this._viewer2._stage.removeAllComponents();
    }

    this._el('empty-state').hidden = false;
    this._hideError();
  }

  // ---- loading / error helpers ----

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

  _el(id) {
    return document.getElementById(id);
  }
}


/* bootstrap */

document.addEventListener('DOMContentLoaded', () => {
  // change this string to switch between local dev and a deployed server
  const BACKEND_URL = 'http://127.0.0.1:5000';

  const api    = new ProteinAPI(BACKEND_URL);
  const viewer = new ViewerManager('viewport');
  const ui     = new UIController(api, viewer);

  ui.init();
});
