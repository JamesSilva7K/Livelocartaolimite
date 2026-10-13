# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════╗
║  LIVELO — TESTE DE INTEGRAÇÃO COMPLETO                   ║
║  1. União 7 Pay → gera PIX real ou simulado              ║
║  2. Telegram    → dispara todos os eventos para o admin  ║
╚══════════════════════════════════════════════════════════╝
"""
import time, uuid, json, requests, os
from app import app, uniaopay_create_pix

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8390380990:AAGeDvwbsOz7cHXBy22y0vbR4V6DOEFzeA8")
ADMIN_ID  = os.environ.get("SUPREME_ADMIN_ID", "8932547795")
TG_API    = f"https://api.telegram.org/bot{BOT_TOKEN}"

print("=== BLOCO 1 — TESTE UNIÃO 7 PAY (PIX) ===")
with app.app_context():
    res = uniaopay_create_pix(
        amount=19.90,
        payer_name="João Silva",
        payer_cpf="12345678909",
        payer_phone="11999999999",
        payer_email="joao@email.com",
        payment_id=f"test_{int(time.time())}"
    )
    print("Resultado da Geração de PIX:")
    print(json.dumps(res, indent=2))

print("\n=== BLOCO 2 — TESTE TELEGRAM NOTIFICAÇÃO ===")
try:
    r = requests.post(f"{TG_API}/sendMessage", json={
        "chat_id": ADMIN_ID,
        "text": "🚀 <b>[TESTE LIVELO]</b> Gateway União 7 Pay configurado com sucesso!",
        "parse_mode": "HTML"
    }, timeout=10)
    print("Telegram Status:", r.status_code)
except Exception as e:
    print("Erro ao notificar Telegram:", e)
