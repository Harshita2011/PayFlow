"""Parse workflow YAML and use pinned upstream actionlint, without running GitHub jobs."""
from pathlib import Path
import re
import subprocess
import yaml
from ci_tools import ROOT,install

if __name__=='__main__':
    files=sorted((ROOT/'.github/workflows').glob('*.yml'))
    if not files: raise SystemExit('Missing CI workflows')
    for file in files:
        data=yaml.safe_load(file.read_text())
        assert data['permissions']=={'contents':'read'},'Unexpected workflow permission escalation'
        for line in file.read_text().splitlines():
            if 'uses:' in line and not re.search(r'uses: actions/[a-z-]+@[a-f0-9]{40}(?:\s|$)',line):
                raise RuntimeError('Actions must use verified immutable SHAs')
    raise SystemExit(subprocess.run([str(install('actionlint')),'-shellcheck=','-pyflakes=',*map(str,files)],cwd=ROOT).returncode)
