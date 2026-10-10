import sqlite3
db = sqlite3.connect("livelo.db")
db.execute("INSERT OR REPLACE INTO sys_config(key, value) VALUES('admin_chat_id', '8932547795')")
db.commit()
row = db.execute("SELECT value FROM sys_config WHERE key='admin_chat_id'").fetchone()
print("admin_chat_id salvo:", row[0])
db.close()
print("Banco atualizado com sucesso!")
