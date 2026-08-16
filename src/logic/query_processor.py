"""
query_processor.py: Query expansion and normalization utilities.

Extracted from generator.py to keep that file focused on LLM orchestration.

Public API:
    expanded = expand_query(user_question)
"""

# ---------------------------------------------------------------------------
# Query expansion keyword table.
# Keys: ASCII-only so matching works with both Turkish and ASCII keyboard input.
# Values: ASCII synonyms that help the embedding model find relevant chunks.
# ---------------------------------------------------------------------------
_QUERY_EXPANSIONS = {
    "deprem":       "deprem sarsıntı çök kapan tutun tahliye bina",
    "sarsinti":     "deprem sarsıntı çök kapan tutun",
    "sarsıntı":     "deprem sarsıntı çök kapan tutun",
    "yangin":       "yangın söndürme müdahale alev güvenlik",
    "pass":         "yangın söndürücü PASS kuralı pim çek ateşe yönelt sık süpür YSC",
    "sondurucu":    "yangın söndürme cihazı PASS pim çek ateşe yönelt sık süpür",
    "söndürücü":    "yangın söndürme cihazı PASS pim çek ateşe yönelt sık süpür",
    "kacis":        "yangın kaçış tahliye duman güvenli çıkış",
    "tahliye":      "tahliye kaçış toplanma alanı güvenli çıkış",
    "duman":        "duman zehirli gaz kaçış sürünerek ıslak bez",
    "su":           "su arıtma çökeltme filtreleme kaynatma klorlama içme içilebilir",
    "arit":         "su arıtma çökeltme filtreleme kaynatma klorlama",
    "aritma":       "su arıtma çökeltme filtreleme kaynatma klorlama",
    "kirli":        "kirli su arıtma filtreleme kaynatma klorlama",
    "kaynat":       "su arıtma kaynatma filtreleme klorlama",
    "klor":         "su klorlama arıtma dezenfeksiyon çamaşır suyu",
    "ilk yardim":   "ilk yardım acil müdahale yaralı",
    "mors":         "mors alfabesi sos acil sinyal telsiz pmr",
    "alfabesi":     "mors alfabesi sos acil sinyal telsiz pmr",
    "sos":          "mors alfabesi sos acil yardım çağrısı",
    "kirik":        "kırık çıkık atel sabitleme ilk yardım",
    "kırık":        "kırık çıkık atel sabitleme ilk yardım",
    "yanik":        "yanık soğuk su sarma ilk yardım",
    "kanama":       "kanama yara baskı bandaj turnike",
    "enkaz":        "enkaz altında kalma çırpınma gaz kibrit toz boru vurma nefes susuzluk",
    "enkaz alti":   "enkaz altında kalma çırpınma toz gaz kibrit boru vurma nefes",
    "rasyon":       "rasyon yiyecek su günlük plan stok",
    "barinak":      "barınak sığınak çadır kurma",
    "telsiz":       "telsiz haberleşme frekans PMR acil kanal 1",
    "psikoloji":    "psikolojik destek sakinleştirme panik korku",
    "cocuk":        "çocuk psikolojik sakinleştirme nefes masal",
}


def normalize_for_matching(s: str) -> str:
    """
    Converts Turkish-specific characters to ASCII equivalents.
    Used ONLY for keyword matching (NOT for embedding; embedding needs real chars).
    """
    return (
        s.replace('\u0131', 'i').replace('\u0130', 'i')   # ı İ
         .replace('\u011f', 'g').replace('\u011e', 'g')   # ğ Ğ
         .replace('\u00fc', 'u').replace('\u00dc', 'u')   # ü Ü
         .replace('\u015f', 's').replace('\u015e', 's')   # ş Ş
         .replace('\u00f6', 'o').replace('\u00d6', 'o')   # ö Ö
         .replace('\u00e7', 'c').replace('\u00c7', 'c')   # ç Ç
    )


def expand_query(query: str) -> str:
    """
    Appends domain root terms so FTS5 and embedding models match
    inflected Turkish words and hand-curated protocol files.
    """
    q = query.strip().lower()
    q_norm = normalize_for_matching(q)

    expansions_added = []
    for keyword, expansion in _QUERY_EXPANSIONS.items():
        if keyword in q_norm:
            expansions_added.append(expansion)

    if expansions_added:
        combined_exp = " ".join(dict.fromkeys(" ".join(expansions_added).split()))
        expanded = f"{query} {combined_exp}"
        print(f"(*) Query expanded: '{query}' -> '{expanded[:80]}...'")
        return expanded

    return query
