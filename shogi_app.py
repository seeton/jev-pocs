"""Click-to-play shogi against Jev. Local rules; model chooses only legal moves."""
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pygame
import requests
import shogi
from compare import buttons, clicked
from shogi_tactics import annotate, material, best_reply_gain, VALUES

ROOT=Path(__file__).resolve().parent
MODEL='jev-preview'
NAMES=['','歩','香','桂','銀','金','角','飛','玉','と','成香','成桂','成銀','馬','龍']
CELL=62
BOARD=pygame.Rect(40,105,CELL*9,CELL*9)

def description(board, move):
    target=shogi.SQUARE_NAMES[move.to_square]
    if move.drop_piece_type: return f'Drop {NAMES[move.drop_piece_type]} at {target}'
    piece=board.piece_at(move.from_square)
    captured=board.piece_at(move.to_square)
    return f'{NAMES[piece.piece_type]} {shogi.SQUARE_NAMES[move.from_square]} to {target}'+(' promote' if move.promotion else '')+(f' capture {NAMES[captured.piece_type]}' if captured else '')

def choose(key, sfen, history):
    start=time.perf_counter()
    board=shogi.Board(sfen)
    choices={m.usi():description(board,m)+'; tactical facts: '+json.dumps(annotate(board,m)) for m in list(board.legal_moves)}
    state={'game':'Japanese shogi','sfen':sfen,'board':board.kif_str(),
           'side_to_move':'sente / black' if board.turn==shogi.BLACK else 'gote / white',
           'recent_moves':history[-20:], 'in_check':board.is_check(),
           'material_balance_for_you':material(board,board.turn),
           'your_best_capture_now':best_reply_gain(board),
           'piece_values_in_pawn_units':VALUES,
           'tactical_notes':'Capture swing includes removing enemy board value AND gaining the demoted piece in hand. '
             'Reply risk checks opponent captures and one immediate legal recapture on the same square. '
             'It omits longer exchanges, quiet threats and future mates; zero risk does NOT mean safe. '
             'Values are heuristic material units, not engine evaluation.'}
    preprocessing_ms=round((time.perf_counter()-start)*1000)
    calls=0; resolved_models=[]
    def request(options):
        nonlocal calls
        calls+=1
        r=requests.post('https://api.typesafe.ai/v1/systemone',headers={'Authorization':f'Bearer {key}'},
            json={'model':MODEL,'state':state,'questions':{'move':{'type':'choice',
              'instructions':'Choose the strongest legal shogi move. Prefer an annotated checkmate, then safe material gains, then king safety and development. Use the tactical facts to avoid free losses; do not blindly maximize material or give check without benefit. Reply risk is a limited exchange estimate, not a full search. Coordinates use USI notation. Select exactly one provided move.',
              'criteria':options}}},timeout=(3,10),allow_redirects=False)
        if r.status_code!=200: raise RuntimeError(f'API HTTP {r.status_code}')
        data=r.json(); selected=data['answers']['move']['choice']
        resolved_models.append(data.get('model','unknown'))
        if selected not in options: raise ValueError('Invalid choice')
        return selected
    try:
        if len(choices)<=255: move=request(choices)
        else:
            # Keep every legal move eligible even in positions with many drops.
            items=list(choices.items())
            finalists=[request(dict(items[i:i+255])) for i in range(0,len(items),255)]
            move=request({m:choices[m] for m in finalists})
        return {'move':move,'latency_ms':round((time.perf_counter()-start)*1000),'calls':calls,'sfen':sfen,
                'requested_model':MODEL,'resolved_models':resolved_models,'preprocessing_ms':preprocessing_ms,
                'state':state,'criteria':choices}
    except RuntimeError as e: error=str(e)
    except requests.RequestException: error='通信に失敗しました'
    except (ValueError,KeyError,TypeError): error='応答の形式が不正です'
    return {'error':error,'calls':calls,'sfen':sfen}

class Game:
    def __init__(self):
        self.board=shogi.Board(); self.moves=[]; self.labels=[]; self.selected=None
        self.promotion=[]; self.result=''; self.error=''; self.latency=0; self.calls=0
        self.resolved_models=[]
        self.folder=ROOT/'runs'/('shogi-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    def save(self):
        self.folder.mkdir(parents=True,exist_ok=True)
        (self.folder/'game.json').write_text(json.dumps({'sfen':self.board.sfen(),'moves':self.moves,
          'result':self.result,'api_calls':self.calls,'last_latency_ms':self.latency,
          'requested_model':MODEL,'resolved_models':self.resolved_models},ensure_ascii=False,indent=2),encoding='utf-8')
    def log_decision(self,answer):
        self.folder.mkdir(parents=True,exist_ok=True)
        with (self.folder/'decisions.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(answer,ensure_ascii=False)+'\n')
    def play(self,move):
        if move not in self.board.legal_moves: return False
        self.labels.append(('▲' if self.board.turn==0 else '△')+description(self.board,move))
        self.moves.append(move.usi()); self.board.push(move); self.selected=None; self.promotion=[]
        if self.board.is_checkmate(): self.result='あなたの勝ち' if self.board.turn==1 else 'Jevの勝ち'
        elif self.board.is_fourfold_repetition(): self.result='千日手（このPoCでは引き分け）'
        elif self.board.is_game_over(): self.result='終局'
        self.save(); return True
    def options(self):
        if self.selected is None: return []
        kind,value=self.selected
        return [m for m in self.board.legal_moves if
                (m.from_square==value if kind=='square' else m.drop_piece_type==value)]
    def square(self,sq):
        if self.promotion or self.result or self.board.turn!=0: return
        moves=[m for m in self.options() if m.to_square==sq]
        if len(moves)>1: self.promotion=moves
        elif moves: self.play(moves[0])
        else:
            p=self.board.piece_at(sq)
            self.selected=('square',sq) if p and p.color==0 else None
    def undo(self):
        if not self.moves: return
        self.board.pop(); self.moves.pop(); self.labels.pop()
        if self.board.turn==1 and self.moves:
            self.board.pop();self.moves.pop();self.labels.pop()
        self.result='';self.error='';self.selected=None;self.promotion=[];self.save()

def render(screen,g,font,small,piecefont,busy,key_available):
    screen.fill('#101a27')
    def text(s,x,y,c='#dce8f6',f=font): screen.blit(f.render(s,True,c),(x,y))
    text('Jev 将棋 / '+MODEL+' / 戦術情報あり',40,22)
    status=g.result or ('APIキーが未登録です' if not key_available else g.error or ('Jevが考えています…' if busy else 'あなたの番：駒 → 移動先をクリック'))
    text(status,40,62,'#ffcf78',small)
    targets={m.to_square for m in g.options()}
    last=shogi.Move.from_usi(g.moves[-1]) if g.moves else None
    for sq in range(81):
        row,col=divmod(sq,9); rect=pygame.Rect(BOARD.x+col*CELL,BOARD.y+row*CELL,CELL,CELL)
        color='#d9b77a'
        if last and sq==last.to_square: color='#eacd83'
        if g.selected==('square',sq): color='#8ec4ac'
        pygame.draw.rect(screen,color,rect);pygame.draw.rect(screen,'#654b32',rect,1)
        if sq in targets: pygame.draw.circle(screen,'#428879',rect.center,8)
        piece=g.board.piece_at(sq)
        if piece:
            glyph=piecefont.render(NAMES[piece.piece_type],True,'#922f29' if piece.piece_type>=9 else '#252326')
            if piece.color==1: glyph=pygame.transform.rotate(glyph,180)
            screen.blit(glyph,glyph.get_rect(center=rect.center))
    for i in range(9):
        text(str(9-i),BOARD.x+i*CELL+25,BOARD.y-24,f=small)
        text('一二三四五六七八九'[i],BOARD.right+7,BOARD.y+i*CELL+20,f=small)
    items=[]
    for color,y,title in [(1,115,'Jev（後手）の持ち駒'),(0,265,'あなた（先手）の持ち駒')]:
        text(title,650,y)
        hand=g.board.pieces_in_hand[color]
        if not hand:text('なし',650,y+40,f=small)
        for i,(pt,count) in enumerate(sorted(hand.items())):
            box=(650+(i%4)*78,y+40+(i//4)*50,72,42)
            label=f'{NAMES[pt]} {count}'
            if color==0 and not busy and not g.result and g.board.turn==0:
                if g.selected==('hand',pt): label='●'+label
                items.append((f'hand:{pt}',label,box))
            else:text(label,box[0]+5,box[1]+7,f=small)
    text(f'{len(g.moves)}手 / API {g.calls}回 / 応答 {g.latency}ms',650,420,f=small)
    text('直近の指し手',650,459)
    for i,label in enumerate(g.labels[-6:]):text(label,650,500+i*25,f=small)
    if not busy:
        items.extend([('new','新しい対局',(40,700,175,48)),('undo','待った',(230,700,130,48)),
                      ('resign','投了',(375,700,130,48))])
        if g.error:items.append(('retry','再試行',(650,655,150,42)))
    items.append(('quit','閉じる',(840,700,130,48)))
    if g.promotion:
        pygame.draw.rect(screen,'#263c51',(180,315,390,125),border_radius=12)
        text('成りますか？',295,328)
        items.extend([('promote','成る',(200,376,165,48)),('plain','成らない',(385,376,165,48))])
    text('持ち駒もクリックして打てます。新しい対局では先手から開始。',40,770,f=small)
    areas=buttons(screen,small,items);pygame.display.flip();return areas

def main():
    key=os.environ.pop('TYPESAFE_API_KEY','')
    import sys
    if '--smoke' in sys.argv:
        if not key: raise RuntimeError('API key missing')
        game=Game(); game.play(shogi.Move.from_usi('7g7f'))
        answer=choose(key,game.board.sfen(),game.moves)
        game.log_decision(answer)
        if 'error' in answer: raise RuntimeError(answer['error'])
        game.calls=answer['calls'];game.latency=answer['latency_ms']
        game.resolved_models=answer['resolved_models']
        assert game.play(shogi.Move.from_usi(answer['move']))
        print(json.dumps({k:v for k,v in answer.items() if k not in ('state','criteria')}));return
    pygame.init();screen=pygame.display.set_mode((1000,810));pygame.display.set_caption('Jev Shogi')
    path=pygame.font.match_font('yugothic,meiryo,msgothic')
    font,small,piecefont=[pygame.font.Font(path,n) for n in (23,17,29)]
    g=Game();clock=pygame.time.Clock();pool=ThreadPoolExecutor(max_workers=1);future=None;running=True
    try:
        while running:
            if future and future.done():
                answer=future.result();future=None;g.calls+=answer['calls']
                g.log_decision(answer)
                if 'error' in answer:g.error=answer['error']
                elif answer['sfen']==g.board.sfen():
                    g.resolved_models.extend(answer['resolved_models'])
                    g.latency=answer['latency_ms'];g.play(shogi.Move.from_usi(answer['move']))
                g.save()
            areas=render(screen,g,font,small,piecefont,future is not None,bool(key))
            for event in pygame.event.get():
                action=clicked(event,areas)
                if event.type==pygame.QUIT or action=='quit':running=False
                elif future is None:
                    if action=='new':g.save();g=Game()
                    elif action=='undo':g.undo()
                    elif action=='resign' and not g.result:g.result='投了：Jevの勝ち';g.save()
                    elif action=='retry':g.error=''
                    elif action in ('promote','plain') and g.promotion:
                        g.play(next(m for m in g.promotion if m.promotion==(action=='promote')))
                    elif action and action.startswith('hand:') and not g.promotion:g.selected=('hand',int(action.split(':')[1]))
                    elif event.type==pygame.MOUSEBUTTONDOWN and event.button==1 and BOARD.collidepoint(event.pos):
                        x,y=event.pos;g.square(((y-BOARD.y)//CELL)*9+(x-BOARD.x)//CELL)
            if running and key and future is None and g.board.turn==1 and not g.result and not g.error:
                future=pool.submit(choose,key,g.board.sfen(),list(g.moves))
            clock.tick(30)
    finally:
        g.save();pygame.quit();pool.shutdown(wait=True,cancel_futures=True)

if __name__=='__main__':main()
