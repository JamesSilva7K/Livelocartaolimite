from app import app, uniaopay_create_pix
import time

with app.test_request_context():
    res = uniaopay_create_pix(19.90, "Joao Silva", "14887154674", "11999999999", "joao@email.com", "TEST_" + str(int(time.time())))
    print("PIX GENERATED:", res)
