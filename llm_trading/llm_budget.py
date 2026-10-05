"""Persistent, transactional reservations shared by every initial experiment."""
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
import sqlite3
import uuid
from .llm_contract import BudgetExceeded

UNIT=Decimal('1000000000')
INPUT_RATE=Decimal('.15')/Decimal(1000000)
OUTPUT_RATE=Decimal('.60')/Decimal(1000000)

def units(value):
    value=Decimal(value)
    if not value.is_finite() or value<0 or value*UNIT != (value*UNIT).to_integral_value():
        raise ValueError('invalid monetary amount')
    return int(value*UNIT)

def usage_charge(usage):
    if not isinstance(usage,dict): raise ValueError('missing token usage')
    p,c=usage.get('prompt_tokens'),usage.get('completion_tokens')
    if any(type(x) is not int or x<0 for x in (p,c)):
        raise ValueError('invalid token usage; reservation retained')
    if p>128000 or c>512:
        raise ValueError('usage exceeds model context/output limits; reservation retained')
    return p*INPUT_RATE+c*OUTPUT_RATE

def maximum_charge(request: dict) -> Decimal:
    if request.get('model')!='gpt-4o-mini' or request.get('max_completion_tokens')!=512:
        raise ValueError('unapproved model/output cap')
    # All successfully admitted text requests fit the documented 128K context.
    # No tokenizer guess is used. Failed/uncertain requests retain this bound.
    return Decimal(128000)*INPUT_RATE+Decimal(512)*OUTPUT_RATE

class BudgetLedger:
    def __init__(self,path: Path,cap_usd: Decimal):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if units(cap_usd)!=units(Decimal('10')): raise ValueError('approved cap is $10')
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), cap INTEGER NOT NULL, blocked INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, amount INTEGER NOT NULL, state TEXT NOT NULL)')
            row=db.execute('SELECT cap FROM settings WHERE id=1').fetchone()
            if row is None: db.execute('INSERT INTO settings(id,cap) VALUES(1,?)',(units(cap_usd),))
            elif row[0]!=units(cap_usd): raise ValueError('existing budget cap differs')

    @contextmanager
    def transaction(self):
        db=sqlite3.connect(self.path,timeout=30)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally: db.close()

    def reserve(self,request_id: str,maximum_usd: Decimal) -> str:
        amount=units(maximum_usd)
        if amount<=0: raise ValueError('positive reservation required')
        token=uuid.uuid4().hex
        with self.transaction() as db:
            cap,blocked=db.execute('SELECT cap,blocked FROM settings WHERE id=1').fetchone()
            if blocked: raise ValueError('budget accounting blocked; reconciliation required')
            total=db.execute('SELECT COALESCE(SUM(amount),0) FROM reservations').fetchone()[0]
            if total+amount>cap: raise BudgetExceeded('shared $10 API budget exhausted; run incomplete')
            try:
                db.execute('INSERT INTO reservations VALUES(?,?,?,?)',(token,request_id,amount,'reserved'))
            except sqlite3.IntegrityError as exc: raise ValueError('duplicate request reservation') from exc
        return token

    def settle(self,reservation_id: str,usage: dict) -> Decimal:
        charge=usage_charge(usage)
        amount=units(charge)
        overflow=False
        with self.transaction() as db:
            row=db.execute('SELECT amount,state FROM reservations WHERE id=?',(reservation_id,)).fetchone()
            if row is None or row[1]!='reserved': raise ValueError('unknown or settled reservation')
            overflow=amount>row[0]
            db.execute('UPDATE reservations SET amount=?,state=? WHERE id=?',
                       (amount,'overrun' if overflow else 'settled',reservation_id))
            if overflow: db.execute('UPDATE settings SET blocked=1 WHERE id=1')
        if overflow: raise ValueError('usage exceeds reservation; budget blocked')
        return charge

    def spent_and_reserved(self) -> Decimal:
        with self.transaction() as db:
            total=db.execute('SELECT COALESCE(SUM(amount),0) FROM reservations').fetchone()[0]
        return Decimal(total)/UNIT

    def status(self) -> dict:
        with self.transaction() as db:
            cap,blocked=db.execute('SELECT cap,blocked FROM settings WHERE id=1').fetchone()
            rows=db.execute('SELECT state,SUM(amount),COUNT(*) FROM reservations GROUP BY state').fetchall()
        total=sum(row[1] for row in rows)
        return {'cap_usd':str(Decimal(cap)/UNIT),'spent_and_reserved_usd':str(Decimal(total)/UNIT),
                'remaining_usd':str(max(Decimal(0),Decimal(cap-total)/UNIT)),
                'blocked':bool(blocked),'states':{r[0]:{'usd':str(Decimal(r[1])/UNIT),'count':r[2]} for r in rows}}
