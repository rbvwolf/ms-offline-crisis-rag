/**
 * theme.js — Tema / Mod yönetimi
 *
 * Desteklenen modlar: "dark" | "light" | "cli"
 * localStorage'da:
 *   "ragMode"       → aktif mod
 *   "ragModePrev"   → CLI'dan önce kullanılan modern mod (dark|light)
 *                     Sidebar "CLI / Modern Geçiş" butonu buna döner.
 */

const MODES = ['dark', 'light', 'cli'];

function getStoredMode() {
  return localStorage.getItem('ragMode') || 'dark';
}

function applyMode(mode) {
  if (!MODES.includes(mode)) mode = 'dark';

  // CLI'ya geçmeden önce hangi modern modda olduğumuzu kaydet
  const current = document.documentElement.getAttribute('data-mode') || 'dark';
  if (current !== 'cli' && mode === 'cli') {
    localStorage.setItem('ragModePrev', current); // 'dark' veya 'light'
  }

  document.documentElement.setAttribute('data-mode', mode);
  localStorage.setItem('ragMode', mode);
  updateToggleUI(mode);
}

/**
 * Sidebar "CLI / Modern Geçiş" butonu için:
 * CLI → önceki modern moda döner (dark veya light)
 * dark / light → CLI'ya geçer
 */
function toggleCliModern() {
  const current = document.documentElement.getAttribute('data-mode') || 'dark';
  if (current === 'cli') {
    // Önceki modern moda dön
    const prev = localStorage.getItem('ragModePrev') || 'dark';
    applyMode(prev);
  } else {
    // Modern moddan CLI'ya geç, mevcut modu hatırla
    applyMode('cli');
  }
}

function cycleMode() {
  const current = document.documentElement.getAttribute('data-mode') || 'dark';
  const next = MODES[(MODES.indexOf(current) + 1) % MODES.length];
  applyMode(next);
}

function updateToggleUI(mode) {
  // Header'daki 3-way seçici butonlarını güncelle
  MODES.forEach(m => {
    const el = document.getElementById('modeBtn-' + m);
    if (!el) return;
    el.setAttribute('data-active', m === mode ? 'true' : 'false');
  });
}

// Sayfa yüklendiğinde modu uygula
document.addEventListener('DOMContentLoaded', () => {
  applyMode(getStoredMode());

  // Header 3-way seçici
  MODES.forEach(m => {
    const el = document.getElementById('modeBtn-' + m);
    if (el) el.addEventListener('click', () => applyMode(m));
  });
});
