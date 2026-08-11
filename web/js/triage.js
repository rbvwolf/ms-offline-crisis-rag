/**
 * triage.js — Acil Triyaj Karar Ağacı (START Triage Wizard)
 *
 * Çalışma şekli:
 *  - TAMAMEN offline, SIFIR LLM çağrısı
 *  - START (Simple Triage and Rapid Treatment) algoritması
 *  - 3-4 adımda yaralı kategorisi belirlenir: KIRMIZI / SARI / YEŞİL / SİYAH
 *  - Kategori renkli kart olarak gösterilir, tekrar başlatılabilir
 */

'use strict';

// ── START Triage Karar Ağacı ──────────────────────────────────────────────────
// Her node: { id, question, hint?, options: [{ label, next }] }
// next: node_id veya sonuç objesi { result: "KIRMIZI"|"SARI"|"YEŞİL"|"SİYAH", reason, action }

const TRIAGE_TREE = {
  start: {
    id: 'start',
    question: 'Yaralı yürüyebiliyor mu?',
    hint: 'Hafif ve orta dereceli yürüyebilen yaralıları bir kenara yönlendirin.',
    options: [
      { label: '✅ Evet, yürüyebiliyor', next: 'result_yesil' },
      { label: '❌ Hayır, yürüyemiyor', next: 'breathing' },
    ],
  },

  breathing: {
    id: 'breathing',
    question: 'Solunumu var mı?',
    hint: 'Hava yolunu açın (başı geriye yatırın). 10 saniye gözlemleyin.',
    options: [
      { label: '✅ Evet, nefes alıyor', next: 'resp_rate' },
      { label: '❌ Hayır, nefes almıyor', next: 'airway_open' },
    ],
  },

  airway_open: {
    id: 'airway_open',
    question: 'Hava yolu açıldıktan sonra nefes alıyor mu?',
    hint: 'Başı hafifçe geriye yatırın, ağız-burun kontrolü yapın.',
    options: [
      { label: '✅ Evet, şimdi nefes alıyor', next: 'result_kirmizi_airway' },
      { label: '❌ Hayır, hâlâ nefes almıyor', next: 'result_siyah' },
    ],
  },

  resp_rate: {
    id: 'resp_rate',
    question: 'Solunum hızı nasıl?',
    hint: '10 saniye nefes sayısını sayın ve 6 ile çarpın.',
    options: [
      { label: '🐇 30\'dan fazla (hızlı)', next: 'result_kirmizi' },
      { label: '✅ 10-30 arası (normal)', next: 'perfusion' },
      { label: '🐢 10\'dan az (çok yavaş)', next: 'result_kirmizi' },
    ],
  },

  perfusion: {
    id: 'perfusion',
    question: 'Nabzı veya kapiler dolum süresi nasıl?',
    hint: 'Tırnak yatağına basın, bırakın — pembe dönüş 2 saniyeden uzun sürüyor mu?',
    options: [
      { label: '⚡ 2 saniyeden uzun / nabız yok', next: 'result_kirmizi' },
      { label: '✅ 2 saniyeden kısa / nabız var', next: 'mental' },
    ],
  },

  mental: {
    id: 'mental',
    question: 'Basit komutlara uyuyor mu?',
    hint: 'Gözleri açsın / elini sıksın gibi basit komutlar verin.',
    options: [
      { label: '✅ Evet, uyuyor', next: 'result_sari' },
      { label: '❌ Hayır, uymuyor', next: 'result_kirmizi' },
    ],
  },

  // ── Sonuçlar ────────────────────────────────────────────────────────────────
  result_yesil: {
    result: 'YEŞİL',
    label: '🟢 YEŞİL — Geciktirilebilir',
    color: '#22c55e',
    bg: 'color-mix(in srgb, #22c55e 12%, transparent)',
    border: '#16a34a',
    reason: 'Yaralı yürüyebiliyor. Hafif/orta derecede etkilenmiş.',
    actions: [
      'Yaralıyı belirlenen toplanma alanına yönlendirin.',
      'Durumu saatlik yeniden değerlendirin.',
      'Gerekirse hafif yardım sağlayın (sargı, teselli).',
    ],
  },
  result_siyah: {
    result: 'SİYAH',
    label: '⬛ SİYAH — Yaşayamaz',
    color: '#6b7280',
    bg: 'color-mix(in srgb, #6b7280 12%, transparent)',
    border: '#4b5563',
    reason: 'Hava yolu açılmasına rağmen solunum yok. Hayatta kalma ihtimali son derece düşük.',
    actions: [
      'Kıymetli kaynakları diğer hayatta kalabilecek yaralılara yönlendirin.',
      'Yaralıyı rahat bir pozisyona alın.',
      'Mümkünse etiketleyin ve kayıt altına alın.',
    ],
  },
  result_kirmizi: {
    result: 'KIRMIZI',
    label: '🔴 KIRMIZI — Acil Müdahale',
    color: '#ef4444',
    bg: 'color-mix(in srgb, #ef4444 12%, transparent)',
    border: '#dc2626',
    reason: 'Solunum veya dolaşım problemi var. Hemen müdahale gerekiyor.',
    actions: [
      'Hemen müdahale edin: hava yolu, solunum, dolaşım.',
      'Ağır kanamaları kontrol altına alın.',
      'En yakın sağlık ekibine bildirin ve ilk nakledilecekler arasına alın.',
    ],
  },
  result_kirmizi_airway: {
    result: 'KIRMIZI',
    label: '🔴 KIRMIZI — Acil (Hava Yolu Açıldı)',
    color: '#ef4444',
    bg: 'color-mix(in srgb, #ef4444 12%, transparent)',
    border: '#dc2626',
    reason: 'Hava yolu açıldıktan sonra solunum başladı. Hava yolunu korumak için sürekli kontrol şart.',
    actions: [
      'Hava yolunu açık tutun (yan yatış pozisyonu önerilir).',
      'Solunumu 5 dakikada bir kontrol edin.',
      'Hemen tahliyeye dahil edin.',
    ],
  },
  result_sari: {
    result: 'SARI',
    label: '🟡 SARI — Geciktirilebilir (2. Öncelik)',
    color: '#eab308',
    bg: 'color-mix(in srgb, #eab308 12%, transparent)',
    border: '#ca8a04',
    reason: 'Solunum ve dolaşım stabil. Komutlara uyuyor. Acil ama geciktirilebilir.',
    actions: [
      'Kırmızı kategori yaralılar müdahale edildikten sonra müdahale edin.',
      'Yaralıyı izleyin; durumu kötüleşirse Kırmızıya çevirin.',
      'Ağrı kesici veya yatıştırıcı sağlayabilirsiniz.',
    ],
  },
};

// ── Durum ─────────────────────────────────────────────────────────────────────
let _triageHistory = []; // geçilen node id'leri

// ── Stiller ───────────────────────────────────────────────────────────────────
function _injectTriageStyles() {
  if (document.getElementById('triage-styles')) return;
  const style = document.createElement('style');
  style.id = 'triage-styles';
  style.textContent = `
    #triyajPanel {
      display: none;
      flex-direction: column;
      height: 100%;
      overflow: hidden;
    }

    .triage-header {
      padding: 1rem;
      border-bottom: 1px solid var(--border-main);
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .triage-header h2 {
      font-family: var(--font-sans);
      font-size: 1rem;
      font-weight: 700;
      color: var(--text-primary);
      flex: 1;
    }
    .triage-restart-btn {
      padding: 0.25rem 0.75rem;
      border: 1px solid var(--border-card);
      border-radius: 0.375rem;
      background: var(--bg-card);
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 0.75rem;
      cursor: pointer;
    }
    .triage-restart-btn:hover { border-color: var(--accent-primary); color: var(--accent-primary); }

    #triageBody {
      flex: 1;
      overflow-y: auto;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }

    .triage-step-indicator {
      font-family: var(--font-mono);
      font-size: 0.6875rem;
      color: var(--text-muted);
      text-align: center;
    }

    .triage-question-card {
      background: var(--bg-card);
      border: 1px solid var(--border-main);
      border-radius: var(--rounded-card);
      padding: 1.25rem;
    }
    .triage-question-card h3 {
      font-family: var(--font-sans);
      font-size: 1rem;
      font-weight: 700;
      color: var(--text-primary);
      margin-bottom: 0.5rem;
      line-height: 1.4;
    }
    .triage-hint {
      font-family: var(--font-mono);
      font-size: 0.75rem;
      color: var(--text-muted);
      background: var(--bg-canvas);
      border: 1px solid var(--border-card);
      border-radius: 0.375rem;
      padding: 0.5rem 0.75rem;
      margin-bottom: 1rem;
      line-height: 1.5;
    }
    .triage-options {
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }
    .triage-option-btn {
      width: 100%;
      padding: 0.75rem 1rem;
      background: var(--bg-canvas);
      border: 1px solid var(--border-card);
      border-radius: 0.5rem;
      color: var(--text-primary);
      font-family: var(--font-mono);
      font-size: 0.875rem;
      text-align: left;
      cursor: pointer;
      transition: background 0.12s, border-color 0.12s;
    }
    .triage-option-btn:hover {
      background: var(--bg-card);
      border-color: var(--accent-primary);
      color: var(--accent-primary);
    }

    /* Sonuç kartı */
    .triage-result-card {
      border-radius: var(--rounded-card);
      padding: 1.5rem;
      text-align: center;
    }
    .triage-result-emoji { font-size: 3rem; margin-bottom: 0.5rem; }
    .triage-result-label {
      font-family: var(--font-sans);
      font-size: 1.375rem;
      font-weight: 800;
      margin-bottom: 0.75rem;
    }
    .triage-result-reason {
      font-family: var(--font-mono);
      font-size: 0.8rem;
      opacity: 0.85;
      margin-bottom: 1rem;
      line-height: 1.5;
    }
    .triage-result-actions {
      text-align: left;
      background: rgba(0,0,0,0.15);
      border-radius: 0.5rem;
      padding: 0.75rem 1rem;
    }
    .triage-result-actions h4 {
      font-family: var(--font-mono);
      font-size: 0.6875rem;
      opacity: 0.7;
      margin-bottom: 0.5rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .triage-result-actions ul {
      list-style: none;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: 0.375rem;
    }
    .triage-result-actions li {
      font-family: var(--font-mono);
      font-size: 0.8125rem;
      line-height: 1.4;
      display: flex;
      gap: 0.5rem;
    }
    .triage-result-actions li::before { content: '→'; opacity: 0.6; flex-shrink: 0; }

    .triage-history-bar {
      display: flex;
      align-items: center;
      gap: 0.375rem;
      padding: 0.5rem 1.25rem;
      font-family: var(--font-mono);
      font-size: 0.6875rem;
      color: var(--text-muted);
      border-bottom: 1px solid var(--border-card);
      flex-shrink: 0;
      overflow-x: auto;
    }
    .triage-history-step {
      display: flex;
      align-items: center;
      gap: 0.375rem;
      opacity: 0.65;
    }
    .triage-history-step .step-q { color: var(--text-secondary); }
    .triage-history-sep { color: var(--border-card); }
    .triage-new-patient-btn {
      width: 100%;
      padding: 0.875rem;
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: 0.5rem;
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 0.875rem;
      cursor: pointer;
      margin-top: 0.5rem;
      transition: background 0.12s;
    }
    .triage-new-patient-btn:hover { background: var(--bg-canvas); border-color: var(--accent-primary); color: var(--accent-primary); }
  `;
  document.head.appendChild(style);
}

// ── Panel inşası ──────────────────────────────────────────────────────────────
function _buildTriagePanel() {
  if (document.getElementById('triyajPanel')) return;

  const main = document.getElementById('main');
  if (!main) return;

  const panel = document.createElement('div');
  panel.id = 'triyajPanel';
  panel.innerHTML = `
    <div class="triage-header">
      <h2>🚨 Acil Triyaj</h2>
      <button class="triage-restart-btn" id="triageRestartBtn">↺ Yeniden Başlat</button>
    </div>
    <div class="triage-history-bar" id="triageHistoryBar"></div>
    <div id="triageBody"></div>`;

  main.appendChild(panel);

  document.getElementById('triageRestartBtn').addEventListener('click', _startTriage);
}

// ── Triyaj mantığı ────────────────────────────────────────────────────────────
function _startTriage() {
  _triageHistory = [];
  _renderTriageNode('start');
}

function _renderTriageNode(nodeId) {
  const node = TRIAGE_TREE[nodeId];
  if (!node) return;

  const body = document.getElementById('triageBody');
  if (!body) return;
  body.innerHTML = '';

  // Sonuç mu?
  if (node.result) {
    _renderTriageResult(node);
    return;
  }

  // Adım göstergesi
  const stepEl = document.createElement('div');
  stepEl.className = 'triage-step-indicator';
  stepEl.textContent = `Adım ${_triageHistory.length + 1}`;
  body.appendChild(stepEl);

  // Soru kartı
  const card = document.createElement('div');
  card.className = 'triage-question-card';

  let html = `<h3>${_escHtml(node.question)}</h3>`;
  if (node.hint) {
    html += `<div class="triage-hint">💡 ${_escHtml(node.hint)}</div>`;
  }
  html += `<div class="triage-options">`;
  node.options.forEach((opt, i) => {
    html += `<button class="triage-option-btn" data-next="${_escHtml(opt.next)}" data-label="${_escHtml(opt.label)}">${_escHtml(opt.label)}</button>`;
  });
  html += `</div>`;
  card.innerHTML = html;
  body.appendChild(card);

  // Butona tıklanma
  card.querySelectorAll('.triage-option-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _triageHistory.push({ question: node.question, answer: btn.dataset.label });
      _updateHistoryBar();
      _renderTriageNode(btn.dataset.next);
    });
  });

  _updateHistoryBar();
}

function _renderTriageResult(result) {
  const body = document.getElementById('triageBody');
  if (!body) return;
  body.innerHTML = '';

  const card = document.createElement('div');
  card.className = 'triage-result-card';
  card.style.background = result.bg;
  card.style.border = `2px solid ${result.border}`;
  card.style.color  = result.color;

  const actionsHtml = result.actions.map(a => `<li>${_escHtml(a)}</li>`).join('');

  card.innerHTML = `
    <div class="triage-result-label">${result.label}</div>
    <div class="triage-result-reason">${_escHtml(result.reason)}</div>
    <div class="triage-result-actions" style="color:${result.color}">
      <h4>Yapılacaklar</h4>
      <ul>${actionsHtml}</ul>
    </div>`;

  body.appendChild(card);

  const newBtn = document.createElement('button');
  newBtn.className = 'triage-new-patient-btn';
  newBtn.textContent = '➕ Yeni Hasta Değerlendir';
  newBtn.addEventListener('click', _startTriage);
  body.appendChild(newBtn);
}

function _updateHistoryBar() {
  const bar = document.getElementById('triageHistoryBar');
  if (!bar) return;
  if (_triageHistory.length === 0) {
    bar.innerHTML = '<span>Triyaj adımları burada görünecek.</span>';
    return;
  }
  bar.innerHTML = _triageHistory.map((step, i) => `
    <div class="triage-history-step">
      <span class="step-q">${_escHtml(step.question.slice(0, 25))}...</span>
      <span style="color:var(--accent-secondary)">→ ${_escHtml(step.answer.replace(/^[^\s]+\s/, '').slice(0, 20))}</span>
    </div>
    ${i < _triageHistory.length - 1 ? '<span class="triage-history-sep">|</span>' : ''}
  `).join('');
}

// ── Escape ────────────────────────────────────────────────────────────────────
function _escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Dışarıdan çağrılabilir ────────────────────────────────────────────────────
function showTriagePanel() {
  const hideable = ['chatArea', 'inventoryPanel', 'libraryPanel', 'childModePanel'];
  hideable.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });

  const panel = document.getElementById('triyajPanel');
  if (panel) {
    panel.style.display = 'flex';
    // Henüz başlatılmadıysa başlat
    const body = document.getElementById('triageBody');
    if (body && body.children.length === 0) {
      _startTriage();
    }
  }
}

function hideTriagePanel() {
  const panel = document.getElementById('triyajPanel');
  if (panel) panel.style.display = 'none';
}

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  _injectTriageStyles();
  _buildTriagePanel();

  // Sol sidebar nav-triyaj
  const navTriyaj = document.getElementById('nav-triyaj');
  if (navTriyaj) {
    navTriyaj.addEventListener('click', () => {
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      navTriyaj.classList.add('active');
      showTriagePanel();
    });
  }

  // Sol alt acil triyaj butonu
  const triyajBtn = document.getElementById('triyajBtn');
  if (triyajBtn) {
    triyajBtn.addEventListener('click', () => {
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      const navT = document.getElementById('nav-triyaj');
      if (navT) navT.classList.add('active');
      showTriagePanel();
    });
  }
});
