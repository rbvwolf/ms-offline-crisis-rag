"""
query_processor.py — Query expansion and normalization utilities.

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
    "deprem":       "deprem aninda guvensiz sarsinti enkaz",
    "yangin":       "yangin sondurme kacis tahliye duman",
    "su":           "su aritma temizleme icilebilir hale getirme",
    "ilk yardim":   "ilk yardim acil mudahale yarali",
    "mors":         "mors alfabesi nokta cizgi harf kodu SOS sinyal",
    "alfabesi":     "mors alfabesi nokta cizgi harf kodu sinyal",
    "kirik":        "kirik kol bacak atel sabitleme mudahale",
    "yanik":        "yanik deri sogutma sarma mudahale",
    "kanama":       "kanama yara baski uygulama durdurma",
    "enkaz":        "enkaz altinda nefes bekleme kurtarma sinyal",
    "rasyon":       "rasyon yiyecek su gunluk plan hesaplama",
    "barinak":      "barinak siginak cadur kurma afet",
    "telsiz":       "telsiz haberlesme frekans PMR acil iletisim",
    "psikoloji":    "psikolojik destek sakinlestirme panik stres",
    "cocuk":        "cocuk sakinlestirme panik korku psikolojik",
}


def normalize_for_matching(s: str) -> str:
    """
    Converts Turkish-specific characters to ASCII equivalents.
    Used ONLY for keyword matching — NOT for embedding (embedding needs real chars).
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
    If the query is 1-3 words and matches a known keyword (ASCII-normalized),
    appends relevant domain terms to improve retrieval quality.
    Longer queries are returned unchanged.
    """
    q = query.strip().lower()
    if len(q.split()) > 3:
        return query

    q_norm = normalize_for_matching(q)

    for keyword, expansion in _QUERY_EXPANSIONS.items():
        if keyword in q_norm:
            expanded = f"{query} {expansion}"
            print(f"(*) Short query expanded: '{query}' -> '{expanded[:60]}...'")
            return expanded

    return query
