"""
Adiciona endpoint /api/tg-test para testar notificacoes Telegram
e faz verificacao de sintaxe final antes do deploy.
"""
with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

# Adiciona endpoint de teste logo antes do if __name__ == "__main__"
TEST_ENDPOINT = '''

@app.route("/api/tg-test", methods=["GET", "POST"])
def api_tg_test():
    """Endpoint de diagnostico — testa bot token e envia msg de teste."""
    import requests as _rq
    db = get_db()
    cfg_rows = db.execute("SELECT key, value FROM sys_config").fetchall()
    cfg = {r["key"]: r["value"] for r in cfg_rows}

    bot_token = (
        cfg.get("telegram_token")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
        or os.environ.get("BOT_TOKEN")
    )
    supreme_id = (
        cfg.get("admin_chat_id")
        or cfg.get("supreme_admin_id")
        or os.environ.get("SUPREME_ADMIN_ID")
        or os.environ.get("ID_ADMIN_SUPREMO")
        or os.environ.get("ADMIN_CHAT_ID")
    )

    debug = {
        "bot_token_found": bool(bot_token),
        "bot_token_prefix": bot_token[:15] + "..." if bot_token else None,
        "supreme_id": supreme_id,
        "admin_chat_id_in_db": cfg.get("admin_chat_id"),
        "tg_log_channel": cfg.get("tg_log_channel"),
    }

    if not bot_token or not supreme_id:
        return jsonify({"ok": False, "debug": debug, "error": "bot_token ou supreme_id ausente"})

    try:
        r = _rq.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": supreme_id, "text": "Teste de notificacao Livelo OK! O bot esta conectado.", "parse_mode": "HTML"},
            timeout=6
        )
        rj = r.json()
        debug["telegram_response"] = rj
        return jsonify({"ok": rj.get("ok", False), "debug": debug})
    except Exception as e:
        return jsonify({"ok": False, "debug": debug, "error": str(e)})

'''

# Insere antes de "if __name__ == "__main__":"
marker = 'if __name__ == "__main__":'
idx = content.find(marker)
if idx == -1:
    # tenta variante
    marker = "if __name__ == '__main__':"
    idx = content.find(marker)

if idx != -1:
    content = content[:idx] + TEST_ENDPOINT + content[idx:]
    print("Endpoint /api/tg-test adicionado!")
else:
    # Adiciona no final
    content += TEST_ENDPOINT
    print("Endpoint /api/tg-test adicionado no final!")

with open("app.py", "w", encoding="utf-8") as f:
    f.write(content)

import py_compile
try:
    py_compile.compile("app.py", doraise=True)
    print("OK - sem erros de sintaxe!")
except py_compile.PyCompileError as e:
    print(f"ERRO DE SINTAXE: {e}")
