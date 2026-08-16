/**
 * library.js: Kütüphane & Okuyucu (AI-Bypass Belge, Kitap ve Masal Okuyucusu)
 *
 * Özellikler:
 *  - Tab Sıralaması:
 *      1. 🧸 Kitaplar & Masallar (Varsayılan ilk tab - data/stories & data/books klasörleri)
 *      2. 📑 Afet Rehberleri (data/raw_txts)
 *      3. 📄 PDF Dokümanları (data/raw_pdfs & data/pdfs)
 *      4. 📚 Tüm Belgeler
 *  - Son Erişim Tarih & Saat Bilgisi: "Son erişim: 11 Ağustos 2026, 16:32"
 *  - Tamamen Sitede Dahili (In-Page) Onay Modalları:
 *      - Tekli Okuma Sıfırlama Modalı (#libResetSingleModal)
 *      - Tüm Okumaları Sıfırlama Modalı (#libResetAllModal)
 *  - PDF Sayfa Sayfa Birebir Gösterim (Sıfır kayıp)
 *  - Sıfır LLM Çağrısı: %0 Pil Tüketimi
 */

'use strict';

const LIB_STORAGE_KEY = 'crisis_library_progress_v3';
const CHUNK_SIZE = 2000; // TXT bölümlendirme boyutu

// ── Durum ─────────────────────────────────────────────────────────────────────
let _libFiles        = [];   // [{ name, type, category, size }]
let _libProgress     = {};   // { filename: { chunkIndex, total, pct, lastRead } }
let _currentDoc      = null; // { name, type, category, content, chunks }
let _activeTab       = 'masal'; // Varsayılan İLK tab: Kitaplar & Masallar!
let _pendingResetFile = null;

// ── Kalıcı İlerleme (localStorage) ────────────────────────────────────────────
function _loadProgress() {
  try {
    const raw = localStorage.getItem(LIB_STORAGE_KEY);
    _libProgress = raw ? JSON.parse(raw) : {};
  } catch (e) {
    _libProgress = {};
  }
}

function _saveProgress(filename, chunkIndex, total) {
  const pct = Math.min(100, Math.round(((chunkIndex + 1) / Math.max(total, 1)) * 100));
  _libProgress[filename] = {
    chunkIndex,
    total,
    pct,
    lastRead: new Date().toISOString(),
  };
  try {
    localStorage.setItem(LIB_STORAGE_KEY, JSON.stringify(_libProgress));
  } catch (e) {}
}

function _formatTurkishDate(isoString) {
  if (!isoString) return '';
  try {
    const d = new Date(isoString);
    return d.toLocaleDateString('tr-TR', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch (e) {
    return '';
  }
}

function _executeResetSingle(filename) {
  delete _libProgress[filename];
  try {
    localStorage.setItem(LIB_STORAGE_KEY, JSON.stringify(_libProgress));
  } catch (e) {}
  _renderLibraryList();
}

function _executeResetAll() {
  _libProgress = {};
  try {
    localStorage.removeItem(LIB_STORAGE_KEY);
  } catch (e) {}
  _renderLibraryList();
}

// ── Metni Sayfalara Bölme ──────────────────────────────────────────────────────
function _splitIntoPages(content, type) {
  if (!content) return ['[Boş İçerik]'];

  // PDF ise "--- SAYFA X / Y ---" işaretlerinden böl
  if (type === 'pdf' || content.includes('--- SAYFA ')) {
    const rawPages = content.split(/(?=--- SAYFA \d+ \/ \d+ ---)/g);
    const pages = rawPages.map(p => p.trim()).filter(Boolean);
    return pages.length ? pages : [content];
  }

  // TXT metni için bölüm/paragraf bazlı bölme
  const chunks = [];
  const paragraphs = content.split(/\n{2,}/);
  let current = '';
  for (const p of paragraphs) {
    if ((current + p).length > CHUNK_SIZE && current) {
      chunks.push(current.trim());
      current = p + '\n\n';
    } else {
      current += p + '\n\n';
    }
  }
  if (current.trim()) chunks.push(current.trim());
  return chunks.length ? chunks : [content];
}

// ── API Çağrıları ─────────────────────────────────────────────────────────────
async function _fetchFileList() {
  try {
    const res = await fetch('/api/library/list');
    if (!res.ok) throw new Error('Liste alınamadı');
    const data = await res.json();
    _libFiles = data.files || [];
    _renderLibraryList();
  } catch (e) {
    console.warn('[library] dosya listesi alınamadı:', e);
    _libFiles = [];
    _renderLibraryList();
  }
}

async function _fetchAndReadFile(filename, category, type) {
  _renderReaderLoading(filename);
  try {
    const res = await fetch(`/api/file/${encodeURIComponent(filename)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    const pages = _splitIntoPages(data.content || '', data.type || type);
    const prog  = _libProgress[filename];
    const startPage = prog ? Math.min(prog.chunkIndex, pages.length - 1) : 0;

    _currentDoc = {
      name: filename,
      type: data.type || type,
      category: category,
      content: data.content,
      chunks: pages,
    };

    _renderReader(startPage);
  } catch (e) {
    _renderReaderError(filename, e.message);
  }
}

// ── CSS Stilleri ──────────────────────────────────────────────────────────────
function _injectLibraryStyles() {
  if (document.getElementById('lib-styles')) return;
  const style = document.createElement('style');
  style.id = 'lib-styles';
  style.textContent = `
    #libraryPanel {
      display: none;
      flex-direction: column;
      height: 100%;
      overflow: hidden;
    }
    #libraryPanel.active { display: flex; }

    #libListView, #libReaderView {
      display: flex;
      flex-direction: column;
      height: 100%;
    }
    #libReaderView { display: none; }

    .lib-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      padding: 1rem 1.25rem 0.75rem;
      border-bottom: 1px solid var(--border-main);
      flex-shrink: 0;
      background: var(--bg-sidebar-l);
    }
    .lib-header h2 {
      font-family: var(--font-sans);
      font-size: 1rem;
      font-weight: 700;
      color: var(--text-primary);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    /* Sekme (Tab) Bar: Masallar İLK SIRA */
    .lib-tabs {
      display: flex;
      gap: 0.375rem;
      padding: 0.5rem 1.25rem;
      border-bottom: 1px solid var(--border-card);
      background: var(--bg-canvas);
      overflow-x: auto;
      flex-shrink: 0;
    }
    .lib-tab-btn {
      padding: 0.375rem 0.875rem;
      border: 1px solid var(--border-card);
      border-radius: 9999px;
      background: var(--bg-card);
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 0.75rem;
      cursor: pointer;
      white-space: nowrap;
      transition: all 0.15s;
    }
    .lib-tab-btn:hover { border-color: var(--accent-primary); color: var(--text-primary); }
    .lib-tab-btn.active {
      background: var(--accent-primary);
      color: #fff;
      border-color: var(--accent-primary);
      font-weight: 600;
    }

    #libFileList {
      flex: 1;
      overflow-y: auto;
      padding: 1rem;
      display: flex;
      flex-direction: column;
      gap: 0.625rem;
    }

    .lib-file-card {
      display: flex;
      align-items: center;
      gap: 0.875rem;
      padding: 0.875rem 1rem;
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: var(--rounded-card);
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    .lib-file-card:hover {
      border-color: var(--accent-primary);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent-primary) 12%, transparent);
    }
    .lib-file-icon { font-size: 1.625rem; flex-shrink: 0; }
    .lib-file-info { flex: 1; min-width: 0; cursor: pointer; }
    .lib-file-title {
      font-family: var(--font-mono);
      font-size: 0.8125rem;
      font-weight: 600;
      color: var(--text-primary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .lib-file-meta {
      font-family: var(--font-mono);
      font-size: 0.6875rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.5rem;
    }
    .lib-progress-wrap {
      height: 4px;
      background: var(--border-card);
      border-radius: 2px;
      margin-top: 0.375rem;
      overflow: hidden;
    }
    .lib-progress-fill {
      height: 100%;
      background: var(--accent-secondary);
      border-radius: 2px;
      transition: width 0.3s;
    }
    .lib-card-actions {
      display: flex;
      align-items: center;
      gap: 0.375rem;
      flex-shrink: 0;
    }
    .lib-btn-sm {
      padding: 0.25rem 0.625rem;
      border: 1px solid var(--border-card);
      border-radius: 0.375rem;
      background: var(--bg-canvas);
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 0.6875rem;
      cursor: pointer;
    }
    .lib-btn-sm:hover { background: var(--bg-card); border-color: var(--accent-primary); color: var(--accent-primary); }
    .lib-btn-reset:hover { border-color: var(--accent-red); color: var(--accent-red); }

    /* Reader */
    #libReaderContent {
      flex: 1;
      overflow-y: auto;
      padding: 1.5rem;
      font-family: var(--font-mono);
      font-size: 0.875rem;
      color: var(--text-primary);
      line-height: 1.8;
      white-space: pre-wrap;
      background: var(--bg-canvas);
    }
    #libReaderNav {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.75rem 1rem;
      border-top: 1px solid var(--border-main);
      flex-shrink: 0;
      background: var(--bg-sidebar-l);
      gap: 0.5rem;
    }
    .lib-nav-btn {
      padding: 0.375rem 0.875rem;
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 0.375rem;
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 0.75rem;
      cursor: pointer;
    }
    .lib-nav-btn:hover:not(:disabled) { background: var(--accent-primary); color: #fff; border-color: var(--accent-primary); }
    .lib-nav-btn:disabled { opacity: 0.35; cursor: default; }

    .lib-badge {
      font-family: var(--font-mono);
      font-size: 0.625rem;
      padding: 0.15rem 0.4rem;
      border-radius: 0.25rem;
      font-weight: 700;
      text-transform: uppercase;
    }
    .lib-badge.rehber { background: color-mix(in srgb, var(--accent-primary) 15%, transparent); color: var(--accent-primary); }
    .lib-badge.masal  { background: color-mix(in srgb, #ec4899 15%, transparent); color: #ec4899; }
    .lib-badge.pdf    { background: color-mix(in srgb, var(--accent-red) 15%, transparent); color: var(--accent-red); }

    /* Modal Overlay (Dahili In-Page Modal) */
    .lib-modal-overlay {
      display: none;
      position: fixed;
      inset: 0;
      z-index: 1000;
      background: rgba(0,0,0,0.65);
      backdrop-filter: blur(2px);
      align-items: center;
      justify-content: center;
      padding: 1rem;
    }
    .lib-modal-box {
      max-width: 22rem;
      width: 100%;
      background: var(--bg-card);
      border: 1px solid var(--border-main);
      border-radius: var(--rounded-card);
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
      box-shadow: var(--shadow-card);
    }
  `;
  document.head.appendChild(style);
}

// ── Modallar (Sıfırlama İşlemleri) ───────────────────────────────────────────
function _buildLibraryInPageModals() {
  if (document.getElementById('libModalsContainer')) return;

  const container = document.createElement('div');
  container.id = 'libModalsContainer';
  container.innerHTML = `
    <!-- 1. Tekli Okuma Sıfırlama Modalı -->
    <div id="libResetSingleModal" class="lib-modal-overlay">
      <div class="lib-modal-box">
        <div style="display:flex;align-items:center;gap:0.5rem;color:var(--accent-red);">
          <span style="font-size:1.25rem;">⚠️</span>
          <h3 style="font-family:var(--font-sans);font-size:0.9375rem;font-weight:700;">Okuma İlerlemesini Sıfırla</h3>
        </div>
        <p id="libResetSingleModalText" style="font-family:var(--font-mono);font-size:0.8125rem;color:var(--text-secondary);line-height:1.5;">
          Bu belgedeki okuma ilerlemeniz ve kaldığınız sayfa sıfırlanacaktır.
        </p>
        <div style="display:flex;justify-content:flex-end;gap:0.625rem;">
          <button id="libResetSingleCancelBtn" class="lib-btn-sm">İptal</button>
          <button id="libResetSingleConfirmBtn" class="lib-btn-sm lib-btn-reset" style="background:var(--accent-red);color:#fff;border:none;">Evet, Sıfırla</button>
        </div>
      </div>
    </div>

    <!-- 2. Tüm Okumaları Sıfırlama Modalı -->
    <div id="libResetAllModal" class="lib-modal-overlay">
      <div class="lib-modal-box">
        <div style="display:flex;align-items:center;gap:0.5rem;color:var(--accent-red);">
          <span style="font-size:1.25rem;">⚠️</span>
          <h3 style="font-family:var(--font-sans);font-size:0.9375rem;font-weight:700;">Tüm Okuma Geçmişini Sıfırla</h3>
        </div>
        <p style="font-family:var(--font-mono);font-size:0.8125rem;color:var(--text-secondary);line-height:1.5;">
          Kütüphanedeki tüm kitap ve belgelerin okuma geçmişi sıfırlanacaktır. Onaylıyor musunuz?
        </p>
        <div style="display:flex;justify-content:flex-end;gap:0.625rem;">
          <button id="libResetAllCancelBtn" class="lib-btn-sm">İptal</button>
          <button id="libResetAllConfirmBtn" class="lib-btn-sm lib-btn-reset" style="background:var(--accent-red);color:#fff;border:none;">Tümünü Sıfırla</button>
        </div>
      </div>
    </div>`;

  document.body.appendChild(container);

  // Single Reset Modal Handlers
  document.getElementById('libResetSingleCancelBtn').addEventListener('click', () => {
    document.getElementById('libResetSingleModal').style.display = 'none';
    _pendingResetFile = null;
  });
  document.getElementById('libResetSingleConfirmBtn').addEventListener('click', () => {
    if (_pendingResetFile) {
      _executeResetSingle(_pendingResetFile);
      if (_currentDoc && _currentDoc.name === _pendingResetFile) {
        _renderReader(0);
      }
      _pendingResetFile = null;
    }
    document.getElementById('libResetSingleModal').style.display = 'none';
  });

  // All Reset Modal Handlers
  document.getElementById('libResetAllCancelBtn').addEventListener('click', () => {
    document.getElementById('libResetAllModal').style.display = 'none';
  });
  document.getElementById('libResetAllConfirmBtn').addEventListener('click', () => {
    _executeResetAll();
    if (_currentDoc) _renderReader(0);
    document.getElementById('libResetAllModal').style.display = 'none';
  });
}

function _openResetSingleModal(filename) {
  _pendingResetFile = filename;
  const modal = document.getElementById('libResetSingleModal');
  const txt   = document.getElementById('libResetSingleModalText');
  if (txt) txt.textContent = `"${filename}" belgesindeki okuma ilerlemeniz sıfırlanacaktır.`;
  if (modal) modal.style.display = 'flex';
}

function _openResetAllModal() {
  const modal = document.getElementById('libResetAllModal');
  if (modal) modal.style.display = 'flex';
}

// ── Panel İnşası ──────────────────────────────────────────────────────────────
function _buildLibraryPanel() {
  if (document.getElementById('libraryPanel')) return;

  const main = document.getElementById('main');
  if (!main) return;

  const panel = document.createElement('div');
  panel.id = 'libraryPanel';
  panel.innerHTML = `
    <!-- Liste Görünümü -->
    <div id="libListView">
      <div class="lib-header">
        <h2>📚 Afet & Masal Kütüphanesi</h2>
        <div style="display:flex;align-items:center;gap:0.5rem;">
          <button class="lib-btn-sm lib-btn-reset" id="libResetAllBtn">🗑 Tüm Okumaları Sıfırla</button>
          <span style="font-family:var(--font-mono);font-size:0.625rem;padding:0.25rem 0.625rem;border:1px solid var(--accent-secondary);border-radius:9999px;color:var(--accent-secondary);">⚡ AI Yok (Pil Tasarrufu)</span>
        </div>
      </div>

      <!-- Tab Butonları: Masallar İLK SIRA -->
      <div class="lib-tabs">
        <button class="lib-tab-btn active" data-tab="masal">🧸 Kitaplar & Masallar</button>
        <button class="lib-tab-btn" data-tab="rehber">📑 Afet Rehberleri</button>
        <button class="lib-tab-btn" data-tab="pdf">📄 PDF Dokümanları</button>
        <button class="lib-tab-btn" data-tab="all">📚 Tüm Belgeler</button>
      </div>

      <div id="libFileList"></div>
    </div>

    <!-- Okuyucu Görünümü -->
    <div id="libReaderView">
      <div class="lib-header">
        <button class="lib-btn-sm" id="libBackBtn">← Listeye Dön</button>
        <h2 id="libReaderTitle" style="font-size:0.875rem;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">Belge</h2>
        <div style="display:flex;gap:0.375rem;">
          <button class="lib-btn-sm lib-btn-reset" id="libReaderResetBtn" title="Bu kitabın okumasını sıfırla">↺ Sıfırla</button>
        </div>
      </div>
      <div id="libReaderContent"></div>
      <div id="libReaderNav">
        <button class="lib-nav-btn" id="libPrevBtn">← Önceki Sayfa</button>
        <span id="libPageIndicator" style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted);">Sayfa 1 / 1</span>
        <button class="lib-nav-btn" id="libNextBtn">Sonraki Sayfa →</button>
      </div>
    </div>`;

  main.appendChild(panel);

  // Tab tıklama olayları
  panel.querySelectorAll('.lib-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      panel.querySelectorAll('.lib-tab-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _activeTab = btn.dataset.tab;
      _renderLibraryList();
    });
  });

  document.getElementById('libBackBtn').addEventListener('click', _showLibList);
  document.getElementById('libResetAllBtn').addEventListener('click', _openResetAllModal);
  document.getElementById('libReaderResetBtn').addEventListener('click', () => {
    if (_currentDoc) _openResetSingleModal(_currentDoc.name);
  });

  document.getElementById('libPrevBtn').addEventListener('click', () => _navigatePage(-1));
  document.getElementById('libNextBtn').addEventListener('click', () => _navigatePage(1));
}

// ── Liste Renderer ────────────────────────────────────────────────────────────
function _renderLibraryList() {
  const list = document.getElementById('libFileList');
  if (!list) return;

  // Tab filtresi
  let filtered = _libFiles;
  if (_activeTab === 'masal') filtered = _libFiles.filter(f => f.category === 'masal');
  else if (_activeTab === 'rehber') filtered = _libFiles.filter(f => f.category === 'rehber');
  else if (_activeTab === 'pdf') filtered = _libFiles.filter(f => f.type === 'pdf');

  if (filtered.length === 0) {
    const tabName = _activeTab === 'masal' ? 'Kitaplar & Masallar' : (_activeTab === 'rehber' ? 'Afet Rehberleri' : 'PDF Dokümanları');
    list.innerHTML = `
      <div style="text-align:center;padding:3rem 1rem;color:var(--text-muted);font-family:var(--font-mono);font-size:0.8125rem;">
        <div style="font-size:2.5rem;margin-bottom:0.5rem;">📭</div>
        <p style="font-weight:700;color:var(--text-secondary);">${tabName} kategorisinde henüz dosya yok.</p>
        <p style="margin-top:0.375rem;font-size:0.75rem;">
          Masallarınızı <code>data/stories/</code> veya <code>data/books/</code> klasörüne ekleyebilirsiniz.
        </p>
      </div>`;
    return;
  }

  list.innerHTML = '';
  filtered.forEach(file => {
    const prog    = _libProgress[file.name];
    const pct     = prog ? prog.pct : 0;
    const dateStr = prog && prog.lastRead ? ` · Son erişim: ${_formatTurkishDate(prog.lastRead)}` : '';
    const pageTx  = prog ? `Sayfa ${prog.chunkIndex + 1} / ${prog.total} (%${pct} okundu)${dateStr}` : 'Henüz okunmadı';
    const icon    = file.category === 'masal' ? '🧸' : (file.type === 'pdf' ? '📄' : '📑');

    const card = document.createElement('div');
    card.className = 'lib-file-card';
    card.innerHTML = `
      <span class="lib-file-icon">${icon}</span>
      <div class="lib-file-info">
        <div class="lib-file-title">${_escHtml(file.name)}</div>
        <div class="lib-file-meta">
          <span class="lib-badge ${file.category}">${file.category}</span>
          <span>${pageTx}</span>
        </div>
        ${prog ? `<div class="lib-progress-wrap"><div class="lib-progress-fill" style="width:${pct}%"></div></div>` : ''}
      </div>
      <div class="lib-card-actions">
        <button class="lib-btn-sm lib-open-btn">Oku</button>
        ${prog ? `<button class="lib-btn-sm lib-btn-reset lib-card-reset-btn" title="Okuma geçmişini sıfırla">↺</button>` : ''}
      </div>`;

    card.querySelector('.lib-file-info').addEventListener('click', () => {
      _fetchAndReadFile(file.name, file.category, file.type);
    });
    card.querySelector('.lib-open-btn').addEventListener('click', () => {
      _fetchAndReadFile(file.name, file.category, file.type);
    });
    const resetBtn = card.querySelector('.lib-card-reset-btn');
    if (resetBtn) {
      resetBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        _openResetSingleModal(file.name);
      });
    }

    list.appendChild(card);
  });
}

// ── Okuyucu Renderer ──────────────────────────────────────────────────────────
function _renderReaderLoading(filename) {
  _showLibReader();
  const content = document.getElementById('libReaderContent');
  const title   = document.getElementById('libReaderTitle');
  if (title) title.textContent = filename;
  if (content) {
    content.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;height:100%;flex-direction:column;gap:1rem;color:var(--text-muted);font-family:var(--font-mono);">
        <div style="font-size:2rem;">⏳</div>
        <p>Belge yükleniyor...</p>
        <p style="font-size:0.75rem;">${_escHtml(filename)}</p>
      </div>`;
  }
  document.getElementById('libPrevBtn').disabled = true;
  document.getElementById('libNextBtn').disabled = true;
}

function _renderReaderError(filename, msg) {
  const content = document.getElementById('libReaderContent');
  if (content) {
    content.innerHTML = `
      <div style="color:var(--accent-red);font-family:var(--font-mono);padding:1.5rem;">
        ⚠️ Belge okunamadı: ${_escHtml(msg)}<br>
        <span style="font-size:0.75rem;color:var(--text-muted);">${_escHtml(filename)}</span>
      </div>`;
  }
}

function _renderReader(pageIdx) {
  if (!_currentDoc) return;

  const { name, chunks } = _currentDoc;
  const total   = chunks.length;
  const safeIdx = Math.max(0, Math.min(pageIdx, total - 1));

  _saveProgress(name, safeIdx, total);
  _currentDoc._currentPage = safeIdx;

  const prog    = _libProgress[name];
  const pct     = prog ? prog.pct : 100;
  const title   = document.getElementById('libReaderTitle');
  const content = document.getElementById('libReaderContent');
  const pageInd = document.getElementById('libPageIndicator');
  const prevBtn = document.getElementById('libPrevBtn');
  const nextBtn = document.getElementById('libNextBtn');

  if (title)   title.textContent = `${name} (%${pct} okundu)`;
  if (content) content.textContent = chunks[safeIdx];
  if (pageInd) pageInd.textContent = `Sayfa ${safeIdx + 1} / ${total} (%${pct})`;

  if (prevBtn) prevBtn.disabled = (safeIdx === 0);
  if (nextBtn) nextBtn.disabled = (safeIdx === total - 1);

  if (content) content.scrollTop = 0;
}

function _navigatePage(delta) {
  if (!_currentDoc) return;
  const cur = _currentDoc._currentPage || 0;
  _renderReader(cur + delta);
}

function _showLibList() {
  const listView   = document.getElementById('libListView');
  const readerView = document.getElementById('libReaderView');
  if (listView)   listView.style.display   = 'flex';
  if (readerView) readerView.style.display = 'none';
  _currentDoc = null;
  _renderLibraryList();
}

function _showLibReader() {
  const listView   = document.getElementById('libListView');
  const readerView = document.getElementById('libReaderView');
  if (listView)   listView.style.display   = 'none';
  if (readerView) readerView.style.display = 'flex';
}

function _escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Dışarıdan Çağrılabilir API ────────────────────────────────────────────────
function showLibraryPanel() {
  _injectLibraryStyles();
  _buildLibraryInPageModals();

  const hideable = ['chatArea', 'triyajPanel', 'inventoryPanel', 'childModePanel', 'loglarPanel'];
  hideable.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });

  const libPanel = document.getElementById('libraryPanel');
  if (libPanel) {
    libPanel.style.display = 'flex';
    _showLibList();
    _fetchFileList();
  }
}

function hideLibraryPanel() {
  const libPanel = document.getElementById('libraryPanel');
  if (libPanel) libPanel.style.display = 'none';
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  _injectLibraryStyles();
  _buildLibraryPanel();
  _buildLibraryInPageModals();
  _loadProgress();

  const navLib = document.getElementById('nav-kutuphane');
  if (navLib) {
    navLib.addEventListener('click', () => {
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      navLib.classList.add('active');
      showLibraryPanel();
    });
  }
});
