import os, sqlite3

db = sqlite3.connect("livelo.db")
db.row_factory = sqlite3.Row

rows = db.execute(
    "SELECT key, value FROM sys_config WHERE key IN ('admin_chat_id', 'telegram_token', 'tg_log_channel', 'tg_log_pagamentos', 'tg_log_acessos')"
).fetchall()

print("=== sys_config atual ===")
for r in rows:
    val = r["value"]
    display = (val[:25] + "...") if val and len(val) > 25 else (val or "NULL/VAZIO")
    print(f"  {r['key']}: {display}")

if not rows:
    print("  (nenhuma config de TG encontrada no banco)")

# Verifica env vars
print()
print("=== ENV VARS (nao carregadas automaticamente — precisa de .env) ===")
for key in ["SUPREME_ADMIN_ID", "ID_ADMIN_SUPREMO", "ADMIN_CHAT_ID", "TELEGRAM_BOT_TOKEN", "BOT_TOKEN"]:
    v = os.environ.get(key)
    print(f"  {key}: {v[:20] + '...' if v and len(v) > 20 else (v or 'NAO DEFINIDO')}")

# Verifica leads
leads = db.execute("SELECT session_id, nome, pix_status FROM leads ORDER BY created_at DESC LIMIT 3").fetchall()
print()
print("=== Últimos 3 leads ===")
for l in leads:
    print(f"  {l['nome'] or '?'} | status: {l['pix_status']} | sid: {l['session_id'][:12]}...")
