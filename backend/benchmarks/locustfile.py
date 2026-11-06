"""Real HTTP workload. Loopback isolated_server.py only; no public/development targets."""
import json
import os
from pathlib import Path
import random
import math
import time
from uuid import uuid4
from locust import HttpUser, task, between, events
import requests
import gevent
from locust.exception import StopUser

HOST='http://127.0.0.1:18017'
DATA=None
TOTALS={'new_commit_responses':0,'financial_failures':0,'idempotent_replays':0,'uncertain':0}
START=0
END=0
COUNTER=0
COMMIT_LATENCIES=[]


@events.test_start.add_listener
def start(environment,**kwargs):
    global DATA,START
    if environment.host!=HOST: raise RuntimeError('Only the isolated loopback benchmark server is allowed')
    key=os.environ.get('PAYFLOW_BENCH_KEY','')
    response=requests.get(HOST+'/__benchmark/bootstrap',headers={'X-Benchmark-Key':key},timeout=10)
    response.raise_for_status(); DATA=response.json()
    if not DATA.get('isolated'): raise RuntimeError('Missing isolated benchmark identity')
    START=time.perf_counter()
    if os.getenv('BENCH_ALLOW_SUSTAINED')!='1':
        gevent.spawn_later(20,environment.runner.quit)


@events.test_stop.add_listener
def finish(environment,**kwargs):
    global END
    END=time.perf_counter()
    report=requests.get(HOST+'/__benchmark/report',headers={'X-Benchmark-Key':os.environ.get('PAYFLOW_BENCH_KEY','')},timeout=10).json()
    # Includes the small graceful in-flight drain, not just the requested run-time.
    duration=END-START
    http=[s for s in environment.stats.entries.values()]
    def percentile(p):
        values=sorted(COMMIT_LATENCIES)
        return round(values[max(0,math.ceil(len(values)*p)-1)],2) if values else None
    summary={**TOTALS,**report,'seconds':round(duration,3),'committed_tps':round(report['committed']/duration,3),
        'http_requests':sum(s.num_requests for s in http),'http_failures':sum(s.num_failures for s in http),
        'http_rps':round(sum(s.num_requests for s in http)/duration,3),
        'http_p50_ms':environment.stats.total.get_response_time_percentile(.5),
        'http_p95_ms':environment.stats.total.get_response_time_percentile(.95),
        'http_p99_ms':environment.stats.total.get_response_time_percentile(.99),
        'http_routes':[{'name':s.name,'method':s.method,'requests':s.num_requests,'failures':s.num_failures} for s in http],
        'committed_intent_p50_ms':percentile(.5),'committed_intent_p95_ms':percentile(.95),
        'committed_intent_p99_ms':percentile(.99),'intent_latency_samples':len(COMMIT_LATENCIES),
        'users':len(DATA['users']),'source_accounts':len(DATA['users']),'owned_accounts':len(DATA['users'])*2,'api_workers':1,
        'security_overrides':False,'mode':os.getenv('BENCH_MODE','mixed'),'target_financial_tps':os.getenv('BENCH_TARGET_TPS','10')}
    output=Path(os.environ.get('BENCH_REPORT','benchmarks/results/http-smoke.json'))
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(summary,indent=2)+'\n')
    print('BENCHMARK_RESULT '+json.dumps(summary))


class PayFlowUser(HttpUser):
    wait_time=between(.5,1)
    def on_start(self):
        global COUNTER
        if self.host!=HOST or DATA is None: raise StopUser()
        self.index=COUNTER%len(DATA['users']); COUNTER+=1
        self.person=DATA['users'][self.index]
        self.other=DATA['users'][(self.index+1)%len(DATA['users'])]
        self.sequence=0
    def headers(self,person=None): return {'Authorization':'Bearer '+(person or self.person)['token']}
    def post(self,path,body,*,person=None,key=None,name=None):
        headers=self.headers(person)
        if key: headers['Idempotency-Key']=key
        return self.client.post(path,json=body,headers=headers,name=name or path,timeout=15)
    def pay(self,path,body,operation,*,person=None,reference=None):
        started=time.perf_counter()
        person=person or self.person
        key=str(uuid4()); command={'pin':DATA['pin'],'operation':operation,'payload':body}
        if reference: command['reference_id']=reference
        grant=self.post('/security/payment-authorizations',command,person=person,key=key)
        if grant.status_code!=201: TOTALS['financial_failures']+=1; return
        headers={**self.headers(person),'Idempotency-Key':key,'Payment-Authorization':grant.json()['authorization_token']}
        result=self.client.post(path,json=body,headers=headers,name='/payments/intent/'+operation,timeout=15)
        if result.status_code in (200,201):
            if result.headers.get('Payment-Posted')=='true':
                TOTALS['new_commit_responses']+=1
                if len(COMMIT_LATENCIES)<10000: COMMIT_LATENCIES.append((time.perf_counter()-started)*1000)
            elif result.headers.get('Idempotency-Replayed')=='true': TOTALS['idempotent_replays']+=1
        elif result.status_code in (0,503): TOTALS['uncertain']+=1
        else: TOTALS['financial_failures']+=1
        if os.getenv('BENCH_REPLAY')=='1' and result.status_code==201:
            replay=self.client.post(path,json=body,headers=headers,name='/payments/replay/'+operation,timeout=15)
            if replay.headers.get('Idempotency-Replayed')=='true': TOTALS['idempotent_replays']+=1

    @task
    def workload(self):
        self.sequence+=1
        if os.getenv('BENCH_MODE')=='financial':
            # Open-loop-ish pacing per actor; report achieved rate, never equate target with throughput.
            start=time.perf_counter()
            self.direct()
            self.wait_time=lambda: max(0,self.environment.runner.target_user_count/float(os.getenv('BENCH_TARGET_TPS','10'))-(time.perf_counter()-start))
            return
        choice=random.Random(self.index*100000+self.sequence).randrange(100)
        if choice<20: self.client.get('/accounts',headers=self.headers(),name='/accounts')
        elif choice<35: self.client.get('/payments/history?limit=10',headers=self.headers(),name='/payments/history')
        elif choice<40: self.post('/login',{'email':self.person['email'],'password':DATA['password']})
        elif choice<45: self.post('/payments/resolve',{'upi_id':self.other['upi']})
        elif choice<65: self.direct()
        elif choice<73: self.pay('/payments/self-transfer',{'source_account_id':self.person['source'],
            'destination_account_id':self.person['destination'],'amount':'1.00'},'SELF_TRANSFER')
        elif choice<80: self.request_payment(False)
        elif choice<87: self.request_payment(True)
        elif choice<94: self.pay('/recharge',{'mobile':'9876543210','plan_id':'payflow-mobile-99',
            'source_account_id':self.person['source']},'MOBILE_RECHARGE')
        else:
            bill=self.post('/bills/lookup',{'biller_id':'water','reference':f'DEMO{self.index*1000+self.sequence:06}'})
            if bill.status_code==200:
                self.pay('/bills/'+bill.json()['id']+'/pay',{'source_account_id':self.person['source']},'BILL_PAYMENT',reference=bill.json()['id'])
    def direct(self):
        destination=DATA['users'][0] if os.getenv('BENCH_HOT')=='1' and self.index!=0 else self.other
        self.pay('/payments/transfer',{'upi_id':destination['upi'],'amount':'1.00',
            'source_account_id':self.person['source'],'note':'Synthetic load'},'TRANSFER')
    def request_payment(self,split):
        if split:
            created=self.post('/splits',{'title':'Synthetic expense','total_amount':'2.00','include_creator':True,
                'mode':'EQUAL','participants':[{'upi_id':self.other['upi']}]},key=str(uuid4()))
            if created.status_code!=201: return
            reference=next(p['request_id'] for p in created.json()['participants'] if not p['is_creator_share'])
        else:
            created=self.post('/payment-requests',{'upi_id':self.other['upi'],'amount':'1.00','note':'Synthetic request'},key=str(uuid4()))
            if created.status_code!=201: return
            reference=created.json()['id']
        self.pay('/payment-requests/'+reference+'/pay',{'source_account_id':self.other['source']},'REQUEST',person=self.other,reference=reference)
