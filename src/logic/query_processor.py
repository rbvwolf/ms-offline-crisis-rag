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
    "deprem":       "deprem anında hayatta kalma çök kapan tutun enkaz sarsıntı",
    "sarsinti":     "deprem anında hayatta kalma çök kapan tutun enkaz sarsıntı",
    "sarsıntı":     "deprem anında hayatta kalma çök kapan tutun enkaz sarsıntı",
    "yangin":       "yangın söndürme kaçış tahliye duman",
    "su":           "su arıtma çökeltme filtreleme kaynatma içme",
    "ilk yardim":   "ilk yardım acil müdahale yaralı",
    "mors":         "mors alfabesi sos acil sinyal telsiz pmr",
    "alfabesi":     "mors alfabesi sos acil sinyal telsiz pmr",
    "kirik":        "kırık kol bacak atel sabitleme müdahale",
    "yanik":        "yanık deri soğutma sarma müdahale",
    "kanama":       "kanama yara baskı uygulama durdurma",
    "enkaz":        "enkaz altında kalma çök kapan tutun nefes kontrolü hayatta kalma deprem",
    "rasyon":       "rasyon yiyecek su günlük plan hesaplama",
    "barinak":      "barınak sığınak çadır kurma afet",
    "telsiz":       "telsiz haberleşme frekans PMR acil iletişim",
    "psikoloji":    "psikolojik destek sakinleştirme panik stres",
    "cocuk":        "çocuk sakinleştirme panik korku psikolojik",
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
    Appends domain expansion terms if the query contains any emergency keyword
    (ASCII-normalized), regardless of sentence length.
    """
    q = query.strip().lower()
    q_norm = normalize_for_matching(q)

    expansions_added = []
    for keyword, expansion in _QUERY_EXPANSIONS.items():
        if keyword in q_norm:
            expansions_added.append(expansion)

    if expansions_added:
        # Use unique terms only
        combined_exp = " ".join(dict.fromkeys(" ".join(expansions_added).split()))
        expanded = f"{query} {combined_exp}"
        print(f"(*) Query expanded: '{query}' -> '{expanded[:75]}...'")
        return expanded

    return query
