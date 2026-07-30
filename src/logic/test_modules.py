import sys, os, tempfile, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.dirname(__file__))

# ------------------------------------------------------------------
# 1. query_processor
# ------------------------------------------------------------------
from query_processor import expand_query, normalize_for_matching

assert expand_query('kirik') != 'kirik', 'expansion failed for kirik'
long_q = 'kirik kol bacak omuz diz parmak'
assert expand_query(long_q) == long_q, 'long query should not expand'
print('[+] query_processor OK')

# ------------------------------------------------------------------
# 2. context_builder
# ------------------------------------------------------------------
from context_builder import clean_chunk_text, build_context

cleaned = clean_chunk_text('- madde 1\n\nOz madde 2')
assert cleaned  # not empty

fake_docs = [
    ('Deprem sirasinda masa altina gec. Basta ve boyunda yaralan masadan uzak dur.', 0.75, None, -1),
    ('Deprem sirasinda masa altina gec. Basta ve boyunda yaralan masadan uzak dur.', 0.76, None, -1),
    ('kisa', 0.70, None, -1),
]
ctx, cits = build_context(fake_docs)
chunk_count = len([c for c in ctx.split('\n\n') if c.strip()])
assert chunk_count == 1, f'expected 1 chunk after dedup+short filter, got {chunk_count}'
print('[+] context_builder OK')

# ------------------------------------------------------------------
# 3. state_manager (with temp file override)
# ------------------------------------------------------------------
import core.config as cfg
cfg.USER_STATE_PATH = os.path.join(tempfile.gettempdir(), 'test_user_state.json')

# Must import AFTER patching config so it picks up the patched path
import importlib
import state_manager as sm_mod
importlib.reload(sm_mod)

sm = sm_mod.StateManager()

# Direct update
sm.update_inventory_direct({"su": "10 litre", "biskuvi": "2 paket"})
assert sm._state['inventory']['su'] == '10 litre', 'su not stored'
assert sm._state['inventory']['biskuvi'] == '2 paket', 'biskuvi not stored'

# Readable inventory
readable = sm.get_readable_inventory()
assert 'su' in readable, 'readable missing su'
assert 'biskuvi' in readable, 'readable missing biskuvi'
print(f'    readable: {readable}')

# Inventory query detection
assert sm.is_inventory_query('envanterimde ne var'), 'query detect failed'
assert sm.is_inventory_query('elimde ne var'), 'query detect elimde failed'
assert not sm.is_inventory_query('deprem aninda ne yapmaliyim'), 'false positive'

# Regex extraction
extracted = sm.try_extract_inventory('su varmis 10 litre su an, 2 de biskuvim var')
print(f'    extracted: {extracted}')
assert 'su' in extracted, f'su not extracted from: {extracted}'

extracted2 = sm.try_extract_inventory('10 litre su var')
assert 'su' in extracted2, f'su not in extracted2: {extracted2}'

# clean_llm_response
from state_manager import clean_llm_response
raw = "Depremde masa altina gec.\n\nPesi: 80 gram"
cleaned = clean_llm_response(raw)
assert 'Pesi' not in cleaned, f'Pesi not removed: {cleaned!r}'
raw2 = "Ilk adim dikkatli ol.\n\nSonraki adim: Su ic."
cleaned2 = clean_llm_response(raw2)
assert 'Sonraki' not in cleaned2, f'Sonraki not removed: {cleaned2!r}'
print(f'    clean_llm_response OK: {cleaned!r}')

# Context block
ctx = sm.get_context_block()
assert 'su' in ctx, 'context block missing su'

sm.clear()
assert not sm.has_state(), 'clear failed'
print('[+] state_manager OK')

print('[+] All module checks passed.')
