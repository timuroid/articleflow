import json
from pathlib import Path
from articleflow.docx_engine import parse_xml
from articleflow.typography019 import stable_xml
rows=[]
for path in [Path('artifacts/agent028-live/bmstu/learning/iteration-8'),Path('artifacts/agent029-live/herzen/learning/iteration-7'),Path('artifacts/agent030-general/canterbury/learning/iteration-2')]:
 if not (path/'training-conflicts.json').exists():continue
 template=json.loads((path/'template/rules.json').read_text());conflicts=json.loads((path/'training-conflicts.json').read_text());resolved=0
 for c in conflicts:
  kind=c['kind'];group=c.get('when',{}).get('kind') if kind=='layout' else kind
  if kind not in {'paragraph','character'}:continue
  variants={e['set']['style'] for e in c['examples']};keys=set()
  for k in variants:keys.add(tuple(stable_xml(parse_xml(x.encode())) for x in template['styles'][group][k]))
  resolved+=len(keys)==1
 row={'case':str(path.parent.parent.name),'iteration':path.name,'conflicts':len(conflicts),'resolved_by_property_order_only':resolved};rows.append(row);print(row)
Path('artifacts/property-order030.json').write_text(json.dumps(rows,indent=2))
