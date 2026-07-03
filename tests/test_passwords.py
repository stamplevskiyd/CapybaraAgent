from capybara.security.passwords import hash_password


def test_hash_password_returns_argon2_hash() -> None:
    hashed = hash_password("s3cret-password")
    assert hashed.startswith("$argon2")
    assert hashed != "s3cret-password"


def test_hash_password_is_salted_unique() -> None:
    assert hash_password("same-input") != hash_password("same-input")
