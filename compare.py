"""Paired real-time comparison: equal skills, observation schema, clock and response delays."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import time

from battle import Battle, BattleJev, BATTLE_VERSION, ROLE_NAMES, COLORS, ROOT, draw, pygame
from tactical_policy import tactical_orders


def buttons(screen, font, items):
    """Draw controls and return the same rectangles used for mouse hit testing."""
    areas = {}
    for action, label, rect in items:
        box = pygame.Rect(rect)
        color = '#314d6b' if box.collidepoint(pygame.mouse.get_pos()) else '#203650'
        pygame.draw.rect(screen, color, box, border_radius=9)
        pygame.draw.rect(screen, '#55799c', box, width=1, border_radius=9)
        rendered = font.render(label, True, '#e5edf9')
        screen.blit(rendered, rendered.get_rect(center=box.center))
        areas[action] = box
    return areas


def clicked(event, areas):
    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        return next((action for action, rect in areas.items() if rect.collidepoint(event.pos)), None)
    return None


def menu(screen, font, small, titlefont, has_key):
    clock = pygame.time.Clock()
    while True:
        folders = sorted(p for p in (ROOT/'runs').glob('comparison-*') if (p/'summary.json').is_file())
        screen.fill('#0b1020')
        for label, y, face in [('JEV PARTY', 100, titlefont), ('自動戦闘の比較', 160, font),
                               ('敵・技・初期配置・判断の待ち時間を揃えて比較します。', 210, small)]:
            rendered = face.render(label, True, '#dce8f6')
            screen.blit(rendered, rendered.get_rect(center=(630,y)))
        items = [('quit','アプリを閉じる',(410,560,440,52))]
        if has_key: items.append(('live','新しい比較を開始（API使用・90秒）',(410,280,440,64)))
        else: screen.blit(small.render('APIキー未登録：jev.cmd で設定してください', True, '#ffcf78'), (420,300))
        if folders:
            items.append(('replay','前回の比較を見る（APIなし）',(410,370,440,64)))
            summary = json.loads((folders[-1]/'summary.json').read_text(encoding='utf-8'))
            label = f"前回のボス残HP：Jev {summary['jev']['remaining_hp']['boss']:.0f} / ルールAI {summary['rules']['remaining_hp']['boss']:.0f}"
            rendered = small.render(label, True, '#9cb0ca')
            screen.blit(rendered, rendered.get_rect(center=(630,475)))
        areas = buttons(screen, font, items)
        pygame.display.flip()
        for event in pygame.event.get():
            action = clicked(event, areas)
            if event.type == pygame.QUIT or action == 'quit': return None
            if action == 'live': return 'live'
            if action == 'replay': return str(folders[-1])
        clock.tick(30)


def capture(b):
    return {'t':b.t,'units':[asdict(u) for u in b.units],'effects':b.effects,'events':b.events[-12:],'result':b.result}


def restore(b,data):
    b.t=data['t']; b.effects=data['effects']; b.events=data['events']; b.result=data['result']
    for saved,u in zip(data['units'],b.units):
        for key,value in saved.items(): setattr(u,key,value)


def summarize(b):
    return {'result':b.result,'end_sim_seconds':round(b.t,2),'alive':len(b.living('party')),
            'enemies_alive':len(b.living('enemy')),'remaining_hp':{u.id:round(u.hp,1) for u in b.units},
            'skills':b.skills,'interrupts':b.interrupts,'absorbed_damage':round(b.absorbed_damage,1),
            'redirected_damage':round(b.redirected_damage,1),
            'damage_to_enemies':round(sum(u.max_hp-u.hp for u in b.units if u.team=='enemy'),1)}


def display(screen,battles,stats,font,small,titlefont,replay=False,paused=False):
    screen.fill('#0b1020')
    def text(s,x,y,c='#dce8f6',f=small): screen.blit(f.render(str(s),True,c),(x,y))
    text('JEV vs RULES',20,16,'#80dfff',titlefont)
    text('同じ技・初期配置・観測情報・応答待ち時間',360,26,f=font)
    text(('REPLAY / APIなし' if replay else 'LIVE')+f"  {stats['t']:.1f}s",960,29)
    scratch=pygame.Surface((1240,730))
    for i,b in enumerate(battles):
        x=20+i*630
        name='Jev' if i==0 else '固定ルールAI（全スキル対応）'
        text(name,x,78,'#80dfff' if i==0 else '#ffcf78',font)
        fake=dict(controller=name,latency_ms=stats['age_ms'],calls=stats['rounds'],max_calls=stats['rounds'],
                  accepted=0,discarded=0,age_ms=stats['age_ms'],status='')
        draw(scratch,b,fake,font,small,titlefont,False)
        arena=scratch.subsurface((20,90,870,395))
        screen.blit(pygame.transform.smoothscale(arena,(600,273)),(x,115))
        for j,u in enumerate(b.units[:4]):
            yy=407+j*31
            text(ROLE_NAMES[u.role],x,yy,COLORS[u.role])
            text(f'{u.hp:.0f}/{u.max_hp:.0f}',x+105,yy)
            text(u.last.replace('minion','小型'),x+200,yy)
        text(f'巨兵 HP {b.by_id["boss"].hp:.0f}/1600　残敵 {len(b.living("enemy"))}体',x,545)
        text(b.result or '戦闘中',x,578,'#ffcf78',font)
        for j,event in enumerate(b.events[-3:]): text(event.replace('minion','小型'),x,622+j*25,'#9cb0ca')
    text(f"共通の応答待ち {stats['age_ms']:.0f} ms　判断ラウンド {stats['rounds']}",20,704)
    controls = [('pause', '再生' if paused and replay else '再開' if paused else '一時停止', (20,738,190,48))]
    if replay: controls.append(('restart','最初から再生',(225,738,210,48)))
    controls += [('home','メニューへ' if replay else '終了して保存',(840,738,190,48)),
                 ('quit','閉じる',(1045,738,190,48))]
    areas = buttons(screen, font, controls)
    if paused: text('PAUSED',560,77,'#ffcf78',font)
    pygame.display.flip()
    return areas


def main(argv=None, key=''):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration',type=float,default=90)
    parser.add_argument('--interval',type=float,default=0.5)
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--paused',action='store_true',help='Start paused; SPACE begins playback or combat.')
    parser.add_argument('--live',action='store_true',help='Skip menu and run a new comparison.')
    parser.add_argument('--replay',help='Recorded comparison directory, or latest')
    args=parser.parse_args(argv)
    if any(not math.isfinite(v) or v<=0 for v in (args.duration,args.interval)):
        parser.error('Duration and interval must be positive and finite.')
    if args.headless: os.environ['SDL_VIDEODRIVER']='dummy'
    pygame.init()
    screen=pygame.display.set_mode((1260,810))
    pygame.display.set_caption('Jev Party - FAIR COMPARISON'+(' REPLAY' if args.replay else ''))
    path=pygame.font.match_font('yugothic,meiryo,msgothic')
    font,small,titlefont=(pygame.font.Font(path,size) for size in (21,16,29))
    if not args.replay and not args.headless and not args.live:
        selection = menu(screen,font,small,titlefont,bool(key))
        if selection is None:
            pygame.quit(); return None
        if selection != 'live': args.replay=selection; args.paused=True
    if not args.replay and not key: parser.error('Use compare.cmd with a saved key.')
    battles=[Battle(),Battle()]
    stats={'t':0.0,'rounds':0,'age_ms':0.0,'api_calls':0}
    paused=args.paused; running=True; go_home=False; clock=pygame.time.Clock()
    areas={}
    if args.replay:
        folder=sorted(p for p in (ROOT/'runs').glob('comparison-*') if (p/'frames.jsonl').is_file())[-1] if args.replay=='latest' else Path(args.replay)
        frames=[json.loads(line) for line in (folder/'frames.jsonl').read_text(encoding='utf-8').splitlines()]
        index=0; playhead=0.0
        while running:
            dt=clock.tick(30)/1000
            for event in pygame.event.get():
                action=clicked(event,areas)
                if event.type==pygame.QUIT or action=='quit' or (event.type==pygame.KEYDOWN and event.key==pygame.K_ESCAPE): running=False
                elif action=='home': running=False; go_home=True
                elif action=='pause' or (event.type==pygame.KEYDOWN and event.key==pygame.K_SPACE):
                    if index==len(frames)-1: index=0;playhead=0
                    paused=not paused
                elif action=='restart' or (event.type==pygame.KEYDOWN and event.key==pygame.K_r): index=0;playhead=0;paused=False
            if not paused: playhead+=dt
            while index+1<len(frames) and frames[index+1]['stats']['t']<=playhead: index+=1
            if index==len(frames)-1: paused=True
            frame=frames[index]
            for b,saved in zip(battles,frame['battles']): restore(b,saved)
            areas=display(screen,battles,frame['stats'],font,small,titlefont,True,paused)
        pygame.quit();return [] if go_home else None
    client=BattleJev(key); key=None
    executor=ThreadPoolExecutor(max_workers=1)
    future=None; pending=None; sent=0; next_round=0; next_frame=0; accumulator=0
    previous=time.perf_counter(); latencies=[]; usage={'input_tokens':0,'output_tokens':0}; errors=0
    folder=ROOT/'runs'/('comparison-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    frame_log=(folder/'frames.jsonl').open('w',encoding='utf-8')
    rounds=(folder/'rounds.jsonl').open('w',encoding='utf-8')
    metadata={'version':BATTLE_VERSION,'duration':args.duration,'minimum_round_interval':args.interval,
              'timing':'Both snapshots taken on same simulation frame; both answers applied together on observed Jev response frame. Max age 1.5s for both.',
              'information':'Both policies use only snapshot and legal choices; no future state.',
              'limits':'Same simulation time cap; at most ceil(duration/interval)+1 requests, no earlier API call cap.',
              'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('battle.py','tactical_policy.py','compare.py')}}
    for name in ('battle.py','tactical_policy.py','compare.py'):
        (folder/name).write_bytes((ROOT/name).read_bytes())
    (folder/'conditions.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    try:
        while running:
            now=time.perf_counter(); elapsed=now-previous; previous=now
            for event in pygame.event.get():
                action=clicked(event,areas)
                if event.type==pygame.QUIT or action=='quit' or (event.type==pygame.KEYDOWN and event.key==pygame.K_ESCAPE): running=False
                elif action=='home': running=False; go_home=True
                elif action=='pause' or (event.type==pygame.KEYDOWN and event.key==pygame.K_SPACE): paused=not paused
            if not running: break
            finished=all(b.result for b in battles)
            if not paused and not finished:
                accumulator+=elapsed
                for _ in range(min(int(accumulator*30),15)):
                    stats['t']+=1/30
                    for b in battles: b.tick(1/30)
                    accumulator-=1/30
                    if stats['t']>=args.duration:
                        for b in battles:
                            if not b.result: b.result='TIME LIMIT'
                        break
            if future and future.done():
                answer=future.result();future=None
                age=time.perf_counter()-sent; stats['age_ms']=round(age*1000,1);latencies.append(stats['age_ms'])
                for field in usage: usage[field]+=answer.get('usage',{}).get(field,0)
                accepted=[0,0]
                error=answer.get('error')
                if error:
                    errors+=1
                    if answer.get('fatal') or errors>=3:
                        for b in battles:
                            if not b.result:b.result='API ERROR / COMPARISON INCOMPLETE'
                elif age<=1.5 and not paused:
                    for i,(b,orders) in enumerate(zip(battles,[answer.get('orders',{}),pending['baseline_orders']])):
                        if not b.result:accepted[i]=b.apply(orders)
                record={**pending,'jev_answer':answer,'accepted':accepted,'shared_age_ms':stats['age_ms'],
                        'apply_sim_time':round(stats['t'],3)}
                rounds.write(json.dumps(record,ensure_ascii=False)+'\n');rounds.flush();pending=None
                print(json.dumps({'round':stats['rounds'],'t':round(stats['t'],1),'accepted':accepted,'age_ms':stats['age_ms'],'error':error}),flush=True)
            if not paused and not all(b.result for b in battles) and future is None and stats['t']>=next_round:
                pairs=[b.snapshot() if not b.result else ({},{}) for b in battles]
                if any(pair[1] for pair in pairs):
                    pending={'request_sim_time':round(stats['t'],3),'jev_state':pairs[0][0], 'jev_choices':pairs[0][1],
                             'baseline_state':pairs[1][0],'baseline_choices':pairs[1][1],
                             'baseline_orders':tactical_orders(*pairs[1]) if pairs[1][1] else {}}
                    sent=time.perf_counter()
                    if pairs[0][1]:
                        stats['api_calls']+=1
                        future=executor.submit(client.decide,*pairs[0])
                    else:
                        # No Jev decision required (e.g. cooldowns/end); preserve shared timing with last measured delay.
                        def no_jev(delay):
                            time.sleep(delay)
                            return {'orders':{},'usage':{},'latency_ms':delay*1000}
                        future=executor.submit(no_jev,min(stats['age_ms']/1000 or 0.25,1.5))
                    stats['rounds']+=1
                    next_round=stats['t']+args.interval
            if stats['t']>=next_frame or all(b.result for b in battles):
                frame_log.write(json.dumps({'stats':stats,'battles':[capture(b) for b in battles]},ensure_ascii=False)+'\n')
                next_frame=stats['t']+0.2
            if not args.headless:areas=display(screen,battles,stats,font,small,titlefont,False,paused)
            if all(b.result for b in battles):
                # Save once and finish; replay mode can display the completed run without API calls.
                break
            clock.tick(30)
    finally:
        executor.shutdown(wait=True,cancel_futures=True)
        if future and future.done() and not future.cancelled():
            answer=future.result()
            for field in usage:usage[field]+=answer.get('usage',{}).get(field,0)
            rounds.write(json.dumps({**(pending or {}),'jev_answer':answer,'accepted':[0,0],'status':'Stopped: discarded'},ensure_ascii=False)+'\n')
        for b in battles:
            if not b.result:b.result='USER STOP / COMPARISON INCOMPLETE'
        frame_log.write(json.dumps({'stats':stats,'battles':[capture(b) for b in battles]},ensure_ascii=False)+'\n')
        result={'conditions':metadata,'jev':summarize(battles[0]),'rules':summarize(battles[1]),
                'shared_mean_age_ms':round(sum(latencies)/len(latencies),1) if latencies else None,
                'usage':usage,'errors':errors,'rounds':stats['rounds'],'api_calls':stats['api_calls']}
        (folder/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        display(screen,battles,stats,font,small,titlefont)
        pygame.image.save(screen,str(folder/'final.png'))
        frame_log.close();rounds.close();client.session.close();pygame.quit()
        print(json.dumps(result,ensure_ascii=True,indent=2),flush=True)
        print(f'Comparison: {folder}',flush=True)
    if not args.headless and (go_home or running): return []
    return None


if __name__=='__main__':
    import sys
    saved_key=os.environ.pop('TYPESAFE_API_KEY','')
    arguments=sys.argv[1:]
    while arguments is not None:
        arguments=main(arguments,saved_key)
