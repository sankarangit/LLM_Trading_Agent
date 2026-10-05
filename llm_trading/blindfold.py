"""Allowlisted, scale-free model inputs. Never serialize raw engine Context."""
from hashlib import sha256
import math
from pathlib import Path
from .features import FEATURE_CATALOGUE
from .llm_contract import VARIANTS

REGIMES={'LOW_VOL_TREND','HIGH_VOL_TREND','LOW_VOL_RANGE','HIGH_VOL_RANGE','TRANSITION'}

def number(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        raise ValueError('nonfinite or nonnumeric prompt input')
    return round(value,12)

def build_payload(context, initial_cash: float, variant: str, journal: tuple) -> dict:
    if variant not in VARIANTS or number(initial_cash)<=0:
        raise ValueError('invalid payload configuration')
    if not context.bars or any(b.close_time>context.timestamp for b in (*context.bars,*context.higher_bars)):
        raise ValueError('uncompleted/future bar in prompt context')
    bars=context.bars[-24:]
    market={'offsets':list(range(1-len(bars),1)),
            'indexed_closes':[number(b.close/bars[0].close*100) for b in bars]}
    if variant!='llm_only':
        features={}
        for key,value in context.features:
            if key not in FEATURE_CATALOGUE: continue
            if key=='regime':
                if value is not None and value not in REGIMES: raise ValueError('invalid regime')
                features[key]=value
            else:
                features[key]=None if value is None else number(value)
        market['features']=features
    if context.higher_bars:
        higher=context.higher_bars[-24:]
        market['higher_indexed_closes']=[number(b.close/higher[0].close*100) for b in higher]
    a=context.account
    if a.position not in {'FLAT','LONG','SHORT'}: raise ValueError('invalid position')
    account={'position':a.position,'drawdown':number(a.drawdown)}
    for field in ('cash','equity','realized_pnl','unrealized_pnl','exposure','peak_equity',
                  'daily_pnl','transaction_costs','dividend_receivable'):
        account[field+'_fraction']=number(getattr(a,field)/initial_cash)
    safe_journal=[]
    if variant=='stats_llm_journal':
        previous=-1
        for record in journal:
            step=record.get('step')
            if type(step) is not int or step<=previous or step>=len(context.bars)-1:
                raise ValueError('journal ordering/future error')
            previous=step
            action=record.get('action')
            conf=number(record.get('confidence'))
            if action not in {'LONG','SHORT','HOLD','CLOSE'} or not 0<=conf<=1:
                raise ValueError('invalid journal decision')
        for offset,record in enumerate(journal[-20:],start=-min(20,len(journal))):
            safe_journal.append({'offset':offset,'action':record['action'],'confidence':number(record['confidence'])})
    return {'market':market,'account':account,'journal':safe_journal}

def load_prompt(path: Path) -> tuple[str,str]:
    content=Path(path).read_bytes()
    return content.decode('utf-8'),sha256(content).hexdigest()
