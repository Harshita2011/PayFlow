"""Install checksum-pinned upstream CLI tools in ignored .tools, never execute downloads unchecked."""
import hashlib
import io
from pathlib import Path
import platform
import sys
import tarfile
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TOOLS={
 'gitleaks': ('gitleaks/gitleaks','8.30.0',{
  'Windows':('windows_x64.zip','54fe94f644b832dd08e8c3a5915efb3bfa862386d59fb27ca0792cb687a83573'),
  'Linux':('linux_x64.tar.gz','79a3ab579b53f71efd634f3aaf7e04a0fa0cf206b7ed434638d1547a2470a66e')}),
 'actionlint': ('rhysd/actionlint','1.7.7',{
  'Windows':('windows_amd64.zip','7f12f1801bca3d480d67aaf7774f4c2a6359a3ca8eebe382c95c10c9704aa731'),
  'Linux':('linux_amd64.tar.gz','023070a287cd8cccd71515fedc843f1985bf96c436b7effaecce67290e7e0757')})}


def install(name):
    repo,version,systems=TOOLS[name]
    if platform.machine().lower() not in {'amd64','x86_64'}: raise RuntimeError('Tool manifest supports x64 only')
    suffix,digest=systems[platform.system()]
    archive=f'{name}_{version}_{suffix}'
    folder=ROOT/'.tools'; folder.mkdir(exist_ok=True)
    cached=folder/archive
    if not cached.exists():
        with urllib.request.urlopen(f'https://github.com/{repo}/releases/download/v{version}/{archive}',timeout=45) as response:
            data=response.read()
        if hashlib.sha256(data).hexdigest()!=digest: raise RuntimeError('Upstream tool checksum mismatch')
        cached.write_bytes(data)
    data=cached.read_bytes()
    if hashlib.sha256(data).hexdigest()!=digest: raise RuntimeError('Cached tool checksum mismatch')
    binary=name+('.exe' if platform.system()=='Windows' else '')
    if suffix.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as package: contents=package.read(binary)
    else:
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as package: contents=package.extractfile(binary).read()
    target=folder/binary; target.write_bytes(contents); target.chmod(0o700)
    return target


if __name__=='__main__':
    for name in sys.argv[1:] or TOOLS: print('Verified CLI:',install(name).name)
