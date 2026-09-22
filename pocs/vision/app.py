"""Inspect real MVTec photographs locally and optionally route features with Jev."""
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import argparse
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pygame
import requests
from PIL import Image
from pocs.common.paths import ROOT
from pocs.common.ui import buttons,clicked
from pocs.inspection.core import MODEL,LABELS
from .data import DATA,paths,fetch,samples,REVISION
from .model import Detector,decision_state,GRID

def ask(key,state):
    start=time.perf_counter();result={'state':state,'requested_model':MODEL}
    try:
        r=requests.post('https://api.typesafe.ai/v1/systemone',headers={'Authorization':f'Bearer {key}'},
            json={'model':MODEL,'state':state,'questions':{'route':{'type':'choice',
            'instructions':'Apply the supplied numeric routing policy exactly. You are NOT detecting defects from images.',
            'criteria':{'pass':'Score ratio below 0.8.','review':'Score ratio from 0.8 through 1.2 inclusive.',
                        'reject':'Score ratio above 1.2.'}}}},timeout=(3,5),allow_redirects=False)
        if r.status_code!=200:result['error']=f'HTTP {r.status_code}'
        else:
            data=r.json();answer=data['answers']['route']
            if answer['choice'] not in LABELS:raise ValueError('Invalid choice')
            result.update(verdict=answer['choice'],confidence=answer.get('confidence'),model=data.get('model'))
    except requests.RequestException:result['error']='通信エラー'
    except (KeyError,ValueError,TypeError):result['error']='不正な応答'
    result['latency_ms']=round((time.perf_counter()-start)*1000,1);return result

def prepare():
    if not all((DATA/name).is_file() for name in paths()):fetch()
    model=Detector();records=[]
    for path in samples():
        result=model.inspect(path)
        # Ground truth is accessed only AFTER detection; used for evaluation/display.
        kind=path.parent.name;mask_path=DATA/'ground_truth'/kind/(path.stem+'_mask.png')
        truth=np.zeros((GRID,GRID),dtype=bool)
        if kind!='good':
            with Image.open(mask_path) as im:truth=np.asarray(im.convert('L').resize((GRID,GRID),Image.Resampling.NEAREST))>0
        predicted=result['map']>model.pixel_threshold
        union=int((truth|predicted).sum());intersection=int((truth&predicted).sum())
        records.append({'path':path,'kind':kind,'truth':truth,'result':result,
            'mask_iou':intersection/union if union else None})
    return model,records

def summary(records):
    scores=[r['result']['features']['score_ratio'] for r in records]
    positive=[s for s,r in zip(scores,records) if r['kind']!='good']
    negative=[s for s,r in zip(scores,records) if r['kind']=='good']
    auc=sum((a>b)+0.5*(a==b) for a in positive for b in negative)/(len(positive)*len(negative))
    return {'count':len(records),'defect_count':len(positive),'good_count':len(negative),'image_auroc':round(auc,4),
        'binary_threshold':1.0,'binary_misses':sum(s<=1 and r['kind']!='good' for s,r in zip(scores,records)),
        'binary_false_rejects':sum(s>1 and r['kind']=='good' for s,r in zip(scores,records)),
        'review_count':sum(r['result']['local_verdict']=='review' for r in records),
        'vision_mean_ms':round(sum(r['result']['vision_ms'] for r in records)/len(records),1),
        'mean_defect_mask_iou':round(float(np.mean([r['mask_iou'] for r in records if r['kind']!='good'])),4)}

def save(folder,records):
    folder.mkdir(parents=True,exist_ok=True)
    serial=[{'image':str(r['path'].relative_to(DATA)).replace('\\','/'),'ground_truth':r['kind'],
             **{k:v for k,v in r['result'].items() if k not in ('rgb','map')},
             'mask_iou':r['mask_iou'],'jev':r.get('jev')} for r in records]
    report={'dataset':'MVTec AD bottle subset','revision':REVISION,'training':'train/good/000-029',
            'calibration':'train/good/030-039','test':'test/{good,broken_large,broken_small,contamination}/000-007',
            'method':'handcrafted RGB mean/std and gradient patch features; nearest normal spatial neighbour',
            'summary':summary(records),'records':serial}
    (folder/'evaluation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report

def render(screen,record,index,count,report,fonts,show_truth,autoplay,busy,key_available):
    title,font,small=fonts;screen.fill('#101a27')
    def text(s,x,y,color='#dce8f6',face=font):screen.blit(face.render(str(s),True,color),(x,y))
    text('画像検品 / MVTec Bottle',25,22,face=title)
    text('ローカル画像解析 → 数値特徴 → Jevの仕分け',25,65,face=small)
    text(f'{index+1} / {count}',1050,30)
    result=record['result'];f=result['features']
    source=pygame.transform.smoothscale(pygame.image.load(str(record['path'])),(345,345))
    for x,label in ((25,'元の製品写真'),(405,'画像解析：赤 = 異常候補'),(785,'正解領域：緑（評価用）')):
        text(label,x,115,face=small)
        screen.blit(source,(x,153))
    predicted=(result['map']>f['pixel_threshold']).astype(np.uint8)
    def overlay(mask,x,color):
        surface=pygame.Surface((GRID,GRID),pygame.SRCALPHA)
        for y,col in zip(*np.nonzero(mask)):surface.set_at((int(col),int(y)),(*color,135))
        screen.blit(pygame.transform.scale(surface,(345,345)),(x,153))
    overlay(predicted,405,(255,35,55))
    if show_truth:overlay(record['truth'],785,(35,255,105))
    else:
        cover=pygame.Surface((345,345));cover.fill('#203247');screen.blit(cover,(785,153))
        text('「正解を表示」で確認',815,305,face=small)
    text(f"ローカル判定：{LABELS[result['local_verdict']]}",25,525,'#ffd277')
    text(f"異常度 / 閾値 = {f['score_ratio']:.2f}    画像処理 {result['vision_ms']:.0f} ms",25,563,face=small)
    text(f"異常候補の面積 {f['anomalous_patch_percent']:.1f}%",25,595,face=small)
    if show_truth:text(f"正解：{'良品' if record['kind']=='good' else '不良品'} ({record['kind']})",25,631,face=small)
    answer=record.get('jev')
    text('Jev：'+('判定中…' if busy else LABELS.get(answer.get('verdict'),'エラー') if answer else '未実行'),620,525)
    if answer:text(answer.get('error') or f"{answer.get('model')} / {answer['latency_ms']:.0f} ms",620,563,face=small)
    text('Jevには画像・正解・ファイル名を渡しません。',620,595,face=small)
    text('傷の種類は識別せず、正常画像との違いを検出します。',620,631,face=small)
    text(f"32枚の評価：AUROC {report['image_auroc']:.3f} / 見逃し {report['binary_misses']}/{report['defect_count']} / 誤排除 {report['binary_false_rejects']}/{report['good_count']}（二値閾値1.0）",25,686,face=small)
    controls=[('prev','前へ',(25,736,105,45)),('next','次へ',(145,736,105,45)),
              ('auto','停止' if autoplay else '自動再生',(265,736,135,45)),
              ('truth','正解を隠す' if show_truth else '正解を表示',(420,736,170,45)),('quit','閉じる',(1000,736,130,45))]
    if key_available and not busy and answer is None:controls.append(('jev','Jevで仕分け（API）',(620,736,300,45)))
    areas=buttons(screen,font,controls);pygame.display.flip();return areas

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--evaluate',action='store_true')
    parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
    key=os.environ.pop('TYPESAFE_API_KEY','');folder=ROOT/'runs'/('vision-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    if args.evaluate or args.smoke:
        _,records=prepare()
        if args.smoke:
            if not key:parser.error('API key required')
            for r in records[:4]:r['jev']=ask(key,decision_state(r['result']))
        report=save(folder,records);print(json.dumps(report['summary'],indent=2));print(folder);return
    pygame.init();screen=pygame.display.set_mode((1160,810));pygame.display.set_caption('Jev Visual Inspection')
    path=pygame.font.match_font('yugothic,meiryo,msgothic');fonts=[pygame.font.Font(path,n) for n in (29,21,17)]
    pool=ThreadPoolExecutor(max_workers=1);loading=pool.submit(prepare);future=None;pending=None
    records=None;index=0;show_truth=False;autoplay=False;next_at=0;running=True;clock=pygame.time.Clock();error=None
    try:
        while running:
            if records is None:
                screen.fill('#101a27')
                message=error or '正常画像から学習中…（初回はデータをダウンロード）'
                screen.blit(fonts[1].render(message,True,'#dce8f6'),(30,300));pygame.display.flip();areas={}
                if loading.done() and not error:
                    try:_,records=loading.result();report=save(folder,records)['summary']
                    except Exception:error='データの準備に失敗しました。通信を確認して再起動してください。'
            else:
                if future and future.done():
                    pending['jev']=future.result();future=None;save(folder,records)
                if autoplay and time.monotonic()>=next_at:index=(index+1)%len(records);next_at=time.monotonic()+2
                areas=render(screen,records[index],index,len(records),report,fonts,show_truth,autoplay,future is not None,bool(key))
            for event in pygame.event.get():
                action=clicked(event,areas)
                if event.type==pygame.QUIT or action=='quit':running=False
                elif action=='prev':index=(index-1)%len(records)
                elif action=='next':index=(index+1)%len(records)
                elif action=='truth':show_truth=not show_truth
                elif action=='auto':autoplay=not autoplay;next_at=time.monotonic()+2
                elif action=='jev':
                    autoplay=False;pending=records[index];future=pool.submit(ask,key,decision_state(pending['result']))
            clock.tick(30)
    finally:
        pygame.quit();pool.shutdown(wait=True,cancel_futures=True)
        if future and future.done() and not future.cancelled():pending['jev']=future.result()
        if records:save(folder,records)

if __name__=='__main__':main()
