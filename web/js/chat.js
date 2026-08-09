/**
 * chat.js — Sohbet yonetimi (persisted history, backend stream ready)
 *
 * Persists chat history in localStorage under 'crisis_chat_history'
 * so F5 refresh does NOT wipe the chat.
 */

const QUICK_CHIPS = [
  'Mors Alfabesi',
  'Su Ar\u0131tma',
  'Deprem Protokol\u00fc',
  '\u0130lk Yard\u0131m: K\u0131r\u0131k',
  'Acil Triyaj',
];

const LOCAL_STORAGE_KEY = 'crisis_chat_history';

function loadChatHistory() {
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw);
  } catch (e) {
    return [];
  }
}

function saveChatHistory(history) {
  try {
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(history));
  } catch (e) {}
}

function renderSavedHistory() {
  const history = loadChatHistory();
  // introScreen stays permanently at top of scrollable #chatArea
  history.forEach(item => {
    appendMessageDOM(item.role, item.html, false);
  });
}

function scrollToBottom() {
  const chatArea = document.getElementById('chatArea');
  if (chatArea) {
    chatArea.scrollTop = chatArea.scrollHeight;
  }
}

function appendMessageDOM(role, html, shouldSave = true) {
  const chatContainer = document.getElementById('chatMessages');
  if (!chatContainer) return;

  // introScreen stays permanently at top of scrollable #chatArea
  const isUser = role === 'user';

  const wrapper = document.createElement('div');
  wrapper.className = `flex flex-col gap-1 ${isUser ? 'items-end' : 'items-start'}`;

  const label = document.createElement('span');
  label.className = 'text-[10px] uppercase tracking-wider font-mono';
  label.style.color = isUser ? 'var(--text-muted)' : 'var(--text-accent)';
  label.textContent = isUser ? 'Kullanıcı' : 'CRISIS Asistanı';

  const bubble = document.createElement('div');
  bubble.className = `px-4 py-3 max-w-[85%] text-sm leading-relaxed`;
  bubble.style.background   = isUser ? 'var(--bg-user-bubble)' : 'var(--bg-card)';
  bubble.style.border       = `1px solid ${isUser ? 'var(--border-card)' : 'var(--border-main)'}`;
  bubble.style.borderRadius = isUser
    ? 'var(--rounded-bubble) var(--rounded-bubble) 0.25rem var(--rounded-bubble)'
    : 'var(--rounded-bubble) var(--rounded-bubble) var(--rounded-bubble) 0.25rem';
  bubble.style.color = 'var(--text-primary)';
  bubble.innerHTML = html;

  const headerRow = document.createElement('div');
  headerRow.style.cssText = 'display:flex;align-items:center;gap:0.5rem;';
  headerRow.appendChild(label);

  // Copy button — only for assistant messages
  if (!isUser) {
    const copyBtn = document.createElement('button');
    copyBtn.title = 'Kopyala';
    copyBtn.style.cssText = [
      'background:none',
      'border:none',
      'cursor:pointer',
      'padding:0.1rem 0.3rem',
      'color:var(--text-muted)',
      'font-size:0.7rem',
      'opacity:0.55',
      'transition:opacity 0.15s',
      'border-radius:0.25rem',
      'line-height:1',
    ].join(';');
    copyBtn.innerHTML = '&#x2398;'; // ⎘ clipboard icon
    copyBtn.addEventListener('mouseenter', () => copyBtn.style.opacity = '1');
    copyBtn.addEventListener('mouseleave', () => copyBtn.style.opacity = '0.55');
    copyBtn.addEventListener('click', () => {
      const rawText = bubble.innerText || bubble.textContent || '';
      navigator.clipboard.writeText(rawText.trim()).then(() => {
        copyBtn.innerHTML = '&#x2713;'; // ✓
        copyBtn.style.color = 'var(--accent-secondary)';
        setTimeout(() => {
          copyBtn.innerHTML = '&#x2398;';
          copyBtn.style.color = 'var(--text-muted)';
        }, 1500);
      }).catch(() => {
        // Fallback for older browsers
        const ta = document.createElement('textarea');
        ta.value = rawText.trim();
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      });
    });
    headerRow.appendChild(copyBtn);
  }

  wrapper.appendChild(headerRow);
  wrapper.appendChild(bubble);
  chatContainer.appendChild(wrapper);
  scrollToBottom();

  if (shouldSave) {
    const history = loadChatHistory();
    history.push({ role, html });
    saveChatHistory(history);
  }

  return bubble;
}

function appendMessage(role, html) {
  return appendMessageDOM(role, html, true);
}

function clearChat() {
  localStorage.removeItem(LOCAL_STORAGE_KEY);
  const chatContainer = document.getElementById('chatMessages');
  if (chatContainer) chatContainer.innerHTML = '';

  const intro = document.getElementById('introScreen');
  if (intro) intro.style.display = 'block';

  closeClearModal();
}

function showClearModal() {
  const modal = document.getElementById('clearModal');
  if (modal) modal.style.display = 'flex';
}

function closeClearModal() {
  const modal = document.getElementById('clearModal');
  if (modal) modal.style.display = 'none';
}

function sendMessage(text) {
  if (!text.trim()) return;
  appendMessage('user', escapeHtml(text));

  // Placeholder streaming assistant message bubble
  const assistantBubble = appendMessageDOM('assistant',
    `<p class="animate-breathe" style="color:var(--text-muted);">Yan\u0131t haz\u0131rlan\u0131yor...</p>`,
    false
  );

  let fullResponse = '';

  // FastAPI SSE endpoint (/api/chat)
  fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: text })
  })
  .then(res => {
    if (!res.ok) {
      return res.json().then(data => {
        throw new Error(data.error || 'Sunucu hatas\u0131');
      });
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');

    function readChunk() {
      reader.read().then(({ done, value }) => {
        if (done) {
          // Save completed assistant response to history
          if (fullResponse) {
            const cleanText = cleanStreamOutput(fullResponse);
            const history = loadChatHistory();
            history.push({ role: 'assistant', html: escapeHtml(cleanText).replace(/\n/g, '<br>') });
            saveChatHistory(history);
          }
          // Refresh RAG debug panel
          if (typeof updateRagPanel === 'function') updateRagPanel();
          return;
        }

        const chunkText = decoder.decode(value, { stream: true });
        const lines = chunkText.split('\n');

        lines.forEach(line => {
          if (line.startsWith('data: ')) {
            const dataStr = line.slice(6).trim();
            if (dataStr === '[DONE]') return;
            try {
              const parsed = JSON.parse(dataStr);
              if (parsed.rag_docs) {
                renderRagPanel(parsed.rag_docs);
              } else if (parsed.token) {
                fullResponse += parsed.token;
                const cleanText = cleanStreamOutput(fullResponse);
                assistantBubble.innerHTML = `<p>${escapeHtml(cleanText).replace(/\n/g, '<br>')}</p>`;
                scrollToBottom();
              }
            } catch (e) {
              // Direct text token
              fullResponse += dataStr;
              const cleanText = cleanStreamOutput(fullResponse);
              assistantBubble.innerHTML = `<p>${escapeHtml(cleanText).replace(/\n/g, '<br>')}</p>`;
              scrollToBottom();
            }
          }
        });

        readChunk();
      }).catch(err => {
        assistantBubble.innerHTML = `<p style="color:var(--text-danger);">Hata: ${escapeHtml(err.message)}</p>`;
        scrollToBottom();
      });
    }

    assistantBubble.innerHTML = '';
    readChunk();
  })
  .catch(err => {
    // Fallback if backend model is not ready yet
    assistantBubble.innerHTML = `<p style="color:var(--text-muted);">[Mock / Çevrimdışı] Yerel veritabanında arandı. (Backend henüz bağlanıyor: ${escapeHtml(err.message)})</p>`;
  });
}

function cleanStreamOutput(text) {
  let cleaned = text;
  // Remove [BITTI] tag and trailing garbage
  cleaned = cleaned.replace(/\[BITTI\].*$/gis, '');
  // Remove prompt leak headers & hallucinated preamble prefixes
  cleaned = cleaned.replace(/^(?:Programını\s+kullanmaktadır:?|Programı:?|Yanı?t\s+Formatı?\s+ve\s+Kurallı?:?|Mors\s+alfabesi\s+veya\s+sinyal\s+sorularıyla?:?.*|Şimdi\s+Yanı?t?:?|Yanı?t?:?)\s*/gim, '');
  // Strip markdown bold/italic markers that the model emits despite being told not to
  cleaned = cleaned.replace(/\*\*([^*]+)\*\*/g, '$1');  // **bold** → plain
  cleaned = cleaned.replace(/\*([^*]+)\*/g, '$1');       // *italic* → plain
  cleaned = cleaned.replace(/__([^_]+)__/g, '$1');       // __bold__ → plain
  cleaned = cleaned.replace(/_([^_]+)_/g, '$1');         // _italic_ → plain
  return cleaned.trim();
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function initQuickChips() {
  const container = document.getElementById('quickChips');
  if (!container) return;
  container.innerHTML = '';
  QUICK_CHIPS.forEach(chip => {
    const btn = document.createElement('button');
    btn.textContent = `[${chip}]`;
    btn.style.cssText = `
      padding: 0.25rem 0.75rem;
      border: 1px solid var(--border-card);
      border-radius: var(--rounded-chip);
      background: var(--bg-chip);
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 0.75rem;
      cursor: pointer;
    `;
    btn.addEventListener('click', () => sendMessage(chip));
    container.appendChild(btn);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initQuickChips();
  renderSavedHistory();

  const sendBtn = document.getElementById('sendBtn');
  const input   = document.getElementById('cliInput');

  if (sendBtn && input) {
    sendBtn.addEventListener('click', () => {
      const val = input.value.trim();
      if (!val) return;
      input.value = '';
      sendMessage(val);
    });
  }

  if (typeof initHistory === 'function' && input) {
    initHistory(input, sendMessage);
  }

  const clearBtn = document.getElementById('clearChatBtn');
  if (clearBtn) clearBtn.addEventListener('click', showClearModal);

  const confirmBtn = document.getElementById('confirmClearBtn');
  if (confirmBtn) confirmBtn.addEventListener('click', clearChat);

  const cancelBtn = document.getElementById('cancelClearBtn');
  if (cancelBtn) cancelBtn.addEventListener('click', closeClearModal);

  updateRagPanel();
});

function renderRagPanel(chunks) {
  const container = document.getElementById('ragCards');
  if (!container || !chunks || chunks.length === 0) return;

  container.innerHTML = '';
  const loadedFiles = new Set();

  chunks.forEach((chunkObj) => {
    const text = chunkObj.text || '';
    const dist = chunkObj.distance !== undefined ? chunkObj.distance.toFixed(2) : '0.00';
    const file = chunkObj.source_file || (chunkObj.metadata ? (chunkObj.metadata.source || chunkObj.metadata.file_name) : null) || 'rehber.txt';
    loadedFiles.add(file);

    const card = document.createElement('div');
    card.className = 'citation-card modern-only';
    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;gap:0.5rem;overflow:hidden;">
        <span style="font-family:var(--font-mono);font-size:0.625rem;padding:0.125rem 0.375rem;background:var(--bg-canvas);border:1px solid var(--border-card);border-radius:0.25rem;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:65%;" title="${escapeHtml(file)}">${escapeHtml(file)}</span>
        <span style="font-family:var(--font-mono);font-size:0.625rem;color:var(--accent-tertiary);flex-shrink:0;white-space:nowrap;">dist: ${dist}</span>
      </div>
      <p style="font-family:var(--font-mono);font-size:0.6875rem;color:var(--text-secondary);line-height:1.5;overflow:hidden;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;">
        "${escapeHtml(text.slice(0, 200))}..."
      </p>
    `;
    container.appendChild(card);
  });

  // Update YUKLU MODULLER list in right sidebar
  const modulesList = document.getElementById('loadedModulesList');
  if (modulesList && loadedFiles.size > 0) {
    modulesList.innerHTML = '';
    loadedFiles.forEach(fileName => {
      const item = document.createElement('div');
      item.style.cssText = 'display:flex;align-items:center;gap:0.5rem;font-family:var(--font-mono);font-size:0.6875rem;color:var(--text-secondary);';
      item.innerHTML = `
        <span class="modern-only" style="width:0.4rem;height:0.4rem;border-radius:50%;background:var(--accent-secondary);flex-shrink:0;"></span>
        <span class="cli-only" style="color:var(--accent-primary);">[*]</span>
        <span style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${escapeHtml(fileName)}">${escapeHtml(fileName)}</span>
      `;
      modulesList.appendChild(item);
    });
  }
}

function updateRagPanel() {
  fetch('/api/rag-debug')
    .then(res => res.json())
    .then(data => {
      if (data.chunks && data.chunks.length > 0) {
        renderRagPanel(data.chunks);
      }
    })
    .catch(() => {});
}


