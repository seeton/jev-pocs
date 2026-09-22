"""Synthetic measured parts and a fully specified inspection standard."""
import random
import time
import requests

MODEL='jev-preview'
LABELS={'pass':'良品','reject':'不良品','review':'要確認'}
FIELDS={'width_mm':'幅 mm','weight_g':'重量 g','scratch_mm':'傷 mm','color_delta':'色差','label_ok':'ラベル'}
RULES=('Reject if ANY available measurement violates its inclusive allowed range, '
       'scratch or color exceeds its maximum, or label_ok is false. '
       'Otherwise review if ANY measurement is null (unavailable). '
       'Otherwise pass. Exact boundary values pass. Known failures override missing data. '
       'Use the specification of this product, not other products. No images are provided.')

def make_batch(seed=7,count=24):
    rng=random.Random(seed); items=[]
    cases=['good','boundary','width','weight','scratch','color','label','missing','missing_bad','good','good','good']
    for i in range(count):
        grade=rng.choice(['standard','premium'])
        spec={'width_mm':[49.5,50.5],'weight_g':[97,103],
              'scratch_mm_max':0.3 if grade=='premium' else 1.0,
              'color_delta_max':2 if grade=='premium' else 4,'label_required':True}
        m={'width_mm':round(rng.uniform(49.6,50.4),2),'weight_g':round(rng.uniform(98,102),1),
           'scratch_mm':0.1,'color_delta':1,'label_ok':True}
        case=cases[i%len(cases)]; expected='pass'
        if case=='boundary':m.update(width_mm=50.5,weight_g=97,scratch_mm=spec['scratch_mm_max'],color_delta=spec['color_delta_max'])
        elif case=='width':m['width_mm']=49.3;expected='reject'
        elif case=='weight':m['weight_g']=104;expected='reject'
        elif case=='scratch':m['scratch_mm']=round(spec['scratch_mm_max']+0.2,1);expected='reject'
        elif case=='color':m['color_delta']=spec['color_delta_max']+0.5;expected='reject'
        elif case=='label':m['label_ok']=False;expected='reject'
        elif case=='missing':m[rng.choice(list(FIELDS))]=None;expected='review'
        elif case=='missing_bad':m.update(weight_g=None,label_ok=False);expected='reject'
        items.append({'grade':grade,'specification':spec,'measurements':m,'expected':expected,'case':case})
    rng.shuffle(items)
    for i,item in enumerate(items):item['id']=f'P{i+1:03d}'
    return items

def payload(item):
    return {'product_id':item['id'],'grade':item['grade'],'specification':dict(item['specification']),
            'measurements':dict(item['measurements']),'inspection_rules':RULES}

def rule_decision(item):
    m=item['measurements'];s=item['specification'];failed=[]
    for field in ('width_mm','weight_g'):
        if m[field] is not None and not s[field][0]<=m[field]<=s[field][1]:failed.append(field)
    for field in ('scratch_mm','color_delta'):
        if m[field] is not None and m[field]>s[field+'_max']:failed.append(field)
    if m['label_ok'] is False:failed.append('label_ok')
    if failed:return 'reject',failed
    if any(v is None for v in m.values()):return 'review',['missing_measurement']
    return 'pass',[]

def decide(key,state):
    start=time.perf_counter()
    result={'state':state,'requested_model':MODEL}
    try:
        response=requests.post('https://api.typesafe.ai/v1/systemone',
            headers={'Authorization':f'Bearer {key}'},json={'model':MODEL,'state':state,'questions':{
                'verdict':{'type':'choice','instructions':'Apply the provided inspection rules exactly to this product.',
                'criteria':{'pass':'All checks present and within specification.','reject':'At least one known failed check.',
                            'review':'Missing measurement, with no known failed check.'}}}},timeout=(3,4),allow_redirects=False)
        if response.status_code!=200:
            result.update(error=f'HTTP {response.status_code}',fatal=response.status_code in (400,401,402,403,404,422,429))
        else:
            data=response.json(); answer=data['answers']['verdict'];verdict=answer['choice']
            if verdict not in LABELS:raise ValueError('Unexpected verdict')
            result.update(verdict=verdict,confidence=answer.get('confidence'),model=data.get('model'),usage=data.get('usage',{}))
    except requests.RequestException:result['error']='通信エラー / タイムアウト'
    except (KeyError,ValueError,TypeError):result['error']='不正なAPI応答'
    result['latency_ms']=round((time.perf_counter()-start)*1000,1)
    return result

def metrics(records,field):
    completed=[r for r in records if r.get('finalized')]
    counts={k:sum(r[field]==k for r in completed) for k in LABELS}
    counts.update(total=len(completed),correct=sum(r[field]==r['item']['expected'] for r in completed),
        misses=sum(r['item']['expected']=='reject' and r[field]=='pass' for r in completed),
        false_rejects=sum(r['item']['expected']=='pass' and r[field]=='reject' for r in completed))
    return counts
