"""Analyze application modules, never vendored environments or generated artifacts."""
from pathlib import Path
import subprocess
import sys

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    output=root/'test-artifacts'/'bandit.json'; output.parent.mkdir(exist_ok=True)
    files=sorted(str(p) for p in (root/'backend').glob('*.py'))
    raise SystemExit(subprocess.run([sys.executable,'-m','bandit',*files,'-ll','-f','json','-o',str(output)]).returncode)
