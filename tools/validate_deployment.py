"""Local safety validation; not a substitute for provider-account validation or approval."""
import json
from pathlib import Path
import yaml

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    blueprint=yaml.safe_load((root/'render.yaml').read_text())
    assert 'databases' not in blueprint,'Managed DB creation requires separate approval'
    for group in blueprint.get('envVarGroups',[]):
        assert not any(value.get('sync') is False for value in group['envVars']),'Render ignores sync:false in groups'
    for service in blueprint['services']:
        assert service['autoDeployTrigger']=='off'
        assert service['runtime']=='docker'
        values={x.get('key'):x for x in service['envVars'] if 'key' in x}
        assert values['DATABASE_URL'].get('sync') is False
        assert values['CORS_ALLOWED_ORIGINS'].get('sync') is False
    api=next(s for s in blueprint['services'] if s['type']=='web')
    assert api['preDeployCommand']=='python -m migrate','Public release hook must not silently upgrade schemas'
    vercel=json.loads((root/'frontend/vercel.json').read_text())
    assert vercel['git']['deploymentEnabled'] is False
    assert vercel['outputDirectory']=='dist'
    print('Local provider safety checks passed; no cloud account or deployment was used.')
