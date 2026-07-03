from app.services.auth import api_key_prefix, hash_api_key


def test_api_key_hashing_is_stable_and_non_plaintext() -> None:
    api_key = "inferx-test-key"

    digest = hash_api_key(api_key)

    assert digest == hash_api_key(api_key)
    assert digest != api_key
    assert len(digest) == 64


def test_api_key_prefix_keeps_short_non_secret_identifier() -> None:
    assert api_key_prefix("inferx-test-key") == "inferx-t"
