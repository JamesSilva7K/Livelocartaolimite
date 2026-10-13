import app as flask_app
with flask_app.app.app_context():
    # Teste 1: Entrega normal (19.90 visual -> 20.00 na API)
    pix1 = flask_app.uniaopay_create_pix(19.90, 'Carlos Eduardo', '12345678909', '11999999999', 'carlos@email.com', 'test_pac')
    print("1. TESTE PAC (19.90 visual / 20.00 API):")
    print("   OK:", pix1.get("ok"))
    print("   Transaction ID:", pix1.get("transaction_id"))
    print("   PIX Code len:", len(pix1.get("pix_code", "")))
    print("   QR Code start:", pix1.get("qr_code_url", "")[:40])

    # Teste 2: SEDEX (24.90)
    pix2 = flask_app.uniaopay_create_pix(24.90, 'Mariana Souza', '12345678909', '11988887777', 'mariana@email.com', 'test_sedex')
    print("\n2. TESTE SEDEX (24.90):")
    print("   OK:", pix2.get("ok"))
    print("   Transaction ID:", pix2.get("transaction_id"))
    print("   PIX Code len:", len(pix2.get("pix_code", "")))
