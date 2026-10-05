from decimal import Decimal
import json
import subprocess
import sys
import pytest
from llm_trading.llm_budget import BudgetLedger, maximum_charge
from llm_trading.llm_cache import ResponseCache
from llm_trading.llm_contract import BudgetExceeded

def test_persistent_cap_reservations_and_uncertain_charge(tmp_path):
    p=tmp_path/'budget.sqlite'
    a=BudgetLedger(p,Decimal('10'))
    token=a.reserve('first',Decimal('9.99'))
    b=BudgetLedger(p,Decimal('10'))
    with pytest.raises(BudgetExceeded): b.reserve('second',Decimal('.02'))
    assert b.spent_and_reserved()==Decimal('9.99')
    for bad in ({},{'prompt_tokens':-1,'completion_tokens':2},
                {'prompt_tokens':True,'completion_tokens':2},
                {'prompt_tokens':10**309,'completion_tokens':2},
                {'prompt_tokens':1000,'completion_tokens':513}):
        with pytest.raises(ValueError): a.settle(token,bad)
        assert b.spent_and_reserved()==Decimal('9.99')
    assert a.settle(token,{'prompt_tokens':2000,'completion_tokens':200})==Decimal('.00042')
    assert b.spent_and_reserved()==Decimal('.00042')
    with pytest.raises(ValueError): BudgetLedger(p,Decimal('20'))

def test_concurrent_processes_cannot_overspend(tmp_path):
    p=tmp_path/'budget.sqlite'
    BudgetLedger(p,Decimal('10'))
    code='from llm_trading.llm_budget import BudgetLedger; from decimal import Decimal; import sys; BudgetLedger(sys.argv[1],Decimal("10")).reserve(sys.argv[2],Decimal("6"))'
    processes=[subprocess.Popen([sys.executable,'-c',code,str(p),str(i)],stdout=subprocess.PIPE,stderr=subprocess.PIPE) for i in range(2)]
    codes=[proc.communicate() or None for proc in processes]
    assert sorted(proc.returncode for proc in processes)==[0,1]
    assert BudgetLedger(p,Decimal('10')).spent_and_reserved()==Decimal('6')

def test_usage_exceeding_reservation_books_greater_charge_and_stops(tmp_path):
    a=BudgetLedger(tmp_path/'b.sqlite',Decimal('10'))
    r=a.reserve('a',Decimal('.000001'))
    with pytest.raises(ValueError): a.settle(r,{'prompt_tokens':2000,'completion_tokens':200})
    assert a.spent_and_reserved()==Decimal('.00042')
    with pytest.raises(ValueError): a.reserve('b',Decimal('.01'))

def test_maximum_charge_uses_documented_ceiling():
    assert maximum_charge({'model':'gpt-4o-mini','max_completion_tokens':512})==Decimal('.0195072')

def test_cache_exact_identity_and_corruption(tmp_path):
    cache=ResponseCache(tmp_path/'cache')
    request={'model':'gpt-4o-mini','messages':[{'role':'user','content':'account 1'}]}
    response={'usage':{'prompt_tokens':2000,'completion_tokens':200},'choices':[]}
    assert cache.get(request) is None
    cache.put(request,response)
    assert cache.get(request)==response
    assert cache.get({**request,'temperature':1}) is None
    assert cache.get({**request,'messages':[{'role':'user','content':'account 2'}]}) is None
    file=next((tmp_path/'cache').glob('*.json'))
    raw=json.loads(file.read_text())
    raw['response']['usage']['prompt_tokens']=0
    file.write_text(json.dumps(raw))
    with pytest.raises(ValueError,match='integrity'): cache.get(request)
