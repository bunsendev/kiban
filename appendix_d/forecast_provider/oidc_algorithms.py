"""JWT検証とOIDCプリフライトが共有する非対称署名方式。"""

ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EdDSA"})
