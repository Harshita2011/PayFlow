"""Scan Git-visible working files, excluding ignored secrets/artifacts; redact findings."""
from pathlib import Path
import shutil
import subprocess
import tempfile
from ci_tools import ROOT, install


if __name__=='__main__':
    scanner=install('gitleaks')
    output=ROOT/'test-artifacts'/'gitleaks.json'; output.parent.mkdir(exist_ok=True)
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    with tempfile.TemporaryDirectory(prefix='payflow-source-scan-') as temporary:
        folder=Path(temporary)
        for name in names:
            source=ROOT/name
            if not name or not source.is_file(): continue
            # Never stage private dotenv files even if accidentally added to Git.
            if source.name.startswith('.env') and not source.name.endswith('.example'):
                raise SystemExit('Private environment file is Git-visible; remove it from tracking and rotate credentials.')
            target=folder/name; target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source,target)
        result=subprocess.run([str(scanner),'dir',str(folder),'--redact','--no-banner','--report-format','json',
            '--report-path',str(output)],capture_output=True,text=True)
    print('Secret scan passed' if result.returncode==0 else 'Secret scan failed; inspect the local redacted report, never print candidate secrets.')
    raise SystemExit(result.returncode)
