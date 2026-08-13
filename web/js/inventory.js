/**
 * inventory.js — Görsel Envanter Yönetimi (Kare Kartlar, In-Page Modallar, Canlı Telemetri Logu)
 *
 * Yenilikler:
 *  1. Buton Sırası: [ − (Çıkart) ]  [ 🗑 (Sil) ]  [ + (Ekle) ]
 *  2. Kare Kart UI: 140x140px derli toplu kare kartlar
 *  3. In-Page Onay Modalları (Sitede Dahili Modal):
 *      - Tekli Silme Onay Modalı (#invDeleteModal)
 *      - Tümünü Temizle Onay Modalı (#invClearModal)
 *  4. Sağ Sidebar Envanter Enjeksiyonu Canlı Logu (#ctxInventoryInjected):
 *      - Her ekleme/çıkarma/silme işleminde zaman damgalı log düşer
 *  5. Hızlı Tepki Veren Inputlar (Kasma yapmayan düz font & sıfır ağır CSS efekti)
 */

'use strict';

// ── Sabitler & İkonlar ────────────────────────────────────────────────────────
const INV_ICONS = {
  meyveSuyu: '🍊', 'meyve suyu': '🍊', meyve: '🍎',
  su: '💧', suyu: '💧', içmeSuyu: '💧',
  ekmek: '🍞', bisküvi: '🍪', biskuvi: '🍪', buskuvi: '🍪', konserve: '🥫',
  ilaç: '💊', ilac: '💊', aspirin: '💊', hap: '💊',
  ilkYardim: '🩹', 'yara bandı': '🩹', 'yara bandi': '🩹', 'ilk yardım': '🩹',
  battaniye: '🛏️', çadır: '⛺', cadir: '⛺',
  fener: '🔦', 'el feneri': '🔦', pil: '🔋',
  kibrit: '🔥', mum: '🕯️',
  telsiz: '📻', radyo: '📻',
  çakmak: '🪔', cakmak: '🪔',
  süt: '🥛', sut: '🥛', çikolata: '🍫', cikolata: '🍫',
  peynir: '🧀', zeytin: '🫒',
};

const DEFAULT_ICON = '📦';

// Envanter işlem logları (Sağ sidebar için)
const _inventoryActionLogs = [];

function _icon(name) {
  const low = String(name || '').toLowerCase().replace(/\s+/g, '');
  for (const [k, v] of Object.entries(INV_ICONS)) {
    if (low.includes(k.toLowerCase().replace(/\s+/g, ''))) return v;
  }
  return DEFAULT_ICON;
}

function _parseQty(str) {
  const m = String(str || '').match(/^(\d+[\.,]?\d*)\s*(.*)?$/);
  if (!m) return { num: 1, unit: 'adet' };
  return { num: parseFloat(m[1].replace(',', '.')), unit: (m[2] || 'adet').trim() };
}

// ── Durum ─────────────────────────────────────────────────────────────────────
let _invState      = {}; // { itemKey: "5 litre" }
let _pendingDeleteItem = null;

// ── Sağ Sidebar Envanter Logu Güncelleyici ───────────────────────────────────
function logInventoryAction(actionText) {
  const timeStr = new Date().toLocaleTimeString('tr-TR');
  _inventoryActionLogs.unshift(`[${timeStr}] ${actionText}`);
  if (_inventoryActionLogs.length > 8) _inventoryActionLogs.pop();

  const ctxInjected = document.getElementById('ctxInventoryInjected');
  if (ctxInjected) {
    ctxInjected.innerHTML = _inventoryActionLogs.map(log =>
      `<div style="font-family:var(--font-mono);font-size:0.6875rem;color:var(--accent-secondary);margin-bottom:0.25rem;">📦 ${log}</div>`
    ).join('');
  }
}

// ── API Çağrıları ─────────────────────────────────────────────────────────────
async function _fetchInventory() {
  try {
    const res = await fetch('/api/inventory');
    if (!res.ok) return;
    _invState = await res.json();
    renderInventoryCards();
  } catch (e) {
    console.warn('[inventory] GET /api/inventory hata:', e);
  }
}

async function _postInventory(item, action, amount, customLogText) {
  try {
    const res = await fetch('/api/inventory', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item, action, amount }),
    });
    if (!res.ok) return;
    _invState = await res.json();
    renderInventoryCards();

    if (customLogText) {
      logInventoryAction(customLogText);
    } else if (action === 'delete') {
      logInventoryAction(`"${item}" envanterden çıkarıldı.`);
    } else {
      logInventoryAction(`"${item}" güncellendi: ${amount}`);
    }
  } catch (e) {
    console.warn('[inventory] POST /api/inventory hata:', e);
  }
}

async function _clearAllInventoryAPI() {
  try {
    const res = await fetch('/api/inventory', { method: 'DELETE' });
    if (!res.ok) return;
    _invState = {};
    renderInventoryCards();
    logInventoryAction('Tüm envanter sıfırlandı ve temizlendi.');
  } catch (e) {
    console.warn('[inventory] DELETE /api/inventory hata:', e);
  }
}

// ── Kart Renderer (140x140px Kare Kartlar) ──────────────────────────────────
function renderInventoryCards() {
  const container = document.getElementById('inventoryCards');
  if (!container) return;

  container.innerHTML = '';
  const entries = Object.entries(_invState);

  if (entries.length === 0) {
    container.innerHTML = `
      <div style="width:100%;text-align:center;padding:3rem 1rem;color:var(--text-muted);font-family:var(--font-mono);font-size:0.8125rem;">
        <div style="font-size:2.5rem;margin-bottom:0.5rem;">📭</div>
        <p style="font-weight:700;color:var(--text-secondary);">Envanteriniz boş.</p>
        <p style="font-size:0.75rem;margin-top:0.375rem;">
          "+ Malzeme Ekle" butonunu kullanın veya sohbetten<br><code>envanter ekle su 5 litre</code> yazın.
        </p>
      </div>`;
    return;
  }

  entries.forEach(([key, valStr]) => {
    const { num, unit } = _parseQty(valStr);
    const icon = _icon(key);
    const card = document.createElement('div');
    card.className = 'inv-card';
    card.innerHTML = `
      <div class="inv-card-icon">${icon}</div>
      <div class="inv-card-name" title="${_escHtml(key)}">${_escHtml(key)}</div>
      <div class="inv-card-qty">${_escHtml(valStr)}</div>
      <!-- Sıralama: [ - (Azalt) ]  [ 🗑 (Sil) ]  [ + (Artır) ] -->
      <div class="inv-card-controls">
        <button class="inv-btn inv-btn-minus" data-item="${_escHtml(key)}" data-unit="${_escHtml(unit)}" title="Azalt">−</button>
        <button class="inv-btn inv-btn-del"   data-item="${_escHtml(key)}" title="Tümünü Sil">🗑</button>
        <button class="inv-btn inv-btn-plus"  data-item="${_escHtml(key)}" data-unit="${_escHtml(unit)}" title="Artır">+</button>
      </div>`;
    container.appendChild(card);
  });

  // Event Listeners
  container.querySelectorAll('.inv-btn-plus').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = btn.dataset.item;
      const unit = btn.dataset.unit || 'adet';
      _postInventory(item, 'add', `1 ${unit}`, `+1 ${unit} ${item} eklendi.`);
    });
  });

  container.querySelectorAll('.inv-btn-minus').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = btn.dataset.item;
      const unit = btn.dataset.unit || 'adet';
      const cur  = _invState[item];
      if (cur) {
        const { num } = _parseQty(cur);
        if (num <= 1) {
          _openSingleDeleteModal(item);
        } else {
          _postInventory(item, 'delete', `1 ${unit}`, `-1 ${unit} ${item} çıkarıldı.`);
        }
      }
    });
  });

  container.querySelectorAll('.inv-btn-del').forEach(btn => {
    btn.addEventListener('click', () => {
      _openSingleDeleteModal(btn.dataset.item);
    });
  });
}

// ── In-Page Modallar (Tekli Silme, Tümünü Sıfırlama, Yeni Malzeme Ekle) ──────
function _buildInventoryInPageModals() {
  if (document.getElementById('invModalsContainer')) return;

  const container = document.createElement('div');
  container.id = 'invModalsContainer';
  container.innerHTML = `
    <!-- 1. Malzeme Ekle Modalı -->
    <div id="invAddModal" class="inv-modal-overlay">
      <div class="inv-modal-box">
        <div class="inv-modal-header">
          <h3>➕ Malzeme Ekle</h3>
          <button class="inv-modal-close-x" id="invAddCloseX">&times;</button>
        </div>
        <div style="display:flex;flex-direction:column;gap:0.75rem;">
          <div style="display:flex;flex-direction:column;gap:0.375rem;">
            <label style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted);">Malzeme Adı</label>
            <input id="invAddName" type="text" placeholder="ör: su, bisküvi, pil..." class="inv-input-plain" autocomplete="off">
          </div>
          <div style="display:flex;gap:0.75rem;">
            <div style="flex:1;display:flex;flex-direction:column;gap:0.375rem;">
              <label style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted);">Miktar</label>
              <input id="invAddQty" type="number" min="1" value="1" class="inv-input-plain">
            </div>
            <div style="flex:1;display:flex;flex-direction:column;gap:0.375rem;">
              <label style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted);">Birim</label>
              <select id="invAddUnit" class="inv-input-plain">
                <option>adet</option>
                <option>litre</option>
                <option>kg</option>
                <option>paket</option>
                <option>kutu</option>
                <option>tane</option>
              </select>
            </div>
          </div>
        </div>
        <div class="inv-modal-footer">
          <button id="invAddCancelBtn" class="inv-modal-btn-cancel">İptal</button>
          <button id="invAddConfirmBtn" class="inv-modal-btn-confirm">Ekle</button>
        </div>
      </div>
    </div>

    <!-- 2. Tekli Silme Onay Modalı -->
    <div id="invDeleteModal" class="inv-modal-overlay">
      <div class="inv-modal-box">
        <div class="inv-modal-header" style="color:var(--accent-red);">
          <span style="font-size:1.25rem;">⚠️</span>
          <h3>Malzemeyi Sil</h3>
        </div>
        <p id="invDeleteModalText" style="font-family:var(--font-mono);font-size:0.8125rem;color:var(--text-secondary);line-height:1.5;">
          Bu malzemeyi envanterinizden silmek istediğinize emin misiniz?
        </p>
        <div class="inv-modal-footer">
          <button id="invDeleteCancelBtn" class="inv-modal-btn-cancel">İptal</button>
          <button id="invDeleteConfirmBtn" class="inv-modal-btn-danger">Evet, Sil</button>
        </div>
      </div>
    </div>

    <!-- 3. Tümünü Temizle Onay Modalı -->
    <div id="invClearModal" class="inv-modal-overlay">
      <div class="inv-modal-box">
        <div class="inv-modal-header" style="color:var(--accent-red);">
          <span style="font-size:1.25rem;">⚠️</span>
          <h3>Tüm Envanteri Sıfırla</h3>
        </div>
        <p style="font-family:var(--font-mono);font-size:0.8125rem;color:var(--text-secondary);line-height:1.5;">
          Tüm kaydedilmiş malzemeleriniz silinecektir. Bu işlem geri alınamaz. Onaylıyor musunuz?
        </p>
        <div class="inv-modal-footer">
          <button id="invClearCancelBtn" class="inv-modal-btn-cancel">İptal</button>
          <button id="invClearConfirmBtn" class="inv-modal-btn-danger">Tümünü Sil</button>
        </div>
      </div>
    </div>`;

  document.body.appendChild(container);

  // Ekle Modalı Handlers
  document.getElementById('invAddCloseX').addEventListener('click', _closeAddModal);
  document.getElementById('invAddCancelBtn').addEventListener('click', _closeAddModal);
  document.getElementById('invAddConfirmBtn').addEventListener('click', _confirmAddModal);

  // Tekli Silme Modalı Handlers
  document.getElementById('invDeleteCancelBtn').addEventListener('click', () => {
    document.getElementById('invDeleteModal').style.display = 'none';
    _pendingDeleteItem = null;
  });
  document.getElementById('invDeleteConfirmBtn').addEventListener('click', () => {
    if (_pendingDeleteItem) {
      _postInventory(_pendingDeleteItem, 'delete', 'ALL', `"${_pendingDeleteItem}" tamamen silindi.`);
      _pendingDeleteItem = null;
    }
    document.getElementById('invDeleteModal').style.display = 'none';
  });

  // Tümünü Sıfırlama Modalı Handlers
  document.getElementById('invClearCancelBtn').addEventListener('click', () => {
    document.getElementById('invClearModal').style.display = 'none';
  });
  document.getElementById('invClearConfirmBtn').addEventListener('click', () => {
    _clearAllInventoryAPI();
    document.getElementById('invClearModal').style.display = 'none';
  });
}

function _openSingleDeleteModal(item) {
  _buildInventoryInPageModals();
  _pendingDeleteItem = item;
  const modal = document.getElementById('invDeleteModal');
  const txt   = document.getElementById('invDeleteModalText');
  if (txt) txt.textContent = `"${item}" malzemesini envanterden tamamen silmek istediğinize emin misiniz?`;
  if (modal) modal.style.display = 'flex';
}

function _openClearAllModal() {
  _buildInventoryInPageModals();
  const modal = document.getElementById('invClearModal');
  if (modal) modal.style.display = 'flex';
}

function _openAddModal() {
  _buildInventoryInPageModals();
  const modal = document.getElementById('invAddModal');
  if (modal) {
    modal.style.display = 'flex';
    const input = document.getElementById('invAddName');
    if (input) {
      input.value = '';
      setTimeout(() => input.focus(), 30);
    }
  }
}

function _closeAddModal() {
  const modal = document.getElementById('invAddModal');
  if (modal) modal.style.display = 'none';
}

function _confirmAddModal() {
  const name = document.getElementById('invAddName').value.trim().toLowerCase();
  const qty  = parseFloat(document.getElementById('invAddQty').value) || 1;
  const unit = document.getElementById('invAddUnit').value;
  if (!name) return;
  _postInventory(name, 'add', `${qty} ${unit}`, `+${qty} ${unit} ${name} eklendi.`);
  _closeAddModal();
}

// ── CSS Stilleri Enjeksiyonu ──────────────────────────────────────────────────
function _injectInventoryStyles() {
  if (document.getElementById('inv-styles')) return;
  const style = document.createElement('style');
  style.id = 'inv-styles';
  style.textContent = `
    #inventoryPanel {
      display: none;
      flex-direction: column;
      flex: 1;
      width: 100%;
      height: 100%;
      padding: 1.25rem;
      overflow-y: auto;
    }
    #inventoryPanel.active { display: flex; }

    .inv-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 1.25rem;
      padding-bottom: 0.875rem;
      border-bottom: 1px solid var(--border-main);
    }
    .inv-header h2 {
      font-family: var(--font-sans);
      font-size: 1rem;
      font-weight: 700;
      color: var(--text-primary);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .inv-header-actions {
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .inv-add-btn {
      padding: 0.375rem 0.875rem;
      background: var(--accent-primary);
      color: #fff;
      border: none;
      border-radius: 0.5rem;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      font-weight: 600;
      cursor: pointer;
    }
    .inv-add-btn:hover { opacity: 0.88; }

    .inv-clear-all-btn {
      padding: 0.375rem 0.75rem;
      background: transparent;
      color: var(--text-secondary);
      border: 1px solid var(--border-card);
      border-radius: 0.5rem;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      cursor: pointer;
    }
    .inv-clear-all-btn:hover { border-color: var(--accent-red); color: var(--accent-red); }

    /* KARE KARTLAR UI (140x140px) */
    #inventoryCards {
      display: flex;
      flex-wrap: wrap;
      gap: 1rem;
      align-items: flex-start;
      padding: 0.25rem 0;
    }

    .inv-card {
      width: 140px;
      height: 140px;
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: var(--rounded-card);
      padding: 0.625rem;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: space-between;
      box-sizing: border-box;
      transition: border-color 0.15s, box-shadow 0.15s;
    }
    .inv-card:hover {
      border-color: var(--accent-primary);
      box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent-primary) 15%, transparent);
    }
    .inv-card-icon { font-size: 1.625rem; line-height: 1; }
    .inv-card-name {
      font-family: var(--font-mono);
      font-size: 0.6875rem;
      color: var(--text-secondary);
      text-align: center;
      text-transform: capitalize;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .inv-card-qty {
      font-family: var(--font-sans);
      font-size: 0.875rem;
      font-weight: 700;
      color: var(--text-primary);
    }
    /* Controls: [ - (Azalt) ] [ 🗑 (Sil) ] [ + (Artır) ] */
    .inv-card-controls {
      display: flex;
      gap: 0.25rem;
      width: 100%;
      justify-content: center;
    }
    .inv-btn {
      flex: 1;
      height: 1.625rem;
      border: 1px solid var(--border-card);
      border-radius: 0.375rem;
      background: var(--bg-canvas);
      color: var(--text-secondary);
      font-size: 0.75rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
    }
    .inv-btn-plus:hover  { background: var(--accent-primary); color: #fff; border-color: var(--accent-primary); }
    .inv-btn-minus:hover { background: var(--bg-card); color: var(--text-primary); border-color: var(--accent-primary); }
    .inv-btn-del:hover   { background: var(--accent-red); color: #fff; border-color: var(--accent-red); }

    /* In-Page Modal Styles */
    .inv-modal-overlay {
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
    .inv-modal-box {
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
    .inv-modal-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
    }
    .inv-modal-header h3 {
      font-family: var(--font-sans);
      font-size: 0.9375rem;
      font-weight: 700;
      color: var(--text-primary);
    }
    .inv-modal-close-x {
      background: none;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 1.25rem;
    }
    .inv-modal-footer {
      display: flex;
      justify-content: flex-end;
      gap: 0.625rem;
      margin-top: 0.25rem;
    }
    .inv-modal-btn-cancel {
      padding: 0.375rem 0.875rem;
      border: 1px solid var(--border-card);
      border-radius: 0.375rem;
      background: transparent;
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 0.75rem;
      cursor: pointer;
    }
    .inv-modal-btn-confirm {
      padding: 0.375rem 0.875rem;
      border: none;
      border-radius: 0.375rem;
      background: var(--accent-primary);
      color: #fff;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      font-weight: 600;
      cursor: pointer;
    }
    .inv-modal-btn-danger {
      padding: 0.375rem 0.875rem;
      border: none;
      border-radius: 0.375rem;
      background: var(--accent-red);
      color: #fff;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      font-weight: 600;
      cursor: pointer;
    }

    /* Kasma Yapmayan Düz Input Fontu (Item 8 Fix) */
    .inv-input-plain {
      padding: 0.5rem 0.75rem;
      border: 1px solid var(--border-card);
      border-radius: 0.375rem;
      background: var(--bg-canvas);
      color: var(--text-primary);
      font-family: var(--font-sans);
      font-size: 0.875rem;
      outline: none;
      transition: border-color 0.12s;
    }
    .inv-input-plain:focus {
      border-color: var(--accent-primary);
    }
  `;
  document.head.appendChild(style);
}

// ── Panel İnşası ──────────────────────────────────────────────────────────────
function _buildInventoryPanel() {
  const addBtn = document.getElementById('invAddBtn');
  const clearBtn = document.getElementById('invClearAllBtn');
  if (addBtn && !addBtn.dataset.bound) {
    addBtn.dataset.bound = 'true';
    addBtn.addEventListener('click', _openAddModal);
  }
  if (clearBtn && !clearBtn.dataset.bound) {
    clearBtn.dataset.bound = 'true';
    clearBtn.addEventListener('click', _openClearAllModal);
  }
}

function _escHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Dışarıdan Çağrılabilir API ────────────────────────────────────────────────
function showInventoryPanel() {
  _injectInventoryStyles();
  _buildInventoryPanel();
  _buildInventoryInPageModals();

  const hideable = ['chatArea', 'triyajPanel', 'libraryPanel', 'childModePanel', 'loglarPanel', 'kutuphanePanel'];
  hideable.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });

  const invPanel = document.getElementById('inventoryPanel');
  if (invPanel) {
    invPanel.style.display = 'flex';
    _fetchInventory();
  }
}

function hideInventoryPanel() {
  const invPanel = document.getElementById('inventoryPanel');
  if (invPanel) invPanel.style.display = 'none';
}

function refreshInventoryIfVisible() {
  const panel = document.getElementById('inventoryPanel');
  if (panel && panel.style.display !== 'none') {
    _fetchInventory();
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
function _initInventoryEvents() {
  _injectInventoryStyles();
  _buildInventoryPanel();
  _buildInventoryInPageModals();

  const navEnv = document.getElementById('nav-envanter');
  if (navEnv) {
    navEnv.addEventListener('click', (e) => {
      e.preventDefault();
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      navEnv.classList.add('active');
      showInventoryPanel();
    });
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initInventoryEvents);
} else {
  _initInventoryEvents();
}
