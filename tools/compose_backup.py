"""Backup + restore exercise in a NEW verified local Compose database. No overwrite/reset option."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from uuid import uuid4
from compose_guard import ROOT,owned,docker,api_python

SNAPSHOT="""
import hashlib,json,sys
from sqlalchemy import create_engine,inspect,text
from database import engine
target=sys.stdin.read().strip()
if target: engine=create_engine(engine.url.set(database=target))
with engine.connect().execution_options(isolation_level='REPEATABLE READ') as c:
 c.execute(text('SET TRANSACTION READ ONLY'))
 result={}
 for name in inspect(c).get_table_names():
  identifier=c.dialect.identifier_preparer.quote(name)
  rows=sorted(c.execute(text('SELECT row_to_json(t)::text FROM '+identifier+' t')).scalars())
  result[name]=hashlib.sha256(json.dumps(rows).encode()).hexdigest()
 print(json.dumps(result))
"""


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['exercise'])
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    source=owned('postgres'); owned('api')
    output=args.output.resolve(); folder=(ROOT/'backups').resolve()
    if not output.is_relative_to(folder): raise SystemExit('Private backup output must be inside the ignored backups directory')
    checksum_file=output.with_suffix(output.suffix+'.sha256')
    if output.exists() or checksum_file.exists(): raise SystemExit('Existing backup or checksum preserved; choose a new output filename')
    output.parent.mkdir(exist_ok=True,parents=True)
    before=json.loads(api_python(SNAPSHOT))
    fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:
        result=subprocess.run(['docker','exec',source,'pg_dump','-U','payflow_admin','-d','payflow_demo','--format=custom','--no-owner'],stdout=stream,stderr=subprocess.PIPE)
    if result.returncode: raise SystemExit('Backup failed; private partial file retained for operator inspection')
    digest=hashlib.file_digest(output.open('rb'),'sha256').hexdigest()
    with checksum_file.open('x') as stream: stream.write(digest+'\n')
    if before!=json.loads(api_python(SNAPSHOT)):
        raise SystemExit('Source changed during exercise; backup is retained, no restore attempted. Quiesce only the owned local demo before retrying.')
    target='payflow_restore_'+uuid4().hex+'_tests'
    if not re.fullmatch(r'payflow_restore_[a-f0-9]{32}_tests',target): raise SystemExit('Invalid generated restore target')
    exists=docker('exec',source,'psql','-U','payflow_admin','-d','postgres','-At','-c',f"SELECT 1 FROM pg_database WHERE datname='{target}'").strip()
    if exists: raise SystemExit('Restore target already exists; no overwrite permitted')
    docker('exec',source,'createdb','-U','payflow_admin','--owner','payflow_owner',target)
    check=hashlib.file_digest(output.open('rb'),'sha256').hexdigest()
    if check!=digest: raise SystemExit('Backup checksum changed; no restore performed')
    with output.open('rb') as stream:
        result=subprocess.run(['docker','exec','-i',source,'pg_restore','-U','payflow_admin','-d',target,'--no-owner','--exit-on-error'],stdin=stream,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if result.returncode: raise SystemExit('Restore failed in the new isolated database; source unchanged, restore target retained')
    after=json.loads(api_python(SNAPSHOT,input=target))
    if before!=after: raise SystemExit('Restored records differ; both source and restore database are retained')
    script="""
import json,sys
from sqlalchemy import create_engine
from database import engine
from reconcile import reconcile
target=sys.stdin.read().strip()
engine=create_engine(engine.url.set(database=target))
with engine.connect() as c: result=reconcile(c)
assert result['balanced'] and not any(v for k,v in result.items() if k!='balanced')
print('Restored ledger reconciliation passed')
"""
    print(api_python(script,input=target).strip())
    print('Backup/restore passed: checksum verified, all table records identical, source unchanged; NEW restore database retained:',target)
