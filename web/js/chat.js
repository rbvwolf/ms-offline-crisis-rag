/**
 * chat.js: Sohbet yonetimi (persisted history, backend stream ready)
 *
 * Persists chat history in localStorage under 'crisis_chat_history'
 * so F5 refresh does NOT wipe the chat.
 */

const QUICK_CHIPS = [
  'Envanter',
  'Mors Alfabesi',
  'Su Arıtma',
  'Deprem Protokolü',
  'İlk Yardım: Kırık',
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
  const container = document.getElementById('chatScrollArea') || document.getElementById('chatArea');
  if (container) {
    container.scrollTop = container.scrollHeight;
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

  // Copy button: only for assistant messages
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
  let firstTokenReceived = false;
  let s6Interval = null;  // S6: polls /api/logs to detect RAG completion

  // S6: Start polling system logs; when RAG ARAMA entry appears, update bubble
  s6Interval = setInterval(async () => {
    if (firstTokenReceived) { clearInterval(s6Interval); return; }
    try {
      const r = await fetch('/api/logs');
      const d = await r.json();
      if (!d.logs || !d.logs.length) return;
      // Search recent logs (last 30) for the RAG ARAMA entry
      const ragLog = d.logs.slice(-30).reverse().find(l =>
        l.message && l.message.includes('RAG ARAMA')
      );
      if (ragLog && !firstTokenReceived) {
        const m = ragLog.message.match(/(\d+) ilgili par/);
        const count = m ? m[1] : '?';
        assistantBubble.innerHTML = `<p class="animate-breathe" style="color:var(--text-muted);font-size:0.82rem;"><strong style="color:var(--text-accent);">${count} kaynak bulundu,</strong> yanıt hazırlanıyor...</p>`;
        scrollToBottom();
        clearInterval(s6Interval);
      }
    } catch(e) {}
  }, 250);

  // FastAPI SSE endpoint (/api/chat)
  fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: text })
  })
  .then(res => {
    if (!res.ok) {
      return res.json().then(data => {
        throw new Error(data.error || 'Sunucu hatası');
      });
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let sseBuffer = '';  // H-1 FIX: accumulate partial SSE data across TCP chunks

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
          clearInterval(s6Interval);  // ensure polling stops on stream end
          return;
        }

        // H-1 FIX: Append decoded chunk to buffer and process only complete SSE events
        sseBuffer += decoder.decode(value, { stream: true });
        const events = sseBuffer.split('\n\n');
        // Last element may be incomplete — keep it in the buffer
        sseBuffer = events.pop() || '';

        events.forEach(event => {
          const lines = event.split('\n');
          lines.forEach(line => {
            if (line.startsWith('data: ')) {
              const dataStr = line.slice(6).trim();
              if (dataStr === '[DONE]') return;
              try {
                const parsed = JSON.parse(dataStr);

                if (parsed.rag_docs) {
                  // Update right panel
                  try { renderRagPanel(parsed.rag_docs); } catch (e) {}

                  // Update assistant bubble with source count
                  const srcCount = (parsed.rag_docs || []).length;
                  if (srcCount > 0 && !firstTokenReceived) {
                    assistantBubble.innerHTML = `<p class="animate-breathe" style="color:var(--text-muted);font-size:0.82rem;"><strong style="color:var(--text-accent);">${srcCount} kaynak bulundu,</strong> yanıt hazırlanıyor...</p>`;
                    scrollToBottom();
                  }

                } else if (parsed.telemetry) {
                  try { renderTelemetry(parsed.telemetry); } catch (e) {}

                } else if (parsed.token) {
                  if (!firstTokenReceived) {
                    firstTokenReceived = true;
                    if (s6Interval) clearInterval(s6Interval);  // stop log polling
                    assistantBubble.innerHTML = ''; // clear waiting placeholder on first token
                  }
                  fullResponse += parsed.token;
                  const cleanText = cleanStreamOutput(fullResponse);
                  assistantBubble.innerHTML = `<p>${escapeHtml(cleanText).replace(/\n/g, '<br>')}</p>`;
                  scrollToBottom();
                }

              } catch (e) {
                // Partial JSON or non-JSON data — skip silently (buffer handles framing)
              }
            }
          });
        });

        readChunk();
      }).catch(err => {
        if (s6Interval) clearInterval(s6Interval);
        assistantBubble.innerHTML = `<p style="color:var(--text-danger);">Hata: ${escapeHtml(err.message)}</p>`;
        scrollToBottom();
      });
    }

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
  // Remove exact prompt leak headers & hallucinated preamble prefixes ONLY
  cleaned = cleaned.replace(/^(?:Programını\s+kullanmaktadır:?|Programı:?|Yanıt\s+Formatı:?|Şimdi\s+Yanıt\s+Verin:?)\s*/gim, '');
  // Strip cut-off dangling stop headers at the very end of stream
  cleaned = cleaned.replace(/\n*(?:Bilinç Bozukluklar.*|Enkaz Altında Kalırsan.*|Bu konuda veritaban[ıi]mda.*|Verilen bilgileri.*|Bu ilkeleri.*|Bu yöntemleri.*)\s*$/gi, '');
  // Strip nonsense lines
  cleaned = cleaned.replace(/.*yalanları söyler.*/gi, '');
  cleaned = cleaned.replace(/.*kötülük için yalanları.*/gi, '');
  cleaned = cleaned.replace(/.*Hazırlık durumunu söyledikçe.*/gi, '');
  cleaned = cleaned.replace(/.*Amatörler, bu m.*/gi, '');
  // Strip markdown bold/italic markers
  cleaned = cleaned.replace(/\*\*([^*]+)\*\*/g, '$1');
  cleaned = cleaned.replace(/\*([^*]+)\*/g, '$1');
  cleaned = cleaned.replace(/__([^_]+)__/g, '$1');
  cleaned = cleaned.replace(/_([^_]+)_/g, '$1');
  return cleaned.trim();
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function initRightSidebarTabs() {
  const nav = document.getElementById('sidebarTabsNav');
  if (!nav) return;

  const buttons = nav.querySelectorAll('button[data-target]');
  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      // Deactivate all buttons
      buttons.forEach(b => {
        b.classList.remove('active');
        b.style.borderLeft = 'none';
        b.style.color = '';
      });

      // Activate clicked button
      btn.classList.add('active');
      btn.style.borderLeft = '3px solid var(--accent-tertiary)';
      btn.style.color = 'var(--accent-tertiary)';

      // Hide all panels
      const targetId = btn.getAttribute('data-target');
      document.querySelectorAll('.sidebar-panel').forEach(panel => {
        panel.style.display = 'none';
      });

      // Show target panel
      const targetPanel = document.getElementById(targetId);
      if (targetPanel) {
        targetPanel.style.display = 'flex';
      }
    });
  });

  // Raw Prompt toggle button
  const togglePromptBtn = document.getElementById('toggleRawPromptBtn');
  const rawPromptBox = document.getElementById('rawPromptBox');
  if (togglePromptBtn && rawPromptBox) {
    togglePromptBtn.addEventListener('click', () => {
      const isHidden = rawPromptBox.style.display === 'none';
      rawPromptBox.style.display = isHidden ? 'block' : 'none';
    });
  }

  // Citation Detail Modal close button
  const closeCitationBtn = document.getElementById('closeCitationModalBtn');
  const citationModal = document.getElementById('citationModal');
  if (closeCitationBtn && citationModal) {
    closeCitationBtn.addEventListener('click', () => {
      citationModal.style.display = 'none';
    });
  }

  // Global Backdrop Click-to-Close for all modals (Item 11.3)
  document.addEventListener('click', (e) => {
    const modalIds = [
      'citationModal', 'clearModal', 'settingsModal',
      'invAddModal', 'invDeleteModal', 'invClearModal',
      'libResetSingleModal', 'libResetAllModal'
    ];
    modalIds.forEach(id => {
      const modalEl = document.getElementById(id);
      if (modalEl && e.target === modalEl) {
        modalEl.style.display = 'none';
      }
    });
  });

  // View Full File button inside modal
  const viewFullFileBtn = document.getElementById('viewFullFileBtn');
  const viewChunkTextBtn = document.getElementById('viewChunkTextBtn');
  const contentEl = document.getElementById('citationModalContent');

  if (viewFullFileBtn) {
    viewFullFileBtn.addEventListener('click', () => {
      if (!currentActiveFilename) return;
      if (contentEl) contentEl.textContent = 'Tüm dosya yükleniyor...';
      fetch(`/api/file/${encodeURIComponent(currentActiveFilename)}`)
        .then(res => res.json())
        .then(data => {
          if (data.content && contentEl) {
            contentEl.textContent = `=== [ DOSYA İÇERİĞİ: ${data.filename} ] ===\n\n${data.content}`;
            if (viewFullFileBtn) viewFullFileBtn.style.display = 'none';
            if (viewChunkTextBtn) viewChunkTextBtn.style.display = 'flex';
          } else if (contentEl) {
            contentEl.textContent = `Hata: ${data.error || 'Dosya okunamadı'}`;
          }
        })
        .catch(err => {
          if (contentEl) contentEl.textContent = `İletişim Hatası: ${err.message}`;
        });
    });
  }

  if (viewChunkTextBtn) {
    viewChunkTextBtn.addEventListener('click', () => {
      if (contentEl) contentEl.textContent = currentActiveChunkText;
      if (viewChunkTextBtn) viewChunkTextBtn.style.display = 'none';
      if (viewFullFileBtn) viewFullFileBtn.style.display = 'flex';
    });
  }
}

let currentActiveFilename = '';
let currentActiveChunkText = '';

function openCitationModal(title, text, filename) {
  const modal = document.getElementById('citationModal');
  const titleEl = document.getElementById('citationModalTitle');
  const contentEl = document.getElementById('citationModalContent');
  const fullFileBtn = document.getElementById('viewFullFileBtn');
  const chunkBtn = document.getElementById('viewChunkTextBtn');

  if (modal && titleEl && contentEl) {
    let cleanFile = filename;
    if (!cleanFile && title) {
      cleanFile = title.replace(/^[\*\s\-\[\]A-Za-z]+\]\s*/i, '').trim();
    }
    currentActiveFilename = cleanFile || title;
    currentActiveChunkText = text || 'Henüz kaynak alıntısı getirilmedi. Lütfen bir soru sorun.';
    titleEl.textContent = title;
    contentEl.textContent = currentActiveChunkText;

    if (fullFileBtn) fullFileBtn.style.display = 'flex';
    if (chunkBtn) chunkBtn.style.display = 'none';

    modal.style.display = 'flex';
  }
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
      white-space: nowrap;
      flex-shrink: 0;
    `;
    btn.addEventListener('click', () => sendMessage(chip));
    container.appendChild(btn);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initQuickChips();
  renderSavedHistory();
  initRightSidebarTabs();

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

  // ── nav-chat: Sohbet paneline dön ───────────────────────────────────────────
  const navChat = document.getElementById('nav-chat');
  if (navChat) {
    navChat.addEventListener('click', () => {
      document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
      navChat.classList.add('active');

      // Diğer panelleri gizle
      ['triyajPanel', 'inventoryPanel', 'libraryPanel', 'childModePanel'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
      });

      // Sohbeti göster
      const chatArea = document.getElementById('chatArea');
      if (chatArea) chatArea.style.display = 'flex';
    });
  }

  // ── Ayarlar Modalı (İnteraktif Parametre Yönetimi) ────────────────────────
  const settingsBtn = document.getElementById('settingsBtn');
  const settingsModal = document.getElementById('settingsModal');
  const closeSettingsBtn = document.getElementById('closeSettingsModalBtn');
  const saveSettingsBtn = document.getElementById('saveSettingsBtn');

  const settingTempInput = document.getElementById('settingTemp');
  const settingTempVal = document.getElementById('settingTempVal');
  const settingTopKInput = document.getElementById('settingTopK');
  const settingMaxContextInput = document.getElementById('settingMaxContext');
  const settingClearHistoryBtn = document.getElementById('settingClearHistoryBtn');
  const settingClearLogsBtn = document.getElementById('settingClearLogsBtn');

  const _loadSettingsToUI = () => {
    const temp = localStorage.getItem('app_setting_temp') || '0.1';
    const topK = localStorage.getItem('app_setting_top_k') || '4';
    const maxCtx = localStorage.getItem('app_setting_max_context') || '16000';

    if (settingTempInput) settingTempInput.value = temp;
    if (settingTempVal) settingTempVal.textContent = temp;
    if (settingTopKInput) settingTopKInput.value = topK;
    if (settingMaxContextInput) settingMaxContextInput.value = maxCtx;
  };

  if (settingTempInput && settingTempVal) {
    settingTempInput.addEventListener('input', () => {
      settingTempVal.textContent = settingTempInput.value;
    });
  }

  window.openSettingsModal = function() {
    _loadSettingsToUI();
    if (settingsModal) settingsModal.style.display = 'flex';
  };

  window.closeSettingsModal = function() {
    if (settingsModal) settingsModal.style.display = 'none';
  };

  if (settingsBtn) {
    settingsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      window.openSettingsModal();
    });
  }
  if (closeSettingsBtn) {
    closeSettingsBtn.addEventListener('click', () => {
      window.closeSettingsModal();
    });
  }
  if (saveSettingsBtn && settingsModal) {
    saveSettingsBtn.addEventListener('click', () => {
      const temp = settingTempInput ? settingTempInput.value : '0.1';
      const topK = settingTopKInput ? settingTopKInput.value : '4';
      const maxCtx = settingMaxContextInput ? settingMaxContextInput.value : '16000';

      localStorage.setItem('app_setting_temp', temp);
      localStorage.setItem('app_setting_top_k', topK);
      localStorage.setItem('app_setting_max_context', maxCtx);

      try {
        fetch('/api/logs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: `⚙️ [SİSTEM AYARLARI] Güncellendi: Temp=${temp}, Top-K=${topK}, ContextLimit=${maxCtx}` })
        }).catch(() => {});
      } catch (e) {}

      settingsModal.style.display = 'none';
    });
  }

  if (settingClearHistoryBtn) {
    settingClearHistoryBtn.addEventListener('click', () => {
      clearChatHistory();
      if (settingsModal) settingsModal.style.display = 'none';
    });
  }

  if (settingClearLogsBtn) {
    settingClearLogsBtn.addEventListener('click', () => {
      fetch('/api/logs', { method: 'DELETE' })
        .then(() => {
          if (typeof refreshLogs === 'function') refreshLogs();
          if (settingsModal) settingsModal.style.display = 'none';
        }).catch(() => {});
    });
  }

  checkLlmStatus();
  updateRagPanel();
});

let _statusSse = null;

function checkLlmStatus() {
  const dot  = document.getElementById('topbarLlmDot');
  const text = document.getElementById('topbarLlmText');
  if (!dot || !text) return;

  fetch('/api/status')
    .then(res => res.json())
    .then(data => {
      if (data.model === 'ready') {
        dot.style.background = 'var(--accent-secondary)';
        text.style.color      = 'var(--accent-secondary)';
        text.textContent      = 'Yerel LLM Aktif (phi-3.5-mini)';
        if (_statusSse) { _statusSse.close(); _statusSse = null; }
        return;
      }

      // Model yükleniyor: SSE push akışını dinle
      dot.style.background = 'var(--accent-red)';
      text.style.color      = 'var(--accent-red)';
      text.textContent      = 'Yerel LLM Yükleniyor...';

      if (_statusSse) return; // Bağlantı zaten açık, tekrar açma!

      _statusSse = new EventSource('/api/status/stream');
      _statusSse.onmessage = (e) => {
        if (_statusSse) { _statusSse.close(); _statusSse = null; }
        try {
          const payload = JSON.parse(e.data);
          if (payload.model === 'ready') {
            dot.style.background = 'var(--accent-secondary)';
            text.style.color      = 'var(--accent-secondary)';
            text.textContent      = 'Yerel LLM Aktif (phi-3.5-mini)';
          }
        } catch (err) {}
      };
      _statusSse.onerror = () => {
        if (_statusSse) { _statusSse.close(); _statusSse = null; }
      };
    })
    .catch(() => {});
}

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
    card.style.cursor = 'pointer';
    card.title = 'Tam metni görüntülemek için tıklayın';

    // Distance badge color
    let badgeColor = 'var(--accent-tertiary)';
    if (chunkObj.distance <= 0.65) badgeColor = 'var(--accent-secondary)';
    else if (chunkObj.distance > 0.80) badgeColor = 'var(--text-danger)';

    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.5rem;gap:0.5rem;overflow:hidden;">
        <span style="font-family:var(--font-mono);font-size:0.625rem;padding:0.125rem 0.375rem;background:var(--bg-canvas);border:1px solid var(--border-card);border-radius:0.25rem;color:var(--text-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:65%;" title="${escapeHtml(file)}">${escapeHtml(file)}</span>
        <span style="font-family:var(--font-mono);font-size:0.625rem;color:${badgeColor};flex-shrink:0;white-space:nowrap;">dist: ${dist}</span>
      </div>
      <p style="font-family:var(--font-mono);font-size:0.6875rem;color:var(--text-secondary);line-height:1.5;overflow:hidden;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;">
        "${escapeHtml(text.slice(0, 200))}..."
      </p>
    `;

    card.addEventListener('click', () => {
      openCitationModal(`${file} (Mesafe: ${dist})`, text, file);
    });

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

function renderTelemetry(telemetry) {
  if (!telemetry) return;

  const ctxStats = telemetry.context_stats;
  const searchStats = telemetry.search_stats;

  // 1. Update Bağlam Penceresi
  if (ctxStats) {
    const totalChars = ctxStats.total_chars || 0;
    const totalCapacity = 16000; // Total LLM window capacity (4,096 tokens)
    const pct = Math.min(100, Math.round((totalChars / totalCapacity) * 100));
    const estTokens = ctxStats.estimated_tokens || Math.round(totalChars / 4);

    const capacityText = document.getElementById('ctxCapacityText');
    if (capacityText) {
      capacityText.textContent = `${totalChars.toLocaleString()} / 16,000 kr (%${pct}) [~${estTokens} / 4,096 token]`;
    }

    const progressBar = document.getElementById('ctxProgressBar');
    if (progressBar) {
      progressBar.style.width = `${pct}%`;
      progressBar.style.background = pct >= 95 ? 'var(--accent-red)' : 'var(--accent-primary)';
    }

    const invInjected = document.getElementById('ctxInventoryInjected');
    if (invInjected) {
      invInjected.textContent = ctxStats.inventory_status || (
        ctxStats.inventory_injected
          ? 'Aktif (Kullanıcı stok bilgisi prompta eklendi)'
          : 'Pasif (Sorgu stoklama ile ilgili değil)'
      );
      invInjected.style.color = ctxStats.inventory_injected ? 'var(--accent-secondary)' : 'var(--text-secondary)';
    }

    const rawPromptBox = document.getElementById('rawPromptBox');
    if (rawPromptBox && ctxStats.system_prompt) {
      rawPromptBox.textContent = ctxStats.system_prompt;
    }
  }

  // 2. Update Kaynak Alıntıları Tab
  if (ctxStats && ctxStats.citations) {
    const citationsList = document.getElementById('citationsList');
    if (citationsList) {
      citationsList.innerHTML = '';
      if (ctxStats.citations.length === 0) {
        citationsList.innerHTML = '<p style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted);">Alıntı yapılmadı veya envanter komutu doğrudan çalıştırıldı.</p>';
      } else {
        ctxStats.citations.forEach((cit, idx) => {
          const card = document.createElement('div');
          card.className = 'citation-card modern-only';
          card.style.cssText = 'padding:0.625rem;background:var(--bg-card);border:1px solid var(--border-card);border-radius:0.375rem;cursor:pointer;';
          const srcLabel = typeof cit === 'string' ? cit : (cit.label || cit.source || 'Rehber');
          const srcText = typeof cit === 'string' ? '' : (cit.text || '');
          const srcFile = typeof cit === 'string' ? cit : (cit.source || '');

          card.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.375rem;">
              <span style="font-family:var(--font-mono);font-size:0.6875rem;font-weight:600;color:var(--accent-primary);">${escapeHtml(srcLabel)}</span>
            </div>
            <p style="font-family:var(--font-mono);font-size:0.6875rem;color:var(--text-secondary);line-height:1.4;">
              "${escapeHtml(srcText ? srcText.slice(0, 150) + '...' : 'Tam metni görüntülemek için tıklayın.')}"
            </p>
          `;
          card.addEventListener('click', () => {
            openCitationModal(srcLabel, srcText || 'Alıntı parçası metni.', srcFile);
          });
          citationsList.appendChild(card);
        });
      }
    }
  }

  // 3. Update Hata Ayıklama (Debug) Tab
  if (searchStats) {
    const metricBestDist = document.getElementById('metricBestDist');
    if (metricBestDist && searchStats.best_distance !== undefined) {
      metricBestDist.textContent = searchStats.best_distance.toFixed(2);
    }
    const metricSearchTime = document.getElementById('metricSearchTime');
    if (metricSearchTime) {
      metricSearchTime.textContent = `${searchStats.retrieved_count || 0} chunk`;
    }

    const consoleLog = document.getElementById('debugConsoleLog');
    if (consoleLog) {
      const timeStr = new Date().toLocaleTimeString();
      const queryName = searchStats.query || searchStats.expanded_query || 'Sorgu';
      const line = document.createElement('div');
      line.textContent = `[${timeStr}] RRF Arama ("${queryName}"): Top ${searchStats.retrieved_count} chunk seçildi (En iyi dist: ${searchStats.best_distance})`;
      consoleLog.appendChild(line);
      consoleLog.scrollTop = consoleLog.scrollHeight;
    }
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


