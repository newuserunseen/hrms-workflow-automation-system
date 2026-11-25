from app.security import hash_password, verify_password, create_token
from jose import jwt
from app.security import SECRET_KEY, ALGORITHM

def test_password_hash_round_trip():
    hashed = hash_password("StrongPassphrase!2026")
    assert hashed != "StrongPassphrase!2026"
    assert verify_password("StrongPassphrase!2026", hashed)
    assert not verify_password("wrong-password", hashed)

def test_jwt_contains_user_subject():
    token = create_token(42)
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["sub"] == "42"
    assert "exp" in payload
