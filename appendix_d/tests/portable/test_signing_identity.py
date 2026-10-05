import pytest
from cryptography.hazmat.primitives import serialization

from portable.runtime.api_credentials import ApiCredentials
from portable.signing_identity import create


def test_encrypted_signing_identity_roundtrip_and_no_overwrite(tmp_path):
    root = tmp_path / "new-identity"
    create(root)
    password = ApiCredentials(root / "passphrase.dpapi").load()
    private = (root / "release-update-private.pem").read_bytes()
    assert b"ENCRYPTED PRIVATE KEY" in private
    assert password.encode() not in private
    assert password.encode() not in (root / "passphrase.dpapi").read_bytes()
    key = serialization.load_pem_private_key(private, password=password.encode())
    public = serialization.load_pem_public_key((root / "release-update-public.pem").read_bytes())
    public.verify(key.sign(b"synthetic release"), b"synthetic release")
    with pytest.raises(FileExistsError):
        create(root)
    assert (root / "release-update-private.pem").read_bytes() == private
