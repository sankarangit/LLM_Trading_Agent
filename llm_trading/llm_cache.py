"""Content-addressed exact-request cache; mismatched/corrupt data fails closed."""
from hashlib import sha256
import os
from pathlib import Path
import uuid
from .data import canonical
from .llm_contract import strict_json

def request_hash(request): return sha256(canonical(request).encode('utf-8')).hexdigest()

class ResponseCache:
    def __init__(self,path: Path):
        self.path=Path(path)
        self.path.mkdir(parents=True,exist_ok=True)

    def get(self,request: dict) -> dict | None:
        path=self.path/(request_hash(request)+'.json')
        if not path.exists(): return None
        value=strict_json(path.read_text(encoding='utf-8'))
        if (value.get('request')!=request or value.get('response_hash')!=
                sha256(canonical(value.get('response')).encode()).hexdigest()):
            raise ValueError('LLM cache integrity failure')
        return value['response']

    def put(self,request: dict,response: dict) -> None:
        dest=self.path/(request_hash(request)+'.json')
        content=canonical({'request':request,'response':response,
                           'response_hash':sha256(canonical(response).encode()).hexdigest()})
        temp=self.path/('.pending-'+uuid.uuid4().hex)
        try:
            with temp.open('x',encoding='utf-8') as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            try: os.link(temp,dest)
            except FileExistsError:
                # Another process won the immutable first-response publication.
                self.get(request)
        finally:
            temp.unlink(missing_ok=True)
