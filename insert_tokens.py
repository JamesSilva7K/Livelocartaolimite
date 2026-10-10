import sqlite3

tokens = "8bd69523d509bbb5fe72d3bed5379fd41aa59c51f28f0738a455c991b994d0bd, ad7535881b3d20f86a52f7ba6c892ec7ecdb909faa1758200ebb5162a8972765, 60aeb5c774fc68dcc0649cef21e79ccdab75bafd9021ceb34c0c4c14c74d6666, 5e4af1b1b68fed65e6e31a21a2d4ed8cf8318669f06ade7463d334b3051c3c99"

conn = sqlite3.connect('livelo.db')
conn.execute("INSERT OR REPLACE INTO sys_config (key, value) VALUES ('cpf_token', ?)", (tokens,))
conn.commit()
conn.close()
print("Tokens inseridos com sucesso!")
