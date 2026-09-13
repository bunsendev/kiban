"""外部OIDC IdP接続前の技術検査。"""

from .contracts import OidcPreflightSettings
from .runner import run_preflight

__all__ = ["OidcPreflightSettings", "run_preflight"]
