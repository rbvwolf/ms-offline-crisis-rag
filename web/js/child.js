/**
 * child.js — Çocuk Modu (Child Crisis Protocol & Calming Assistant)
 *
 * Özellikler:
 *  - data/kisa_hikayeler/ dizininden dinamik masal yükleme API'si (`/api/child-stories`)
 *  - 15'li Varyasyon Havuzundan rastgele 5 öge seçen ve kullanıcı ögelerini koruyan Deprem Çantası
 *  - Emojisiz, saniyeli geriye sayan 4s Nefes Egzersizi
 *  - Özel Çocuk Masalı Modalı (#childStoryModal) ve "🎲 Başka Masal Getir" Butonu
 *  - Güncel Türkiye 112 Tek Acil Çağrı Rehberi
 *  - Tam Görünürlüklü Otomatik Kaydırmalı Çocuk Asistanı
 */

'use strict';

let _childBreathingTimer = null;
let _childBreathingStepTimer = null;
let _currentStoryIndex = 0;

let _CHILD_STORIES = [
  {
    id: "01_ormandaki_ruzgarli_gun",
    title: "🌲 Ormandaki Rüzgarlı Gün Masalı",
    content: `Merhaba küçük dostum. Şu an dışarıda biraz gürültü olabilir, tıpkı ormandaki rüzgarlı bir gün gibi. Ormanda rüzgar çok sert estiğinde, akıllı küçük ayılar hemen annelerinin yanına kıvrılır ve sıcak mağaralarında beklerler. Dışarıdaki rüzgar ağaçları ne kadar sallarsa sallasın, mağaranın içi hep güvenli ve sakindir. Biz de şimdi seninle o küçük ayılar gibiyiz. Gözlerimizi kapatıp derin bir nefes alacağız. Karnımızı kocaman bir balon gibi şişireceğiz... ve yavaşça söndüreceğiz. Aferin sana. Rüzgar birazdan dinecek, o zamana kadar ben senin yanındayım, sana sarılıyorum ve hiçbir yere gitmiyorum.`
  },
  {
    id: "02_akilli_kucuk_tavsan",
    title: "🐰 Akıllı Küçük Tavşanın Yuvası",
    content: `Bir zamanlar yemyeşil bir ormanda küçük bir tavşan yaşarmış. Bir gün yer hafifçe sallandığında, tavşan paniklemek yerine hemen sağlam kökleri olan koca meşe ağacının yanına çökmüş, kulaklarını kapatıp sarsıntı geçene kadar beklemiş. Sarsıntı bittiğinde annesi gelip ona sarılmış ve 'Aferin sana küçük tavşan, ne kadar akıllıca davrandın!' demiş. Sen de tıpkı o akıllı tavşan gibi sağlam masanın altında güvendesin.`
  },
  {
    id: "03_cesur_kucuk_yildiz",
    title: "⭐ Cesur Küçük Yıldız",
    content: `Gece gökyüzünde parıldayan küçük bir yıldız varmış. Bazen bulutlar önünü kapattığında veya elektrikler kesildiğinde karanlıktan korkarmış. Ama sonra hatırlamış ki kendi içinde harika bir ışık var! El fenerini yaktığında karanlık hemen kaçışırmış. Elektrikler kesilse bile bu sadece bir mola. Fenerimizi yakarız, birbirimizin elini tutarız ve ışığımız hiç sönmez.`
  }
];

const BAG_VARIATION_POOL = [
  { key: "base_toy", text: "🧸 En Sevdiğim Oyuncak veya Bebek", isBase: true },
  { key: "base_light", text: "🔦 Küçük El Feneri veya Işık", isBase: true },
  { key: "base_whistle", text: "📢 Düdük (Sesimi Duyurmak İçin)", isBase: true },
  { key: "base_water", text: "💧 Küçük Matara veya Temiz Su", isBase: true },
  { key: "base_blanket", text: "🧣 Sıcak Tutan Şal veya Battaniye", isBase: true },
  { key: "base_biscuit", text: "🍪 Tok Tutan Bisküvi / Kraker", isBase: true },
  { key: "base_bandage", text: "🩹 Küçük Yara Bandı ve Tentürdiyot", isBase: true },
  { key: "base_raincoat", text: "🌧️ Katlanabilir Çocuk Yağmurluğu", isBase: true },
  { key: "base_idcard", text: "📋 İletişim Numaraları Yazılı Bilgi Kartı", isBase: true },
  { key: "base_wipes", text: "🧻 Cep Boy Islak Mendil ve Peçete", isBase: true },
  { key: "base_socks", text: "🧦 Yedek Sıcak Çorap", isBase: true },
  { key: "base_radio", text: "📻 Küçük Pilli Radyo", isBase: true },
  { key: "base_canned", text: "🥫 Kolay Açılır Konserve / Çerez", isBase: true },
  { key: "base_drawing", text: "🎨 Resim Defteri ve Renkli Kalemler", isBase: true },
  { key: "base_sanitizer", text: "🧴 Küçük Boy El Dezenfektanı", isBase: true }
];

function _injectChildStyles() {
  if (document.getElementById('child-styles')) return;
  const style = document.createElement('style');
  style.id = 'child-styles';
  style.textContent = `
    .child-card {
      background: var(--bg-card);
      border: 1px solid var(--border-card);
      border-radius: var(--rounded-card);
      padding: 1rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
      box-shadow: var(--shadow-card);
      transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .child-card:hover {
      border-color: var(--accent-primary);
    }
    .child-step-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 2.25rem;
      height: 2.25rem;
      border-radius: 50%;
      background: var(--bg-canvas);
      border: 2px solid var(--accent-primary);
      color: var(--accent-primary);
      font-weight: 700;
      font-family: var(--font-mono);
      font-size: 1rem;
    }
    .child-bag-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      padding: 0.625rem 0.875rem;
      background: var(--bg-canvas);
      border: 1px solid var(--border-card);
      border-radius: 0.5rem;
      cursor: pointer;
      font-family: var(--font-sans);
      font-size: 0.875rem;
      color: var(--text-primary);
      user-select: none;
      transition: all 0.15s ease;
    }
    .child-bag-item.checked {
      border-color: var(--accent-secondary);
      background: rgba(78, 222, 163, 0.12);
      text-decoration: line-through;
      color: var(--text-muted);
    }
    .breathe-wrapper {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 0.75rem 0;
      gap: 0.75rem;
    }
    .breathe-circle-btn {
      width: 130px;
      height: 130px;
      border-radius: 50%;
      background: var(--accent-primary);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      color: #13131b;
      font-weight: 800;
      font-family: var(--font-mono);
      font-size: 1rem;
      cursor: pointer;
      border: 4px solid rgba(255,255,255,0.4);
      box-shadow: 0 0 25px rgba(192, 193, 255, 0.4);
      transition: transform 0.8s ease-in-out, background 0.5s ease;
      user-select: none;
      text-align: center;
      line-height: 1.2;
    }
    .breathe-circle-btn.inhale {
      transform: scale(1.15);
      background: var(--accent-secondary);
    }
    .breathe-circle-btn.hold {
      transform: scale(1.15);
      background: var(--accent-tertiary);
    }
    .breathe-circle-btn.exhale {
      transform: scale(0.9);
      background: var(--accent-primary);
    }
    .celebration-badge {
      padding: 0.75rem;
      background: rgba(78, 222, 163, 0.15);
      border: 1px dashed var(--accent-secondary);
      border-radius: 0.5rem;
      text-align: center;
      font-family: var(--font-sans);
      font-weight: 700;
      font-size: 0.875rem;
      color: var(--accent-secondary);
      animation: breathe 1.5s infinite;
    }
  `;
  document.head.appendChild(style);
}

function _buildChildPanelHTML() {
  const panel = document.getElementById('childModePanel');
  if (!panel) return;
  if (panel.innerHTML.trim().length > 0) return;

  panel.innerHTML = `
    <!-- Header -->
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1.25rem;padding-bottom:0.875rem;border-bottom:1px solid var(--border-main);">
      <div style="display:flex;align-items:center;gap:0.75rem;">
        <div style="width:2.5rem;height:2.5rem;border-radius:50%;background:rgba(192, 193, 255, 0.15);display:flex;align-items:center;justify-content:center;border:1px solid var(--accent-primary);">
          <span class="material-symbols-outlined" style="color:var(--accent-primary);font-size:24px;">child_care</span>
        </div>
        <div>
          <h2 style="font-family:var(--font-sans);font-size:1.125rem;font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:0.5rem;">
            🧸 Çocuk Afet Rehberi & Sakinleşme Alanı
          </h2>
          <p style="font-family:var(--font-mono);font-size:0.75rem;color:var(--text-muted);margin-top:0.125rem;">
            Çocuklar için güvende kalma rehberi, rahatlatıcı ritimler ve anlaşılır kılavuzlar.
          </p>
        </div>
      </div>
      <span style="font-family:var(--font-mono);font-size:0.75rem;padding:0.25rem 0.625rem;background:rgba(78, 222, 163, 0.15);border:1px solid var(--accent-secondary);border-radius:9999px;color:var(--accent-secondary);font-weight:600;">
        🛡️ Güvenli Mod
      </span>
    </div>

    <!-- 2 Sutunlu Izgara -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(320px, 1fr));gap:1.25rem;align-items:start;">
      
      <!-- SOL SÜTUN -->
      <div style="display:flex;flex-direction:column;gap:1.25rem;">

        <!-- 1. Çök - Kapan - Tutun -->
        <div class="child-card">
          <div style="display:flex;align-items:center;gap:0.5rem;border-bottom:1px solid var(--border-card);padding-bottom:0.625rem;">
            <span style="font-size:1.25rem;">🐢</span>
            <h3 style="font-family:var(--font-sans);font-size:0.9375rem;font-weight:700;color:var(--text-primary);">
              Deprem Anında 3 Altın Adım
            </h3>
          </div>
          <div style="display:flex;flex-direction:column;gap:0.75rem;">
            <div style="display:flex;align-items:flex-start;gap:0.75rem;">
              <div class="child-step-badge">1</div>
              <div>
                <strong style="color:var(--accent-primary);display:block;font-size:0.875rem;">ÇÖK!</strong>
                <span style="font-size:0.8125rem;color:var(--text-secondary);">Hemen yere dizlerinin üzerine çök. Ayakta durma, hemen alçal.</span>
              </div>
            </div>
            <div style="display:flex;align-items:flex-start;gap:0.75rem;">
              <div class="child-step-badge">2</div>
              <div>
                <strong style="color:var(--accent-secondary);display:block;font-size:0.875rem;">KAPAN!</strong>
                <span style="font-size:0.8125rem;color:var(--text-secondary);">Başını ve boynunu kollarınla koru. Sağlam bir masanın altına gir.</span>
              </div>
            </div>
            <div style="display:flex;align-items:flex-start;gap:0.75rem;">
              <div class="child-step-badge">3</div>
              <div>
                <strong style="color:var(--accent-tertiary);display:block;font-size:0.875rem;">TUTUN!</strong>
                <span style="font-size:0.8125rem;color:var(--text-secondary);">Sarsıntı bitene kadar masanın ayağına sıkıca tutun. Başını koru.</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 2. Derin Nefes & Sakinleşme Egzersizi -->
        <div class="child-card" style="text-align:center;">
          <div style="display:flex;align-items:center;justify-content:center;gap:0.5rem;border-bottom:1px solid var(--border-card);padding-bottom:0.625rem;">
            <span style="font-size:1.25rem;">🌬️</span>
            <h3 style="font-family:var(--font-sans);font-size:0.9375rem;font-weight:700;color:var(--text-primary);">
              Sakinleşme Balonu Egzersizi
            </h3>
          </div>
          <p style="font-size:0.8125rem;color:var(--text-secondary);line-height:1.4;">
            Korktuğunda karnını kocaman bir balon gibi düşün. Daireye tıkla ve ritme katıl!
          </p>

          <div class="breathe-wrapper">
            <div id="childBreatheCircle" class="breathe-circle-btn" title="Başlatmak veya durdurmak için tıkla">
              <span id="childBreatheState" style="font-size:1rem;font-weight:800;">BAŞLA</span>
              <span id="childBreatheCountdown" style="font-size:0.8125rem;opacity:0.9;margin-top:0.25rem;">Tıkla</span>
            </div>
            <p id="childBreatheText" style="font-family:var(--font-mono);font-size:0.8125rem;color:var(--accent-primary);font-weight:600;min-height:1.2rem;margin:0;">
              Ritme katılmak için yukarıdaki daireye dokun.
            </p>
          </div>
        </div>

      </div>

      <!-- SAĞ SÜTUN -->
      <div style="display:flex;flex-direction:column;gap:1.25rem;">

        <!-- 3. Çocuk Deprem Çantası (15'li Varyasyon Havuzlu + Kullanıcı Ögelerini Koruyan Sıfırlama) -->
        <div class="child-card" id="childBagCard">
          <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border-card);padding-bottom:0.625rem;">
            <div style="display:flex;align-items:center;gap:0.5rem;">
              <span style="font-size:1.25rem;">🎒</span>
              <h3 style="font-family:var(--font-sans);font-size:0.9375rem;font-weight:700;color:var(--text-primary);">
                Benim Deprem Çantam
              </h3>
            </div>
            <span id="childBagProgress" style="font-family:var(--font-mono);font-size:0.75rem;color:var(--accent-secondary);font-weight:700;">0 / 0</span>
          </div>

          <div id="childBagItems" style="display:flex;flex-direction:column;gap:0.5rem;"></div>

          <!-- Özel Öge Ekleme Kutusu -->
          <div style="display:flex;gap:0.5rem;margin-top:0.25rem;">
            <input type="text" id="childBagCustomInput" placeholder="Çantama başka ne koyayım? (ör: bisküvi)" style="flex:1;background:var(--bg-canvas);border:1px solid var(--border-card);border-radius:0.375rem;padding:0.375rem 0.625rem;font-size:0.8125rem;color:var(--text-primary);outline:none;">
            <button id="childBagAddBtn" style="padding:0.375rem 0.75rem;background:var(--accent-primary);color:#13131b;border:none;border-radius:0.375rem;font-family:var(--font-mono);font-size:0.75rem;font-weight:700;cursor:pointer;">+ Ekle</button>
            <button id="childBagResetBtn" style="padding:0.375rem 0.5rem;background:transparent;border:1px solid var(--border-card);border-radius:0.375rem;color:var(--text-muted);font-family:var(--font-mono);font-size:0.75rem;cursor:pointer;" title="Yeni 5'li Varyasyon Getir & İşaretleri Sıfırla">🔄</button>
          </div>

          <!-- Kutlama Rozeti (Sadece tümü tamamlanınca açılır) -->
          <div id="childBagCelebration" class="celebration-badge" style="display:none;">
            🎉 Harika! Deprem Çantan Eksiksiz Hazırlandı! 🏆
          </div>
        </div>

        <!-- 4. Sakinleştirici Masal Seçici ve Özel Modal -->
        <div class="child-card">
          <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border-card);padding-bottom:0.625rem;">
            <div style="display:flex;align-items:center;gap:0.5rem;">
              <span style="font-size:1.25rem;">📖</span>
              <h3 style="font-family:var(--font-sans);font-size:0.9375rem;font-weight:700;color:var(--text-primary);">
                Sakinleştirici Masallar (Kısa Hikayeler)
              </h3>
            </div>
            <select id="childStorySelect" style="background:var(--bg-canvas);border:1px solid var(--border-card);border-radius:0.375rem;color:var(--text-secondary);font-size:0.75rem;padding:0.25rem 0.5rem;outline:none;max-width:150px;">
              ${_CHILD_STORIES.map(s => `<option value="${s.id}">${s.title}</option>`).join('')}
            </select>
          </div>
          <p id="childStoryPreviewText" style="font-size:0.8125rem;color:var(--text-secondary);line-height:1.5;min-height:3.5rem;">
            "${_CHILD_STORIES[0].content.substring(0, 140)}..."
          </p>
          <button id="childReadStoryBtn" style="padding:0.5rem 1rem;background:var(--bg-canvas);border:1px solid var(--border-card);border-radius:0.5rem;color:var(--accent-primary);font-family:var(--font-mono);font-size:0.8125rem;cursor:pointer;font-weight:600;display:flex;align-items:center;justify-content:center;gap:0.375rem;">
            <span class="material-symbols-outlined" style="font-size:18px;">menu_book</span> Masalın Tamamını Oku
          </button>
        </div>

        <!-- 5. Ezberlenecek Numaralar (Güncel 112 Tek Acil Çağrı Rehberi) -->
        <div class="child-card">
          <div style="display:flex;align-items:center;gap:0.5rem;border-bottom:1px solid var(--border-card);padding-bottom:0.625rem;">
            <span style="font-size:1.25rem;">📞</span>
            <h3 style="font-family:var(--font-sans);font-size:0.9375rem;font-weight:700;color:var(--text-primary);">
              Ezberlenecek Tek Numaramız
            </h3>
          </div>
          <div style="padding:0.75rem;background:rgba(239, 68, 68, 0.1);border:1px solid var(--accent-red);border-radius:0.5rem;text-align:center;">
            <div style="font-family:var(--font-mono);font-size:2rem;font-weight:900;color:var(--accent-red);letter-spacing:0.05em;">112</div>
            <div style="font-size:0.8125rem;font-weight:700;color:var(--text-primary);margin-top:0.25rem;">TEK ACİL ÇAĞRI MERKEZİ</div>
            <div style="font-size:0.75rem;color:var(--text-muted);margin-top:0.25rem;line-height:1.4;">
              💡 Türkiye'de İtfaiye, Polis, Ambulans ve Jandarma <strong>tek numara 112</strong> altında birleşmiştir. Sadece 112'yi araman yeterlidir!
            </div>
          </div>
        </div>

      </div>

    </div>

    <!-- Soru-Cevap Kutusu -->
    <div class="child-card" style="margin-top:1.25rem;" id="childQaCard">
      <div style="display:flex;align-items:center;gap:0.5rem;">
        <span style="font-size:1.25rem;">💬</span>
        <h3 style="font-family:var(--font-sans);font-size:0.9375rem;font-weight:700;color:var(--text-primary);">
          Aklına Takılan Bir Şey Var mı? (Çocuk Asistanı)
        </h3>
      </div>
      
      <!-- Hızlı Çipler -->
      <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-top:0.25rem;">
        <button class="chip child-quick-chip" data-query="Deprem nedir?">❓ Deprem nedir?</button>
        <button class="chip child-quick-chip" data-query="Elektrikler kesilirse ne yapmalıyım?">💡 Elektrik kesilirse ne yapılır?</button>
        <button class="chip child-quick-chip" data-query="Neden asansöre binilmez?">🛗 Neden asansör kullanılmaz?</button>
        <button class="chip child-quick-chip" data-query="Korktuğumda kime haber vermeliyim?">👨‍👩‍👧 Korktuğumda kime haber vermeliyim?</button>
      </div>

      <!-- Yanıt Kutusu -->
      <div id="childAnswerBox" style="display:none;padding:1rem;background:var(--bg-canvas);border:1px solid var(--border-card);border-radius:0.5rem;font-size:0.875rem;color:var(--text-primary);line-height:1.6;white-space:pre-wrap;"></div>
    </div>

    <!-- ÖZEL ÇOCUK MASALI MODALI -->
    <div id="childStoryModal" style="display:none;position:fixed;inset:0;z-index:2100;background:rgba(0,0,0,0.75);backdrop-filter:blur(4px);align-items:center;justify-content:center;padding:1rem;">
      <div style="max-width:32rem;width:100%;background:var(--bg-card);border:1px solid var(--border-main);border-radius:var(--rounded-card);padding:1.25rem;box-shadow:var(--shadow-card);display:flex;flex-direction:column;gap:1rem;max-height:85vh;">
        <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border-card);padding-bottom:0.75rem;">
          <h3 id="childModalTitle" style="font-family:var(--font-sans);font-weight:700;font-size:1rem;color:var(--text-primary);display:flex;align-items:center;gap:0.5rem;">
            📖 Masal
          </h3>
          <div style="display:flex;align-items:center;gap:0.5rem;">
            <button id="childModalRefreshBtn" style="padding:0.25rem 0.625rem;background:var(--bg-canvas);border:1px solid var(--border-card);border-radius:0.25rem;color:var(--accent-primary);font-family:var(--font-mono);font-size:0.75rem;cursor:pointer;display:flex;align-items:center;gap:0.25rem;">
              🎲 Başka Masal Getir
            </button>
            <button id="childModalCloseBtn" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:20px;line-height:1;">&times;</button>
          </div>
        </div>
        <div id="childModalContent" style="font-family:var(--font-sans);font-size:0.9375rem;color:var(--text-secondary);line-height:1.7;white-space:pre-wrap;background:var(--bg-canvas);padding:1rem;border:1px solid var(--border-card);border-radius:0.375rem;max-height:60vh;overflow-y:auto;"></div>
      </div>
    </div>
  `;

  _bindChildEvents();
  _renderChildBagItems();
  _fetchChildStoriesFromBackend();
}

function _fetchChildStoriesFromBackend() {
  fetch('/api/child-stories')
    .then(res => res.json())
    .then(data => {
      if (data.stories && data.stories.length > 0) {
        _CHILD_STORIES = data.stories;
        const storySelect = document.getElementById('childStorySelect');
        const storyPreview = document.getElementById('childStoryPreviewText');
        if (storySelect) {
          storySelect.innerHTML = _CHILD_STORIES.map(s => `<option value="${s.id}">${s.title}</option>`).join('');
          if (_CHILD_STORIES[0] && storyPreview) {
            storyPreview.textContent = `"${_CHILD_STORIES[0].content.substring(0, 140)}..."`;
          }
        }
      }
    })
    .catch(() => {});
}

function _getOrGenerateBaseItems(forceNew = false) {
  if (!forceNew) {
    try {
      const saved = JSON.parse(localStorage.getItem('child_current_base_items'));
      if (saved && saved.length === 5) return saved;
    } catch (e) {}
  }

  // Shuffle BAG_VARIATION_POOL and pick 5 random items
  const shuffled = [...BAG_VARIATION_POOL].sort(() => 0.5 - Math.random());
  const selected = shuffled.slice(0, 5);
  localStorage.setItem('child_current_base_items', JSON.stringify(selected));
  return selected;
}

function _getCustomBagItems() {
  try {
    const raw = JSON.parse(localStorage.getItem('child_custom_bag_items')) || [];
    // Only keep items explicitly added by the user (key starts with 'custom_')
    return raw.filter(item => item && item.key && String(item.key).startsWith('custom_'));
  } catch (e) {
    return [];
  }
}

function _renderChildBagItems() {
  const container = document.getElementById('childBagItems');
  if (!container) return;

  const baseItems = _getOrGenerateBaseItems(false);
  const customItems = _getCustomBagItems();
  const allItems = [...baseItems, ...customItems];

  let checkedKeys = [];
  try {
    checkedKeys = JSON.parse(localStorage.getItem('child_bag_checked') || '[]');
  } catch (e) {}

  container.innerHTML = allItems.map((it, idx) => {
    const isChecked = checkedKeys.includes(it.key);
    const deleteBtn = it.isBase ? '' : `
      <button class="child-item-del-btn" data-custom-key="${it.key}" style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:0.875rem;" title="Sil">&times;</button>
    `;
    return `
      <div class="child-bag-item ${isChecked ? 'checked' : ''}" data-key="${it.key}">
        <span>${it.text}</span>
        ${deleteBtn}
      </div>
    `;
  }).join('');

  // Item click toggle
  container.querySelectorAll('.child-bag-item').forEach(el => {
    el.addEventListener('click', (e) => {
      if (e.target.classList.contains('child-item-del-btn')) return;
      el.classList.toggle('checked');
      _saveChildBagState();
    });
  });

  // Custom Item delete
  container.querySelectorAll('.child-item-del-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const targetKey = btn.dataset.customKey;
      let list = _getCustomBagItems();
      list = list.filter(i => i.key !== targetKey);
      localStorage.setItem('child_custom_bag_items', JSON.stringify(list));
      _renderChildBagItems();
    });
  });

  _updateChildBagProgress();
}

function _bindChildEvents() {
  // Nefes Egzersizi (Circle Button Click)
  const circleBtn = document.getElementById('childBreatheCircle');
  if (circleBtn) {
    circleBtn.addEventListener('click', _toggleChildBreathing);
  }

  // Özel Öge Ekleme
  const addBtn = document.getElementById('childBagAddBtn');
  const input = document.getElementById('childBagCustomInput');
  if (addBtn && input) {
    const doAdd = () => {
      const val = input.value.trim();
      if (!val) return;
      const customList = _getCustomBagItems();
      const newKey = 'custom_' + Date.now();
      customList.push({ key: newKey, text: `✨ ${val}`, isBase: false });
      localStorage.setItem('child_custom_bag_items', JSON.stringify(customList));
      input.value = '';
      _renderChildBagItems();
    };
    addBtn.addEventListener('click', doAdd);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') doAdd();
    });
  }

  // Çanta Sıfırla: Generates a NEW random 5-item variation while preserving user custom items
  const resetBtn = document.getElementById('childBagResetBtn');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      _getOrGenerateBaseItems(true); // Force new 5 random base variation items
      localStorage.setItem('child_bag_checked', JSON.stringify([]));
      _renderChildBagItems();
    });
  }

  // Masal Seçici ve Okuyucu
  const storySelect = document.getElementById('childStorySelect');
  const storyPreview = document.getElementById('childStoryPreviewText');
  if (storySelect && storyPreview) {
    storySelect.addEventListener('change', () => {
      const selected = _CHILD_STORIES.find(s => s.id === storySelect.value) || _CHILD_STORIES[0];
      _currentStoryIndex = _CHILD_STORIES.findIndex(s => s.id === selected.id);
      storyPreview.textContent = `"${selected.content.substring(0, 140)}..."`;
    });
  }

  const readStoryBtn = document.getElementById('childReadStoryBtn');
  if (readStoryBtn) {
    readStoryBtn.addEventListener('click', () => {
      const val = storySelect ? storySelect.value : (_CHILD_STORIES[0] ? _CHILD_STORIES[0].id : '');
      const selected = _CHILD_STORIES.find(s => s.id === val) || _CHILD_STORIES[0];
      if (selected) {
        _openDedicatedStoryModal(selected.title, selected.content);
      }
    });
  }

  // Hızlı Çipler
  document.querySelectorAll('.child-quick-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const q = chip.dataset.query;
      _askChildQuestion(q);
    });
  });

  // Dedicated Story Modal events
  const modalCloseBtn = document.getElementById('childModalCloseBtn');
  const modalRefreshBtn = document.getElementById('childModalRefreshBtn');
  const modal = document.getElementById('childStoryModal');

  if (modalCloseBtn && modal) {
    modalCloseBtn.addEventListener('click', () => {
      modal.style.display = 'none';
    });
  }

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.style.display = 'none';
    });
  }

  if (modalRefreshBtn) {
    modalRefreshBtn.addEventListener('click', () => {
      _currentStoryIndex = (_currentStoryIndex + 1) % _CHILD_STORIES.length;
      const nextStory = _CHILD_STORIES[_currentStoryIndex];
      if (nextStory) {
        if (storySelect) storySelect.value = nextStory.id;
        if (storyPreview) storyPreview.textContent = `"${nextStory.content.substring(0, 140)}..."`;
        _openDedicatedStoryModal(nextStory.title, nextStory.content);
      }
    });
  }
}

function _toggleChildBreathing() {
  const circle = document.getElementById('childBreatheCircle');
  const stateText = document.getElementById('childBreatheState');
  const countdownText = document.getElementById('childBreatheCountdown');
  const text = document.getElementById('childBreatheText');
  if (!circle || !stateText || !text) return;

  if (_childBreathingTimer) {
    clearInterval(_childBreathingTimer);
    clearInterval(_childBreathingStepTimer);
    _childBreathingTimer = null;
    _childBreathingStepTimer = null;
    circle.className = 'breathe-circle-btn';
    stateText.textContent = 'BAŞLA';
    if (countdownText) countdownText.textContent = 'Tıkla';
    text.textContent = 'Egzersiz durduruldu.';
    return;
  }

  let phase = 0; // 0: NEFES AL, 1: TUT, 2: VER
  let secondsLeft = 4;

  const runPhase = () => {
    secondsLeft = 4;
    if (phase === 0) {
      circle.className = 'breathe-circle-btn inhale';
      stateText.textContent = 'NEFES AL';
      text.textContent = '🎈 Karnını kocaman bir balon gibi şişir...';
    } else if (phase === 1) {
      circle.className = 'breathe-circle-btn hold';
      stateText.textContent = 'TUT';
      text.textContent = '🌟 Nefesini sakince tut...';
    } else if (phase === 2) {
      circle.className = 'breathe-circle-btn exhale';
      stateText.textContent = 'VER';
      text.textContent = '💨 Balondaki havayı yavaşça boşalt...';
    }
    if (countdownText) countdownText.textContent = `${secondsLeft}s`;

    if (_childBreathingStepTimer) clearInterval(_childBreathingStepTimer);
    _childBreathingStepTimer = setInterval(() => {
      secondsLeft -= 1;
      if (secondsLeft > 0) {
        if (countdownText) countdownText.textContent = `${secondsLeft}s`;
      }
    }, 1000);

    phase = (phase + 1) % 3;
  };

  runPhase();
  _childBreathingTimer = setInterval(runPhase, 4000);
}

function _saveChildBagState() {
  const checkedKeys = [];
  document.querySelectorAll('.child-bag-item.checked').forEach(item => {
    checkedKeys.push(item.dataset.key);
  });
  localStorage.setItem('child_bag_checked', JSON.stringify(checkedKeys));
  _updateChildBagProgress();
}

function _updateChildBagProgress() {
  const total = document.querySelectorAll('.child-bag-item').length;
  const checked = document.querySelectorAll('.child-bag-item.checked').length;
  const prog = document.getElementById('childBagProgress');
  const celeb = document.getElementById('childBagCelebration');

  if (prog) prog.textContent = `${checked} / ${total}`;

  if (celeb) {
    if (total > 0 && checked === total) {
      celeb.style.display = 'block';
    } else {
      celeb.style.display = 'none';
    }
  }
}

function _openDedicatedStoryModal(title, content) {
  const modalTitle = document.getElementById('childModalTitle');
  const modalContent = document.getElementById('childModalContent');
  const modal = document.getElementById('childStoryModal');
  if (modalTitle) modalTitle.textContent = title || '📖 Sakinleştirici Masal';
  if (modalContent) modalContent.textContent = content || '';
  if (modal) modal.style.display = 'flex';

  try {
    fetch('/api/logs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: `🧸 [ÇOCUK MODU] Masal okundu: ${title}` })
    }).catch(() => {});
  } catch (e) {}
}

function _askChildQuestion(question) {
  const box = document.getElementById('childAnswerBox');
  const panel = document.getElementById('childModePanel');
  if (!box) return;

  box.style.display = 'block';
  box.innerHTML = `<span style="color:var(--accent-primary);font-weight:600;">Soru: ${question}</span>\n\n<em>Yanıt hazırlanıyor...</em>`;

  if (panel) {
    setTimeout(() => {
      panel.scrollTo({ top: panel.scrollHeight, behavior: 'smooth' });
    }, 50);
  }

  const kidAnswers = {
    "deprem nedir?": "Deprem, dünyamızın yer altındaki kayaların tıpkı uykuda esneyen bir dev gibi hafifçe kımıldamasıdır. Evler biraz sallanabilir ama binalar sağlamdır. Çöküp masanın altına girdiğinde güvendesin!",
    "elektrikler kesilirse ne yapmalıyım?": "Elektrik kesintisi çok normal bir güvenlik önlemidir. Hava karardığında el fenerimizi açarız ve ailemizin yanına geçeriz. Panik yapacak hiçbir şey yok!",
    "neden asansöre binilmez?": "Sarsıntı anında elektrikler kesilebileceği için asansörler durabilir. En güvenlisi sağlam bir masanın altına çöküp beklemek, sarsıntı bitince merdivenleri kullanmaktır.",
    "korktuğumda kime haber vermeliyim?": "Korktuğunda hemen annene, babana, öğretmenine veya yanındaki yetişkine sarılabilirsin. 'Ben korkuyorum' demek çok cesurca bir davranıştır!"
  };

  const lowered = question.toLowerCase();
  let matched = null;
  for (const [k, v] of Object.entries(kidAnswers)) {
    if (lowered.includes(k) || k.includes(lowered)) {
      matched = v;
      break;
    }
  }

  if (matched) {
    box.innerHTML = `<strong style="color:var(--accent-secondary);font-size:0.9375rem;">🧸 Çocuk Asistanı Yanıtı:</strong>\n\n${matched}`;
  } else {
    box.innerHTML = `<strong style="color:var(--accent-secondary);font-size:0.9375rem;">🧸 Çocuk Asistanı Yanıtı:</strong>\n\n"Hiç korkma küçük dostum! Bir sarsıntı olduğunda yapman gereken tek şey sağlam bir masanın altına çökmek, başını korumak ve büyüklerinin yanında güvende kalmaktır. Yanındayız!"`;
  }

  if (panel) {
    setTimeout(() => {
      panel.scrollTo({ top: panel.scrollHeight, behavior: 'smooth' });
    }, 100);
  }
}

// ── Dışarıdan Çağrılabilir API ────────────────────────────────────────────────
function showChildPanel() {
  _injectChildStyles();
  _buildChildPanelHTML();

  const hideable = ['chatArea', 'triyajPanel', 'inventoryPanel', 'libraryPanel', 'loglarPanel'];
  hideable.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
  });

  const panel = document.getElementById('childModePanel');
  if (panel) {
    panel.style.display = 'flex';
  }
}

function hideChildPanel() {
  if (_childBreathingTimer) {
    clearInterval(_childBreathingTimer);
    clearInterval(_childBreathingStepTimer);
    _childBreathingTimer = null;
    _childBreathingStepTimer = null;
  }
  const panel = document.getElementById('childModePanel');
  if (panel) panel.style.display = 'none';
}
