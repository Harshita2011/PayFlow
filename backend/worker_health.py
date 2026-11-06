"""Local container heartbeat probe; no public endpoint or sensitive payload."""
import json
import os
from pathlib import Path
import time


def heartbeat():
    name=os.getenv('WORKER_HEARTBEAT_FILE')
    if name:
        target=Path(name)
        temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps({'monotonic':time.monotonic()}),encoding='utf-8')
        temporary.replace(target)


if __name__=='__main__':
    try:
        target=Path(os.environ['WORKER_HEARTBEAT_FILE'])
        age=time.monotonic()-json.loads(target.read_text())['monotonic']
        raise SystemExit(0 if 0<=age<=60 else 1)
    except (OSError,ValueError,KeyError,TypeError):
        raise SystemExit(1)
