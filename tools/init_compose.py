"""Create a NEW private local Compose environment; never overwrite an existing file."""
import os
from pathlib import Path
import secrets

if __name__=='__main__':
    target=Path(__file__).resolve().parents[1]/'.env.compose'
    values={name:secrets.token_hex(32) for name in ['POSTGRES_ADMIN_PASSWORD','PAYFLOW_OWNER_PASSWORD',
        'PAYFLOW_APP_PASSWORD','PAYFLOW_WORKER_PASSWORD','JWT_SECRET_KEY','WORKER_CONFIG_KEY']}
    values.update({'PAYFLOW_HTTP_PORT':'18080','MIGRATION_EXPECTED_REVISION':'base','PAYFLOW_OPS_TOKEN':''})
    try:
        descriptor=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        raise SystemExit('Existing .env.compose preserved; no changes made.')
    with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as stream:
        stream.write('\n'.join(f'{key}={value}' for key,value in values.items())+'\n')
    print('Created private .env.compose; values are not printed. Review local file permissions.')
