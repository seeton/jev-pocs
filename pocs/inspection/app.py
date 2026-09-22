"""Button-operated synthetic inspection line; Jev versus exact specification rules."""
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import argparse
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import pygame
from pocs.common.paths import ROOT
from pocs.common.ui import buttons,clicked
from .core import MODEL,LABELS,FIELDS,make_batch,payload,rule_decision,decide,metrics

COLORS={'pass':'#69d6ae','reject':'#ff7e87','review':'#ffd277'}
DEADLINE=4.0

def finalize(record, now):
    if record.get('finalized') or now-record['born']<DEADLINE:return
    answer=record.get('answer',{})
    in_time=record.get('received',float('inf'))<=record['born']+DEADLINE
    record['route']=answer.get('verdict','review') if in_time else 'review'
    record['reason']='判定完了' if in_time and 'verdict' in answer else 'APIエラー' if in_time else '時間切れ'
    if record.get('rules_only'):record['route']=record['baseline'];record['reason']='固定ルール'
    record['finalized']=True

class Line:
    def __init__(self,key,seed=7,count=24):
        self.key=key;self.seed=seed;self.count=count;self.batch=make_batch(seed,count)
        self.records=[];self.t=0.;self.next_item=0.;self.interval=1.2
        self.started=False;self.paused=False;self.rules_only=False;self.fatal=False;self.closed=False
        self.future=None;self.pending=None;self.pool=ThreadPoolExecutor(max_workers=1)
        self.folder=ROOT/'runs'/('inspection-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    @property
    def finished(self):return len(self.records)==self.count and all(r.get('finalized') for r in self.records) and self.future is None
    def update(self,dt):
        if not self.started:return
        if not self.paused:self.t+=dt
        if self.future and self.future.done():
            answer=self.future.result();self.pending['answer']=answer;self.pending['received']=self.t
            self.pending['wall_age_ms']=round((time.perf_counter()-self.pending['sent_wall'])*1000,1)
            if answer.get('fatal'):self.fatal=True
            self.future=None;self.pending=None
        if self.paused:return
        if len(self.records)<self.count and self.t>=self.next_item:
            item=self.batch[len(self.records)];baseline,failed=rule_decision(payload(item))
            self.records.append({'item':item,'born':self.t,'baseline':baseline,'failed_checks':failed,'rules_only':self.rules_only})
            self.next_item=self.t+self.interval
        for record in self.records:finalize(record,self.t)
        if self.future is None and not self.rules_only and not self.fatal:
            candidate=next((r for r in self.records if not r.get('sent') and not r.get('finalized')),None)
            if candidate is not None:
                candidate['sent']=True;candidate['sent_wall']=time.perf_counter();self.pending=candidate
                self.future=self.pool.submit(decide,self.key,payload(candidate['item']))
    def save(self):
        self.folder.mkdir(parents=True,exist_ok=True)
        records=[{k:v for k,v in r.items() if k!='sent_wall'} for r in self.records]
        data={'model':MODEL,'seed':self.seed,'count':self.count,'interval':self.interval,'deadline_seconds':DEADLINE,
              'rules_only':self.rules_only,'completed':self.finished,'line_seconds':round(self.t,2),
              'jev' if not self.rules_only else 'rules_demo':metrics(self.records,'route'),
              'baseline':metrics(self.records,'baseline'),'records':records}
        (self.folder/'results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    def close(self):
        if self.closed:return
        self.pool.shutdown(wait=True,cancel_futures=True)
        if self.future and self.future.done() and not self.future.cancelled():
            self.pending['answer']=self.future.result();self.pending['received']=self.t;self.future=None
        self.save();self.closed=True

def render(screen,line,fonts):
    title,font,small=fonts;screen.fill('#101a27')
    def text(s,x,y,color='#dce8f6',face=font):screen.blit(face.render(str(s),True,color),(x,y))
    text('Jev 検品ライン',30,22,face=title)
    text('模擬センサー入力 / 画像認識ではありません',400,36,face=small)
    status='開始を押してください' if not line.started else '検品完了' if line.finished else '一時停止' if line.paused else '稼働中'
    if line.fatal:status='API停止：未判定品は要確認へ'
    text(status,30,78,'#ffd277')
    text(f'{len(line.records)} / {line.count} 個   仕分け期限 {DEADLINE:.0f}秒   {line.t:.1f}秒',650,80,face=small)
    pygame.draw.rect(screen,'#25394a',(30,160,825,130),border_radius=14)
    for x in range(50,850,35):pygame.draw.line(screen,'#395063',(x,270),(x+15,180),2)
    pygame.draw.rect(screen,'#78c6ec',(160,150,5,150))
    text('検査データ取得',110,122,face=small);text('仕分けゲート',725,122,face=small)
    pygame.draw.line(screen,'#dce8f6',(820,155),(820,300),3)
    for r in line.records:
        age=line.t-r['born']
        if age>DEADLINE+1.3:continue
        x=90+730*min(age/DEADLINE,1)
        route=r.get('route');y=222
        if route:
            i=list(LABELS).index(route);f=min((age-DEADLINE)/1.2,1);x+=115*f;y+=(168+i*115-222)*f
        rect=pygame.Rect(int(x)-25,int(y)-25,50,50)
        pygame.draw.rect(screen,COLORS.get(route,'#a9cce0'),rect,border_radius=7)
        if (r['item']['measurements']['scratch_mm'] or 0)>0.2:
            pygame.draw.line(screen,'#b1474d',(rect.x+7,rect.y+6),(rect.x+29,rect.y+14),2)
        if r['item']['measurements']['label_ok'] is False:
            pygame.draw.circle(screen,'#b1474d',(rect.right-7,rect.bottom-7),4)
        text(r['item']['id'],rect.x+3,rect.y+13,'#13202c',small)
    for i,(verdict,label) in enumerate(LABELS.items()):
        y=135+i*115;pygame.draw.rect(screen,'#25394a',(900,y,195,95),border_radius=12)
        n=sum(r.get('route')==verdict for r in line.records)
        text(f'{label}  {n} 個',920,y+30,COLORS[verdict])
    left='固定ルール（APIなし）' if line.rules_only else 'Jev（期限切れは要確認）'
    text(left,30,330);text('固定ルール：同じ入力・同じ基準',440,330)
    for x,field in ((30,'route'),(440,'baseline')):
        m=metrics(line.records,field)
        text(f"基準と一致 {m['correct']} / {m['total']}",x,374)
        text(f"見逃し {m['misses']}   良品の誤排除 {m['false_rejects']}",x,414,face=small)
        text(f"良品 {m['pass']} / 不良 {m['reject']} / 要確認 {m['review']}",x,446,face=small)
    answers=[r['answer'] for r in line.records if 'answer' in r]
    avg=sum(a['latency_ms'] for a in answers)/len(answers) if answers else 0
    text(f'API {sum(bool(r.get("sent")) for r in line.records)} 回 / 平均往復 {avg:.0f} ms',30,493,face=small)
    text('基準をコード化できる課題なので、固定ルールは強い比較対象です。',30,526,'#9eafc2',small)
    r=next((r for r in reversed(line.records) if r.get('finalized')),line.records[-1] if line.records else None)
    if r:
        item=r['item'];s=item['specification'];m=item['measurements']
        text(f"直近 {item['id']} / {item['grade']} / 仕分け {LABELS.get(r.get('route'),'判定待ち')}",30,570)
        text(' / '.join(f'{label}: {m[field] if m[field] is not None else "欠測"}' for field,label in FIELDS.items()),30,610,face=small)
        text(f"規格：幅 {s['width_mm']} / 重量 {s['weight_g']} / 傷 ≤ {s['scratch_mm_max']} / 色差 ≤ {s['color_delta_max']} / ラベル必須",30,643,face=small)
        if r.get('finalized'):text(f"正解：{LABELS[item['expected']]}  /  {r['reason']}",30,678,'#ffd277',small)
    items=[('quit','閉じる',(940,733,155,48))]
    if not line.started:
        if line.key or line.rules_only:items.append(('start','検品開始',(30,733,170,48)))
        items.append(('mode','Jev比較' if line.rules_only else 'APIなしで試す',(220,733,195,48)))
        items.append(('speed',f'投入間隔 {line.interval:.1f}秒',(435,733,185,48)))
        if not line.key and not line.rules_only:text('APIキー未登録：APIなしモードで試せます',30,710,face=small)
    else:
        if not line.finished:items.append(('pause','再開' if line.paused else '一時停止',(30,733,170,48)))
        if line.future is None:items.append(('reset','同じ製品でもう一度',(650,733,270,48)))
    areas=buttons(screen,font,items);pygame.display.flip();return areas

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--smoke',action='store_true');parser.add_argument('--seed',type=int,default=7)
    args=parser.parse_args();key=os.environ.pop('TYPESAFE_API_KEY','')
    if args.smoke:
        if not key:parser.error('API key is required')
        data=[]
        for item in make_batch(args.seed,12):
            answer=decide(key,payload(item));data.append({'item':item,'answer':answer})
            print(json.dumps({'id':item['id'],'expected':item['expected'],'verdict':answer.get('verdict'),'latency_ms':answer['latency_ms'],'error':answer.get('error')},ensure_ascii=True),flush=True)
            if answer.get('error'):break
        folder=ROOT/'runs'/('inspection-smoke-'+datetime.now().strftime('%Y%m%d-%H%M%S'));folder.mkdir(parents=True)
        (folder/'results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    pygame.init();screen=pygame.display.set_mode((1130,810));pygame.display.set_caption('Jev Inspection Line')
    path=pygame.font.match_font('yugothic,meiryo,msgothic');fonts=[pygame.font.Font(path,n) for n in (29,21,17)]
    line=Line(key,args.seed);clock=pygame.time.Clock();running=True;saved=False
    try:
        while running:
            dt=clock.tick(30)/1000;line.update(dt);areas=render(screen,line,fonts)
            if line.finished and not saved:line.save();saved=True
            for event in pygame.event.get():
                action=clicked(event,areas)
                if event.type==pygame.QUIT or action=='quit':running=False
                elif action=='start':line.started=True
                elif action=='pause':line.paused=not line.paused
                elif action=='mode':line.rules_only=not line.rules_only
                elif action=='speed':line.interval=0.4 if line.interval==1.2 else 1.2
                elif action=='reset':
                    mode,interval=line.rules_only,line.interval;line.close();line=Line(key,args.seed)
                    line.rules_only=mode;line.interval=interval;saved=False
    finally:line.close();pygame.quit()

if __name__=='__main__':main()
