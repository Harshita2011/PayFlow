"""Operate only this repository's isolated Compose resources; never the development container."""
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
PROJECT='payflow-demo'


def docker(*args, input=None, binary=False):
    result=subprocess.run(['docker',*args],input=input,capture_output=True,text=not binary,cwd=ROOT)
    if result.returncode: raise RuntimeError('Owned Compose command failed; inspect local container diagnostics without publishing secrets')
    return result.stdout


def owned(service):
    name=f'{PROJECT}-{service}-1'
    labels=json.loads(docker('inspect','--format','{{json .Config.Labels}}',name))
    if labels.get('com.docker.compose.project')!=PROJECT or labels.get('com.docker.compose.service')!=service:
        raise RuntimeError('Refusing an unverified Compose target')
    return name


def api_python(script, input=None):
    return docker('exec','-i',owned('api'),'python','-B','-c',script,input=input)


def base_url():
    ports=json.loads(docker('inspect','--format','{{json .NetworkSettings.Ports}}',owned('frontend')))
    binding=ports['8080/tcp'][0]
    if binding['HostIp']!='127.0.0.1': raise RuntimeError('Local smoke requires a loopback-only frontend port')
    database=api_python('from database import engine; print(engine.url.database)').strip()
    if database!='payflow_demo': raise RuntimeError('Local smoke refuses non-demo database targets')
    owned('postgres')
    return 'http://127.0.0.1:'+binding['HostPort']
