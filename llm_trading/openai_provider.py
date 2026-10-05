"""Single-request OpenAI HTTPS adapter; no retry and no secret-bearing errors."""
import time
import urllib.request
import urllib.error
from .data import canonical
from .llm_contract import ProviderResponse, ProviderFailure, ConfigurationError, strict_json

class OpenAIProvider:
    def __init__(self,api_key: str,timeout_seconds: float,transport=None):
        if not isinstance(api_key,str) or not api_key.strip():
            raise ConfigurationError('set OPENAI_API_KEY in the invoking environment')
        self._key=api_key
        self.timeout=timeout_seconds
        # An explicit empty proxy map avoids leaking the authorization header to
        # proxy settings inherited from an unrelated application/environment.
        self.transport=transport or urllib.request.build_opener(urllib.request.ProxyHandler({})).open

    def complete(self,request: dict) -> ProviderResponse:
        req=urllib.request.Request('https://api.openai.com/v1/chat/completions',
            data=canonical(request).encode('utf-8'),method='POST',
            headers={'Authorization':'Bearer '+self._key,'Content-Type':'application/json'})
        start=time.monotonic()
        content=None
        try:
            with self.transport(req,timeout=self.timeout) as response:
                content=response.read(2*1024*1024+1)
            if len(content)>2*1024*1024: raise ProviderFailure('provider response exceeds size limit',content)
            raw=strict_json(content.decode('utf-8'))
            if not isinstance(raw,dict): raise ProviderFailure('invalid provider response',content)
            return ProviderResponse(raw,time.monotonic()-start,content)
        except urllib.error.HTTPError as exc:
            body=exc.read(2*1024*1024+1) if exc.fp is not None else b''
            error={}
            try:
                parsed=strict_json(body.decode('utf-8'))
                if isinstance(parsed,dict) and isinstance(parsed.get('error'),dict): error=parsed['error']
            except (ValueError,UnicodeError): pass
            if exc.code==429 and any(error.get(key) in ('insufficient_quota','billing_hard_limit_reached') for key in ('code','type')):
                raise ConfigurationError('OpenAI quota/billing configuration error; run stopped',body) from None
            if exc.code in (400,401,403,404):
                raise ConfigurationError(f'OpenAI configuration/access error HTTP {exc.code}; run stopped',body) from None
            raise ProviderFailure(f'OpenAI HTTP {exc.code}; no automatic retry',body) from None
        except (OSError,ValueError,UnicodeError) as exc:
            if isinstance(exc,(ConfigurationError,ProviderFailure)): raise
            raise ProviderFailure('OpenAI request failed; charge uncertain; no automatic retry',content) from None
