/**
 * history.js: CLI tarzı komut geçmişi
 * Klavyedeki ↑/↓ ile geçmiş komutları çağırır.
 * Enter ile mesaj gönderir ve history'ye ekler.
 */

const commandHistory = [];
let historyIndex = 0;

function initHistory(inputEl, onSend) {
  if (!inputEl) return;

  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (historyIndex > 0) {
        historyIndex--;
        inputEl.value = commandHistory[historyIndex];
      }
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIndex < commandHistory.length - 1) {
        historyIndex++;
        inputEl.value = commandHistory[historyIndex];
      } else {
        historyIndex = commandHistory.length;
        inputEl.value = '';
      }
    } else if (e.key === 'Enter') {
      const val = inputEl.value.trim();
      if (!val) return;
      commandHistory.push(val);
      historyIndex = commandHistory.length;
      inputEl.value = '';
      if (typeof onSend === 'function') onSend(val);
    }
  });
}
