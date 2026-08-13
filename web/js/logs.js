/**
 * logs.js — Sistem Günlükleri (Live Terminal System Log Viewer)
 *
 * Özellikler:
 *  - FastAPI sunucusu ve RAG telemetrisinden canlı log çekme (GET /api/logs)
 *  - Renk kodlamalı terminal ekranı (INFO: Yeşil/Cyan, WARN: Sarı, ERROR: Kırmızı)
 *  - Canlı arama ve seviye bazlı filtreleme (Tümü, INFO, WARN, ERROR)
 *  - Günlükleri panoya kopyalama ve API üzerinden temizleme
 *  - Panel aktifken 2 saniyede bir otomatik canlı yenileme
 */

'use strict';

let _logsPollInterval = null;
let _logsData = [];
let _activeLevelFilter = 'ALL';
let _activeSearchQuery = '';

function _injectLogsStyles() {
  if (document.getElementById('logs-styles')) return;
  const style = document.createElement('style');
  style.id = 'logs-styles';
  style.textContent = `
    .log-line {
      font-family: var(--font-mono);
      font-size: 0.75rem;
      line-height: 1.5;
      padding: 0.25rem 0.5rem;
      border-radius: 0.25rem;
      display: flex;
      gap: 0.75rem;
      align-items: flex-start;
      word-break: break-all;
    }
    .log-line:hover {
      background: var(--bg-card-high);
    }
    .log-badge-info {
      color: var(--accent-secondary);
      font-weight: 700;
      flex-shrink: 0;
    }
    .log-badge-warn {
      color: var(--accent-amber);
      font-weight: 700;
      flex-shrink: 0;
    }
    .log-badge-error {
      color: var(--accent-red);
      font-weight: 700;
      flex-shrink: 0;
    }
    .log-badge-debug {
      color: var(--accent-tertiary);
      font-weight: 700;
      flex-shrink: 0;
    }
    .log-filter-btn {
      padding: 0.25rem 0.75rem;
      border: 1px solid var(--border-card);
      border-radius: 0.375rem;
      background: var(--bg-card);
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 0.75rem;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .log-filter-btn.active {
      border-color: var(--accent-primary);
      background: var(--bg-card-high);
      color: var(--accent-primary);
      font-weight: 600;
    }
  `;
  document.head.appendChild(style);
}

function _buildLogsPanelHTML() {
  const panel = document.getElementById('loglarPanel');
  if (!panel) return;
  if (panel.innerHTML.trim().length > 0) return;

  panel.innerHTML = `
    <!-- Header -->
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;padding-bottom:0.75rem;border-bottom:1px solid var(--border-main);">
      <div style="display:flex;align-items:center;gap:0.75rem;">
        <div style="width:2.5rem;height:2.5rem;border-radius:var(--rounded-card);background:var(--bg-card);display:flex;align-items:center;justify-content:center;border:1px solid var(--border-card);">
          <span class="material-symbols-outlined" style="color:var(--accent-primary);font-size:22px;">terminal</span>
        </div>
        <div>
          <h2 style="font-family:var(--font-sans);font-size:1rem;font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:0.5rem;">
            📜 Sistem Günlükleri & Konsol
          </h2>
          <p style="font-family:var(--font-mono);font-size:0.6875rem;color:var(--text-muted);margin-top:0.125rem;">
            FastAPI Web sunucusu, RAG arama ve LLM çıkarım olaylarının canlı telemetri günlüğü.
          </p>
        </div>
      </div>
      <div style="display:flex;gap:0.5rem;">
        <button id="logsCopyBtn" class="log-filter-btn" title="Günlükleri Panoya Kopyala">
          📋 Kopyala
        </button>
        <button id="logsClearBtn" class="log-filter-btn" style="color:var(--accent-red);" title="Günlükleri Temizle">
          🗑 Temizle
        </button>
        <button id="logsRefreshBtn" class="log-filter-btn" title="Şimdi Yenile">
          🔄 Yenile
        </button>
      </div>
    </div>

    <!-- Filtreler ve Arama BARI -->
    <div style="display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:0.75rem;margin-bottom:0.875rem;">
      <div style="display:flex;gap:0.375rem;" id="logFilterContainer">
        <button class="log-filter-btn active" data-level="ALL">HEPSİ</button>
        <button class="log-filter-btn" data-level="INFO">INFO</button>
        <button class="log-filter-btn" data-level="WARNING">WARN</button>
        <button class="log-filter-btn" data-level="ERROR">ERROR</button>
      </div>
      <div style="flex:1;max-width:20rem;display:flex;align-items:center;background:var(--bg-card);border:1px solid var(--border-card);border-radius:0.375rem;padding:0 0.5rem;">
        <span class="material-symbols-outlined" style="color:var(--text-muted);font-size:16px;">search</span>
        <input type="text" id="logsSearchInput" placeholder="Loglarda ara..." autocomplete="off" style="width:100%;background:transparent;border:none;outline:none;padding:0.375rem 0.5rem;font-family:var(--font-mono);font-size:0.75rem;color:var(--text-primary);">
      </div>
    </div>

    <!-- Terminal Ekranı -->
    <div id="logsTerminalBox" style="flex:1;background:var(--bg-canvas);border:1px solid var(--border-card);border-radius:var(--rounded-card);padding:0.75rem;overflow-y:auto;font-family:var(--font-mono);font-size:0.75rem;display:flex;flex-direction:column;gap:0.25rem;min-height:300px;">
      <div style="color:var(--text-muted);">&gt; Günlük yükleniyor...</div>
    </div>
  `;

  _bindLogsEvents();
}

function _bindLogsEvents() {
  // Filtre butonları
  document.querySelectorAll('#logFilterContainer .log-filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#logFilterContainer .log-filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _activeLevelFilter = btn.dataset.level;
      _renderLogs();
    });
  });

  // Arama
  const searchInput = document.getElementById('logsSearchInput');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      _activeSearchQuery = e.target.value.toLowerCase().trim();
      _renderLogs();
    });
  }

  // Yenile
  const refreshBtn = document.getElementById('logsRefreshBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', _fetchLogs);
  }

  // Kopyala
  const copyBtn = document.getElementById('logsCopyBtn');
  if (copyBtn) {
    copyBtn.addEventListener('click', () => {
      const text = _logsData.map(l => `[${l.timestamp}] [${l.level}] ${l.message}`).join('\n');
      navigator.clipboard.writeText(text).then(() => {
        copyBtn.textContent = '✅ Kopyalandı!';
        setTimeout(() => copyBtn.textContent = '📋 Kopyala', 2000);
      });
    });
  }

  // Temizle
  const clearBtn = document.getElementById('logsClearBtn');
  if (clearBtn) {
    clearBtn.addEventListener('click', async () => {
      try {
        await fetch('/api/logs', { method: 'DELETE' });
        _logsData = [];
        _renderLogs();
      } catch (e) {}
    });
  }
}

async function _fetchLogs() {
  try {
    const res = await fetch('/api/logs');
    if (!res.ok) return;
    const data = await res.json();
    _logsData = data.logs || [];
    _renderLogs();
  } catch (e) {}
}

function _renderLogs() {
  const terminal = document.getElementById('logsTerminalBox');
  if (!terminal) return;

  let filtered = _logsData;

  if (_activeLevelFilter !== 'ALL') {
    filtered = filtered.filter(l => (l.level || '').toUpperCase() === _activeLevelFilter);
  }

  if (_activeSearchQuery) {
    filtered = filtered.filter(l => 
      (l.message || '').toLowerCase().includes(_activeSearchQuery) ||
      (l.logger || '').toLowerCase().includes(_activeSearchQuery) ||
      (l.timestamp || '').includes(_activeSearchQuery)
    );
  }

  if (filtered.length === 0) {
    terminal.innerHTML = `<div style="color:var(--text-muted);padding:1rem 0;text-align:center;">Hiç kayıt bulunamadı.</div>`;
    return;
  }

  const html = filtered.map(l => {
    const lvl = (l.level || 'INFO').toUpperCase();
    let badgeClass = 'log-badge-info';
    if (lvl.includes('WARN')) badgeClass = 'log-badge-warn';
    else if (lvl.includes('ERR')) badgeClass = 'log-badge-error';
    else if (lvl.includes('DEBUG')) badgeClass = 'log-badge-debug';

    const safeMsg = String(l.message || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    return `
      <div class="log-line">
        <span style="color:var(--text-muted);flex-shrink:0;">[${l.timestamp || '00:00:00'}]</span>
        <span class="${badgeClass}">[${lvl}]</span>
        <span style="color:var(--text-primary);">${safeMsg}</span>
      </div>
    `;
  }).join('');

  terminal.innerHTML = html;
  terminal.scrollTop = terminal.scrollHeight;
}

// ── Dışarıdan Çağrılabilir API ────────────────────────────────────────────────
function showLogsPanel() {
  _injectLogsStyles();
  _buildLogsPanelHTML();

  const hideable = ['chatArea', 'triyajPanel', 'inventoryPanel', 'libraryPanel', 'childModePanel'];
  hideable.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });

  const panel = document.getElementById('loglarPanel');
  if (panel) {
    panel.style.display = 'flex';
    _fetchLogs();
  }

  if (!_logsPollInterval) {
    _logsPollInterval = setInterval(_fetchLogs, 2000);
  }
}

function hideLogsPanel() {
  if (_logsPollInterval) {
    clearInterval(_logsPollInterval);
    _logsPollInterval = null;
  }
  const panel = document.getElementById('loglarPanel');
  if (panel) panel.style.display = 'none';
}
