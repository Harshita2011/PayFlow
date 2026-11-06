"""Bounded local HTTP smoke + resource samples. Start isolated_server.py first."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import requests

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['financial','mixed'],default='mixed')
    parser.add_argument('--duration',type=int,choices=range(6,13),default=8)
    parser.add_argument('--users',type=int,choices=range(1,13),default=12)
    args=parser.parse_args()
    env={**os.environ,'BENCH_MODE':args.mode,'BENCH_TARGET_TPS':'10',
         'BENCH_REPORT':f'benchmarks/results/http-{args.mode}-smoke.json'}
    headers={'X-Benchmark-Key':env.get('PAYFLOW_BENCH_KEY','')}
    first=requests.get('http://127.0.0.1:18017/__benchmark/report',headers=headers,timeout=5)
    first.raise_for_status()
    if first.json()['committed']!=0: raise RuntimeError('Use a fresh isolated fixture for a comparable report')
    samples=[]
    with Path('.verification-locust-'+args.mode+'.log').open('w') as log:
        process=subprocess.Popen([sys.executable,'-m','locust','-f','benchmarks/locustfile.py','--host','http://127.0.0.1:18017',
            '--headless','--users',str(args.users),'--spawn-rate',str(args.users),'--run-time',str(args.duration)+'s',
            '--stop-timeout','10','--only-summary'],env=env,stdout=log,stderr=subprocess.STDOUT)
        while process.poll() is None:
            row={'timestamp':time.time()}
            try:
                docker=subprocess.run(['docker','stats','--no-stream','--format','{{.CPUPerc}}|{{.MemUsage}}','payflow-postgres-5436'],
                    capture_output=True,text=True,timeout=4)
                row['postgres_container_cpu_and_memory']=docker.stdout.strip()
                row['db']=requests.get('http://127.0.0.1:18017/__benchmark/report',headers=headers,timeout=5).json()
            except (OSError,subprocess.TimeoutExpired,requests.RequestException):
                row['sample_unavailable']=True
            samples.append(row); time.sleep(.5)
    Path(f'benchmarks/results/resources-{args.mode}.json').write_text(json.dumps(samples,indent=2)+'\n')
    print(Path(env['BENCH_REPORT']).read_text() if Path(env['BENCH_REPORT']).exists() else 'No benchmark summary produced')
    raise SystemExit(process.returncode)
