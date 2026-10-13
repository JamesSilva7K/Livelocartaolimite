import os
import sqlite3
import shutil

# Backup current DB
if os.path.exists("livelo.db"):
    shutil.copy2("livelo.db", "livelo.db.bak")
    # Also grab other configs
    old_db = sqlite3.connect("livelo.db")
    old_configs = old_db.execute("SELECT key, value FROM sys_config").fetchall()
    old_db.close()
    os.remove("livelo.db")
else:
    old_configs = []

from app import init_db
init_db()

new_db = sqlite3.connect("livelo.db")

# Insert all old configs back
for k, v in old_configs:
    new_db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES (?, ?)", (k, v))

# Set default plan prices
new_db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('frete_expresso', '19,90')")
new_db.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('frete_padrao', '14,90')")

# Create default admin if missing
admin = new_db.execute("SELECT * FROM admin").fetchone()
if not admin:
    from werkzeug.security import generate_password_hash
    new_db.execute("INSERT INTO admin (username, password) VALUES ('admin', ?)", (generate_password_hash("admin"),))

new_db.commit()
new_db.close()
print("Database rebuilt successfully with correct API keys!")
