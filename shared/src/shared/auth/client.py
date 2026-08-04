from typing import Any

import httpx

from shared.auth.service_token import mint_service_token


class ServiceHttpClient(httpx.Client):
    def __init__(self, *, secret: str, issuer: str, base_url: str = "",
                 timeout: float = 10.0, **kwargs: Any):
        super().__init__(base_url=base_url, timeout=timeout, **kwargs)
        self._secret = secret
        self._issuer = issuer

    def request(self, method: str, url: Any, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", None) or {})
        headers["X-Service-Token"] = mint_service_token(
            secret=self._secret, issuer=self._issuer
        )
        return super().request(method, url, headers=headers, **kwargs)
