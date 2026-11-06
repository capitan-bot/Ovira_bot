from config.crypto import decrypt_bytes, decrypt_text, encrypt_bytes, encrypt_text


def test_roundtrip_text():
    assert decrypt_text(encrypt_text("secret")) == "secret"


def test_roundtrip_bytes_exact():
    data = b"[Interface]\nPrivateKey = abc\r\n\x00\xff"
    assert decrypt_bytes(encrypt_bytes(data)) == data
