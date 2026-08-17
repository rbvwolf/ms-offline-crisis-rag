/**
 * emergency.js: Acil Durum Modu (Header Panic Mode & Panik Paneli)
 *
 * Özellikler:
 *  - Tam ekran zengin acil müdahale rehberi (Boşluk kalmayacak şekilde 4 zengin kart)
 *  - Ortalanmış SOS Flaşör Kutusu ve Uluslararası SOS Rehberi
 *  - Gerçek Mors SOS zamanlaması (`... --- ...` : 3 Kısa [200ms], 3 Uzun [600ms], 3 Kısa [200ms])
 *  - 5 Yöntemli Detaylı Acil Su Arıtma Kılavuzu
 *  - 6 Adımlı Deprem Tahliye, Vanalar & İlk 5 Dakika Rehberi
 */

'use strict';

let _sosActive = false;
let _sosTimeouts = [];

function _injectEmergencyStyles() {
  if (document.getElementById('emergency-styles')) return;
  const style = document.createElement('style');
  style.id = 'emergency-styles';
  style.textContent = `
    .panic-overlay {
      display: none;
      position: fixed;
      inset: 0;
      z-index: 2000;
      background: #050508;
      color: #ffffff;
      padding: 1.25rem 1.5rem;
      overflow-y: auto;
      flex-direction: column;
      gap: 1rem;
    }
    .panic-overlay.active {
      display: flex;
    }
    .panic-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      grid-template-rows: auto auto;
      gap: 1.25rem;
      flex: 1;
      min-height: 0;
    }
    @media (max-width: 768px) {
      .panic-grid {
        grid-template-columns: 1fr;
      }
    }
    .panic-card {
      background: #111118;
      border: 2px solid #2d2d3d;
      border-radius: 0.875rem;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 1rem;
      box-shadow: 0 4px 25px rgba(0,0,0,0.8);
    }
    .panic-card-danger {
      border-color: #ef4444;
      background: #180606;
    }
    .panic-card-warning {
      border-color: #f59e0b;
      background: #181204;
    }
    .panic-card-info {
      border-color: #3b82f6;
      background: #06101f;
    }
    .panic-btn-action {
      padding: 0.875rem 1rem;
      border: none;
      border-radius: 0.625rem;
      font-family: var(--font-mono);
      font-weight: 800;
      font-size: 0.9375rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      transition: transform 0.1s ease, filter 0.15s ease;
      letter-spacing: 0.02em;
    }
    .panic-btn-action:active {
      transform: scale(0.98);
    }
    .panic-btn-red {
      background: #ef4444;
      color: #ffffff;
    }
    .panic-btn-amber {
      background: #f59e0b;
      color: #111118;
    }
    .sos-flasher {
      width: 100%;
      min-height: 80px;
      padding: 1rem;
      border-radius: 0.5rem;
      background: #1b1b26;
      border: 1px solid #333344;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      font-family: var(--font-mono);
      font-size: 1.375rem;
      font-weight: 800;
      color: #ffffff;
      box-sizing: border-box;
      transition: background 0.1s ease, color 0.1s ease;
    }
    .sos-flasher.short-flash {
      background: #ef4444 !important;
      color: #ffffff !important;
      box-shadow: 0 0 35px #ef4444;
    }
    .sos-flasher.long-flash {
      background: #f59e0b !important;
      color: #111118 !important;
      box-shadow: 0 0 45px #f59e0b;
    }
  `;
  document.head.appendChild(style);
}

function _buildEmergencyOverlayHTML() {
  if (document.getElementById('emergencyPanicOverlay')) return;

  const overlay = document.createElement('div');
  overlay.id = 'emergencyPanicOverlay';
  overlay.className = 'panic-overlay';
  overlay.innerHTML = `
    <!-- Header -->
    <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:2px solid #ef4444;padding-bottom:0.75rem;">
      <div style="display:flex;align-items:center;gap:0.875rem;">
        <div style="width:2.75rem;height:2.75rem;border-radius:0.5rem;background:rgba(239,68,68,0.15);border:1px solid #ef4444;display:flex;align-items:center;justify-content:center;">
          <span class="material-symbols-outlined" style="font-size:1.75rem;color:#ef4444;">emergency</span>
        </div>
        <div>
          <h1 style="font-family:var(--font-mono);font-size:1.25rem;font-weight:900;color:#ef4444;margin:0;letter-spacing:0.02em;">
            ACİL DURUM VE MÜDAHALE PROTOKOLLERİ
          </h1>
          <p style="font-family:var(--font-mono);font-size:0.75rem;color:#aaaaaa;margin-top:0.25rem;">
            Kriz, şebeke kesintisi ve afet durumlarında anlık müdahale rehberi.
          </p>
        </div>
      </div>
      <button id="closeEmergencyPanicBtn" style="padding:0.5rem 1rem;background:#ef4444;color:#ffffff;border:none;border-radius:0.5rem;font-family:var(--font-mono);font-size:0.8125rem;font-weight:800;cursor:pointer;display:flex;align-items:center;gap:0.5rem;transition:opacity 0.15s ease;">
        <span class="material-symbols-outlined" style="font-size:1.125rem;">close</span>
        <span>Kapat (ESC)</span>
      </button>
    </div>

    <!-- 2x2 Dolu Izgara -->
    <div class="panic-grid">
      
      <!-- KART 1 (Sol Üst): Acil Triyaj -->
      <div class="panic-card panic-card-danger">
        <div style="display:flex;flex-direction:column;gap:0.75rem;">
          <div style="display:flex;align-items:center;gap:0.625rem;border-bottom:1px solid rgba(239,68,68,0.3);padding-bottom:0.5rem;">
            <span class="material-symbols-outlined" style="font-size:1.35rem;color:#ef4444;">medical_services</span>
            <h2 style="font-family:var(--font-mono);font-size:1.0625rem;font-weight:800;color:#ef4444;margin:0;">
              1. Acil Triyaj ve Önceliklendirme
            </h2>
          </div>
          <p style="font-family:var(--font-mono);font-size:0.8125rem;color:#dddddd;line-height:1.6;margin:0;">
            Yaralının hayati risk derecesini belirleyip müdahale ve tahliye önceliğini saptayın.
          </p>
          <div style="padding:0.75rem;background:rgba(239,68,68,0.15);border:1px solid rgba(239,68,68,0.4);border-radius:0.5rem;font-family:var(--font-mono);font-size:0.75rem;color:#ffaaaa;line-height:1.6;">
            <div style="font-weight:700;margin-bottom:0.35rem;color:#ffffff;">Müdahale Öncelik Sıralaması:</div>
            <div style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.2rem;">
              <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#ef4444;"></span>
              <strong>Kırmızı (1. Öncelik):</strong> Ağır yaralı, solunum/dolaşım riski &rarr; İlk Müdahale
            </div>
            <div style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.2rem;">
              <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#f59e0b;"></span>
              <strong>Sarı (2. Öncelik):</strong> Kırık ve kanama, bilinci açık &rarr; İkincil Müdahale
            </div>
            <div style="display:flex;align-items:center;gap:0.4rem;">
              <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#10b981;"></span>
              <strong>Yeşil (3. Öncelik):</strong> Ayakta yaralı, hafif sıyrık &rarr; Ertelenebilir
            </div>
          </div>
        </div>
        <button id="panicStartTriageBtn" class="panic-btn-action panic-btn-red">
          <span class="material-symbols-outlined" style="font-size:1.125rem;">checklist</span>
          <span>Triyaj Değerlendirmesini Başlat</span>
        </button>
      </div>

      <!-- KART 2 (Sağ Üst): Gerçek Mors SOS Sinyali & Rehberi -->
      <div class="panic-card panic-card-danger">
        <div style="display:flex;flex-direction:column;gap:0.625rem;">
          <div style="display:flex;align-items:center;gap:0.625rem;border-bottom:1px solid rgba(239,68,68,0.3);padding-bottom:0.5rem;">
            <span class="material-symbols-outlined" style="font-size:1.35rem;color:#ef4444;">sensors</span>
            <h2 style="font-family:var(--font-mono);font-size:1.0625rem;font-weight:800;color:#ef4444;margin:0;">
              2. SOS Sinyali ve Mors Çakarı
            </h2>
          </div>
          
          <!-- Ortalanmış SOS Kutusu -->
          <div id="sosFlasherBox" class="sos-flasher">
            &bull; &bull; &bull; &nbsp; &mdash; &mdash; &mdash; &nbsp; &bull; &bull; &bull; (SOS)
          </div>

          <!-- SOS Nedir Rehberi -->
          <div style="padding:0.625rem 0.75rem;background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.3);border-radius:0.5rem;font-family:var(--font-mono);font-size:0.75rem;color:#fcd34d;line-height:1.5;">
            <strong>Sinyal Standardı:</strong> Uluslararası acil yardım çağrısıdır. 3 Kısa (200ms), 3 Uzun (600ms), 3 Kısa (200ms) ritmiyle çalışır. El feneri, ekran flaşı, düdük veya mekanik boru vuruşlarıyla arama-kurtarma ekiplerine konum bildirmek için kullanılır.
          </div>
        </div>
        <button id="panicToggleSosBtn" class="panic-btn-action panic-btn-amber">
          <span class="material-symbols-outlined" style="font-size:1.125rem;">flash_on</span>
          <span>Mors SOS Çakarını Başlat</span>
        </button>
      </div>

      <!-- KART 3 (Sol Alt): Acil Su Arıtma (5 Detaylı Yöntem) -->
      <div class="panic-card panic-card-warning">
        <div style="display:flex;flex-direction:column;gap:0.625rem;">
          <div style="display:flex;align-items:center;gap:0.625rem;border-bottom:1px solid rgba(245,158,11,0.3);padding-bottom:0.5rem;">
            <span class="material-symbols-outlined" style="font-size:1.35rem;color:#f59e0b;">water_drop</span>
            <h2 style="font-family:var(--font-mono);font-size:1.0625rem;font-weight:800;color:#f59e0b;margin:0;">
              3. Acil Su Arıtma Yöntemleri
            </h2>
          </div>
          <ul style="font-family:var(--font-mono);font-size:0.8125rem;color:#dddddd;line-height:1.6;margin:0;padding-left:1.25rem;">
            <li><strong>1. Süzme:</strong> Bulanık suyu temiz pamuklu kumaş veya tülbentten geçirerek partiküllerden arındırın.</li>
            <li><strong>2. Kaynatma:</strong> Biyolojik mikroorganizmaları yok etmek için en az <strong>1-3 dakika fokurdatın</strong>.</li>
            <li><strong>3. Klorlama:</strong> 1 Litre berrak suya <strong>2 damla kokusuz çamaşır suyu</strong> ekleyip 30 dakika bekletin.</li>
            <li><strong>4. SODIS (Güneşle Arıtma):</strong> Şeffaf PET şişedeki suyu 6 saat doğrudan güneş ışığında tutun.</li>
            <li><strong>5. Yağmur Hasadı:</strong> İlk 10 dakikalık akıntıyı eledikten sonra temiz kapta biriktirin.</li>
          </ul>
        </div>
        <div style="padding:0.5rem 0.75rem;background:rgba(245,158,11,0.15);border:1px solid rgba(245,158,11,0.3);border-radius:0.375rem;font-family:var(--font-mono);font-size:0.75rem;color:#fcd34d;">
          <strong>Kritik Uyarı:</strong> Kimyasal kirlilik şüphesi olan veya deterjanlı suları arıtmadan içmeyin.
        </div>
      </div>

      <!-- KART 4 (Sağ Alt): Tahliye & İlk 5 Dakika -->
      <div class="panic-card panic-card-info">
        <div style="display:flex;flex-direction:column;gap:0.625rem;">
          <div style="display:flex;align-items:center;gap:0.625rem;border-bottom:1px solid rgba(59,130,246,0.3);padding-bottom:0.5rem;">
            <span class="material-symbols-outlined" style="font-size:1.35rem;color:#60a5fa;">fmd_good</span>
            <h2 style="font-family:var(--font-mono);font-size:1.0625rem;font-weight:800;color:#60a5fa;margin:0;">
              4. Tahliye ve İlk Müdahale Protokolü
            </h2>
          </div>
          <ul style="font-family:var(--font-mono);font-size:0.8125rem;color:#dddddd;line-height:1.6;margin:0;padding-left:1.25rem;">
            <li><strong>Sarsıntı Anı:</strong> Pencerelerden uzak durun. Sağlam nesne yanında <strong>Çök-Kapan-Tutun</strong> yapın.</li>
            <li><strong>Tesisat Güvenliği:</strong> Sarsıntı durduğunda doğalgaz, elektrik ve su ana vanalarını derhal kapatın.</li>
            <li><strong>Tahliye:</strong> Asansör kesinlikle kullanmayın. Merdivenlerde başınızı koruyarak bina dışına çıkın.</li>
            <li><strong>Toplanma Alanı:</strong> Önceden belirlenmiş açık afet toplanma alanına intikal edin.</li>
            <li><strong>Haberleşme:</strong> Telefon hatlarını meşgul etmeyin; durumunuzu SMS veya veri kanalıyla bildirin.</li>
            <li><strong>Duman Riski:</strong> Dumanlı alanda yere yakın ilerleyin, ağzınızı ıslak bezle kapatın.</li>
          </ul>
        </div>
        <div style="padding:0.5rem 0.75rem;background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);border-radius:0.375rem;font-family:var(--font-mono);font-size:0.75rem;color:#93c5fd;">
          <strong>Önemli Not:</strong> Ana tesisat vanalarının yerlerini önceden fosforlu bantla işaretleyin.
        </div>
      </div>

    </div>
  `;

  document.body.appendChild(overlay);

  // Backdrop click to close
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) hideEmergencyModal();
  });

  // Event bindings
  document.getElementById('closeEmergencyPanicBtn').addEventListener('click', hideEmergencyModal);

  document.getElementById('panicStartTriageBtn').addEventListener('click', () => {
    hideEmergencyModal();
    if (typeof switchNavPanel === 'function') {
      switchNavPanel('triyaj');
    }
  });

  document.getElementById('panicToggleSosBtn').addEventListener('click', _toggleSosFlasher);
}

// Gerçek Mors SOS Ritmi
function _startRealMorseSos() {
  const box = document.getElementById('sosFlasherBox');
  if (!box) return;

  _clearSosTimeouts();
  _sosActive = true;

  const sequence = [
    // S: • • •
    { duration: 200, isFlash: true, type: 'short', label: '• SİNYAL (KISA)' },
    { duration: 200, isFlash: false },
    { duration: 200, isFlash: true, type: 'short', label: '• SİNYAL (KISA)' },
    { duration: 200, isFlash: false },
    { duration: 200, isFlash: true, type: 'short', label: '• SİNYAL (KISA)' },
    { duration: 500, isFlash: false },

    // O: - - -
    { duration: 600, isFlash: true, type: 'long', label: '- SİNYAL (UZUN)' },
    { duration: 200, isFlash: false },
    { duration: 600, isFlash: true, type: 'long', label: '- SİNYAL (UZUN)' },
    { duration: 200, isFlash: false },
    { duration: 600, isFlash: true, type: 'long', label: '- SİNYAL (UZUN)' },
    { duration: 500, isFlash: false },

    // S: • • •
    { duration: 200, isFlash: true, type: 'short', label: '• SİNYAL (KISA)' },
    { duration: 200, isFlash: false },
    { duration: 200, isFlash: true, type: 'short', label: '• SİNYAL (KISA)' },
    { duration: 200, isFlash: false },
    { duration: 200, isFlash: true, type: 'short', label: '• SİNYAL (KISA)' },
    { duration: 1400, isFlash: false }
  ];

  let cumulativeTime = 0;

  const scheduleSequence = () => {
    if (!_sosActive) return;
    cumulativeTime = 0;

    sequence.forEach(step => {
      const t = setTimeout(() => {
        if (!_sosActive) return;
        if (step.isFlash) {
          box.className = `sos-flasher ${step.type === 'long' ? 'long-flash' : 'short-flash'}`;
          box.textContent = step.label || 'SİNYAL!';
        } else {
          box.className = 'sos-flasher';
          box.textContent = '• • •   - - -   • • • (SOS)';
        }
      }, cumulativeTime);
      _sosTimeouts.push(t);
      cumulativeTime += step.duration;
    });

    const loopTimer = setTimeout(() => {
      if (_sosActive) scheduleSequence();
    }, cumulativeTime);
    _sosTimeouts.push(loopTimer);
  };

  scheduleSequence();
}

function _clearSosTimeouts() {
  _sosTimeouts.forEach(t => clearTimeout(t));
  _sosTimeouts = [];
  _sosActive = false;
}

function _toggleSosFlasher() {
  const box = document.getElementById('sosFlasherBox');
  const btn = document.getElementById('panicToggleSosBtn');
  if (!box || !btn) return;

  if (_sosActive) {
    _clearSosTimeouts();
    box.className = 'sos-flasher';
    box.textContent = '• • •   - - -   • • • (SOS)';
    btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:1.125rem;">flash_on</span><span>Mors SOS Çakarını Başlat</span>';
    return;
  }

  btn.innerHTML = '<span class="material-symbols-outlined" style="font-size:1.125rem;">stop_circle</span><span>Çakarı Durdur</span>';
  _startRealMorseSos();
}

function showEmergencyModal() {
  _injectEmergencyStyles();
  _buildEmergencyOverlayHTML();

  const overlay = document.getElementById('emergencyPanicOverlay');
  if (overlay) {
    overlay.classList.add('active');
  }
}

function hideEmergencyModal() {
  _clearSosTimeouts();
  const overlay = document.getElementById('emergencyPanicOverlay');
  if (overlay) {
    overlay.classList.remove('active');
  }
}

// Global Initialization
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('emergencyPanicBtn');
  if (btn) {
    btn.addEventListener('click', showEmergencyModal);
  }

  // Esc key binding
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      hideEmergencyModal();
    }
  });
});
