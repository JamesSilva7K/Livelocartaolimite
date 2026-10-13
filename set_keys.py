import sqlite3

con = sqlite3.connect('livelo.db')
token = '8390380990:AAGeDvwbsOz7cHXBy22y0vbR4V6DOEFzeA8'
con.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('telegram_token', ?)", (token,))
con.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('bot_token', ?)", (token,))
con.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('frete_expresso', '24,90')")
con.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('frete_padrao', '19,90')")
con.commit()
rows = con.execute("SELECT key, value FROM sys_config WHERE key IN ('telegram_token', 'bot_token', 'frete_expresso', 'frete_padrao')").fetchall()
print("Config atualizada no DB:", rows)
con.close()
