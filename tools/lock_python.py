"""Lock the tested Python 3.11 dependency closure, using published PyPI artifact hashes."""
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import distribution, PackageNotFoundError
import json
from pathlib import Path
import re
import sys
import urllib.request
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT=Path(__file__).resolve().parents[1]


def inputs(path):
    for line in path.read_text().splitlines():
        value=line.split('#')[0].strip()
        if not value: continue
        if value.startswith('-r '): yield from inputs(path.parent/value[3:].strip())
        else: yield Requirement(value)


def lock(input_path,output_path):
    queue=list(inputs(input_path)); selected={}; extras={}
    environments=[default_environment(),{**default_environment(),'sys_platform':'linux','os_name':'posix',
        'platform_system':'Linux','platform_machine':'x86_64'}]
    while queue:
        requirement=queue.pop()
        name=canonicalize_name(requirement.name)
        try: installed=distribution(name)
        except PackageNotFoundError: raise RuntimeError(f'Install the selected input requirements first: {name}') from None
        if installed.version not in requirement.specifier:
            raise RuntimeError(f'Tested installed version does not satisfy the input: {name}')
        previous=extras.get(name)
        merged=(previous or set())|set(requirement.extras)
        if name in selected and merged==previous: continue
        selected[name]=installed.version; extras[name]=merged
        for raw in installed.requires or []:
            dependency=Requirement(raw)
            if dependency.marker is None or any(dependency.marker.evaluate({**env,'extra':extra})
                for env in environments for extra in merged|{''}):
                queue.append(dependency)
    def hashes(item):
        name,version=item
        cache=ROOT/'.tools'/'pypi-hashes'/f'{name}-{version}.json'
        if cache.exists(): data=json.loads(cache.read_text())
        else:
            url=f'https://pypi.org/pypi/{name}/{version}/json'
            with urllib.request.urlopen(url,timeout=30) as response: data=json.load(response)
            cache.parent.mkdir(parents=True,exist_ok=True)
            cache.write_text(json.dumps(data))
        digests=sorted({row['digests']['sha256'] for row in data['urls'] if not row.get('yanked')})
        if not digests or not all(re.fullmatch(r'[a-f0-9]{64}',x) for x in digests):
            raise RuntimeError(f'No verified non-yanked artifact hashes: {name}')
        return name+'=='+version+' \\\n'+''.join('    --hash=sha256:'+digest+(' \\\n' if i<len(digests)-1 else '\n') for i,digest in enumerate(digests))
    with ThreadPoolExecutor(4) as pool: rows=list(pool.map(hashes,sorted(selected.items())))
    output_path.write_text('# Generated from the tested Python 3.11 environment by tools/lock_python.py.\n'
        '# All transitive versions and published artifact hashes are pinned.\n'+ '\n'.join(rows),encoding='utf-8',newline='\n')
    print(f'{output_path.name}: locked {len(rows)} distributions (no credentials or private index URLs)')


if __name__=='__main__':
    lock(Path(sys.argv[1]),Path(sys.argv[2]))
