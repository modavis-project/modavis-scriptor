#!/usr/bin/env python3
"""Run only against a disposable graphics instance: writes explicit QA decisions."""
import hashlib
import http.client
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

base=sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8310'
if ':8010' in base or ':3000' in base:
    raise SystemExit('Refusing to write QA decisions to the normal research service.')
run='example-organ-stops-v1'

for _ in range(120):
    try:
        with urllib.request.urlopen(base+'/health',timeout=2) as response:
            if response.status == 200:
                break
    except (OSError, http.client.HTTPException):
        time.sleep(1)
else:
    raise SystemExit('Test service did not become ready within 120 seconds')


def request(path,method='GET',payload=None,expected=200,headers=None):
    body=json.dumps(payload).encode() if payload is not None else None
    headers={'Content-Type':'application/json',**(headers or {})}
    try:
        response=urllib.request.urlopen(urllib.request.Request(base+path,data=body,method=method,headers=headers),timeout=120)
        code=response.status;raw=response.read()
    except urllib.error.HTTPError as e:
        code=e.code;raw=e.read()
    assert code==expected,(path,code,expected,raw[:500])
    try:return json.loads(raw)
    except (json.JSONDecodeError,UnicodeDecodeError):return raw


for _ in range(180):
    data=request('/runs/'+run)
    if data['run']['status']=='completed':break
    assert data['run']['status']!='failed',data
    time.sleep(1)
else:raise AssertionError('Example did not finish')
result=data['result'];original_hash=result['immutable_result_sha256']
assert len(result['regions'])==21
assert sum(r['clipped'] for r in result['regions'])==3
assert not result['review_events']
assert all(r['effective']==r['parsed'] for r in result['regions'])
assert result['image']['width']==3024 and result['image']['height']==4032
assert result['regions'][2]['parsed']['name']=='Scharff'
assert result['regions'][3]['parsed']['specification']=='11/3'
for region in result['regions']:
    x,y,w,h=region['bbox_normalized']
    assert 0<=x<=1 and 0<=y<=1 and 0<w<=1 and 0<h<=1 and x+w<=1.00001 and y+h<=1.00001
assert result['paradata']['corpus']['input_components']==503980
path=f'/runs/{run}/regions/r003/review'
payload={'action':'accept','reviewer':'QA (automated test)','rationale':'TEST ONLY: manuscript spelling must remain distinct.','name':'Scharf','specification':'IV-VI','kind':'stop','division':'','expected_version':0}
request(path,'PATCH',{**payload,'rationale':''},422)
request(path,'PATCH',{**payload,'reviewer':'  '},422)
request(path,'PATCH',{**payload,'candidate_id':-999},422)
request(path,'PATCH',payload,403,headers={'Origin':'https://untrusted.example'})
accepted=request(path,'PATCH',payload)
assert accepted['regions'][2]['effective']['name']=='Scharf'
assert accepted['regions'][2]['raw_text']==result['regions'][2]['raw_text']
assert '| 3 | Scharf |' in accepted['markdown']
request(path,'PATCH',payload,409)
retained=request(path,'PATCH',{**payload,'action':'retain','expected_version':1})
assert retained['regions'][2]['effective']['name']=='Scharff'
deferred=request(path,'PATCH',{**payload,'action':'defer','expected_version':2})
assert deferred['regions'][2]['effective']==result['regions'][2]['parsed']
assert len(deferred['review_events'])==3 and deferred['immutable_result_sha256']==original_hash
request(f'/runs/{run}/rerun','POST',{'regions':[[.9,.9,.3,.3]]},422)
child=request(f'/runs/{run}/rerun','POST',{'mode':'graphics','regions':[[.167,.13,.12,.1]]},202)['id']
for _ in range(120):
    rerun=request('/runs/'+child)
    if rerun['run']['status']=='completed':break
    assert rerun['run']['status']!='failed',rerun
    time.sleep(1)
else:raise AssertionError('Graphics run did not finish')
assert rerun['run']['parent_id']==run
assert rerun['result']['paradata']['corpus'] is None
assert not any(r['candidates'] for r in rerun['result']['regions'])
assert rerun['result']['image']['sha256']==result['image']['sha256']
bundle=request(f'/runs/{run}/export?format=bundle')
with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
    assert {'original','image.png','result.json','reviewed.json','reviewed.md','raw.md','table.csv','source.json','regions.svg'}<=set(archive.namelist())
    assert hashlib.sha256(archive.read('original')).hexdigest()==result['image']['sha256']
    assert hashlib.sha256(archive.read('result.json')).hexdigest()==original_hash
    assert 'Tucker501' in archive.read('source.json').decode()
    assert 'text-anchor="end"' in archive.read('regions.svg').decode()
report={'status':'passed','api':base,'example':run,'checks':['21 regions / 3 clipped','EXIF coordinates','corpus provenance','no automatic normalization','rationale and identity gates','invalid candidate rejected','cross-origin rejection','accept updates Markdown','raw OCR immutable','stale decision conflict','retain and defer revert to raw','append-only history materialization','ROI bounds','new child run','general graphics corpus isolation','ZIP fixity and attribution'],'qa_child_run':child,'result_sha256':original_hash}
print(json.dumps(report,indent=2))
