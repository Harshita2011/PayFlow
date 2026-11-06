"""Explicit local Compose smoke: synthetic users, real engine, never public/development URLs."""
from decimal import Decimal
import json
import secrets
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from compose_guard import base_url,api_python,docker,owned


def check(condition,message):
    if not condition: raise RuntimeError(message)


def main():
    base=base_url()
    with urlopen(base,timeout=5) as response:
        check(response.status==200,'Frontend failed')
        check(response.headers.get('X-Frame-Options')=='DENY','Frontend security headers missing')
    def call(method,path,body=None,token=None,key=None,grant=None,expected=200):
        headers={'Content-Type':'application/json'}
        if token: headers['Authorization']='Bearer '+token
        if key: headers['Idempotency-Key']=key
        if grant: headers['Payment-Authorization']=grant
        req=Request(base+'/api'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method=method)
        try:
            with urlopen(req,timeout=20) as response: status=response.status; payload=json.load(response)
        except HTTPError as error: status=error.code; payload=json.load(error)
        check(status==expected,f'Smoke step {method} {path.split("/")[1]} returned unexpected status {status}')
        return payload
    call('GET','/health/ready')
    pin='482951'; password=secrets.token_urlsafe(24)
    def person(label):
        email=f'compose-{uuid4().hex}@example.com'
        call('POST','/register',{'full_name':'Compose Demo '+label,'email':email,'password':password},expected=201)
        token=call('POST','/login',{'email':email,'password':password})['access_token']
        call('POST','/security/pin',{'pin':pin,'password':password},token=token,expected=201)
        account=call('POST','/accounts',{'bank_name':'Grove Demo Bank'},token=token,expected=201)
        return {'token':token,'account':account}
    a,b=person('A'),person('B')
    for user,times in [(a,3),(b,1)]:
        for _ in range(times): call('POST','/demo/fund',{},token=user['token'],key=str(uuid4()),expected=201)
    extra=call('POST','/accounts',{'bank_name':'Orbit Demo Bank'},token=a['token'],expected=201)
    call('GET','/accounts/'+str(b['account']['id']),token=a['token'],expected=404)
    direct={'upi_id':b['account']['upi_id'],'source_account_id':a['account']['id'],'amount':'125.50','note':'Compose smoke'}
    call('POST','/payments/transfer',direct,key=str(uuid4()),expected=401)
    call('POST','/payments/transfer',direct,token=a['token'],key=str(uuid4()),expected=403)
    call('POST','/payments/resolve',{'upi_id':b['account']['upi_id']},token=a['token'])
    def pay(user,path,body,operation,reference=None):
        key=str(uuid4()); command={'pin':pin,'operation':operation,'payload':body}
        if reference: command['reference_id']=reference
        grant=call('POST','/security/payment-authorizations',command,token=user['token'],key=key,expected=201)['authorization_token']
        result=call('POST',path,body,token=user['token'],key=key,grant=grant,expected=201)
        check(result['status']=='SUCCESS','Financial posting was not confirmed')
        replay=call('POST',path,body,token=user['token'],key=key,expected=201)
        check(replay['transaction_id']==result['transaction_id'],'Idempotent replay changed receipt')
        return result
    receipt=pay(a,'/payments/transfer',direct,'TRANSFER')
    check(call('GET','/payments/'+receipt['transaction_id'],token=b['token'])['amount']=='125.50','Recipient receipt mismatch')
    collect=call('POST','/payment-requests',{'upi_id':a['account']['upi_id'],'amount':'10.00','note':'Compose request'},
        token=b['token'],key=str(uuid4()),expected=201)
    pay(a,'/payment-requests/'+collect['id']+'/pay',{'source_account_id':a['account']['id']},'REQUEST',collect['id'])
    split=call('POST','/splits',{'title':'Compose shared expense','total_amount':'20.00','mode':'EQUAL',
        'include_creator':True,'participants':[{'upi_id':b['account']['upi_id']}]},token=a['token'],key=str(uuid4()),expected=201)
    contribution=next(x['request_id'] for x in split['participants'] if not x['is_creator_share'])
    pay(b,'/payment-requests/'+contribution+'/pay',{'source_account_id':b['account']['id']},'REQUEST',contribution)
    check(call('GET','/splits/'+split['id'],token=a['token'])['status']=='SETTLED','Split did not settle')
    pay(a,'/payments/self-transfer',{'source_account_id':a['account']['id'],'destination_account_id':extra['id'],'amount':'20.00'},'SELF_TRANSFER')
    pay(a,'/recharge',{'source_account_id':a['account']['id'],'mobile':'9876543210','plan_id':'payflow-mobile-99'},'MOBILE_RECHARGE')
    bill=call('POST','/bills/lookup',{'biller_id':'water','reference':'DEMO000001'},token=a['token'])
    pay(a,'/bills/'+bill['id']+'/pay',{'source_account_id':a['account']['id']},'BILL_PAYMENT',bill['id'])
    accounts_a=call('GET','/accounts',token=a['token']); accounts_b=call('GET','/accounts',token=b['token'])
    check(sum(Decimal(x['balance']) for x in accounts_a+accounts_b)==Decimal('4000')-Decimal('99')-Decimal(bill['amount_due']),'Total funds/settlement mismatch')
    check(Decimal(accounts_b[0]['balance'])==Decimal('1125.50'),'Recipient balance mismatch')
    check(len(call('GET','/payments/history?limit=50',token=a['token'])['items'])>=8,'History incomplete')
    until=time.monotonic()+15
    while time.monotonic()<until:
        if len(call('GET','/activity/notifications?limit=50',token=a['token'])['items'])>=9: break
        time.sleep(.3)
    else: raise RuntimeError('Worker did not deliver expected activity')
    result=api_python("from database import engine; from reconcile import reconcile; import json;\nwith engine.connect() as c: print(json.dumps(reconcile(c)))")
    reconciliation=json.loads(result)
    check(reconciliation['balanced'] and not any(v for k,v in reconciliation.items() if k!='balanced'),'Ledger reconciliation failed')
    for service in ['api','worker']:
        check(docker('exec',owned(service),'id','-u').strip()=='10001','Backend process is not non-root')
    restricted=docker('exec',owned('worker'),'python','-c',
        "from database import engine; from sqlalchemy import text;\nwith engine.connect() as c: print(c.scalar(text(\"SELECT has_table_privilege(current_user,'payments','INSERT') OR has_column_privilege(current_user,'bank_accounts','balance','UPDATE')\")))").strip()
    check(restricted=='False','Worker has financial write privileges')
    print('Local Compose smoke passed: authentication/PIN, accounts, funding, transfer/replay, requests, split settlement, self-transfer, recharge, bills, receipts/history, worker activity, non-root roles, restricted worker and reconciliation.')


if __name__=='__main__': main()
