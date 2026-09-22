"""Four role-based party members controlled by Jev; real-time combat while API is in flight."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
import json
import math
import os
from pathlib import Path
import time

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame
import requests

ROOT = Path(__file__).resolve().parent
ROLE_NAMES = {'tank': 'タンク', 'archer': 'アーチャー', 'mage': 'メイジ', 'healer': 'ヒーラー', 'boss': '巨兵', 'minion': '小型兵'}
COLORS = {'tank': '#5cc8ff', 'archer': '#ffce67', 'mage': '#c397ff', 'healer': '#68e8b0', 'boss': '#fb7185', 'minion': '#fb9b79'}
BATTLE_VERSION = 'tactical-v3'
BOSS_HP, BOSS_DAMAGE = 1600, 64
MINION_HP, MINION_DAMAGE = 200, 20
TAUNT_DURATION, TAUNT_REUSE = 2.0, 10.0
SKILL_REUSE = {'interrupt': 7, 'cover': 9, 'stealth': 10, 'retreat': 7,
               'root': 8, 'barrier': 7, 'rescue': 8}
REACTIONS = {'interrupt', 'cover', 'stealth', 'barrier'}
SKILL_LABELS = {'interrupt':'割込','cover':'かばう','stealth':'隠密','retreat':'退避',
                'root':'足止','barrier':'障壁','rescue':'大回復'}
ROLE_PROMPTS = {
    'tank': 'Protect the party. Enemies deliberately target the backline. Taunt redirects ALL living enemies to you '
            'for only 2 seconds and has a separate 10-second reuse cooldown. Time it to rescue threatened allies; it cannot be permanent. '
            'Guard reduces incoming damage by 60% for 4s. Interrupt cancels a winding-up enemy strike and stuns it 1.5s, range 240, reuse 7s. '
            'Cover dashes to an ally and redirects 70% of its damage to you for 3s (reuse 9s). '
            'Interrupt and cover can be used during normal action cooldown. Prioritize dangerous committed attacks on fragile allies. '
            'Taunt does NOT cancel committed strikes. Do not only guard or wait; attack when allies are safe.',
    'archer': 'Single-target damage dealer. Attack for 20. Stealth makes you untargetable for 2.5s, cancels incoming '
              'strikes on you, but prevents your attacks until it expires; reuse 10s. It transfers enemy pressure to allies. '
              'Retreat shot deals 12 and moves 110px away from that enemy, reuse 7s. '
              'Use attacks to finish enemies; use stealth or retreat when threatened, rather than wasting them on cooldown.',
    'mage': 'Choose ONE spell: buff an ally (damage and healing x1.5 for 6 seconds), debuff an enemy '
            '(damage x0.55 and movement x0.6 for 6 seconds), or AOE damage (22 to every enemy within 95 pixels of the selected enemy). '
            'Root immobilizes one enemy for 3s (reuse 8s), but does NOT stop attacks already in range or cancel windup. '
            'Prefer AOE on clusters; weaken the boss before its big hit, root approaching enemies, buff allies when useful. '
            'Avoid refreshing effects with substantial time remaining.',
    'healer': 'Heal one ally for 30 HP. Prioritize allies at risk of dying based on their HP and enemy targets. '
              'Barrier absorbs 45 damage on one ally for 4s, reuse 7s; can be used during ordinary cooldown before a hit. '
              'Rescue heal restores 55 but locks normal actions for 3s and has reuse 8s, so use it for emergencies. '
              'Heal yourself if necessary. Shield threatened full-health allies before big hits. Otherwise conserve cooldowns.',
}


@dataclass
class Unit:
    id: str
    role: str
    team: str
    x: float
    y: float
    hp: float
    max_hp: float
    cooldown: float = 0
    buff: float = 0
    debuff: float = 0
    guard: float = 0
    taunt: float = 0
    taunt_cooldown: float = 0
    skill_cooldowns: dict = field(default_factory=dict)
    stealth: float = 0
    stun: float = 0
    rooted: float = 0
    shield: float = 0
    shield_time: float = 0
    cover_time: float = 0
    covered_by: str | None = None
    windup: float = 0
    windup_target: str | None = None
    order: str = 'wait'
    last: str = '待機'
    target: str | None = None

    @property
    def alive(self):
        return self.hp > 0

    @property
    def pos(self):
        return self.x, self.y


def distance(a: Unit, b: Unit):
    return math.hypot(a.x - b.x, a.y - b.y)


class Battle:
    def __init__(self):
        self.units = [Unit('tank', 'tank', 'party', 310, 290, 240, 240),
                      Unit('archer', 'archer', 'party', 190, 190, 90, 90),
                      Unit('mage', 'mage', 'party', 170, 385, 85, 85),
                      Unit('healer', 'healer', 'party', 100, 285, 100, 100),
                      Unit('boss', 'boss', 'enemy', 770, 285, BOSS_HP, BOSS_HP)]
        for i, (x, y) in enumerate([(620, 185), (685, 230), (620, 380), (685, 335)], 1):
            self.units.append(Unit(f'minion{i}', 'minion', 'enemy', x, y, MINION_HP, MINION_HP))
        self.by_id = {u.id: u for u in self.units}
        self.t = 0.0
        self.effects = []
        self.events = []
        self.casts = {role: 0 for role in ROLE_PROMPTS}
        self.skills = {}
        self.result = ''
        self.received_damage = {u.id: 0.0 for u in self.units}
        self.interrupts = 0
        self.absorbed_damage = 0.0
        self.redirected_damage = 0.0

    def living(self, team):
        return [u for u in self.units if u.team == team and u.alive]

    def options(self, actor: Unit):
        if not actor.alive or actor.stealth > 0 or actor.stun > 0:
            return {}
        choices = {'wait': 'Wait briefly; no ability used.'}
        enemies, allies = self.living('enemy'), self.living('party')
        ready = lambda skill: actor.skill_cooldowns.get(skill, 0) <= 0
        reactions = {}
        if actor.role == 'tank':
            if ready('interrupt'):
                for enemy in enemies:
                    if enemy.windup > 0 and distance(actor, enemy) <= 240:
                        reactions[f'interrupt:{enemy.id}'] = f'Interrupt {enemy.id} strike on {enemy.windup_target} in {enemy.windup:.2f}s; dash, cancel and stun 1.5s. Reuse 7s.'
            if ready('cover'):
                for ally in allies:
                    if ally is not actor and distance(actor, ally) <= 285:
                        reactions[f'cover:{ally.id}'] = f'Dash to cover {ally.id}; transfer 70% of its damage to tank for 3s. Reuse 9s.'
        if actor.role == 'archer' and ready('stealth'):
            reactions['stealth'] = 'Untargetable for 2.5s; incoming committed strikes miss, but cannot attack while hidden. Reuse 10s.'
        if actor.role == 'healer' and ready('barrier'):
            for ally in allies:
                if ally.shield <= 0 and distance(actor, ally) <= 285:
                    reactions[f'barrier:{ally.id}'] = f'Absorb next 45 damage on {ally.id} for 4s; no heal. Reuse 7s.'
        if actor.cooldown > 0:
            return {'wait': choices['wait'], **reactions} if reactions else {}
        if actor.role in ('tank', 'archer'):
            for target in enemies:
                choices[f'attack:{target.id}'] = f'Attack {target.id}, single target, {10 if actor.role == "tank" else 20} damage.'
                if actor.role == 'archer' and ready('retreat'):
                    choices[f'retreat:{target.id}'] = f'Deal 12 to {target.id}, then retreat 110px away. Reuse 7s; normal cooldown 1.2s.'
        if actor.role == 'tank':
            if actor.taunt_cooldown <= 0:
                choices['taunt'] = 'Redirect all enemies to tank for 2s. Separate reuse cooldown 10s; action cooldown 1.2s.'
            if actor.guard < 1:
                choices['guard'] = 'Self guard: incoming damage -60% for 4s. Cooldown 1.2s.'
        if actor.role == 'mage':
            for target in enemies:
                cluster = [e.id for e in enemies if distance(e, target) <= 95]
                choices[f'aoe:{target.id}'] = f'22 damage to enemies within 95px of {target.id}; currently hits {cluster}.'
                if target.debuff < 1:
                    choices[f'debuff:{target.id}'] = f'Weaken {target.id}: damage x0.55, movement x0.6 for 6s.'
                if ready('root') and target.rooted <= 0:
                    choices[f'root:{target.id}'] = f'Immobilize {target.id} for 3s. Does not stop its attack if already in range. Reuse 8s.'
            for ally in allies:
                if ally.buff < 1:
                    choices[f'buff:{ally.id}'] = f'Buff {ally.id}: damage and healing x1.5 for 6s.'
        if actor.role == 'healer':
            for ally in allies:
                if ally.hp < ally.max_hp - 0.1:
                    choices[f'heal:{ally.id}'] = f'Heal {ally.id} for up to 30 HP (missing {ally.max_hp - ally.hp:.0f}).'
                    if ready('rescue'):
                        choices[f'rescue:{ally.id}'] = f'Emergency heal {ally.id} for 55 HP; locks normal actions 3s, reuse 8s.'
        return {**choices, **reactions}

    def snapshot(self):
        state = {'time_seconds': round(self.t, 1), 'difficulty': BATTLE_VERSION,
                 'goal': 'Defeat all enemies while keeping all four party members alive.',
                 'enemy_strategy': 'Boss prioritizes healer, then mage, then archer. Small enemies prioritize mage or archer. '
                     'They ignore tank unless taunted or no backline remains. Taunt lasts 2s with 10s reuse.',
                 'units': [], 'rules': 'Party actions are selected independently from this shared snapshot. '
                    'Movement into casting range is automatic. Existing orders may execute while API is in flight. '
                    'Effects are durations remaining in seconds; cooldown is seconds until next ability. '
                    'Dead units cannot act. All attacks/heals are single-target except mage AOE. No resurrection. '
                    'Enemy windup is a committed attack on windup_target: boss 1.2s, small enemy 0.7s. '
                    'A taunt affects NEW targeting only, not an existing windup. Interrupt cancels it; stealth evades; barrier absorbs; cover redirects. '
                    'Stealth prevents own attacks too; root stops movement only. Reactions (interrupt, cover, stealth, barrier) work during normal cooldown. '
                    'Account for API latency: a nearly finished windup may land before your answer arrives.'}
        for u in self.units:
            state['units'].append({'id': u.id, 'role': u.role, 'team': u.team, 'hp': round(u.hp, 1), 'max_hp': u.max_hp,
                                   'position': [round(u.x), round(u.y)], 'cooldown': round(u.cooldown, 1),
                                   'buff_seconds': round(u.buff, 1), 'debuff_seconds': round(u.debuff, 1),
                                   'guard_seconds': round(u.guard, 1), 'taunt_seconds': round(u.taunt, 1),
                                   'taunt_reuse_seconds': round(u.taunt_cooldown, 1),
                                   'skill_reuse_seconds': {key:round(value,1) for key,value in u.skill_cooldowns.items()},
                                   'stealth_seconds':round(u.stealth,1), 'stun_seconds':round(u.stun,1),
                                   'root_seconds':round(u.rooted,1), 'shield_hp':round(u.shield,1),
                                   'shield_seconds':round(u.shield_time,1), 'covered_by':u.covered_by if u.cover_time>0 else None,
                                   'cover_seconds':round(u.cover_time,1),
                                   'windup_seconds':round(u.windup,2), 'windup_target':u.windup_target,
                                   'base_attack_damage': BOSS_DAMAGE if u.role == 'boss' else MINION_DAMAGE if u.role == 'minion' else None,
                                   'current_target': u.target})
        choices = {u.id: self.options(u) for u in self.living('party')}
        # A full-health healer with only WAIT needs no model call.
        choices = {key: value for key, value in choices.items() if len(value) > 1}
        return state, choices

    def apply(self, orders):
        accepted = 0
        for actor_id, order in orders.items():
            actor = self.by_id.get(actor_id)
            if actor and order in self.options(actor):
                # Instant reactions execute on acceptance; they must not replace queued normal actions.
                if order.split(':')[0] in REACTIONS:
                    old_order = actor.order
                    actor.order = order
                    self.cast(actor)
                    actor.order = 'wait' if actor.stealth > 0 else old_order
                else:
                    actor.order = order
                accepted += 1
        return accepted

    def move(self, actor, target, reach, dt):
        gap = distance(actor, target)
        if gap <= reach:
            return True
        if actor.rooted > 0 or actor.stun > 0:
            return False
        speed = 42 if actor.role == 'boss' else 65 if actor.team == 'enemy' else 100
        speed *= 0.6 if actor.debuff > 0 else 1
        step = min(speed * dt, gap - reach)
        actor.x += (target.x - actor.x) / gap * step
        actor.y += (target.y - actor.y) / gap * step
        return False

    def effect(self, kind, source, target, amount=0, radius=0):
        self.effects.append({'kind': kind, 'source': source.pos, 'target': target.pos, 'amount': amount,
                             'radius': radius, 'expires': self.t + 0.55})

    def damage(self, source, target, amount):
        if not target.alive or target.stealth > 0:
            return
        amount *= 1.5 if source.buff > 0 else 1
        amount *= 0.55 if source.debuff > 0 else 1
        protector = self.by_id.get(target.covered_by)
        if target.cover_time > 0 and protector and protector.alive and protector is not target and distance(target, protector) <= 160:
            shared = amount * 0.7
            amount -= shared
            self.redirected_damage += shared
            self.take_damage(source, protector, shared)
        self.take_damage(source, target, amount)

    def take_damage(self, source, target, amount):
        amount *= 0.4 if target.guard > 0 else 1
        absorbed = min(target.shield, amount) if target.shield_time > 0 else 0
        target.shield -= absorbed
        amount -= absorbed
        self.absorbed_damage += absorbed
        self.received_damage[target.id] += min(target.hp, amount)
        target.hp = max(0, target.hp - amount)
        self.effect('damage', source, target, amount)

    def cast(self, actor):
        order = actor.order
        skill, _, target_id = order.partition(':')
        target = self.by_id.get(target_id, actor)
        if not target.alive:
            actor.order = 'wait'
            return
        if skill in SKILL_REUSE and actor.skill_cooldowns.get(skill, 0) > 0:
            actor.order = 'wait'
            return
        if skill == 'interrupt' and (target.windup <= 0 or distance(actor,target)>240):
            actor.order = 'wait'
            return
        if skill in ('cover','barrier') and distance(actor,target)>285:
            actor.order = 'wait'
            return
        actor.target=target.id
        if skill == 'attack':
            self.damage(actor, target, 10 if actor.role == 'tank' else 20)
            actor.cooldown = 0.9 if actor.role == 'tank' else 1.2
            label = f'攻撃 → {target.id}'
        elif skill == 'taunt':
            if actor.taunt_cooldown > 0:
                actor.order = 'wait'
                return
            actor.taunt = TAUNT_DURATION
            actor.taunt_cooldown = TAUNT_REUSE
            actor.cooldown = 1.2
            self.effect('taunt', actor, actor, radius=80)
            label = '挑発：敵を引きつける'
        elif skill == 'guard':
            actor.guard = 4
            actor.cooldown = 1.2
            label = '防御：被ダメージ軽減'
        elif skill == 'interrupt':
            self.dash_near(actor,target,43)
            target.windup = 0
            target.windup_target = None
            target.stun = 1.5
            self.interrupts += 1
            self.effect('interrupt',actor,target,radius=45)
            label = f'割り込み → {target.id}'
        elif skill == 'cover':
            self.dash_near(actor,target,25)
            target.covered_by = actor.id
            target.cover_time = 3
            self.effect('cover',actor,target)
            label = f'かばう → {target.id}'
        elif skill == 'stealth':
            actor.stealth = 2.5
            label = 'ステルス：攻撃も休止'
        elif skill == 'retreat':
            self.damage(actor,target,12)
            dx,dy=actor.x-target.x,actor.y-target.y
            length=math.hypot(dx,dy)
            if length<1:
                dx,dy,length=-1,0,1
            actor.x=min(855,max(45,actor.x+110*dx/length))
            actor.y=min(445,max(130,actor.y+110*dy/length))
            actor.cooldown=1.2
            self.effect('retreat',target,actor)
            label=f'退避射撃 → {target.id}'
        elif skill == 'root':
            target.rooted=3
            actor.cooldown=2
            self.effect('root',actor,target,radius=35)
            label=f'足止め → {target.id}'
        elif skill == 'barrier':
            target.shield=45
            target.shield_time=4
            self.effect('barrier',actor,target)
            label=f'障壁 → {target.id}'
        elif skill == 'rescue':
            amount=min(target.max_hp-target.hp,55*(1.5 if actor.buff>0 else 1))
            target.hp+=amount
            actor.cooldown=3
            self.effect('heal',actor,target,amount)
            label=f'緊急回復 → {target.id}'
        elif skill == 'heal':
            amount = min(target.max_hp - target.hp, 30 * (1.5 if actor.buff > 0 else 1))
            target.hp += amount
            actor.cooldown = 1.8
            self.effect('heal', actor, target, amount)
            label = f'回復 → {target.id}'
        elif skill == 'buff':
            target.buff = 6
            actor.cooldown = 2
            self.effect('buff', actor, target)
            label = f'強化 → {target.id}'
        elif skill == 'debuff':
            target.debuff = 6
            actor.cooldown = 2
            self.effect('debuff', actor, target)
            label = f'弱体 → {target.id}'
        elif skill == 'aoe':
            self.effect('aoe', actor, target, radius=95)
            for enemy in self.living('enemy'):
                if distance(enemy, target) <= 95:
                    self.damage(actor, enemy, 22)
            actor.cooldown = 2
            label = f'範囲攻撃 → {target.id}'
        else:
            return
        if skill in SKILL_REUSE:
            actor.skill_cooldowns[skill]=SKILL_REUSE[skill]
        self.casts[actor.role] += 1
        self.skills[skill] = self.skills.get(skill, 0) + 1
        actor.last = label
        actor.order = 'wait'
        self.events.append(f'{self.t:4.1f}s {ROLE_NAMES[actor.role]}：{label}')

    def dash_near(self,actor,target,reach):
        gap=distance(actor,target)
        if gap>reach:
            actor.x=target.x+(actor.x-target.x)/gap*reach
            actor.y=target.y+(actor.y-target.y)/gap*reach

    def enemy_target(self, enemy, allies):
        allies=[a for a in allies if a.stealth<=0]
        if not allies:
            return None
        taunting = [a for a in allies if a.taunt > 0]
        if taunting:
            return min(taunting, key=lambda a: distance(enemy, a))
        priorities = (['healer', 'mage', 'archer', 'tank'] if enemy.role == 'boss' else
                      ['mage', 'archer', 'healer', 'tank'] if enemy.id in ('minion1', 'minion3') else
                      ['archer', 'mage', 'healer', 'tank'])
        return min(allies, key=lambda a: (priorities.index(a.role), distance(enemy, a)))

    def tick(self, dt):
        if self.result:
            return
        self.t += dt
        for u in self.units:
            for timer in ('cooldown', 'buff', 'debuff', 'guard', 'taunt', 'taunt_cooldown',
                          'stealth','stun','rooted','shield_time','cover_time'):
                setattr(u, timer, max(0, getattr(u, timer) - dt))
            u.skill_cooldowns={skill:max(0,value-dt) for skill,value in u.skill_cooldowns.items()}
            if u.shield_time<=0:
                u.shield=0
            if u.cover_time<=0:
                u.covered_by=None
        for actor in self.living('party'):
            if actor.cooldown > 0 or actor.stealth>0 or actor.stun>0 or actor.order == 'wait':
                continue
            skill, _, target_id = actor.order.partition(':')
            target = self.by_id.get(target_id, actor)
            if not target.alive or (skill in ('heal','rescue') and target.hp >= target.max_hp):
                actor.order = 'wait'
                continue
            actor.target = target.id
            reach = 43 if actor.role == 'tank' and skill == 'attack' else 285
            if skill in ('guard', 'taunt') or self.move(actor, target, reach, dt):
                self.cast(actor)
        allies = self.living('party')
        for enemy in self.living('enemy'):
            if not allies:
                break
            if enemy.stun>0:
                continue
            if enemy.windup>0:
                enemy.windup=max(0,enemy.windup-dt)
                if enemy.windup<=0:
                    victim=self.by_id.get(enemy.windup_target)
                    reach=52 if enemy.role=='boss' else 37
                    if victim and victim.alive and victim.stealth<=0 and distance(enemy,victim)<=reach+25:
                        self.damage(enemy,victim,BOSS_DAMAGE if enemy.role=='boss' else MINION_DAMAGE)
                    enemy.windup_target=None
                    allies=self.living('party')
                continue
            target = self.enemy_target(enemy, allies)
            if target is None:
                enemy.target=None
                continue
            enemy.target = target.id
            in_range = self.move(enemy, target, 52 if enemy.role == 'boss' else 37, dt)
            if in_range and enemy.cooldown <= 0:
                enemy.windup=1.2 if enemy.role=='boss' else 0.7
                enemy.windup_target=target.id
                enemy.cooldown = 2.4 if enemy.role == 'boss' else 1.4
        self.effects = [e for e in self.effects if e['expires'] > self.t]
        if not self.living('enemy'):
            self.result = 'VICTORY'
        elif not self.living('party'):
            self.result = 'DEFEAT'


class BattleJev:
    def __init__(self, key):
        self.session = requests.Session()
        self.session.headers['Authorization'] = f'Bearer {key}'

    def decide(self, state, choices):
        start = time.perf_counter()
        result = {'state': state, 'choices': choices}
        questions = {hero: {'type': 'choice', 'instructions': f'Control ONLY {hero}. Select its NEXT action and target. '
                     'Current target is previous state, not a recommendation. ' + ROLE_PROMPTS[hero],
                     'criteria': options} for hero, options in choices.items()}
        try:
            response = self.session.post('https://api.typesafe.ai/v1/systemone',
                json={'model': 'jev-latest', 'state': state, 'questions': questions}, timeout=(3, 3), allow_redirects=False)
            if response.status_code != 200:
                result['error'] = f'HTTP {response.status_code}'
                result['fatal'] = response.status_code in (400, 401, 402, 403, 404, 422, 429)
            else:
                data = response.json()
                orders = {hero: data['answers'][hero]['choice'] for hero in choices}
                if any(order not in choices[hero] for hero, order in orders.items()):
                    raise ValueError('Unexpected choice')
                result.update(orders=orders, answers=data['answers'], usage=data.get('usage', {}), model=data.get('model'))
        except requests.RequestException:
            result['error'] = 'API connection / timeout'
        except (KeyError, TypeError, ValueError):
            result['error'] = 'Invalid API response'
        result['latency_ms'] = round((time.perf_counter() - start) * 1000, 1)
        return result


def basic_orders(battle, choices):
    orders = {}
    for hero, options in choices.items():
        if hero == 'healer':
            options_heal = [a for a in options if a.startswith('heal:')]
            orders[hero] = min(options_heal, key=lambda a: battle.by_id[a.split(':')[1]].hp / battle.by_id[a.split(':')[1]].max_hp) if options_heal else 'wait'
        elif hero == 'tank' and 'taunt' in options:
            orders[hero] = 'taunt'
        elif hero == 'mage':
            aoes = [a for a in options if a.startswith('aoe:')]
            orders[hero] = max(aoes, key=lambda a: sum(distance(e, battle.by_id[a.split(':')[1]]) <= 95 for e in battle.living('enemy'))) if aoes else 'wait'
        else:
            attacks = [a for a in options if a.startswith('attack:')]
            orders[hero] = min(attacks, key=lambda a: battle.by_id[a.split(':')[1]].hp) if attacks else 'wait'
    return orders


def baseline_orders(battle, choices):
    from tactical_policy import tactical_orders
    state, _ = battle.snapshot()
    return tactical_orders(state, choices)


def draw(screen, battle, stats, font, small, titlefont, paused):
    screen.fill('#0b1020')
    def text(s, x, y, color='#e5edf9', f=small):
        screen.blit(f.render(str(s), True, color), (x, y))
    def bar(x, y, width, ratio, color):
        pygame.draw.rect(screen, '#29364b', (x, y, width, 7), border_radius=3)
        pygame.draw.rect(screen, color, (x, y, max(0, width * ratio), 7), border_radius=3)
    text('JEV PARTY', 25, 14, '#80dfff', titlefont)
    text('TACTICAL / 技と対象を選ぶ', 245, 28, f=font)
    text(f"{stats['controller'].upper()}   {battle.t:05.1f}s   API {stats['latency_ms']:.0f} ms", 890, 30)
    pygame.draw.rect(screen, '#111d30', (20, 90, 870, 395), border_radius=15)
    for x in range(40, 885, 40):
        pygame.draw.line(screen, '#19283b', (x, 100), (x, 470))
    for y in range(110, 480, 40):
        pygame.draw.line(screen, '#19283b', (30, y), (880, y))
    for u in battle.units:
        p = (round(u.x), round(u.y))
        if not u.alive:
            pygame.draw.line(screen, '#596477', (p[0]-10, p[1]-10), (p[0]+10, p[1]+10), 3)
            pygame.draw.line(screen, '#596477', (p[0]+10, p[1]-10), (p[0]-10, p[1]+10), 3)
            continue
        radius = 35 if u.role == 'boss' else 19 if u.team == 'party' else 15
        color = COLORS[u.role]
        if u.stealth>0:
            color='#596e8b'
        if u.target and battle.by_id[u.target].alive:
            pygame.draw.line(screen, COLORS[u.role] if u.team=='party' else '#63394a', p, battle.by_id[u.target].pos, 1)
        if u.windup>0 and u.windup_target:
            pygame.draw.line(screen, '#ff596e', p, battle.by_id[u.windup_target].pos, 3)
            text(f'攻撃まで {u.windup:.1f}s',p[0]-45,p[1]-radius-43,'#ff8997')
        pygame.draw.circle(screen, '#060c18', (p[0]+3, p[1]+5), radius+2)
        pygame.draw.circle(screen, color, p, radius)
        if u.role == 'tank':
            pygame.draw.polygon(screen, '#17385a', [(p[0]-10,p[1]-11),(p[0]+10,p[1]-11),(p[0]+8,p[1]+7),(p[0],p[1]+14),(p[0]-8,p[1]+7)])
        elif u.role == 'archer':
            pygame.draw.arc(screen, '#493b20', (p[0]-10,p[1]-13,20,26), -1.5, 1.5, 3)
            pygame.draw.line(screen, '#493b20', (p[0]-12,p[1]), (p[0]+12,p[1]), 3)
        elif u.role == 'mage':
            pygame.draw.polygon(screen, '#442767', [(p[0],p[1]-14),(p[0]-11,p[1]+10),(p[0]+11,p[1]+10)])
        elif u.role == 'healer':
            pygame.draw.line(screen, '#1b5042', (p[0]-10,p[1]), (p[0]+10,p[1]), 5)
            pygame.draw.line(screen, '#1b5042', (p[0],p[1]-10), (p[0],p[1]+10), 5)
        else:
            for dx in (-8, 8):
                pygame.draw.circle(screen, '#3f1425', (p[0]+dx,p[1]-3), 3)
        if u.buff > 0:
            pygame.draw.circle(screen, '#eacb75', p, radius+5, 2)
        if u.debuff > 0:
            pygame.draw.circle(screen, '#ce8cff', p, radius+6, 3)
        if u.guard > 0:
            pygame.draw.circle(screen, '#9ae6ff', p, radius+9, 3)
        if u.shield>0:
            pygame.draw.circle(screen,'#68e8b0',p,radius+12,2)
        if u.cover_time>0 and u.covered_by and battle.by_id[u.covered_by].alive:
            pygame.draw.line(screen,'#5cc8ff',p,battle.by_id[u.covered_by].pos,5)
        if u.stealth>0:
            text('隠密',p[0]-16,p[1]-radius-43,'#a1b2cd')
        if u.stun>0:
            text('STUN',p[0]-20,p[1]-radius-43,'#ffce67')
        if u.rooted>0:
            pygame.draw.circle(screen,'#c397ff',p,radius+7,2)
        if u.taunt > 0:
            text('挑発', p[0]-16, p[1]-radius-43, '#ffce67')
        bar(p[0]-28, p[1]-radius-13, 56, u.hp/u.max_hp, color)
        text(ROLE_NAMES[u.role] if u.team == 'party' else u.id, p[0]-30, p[1]+radius+5, color)
    for e in battle.effects:
        color = '#68e8b0' if e['kind']=='heal' else '#d4a4ff' if e['kind'] in ('aoe','debuff') else '#ffdc8b'
        target = tuple(round(x) for x in e['target'])
        pygame.draw.line(screen, color, e['source'], target, 2)
        if e['radius']:
            pygame.draw.circle(screen, color, target, round(e['radius']*(1-(e['expires']-battle.t)/0.7)), 2)
        if e['amount']:
            text(('+' if e['kind']=='heal' else '-')+str(round(e['amount'])), target[0], target[1]-35-round((0.55-e['expires']+battle.t)*30), color)
    for i, hero in enumerate(battle.units[:4]):
        x = 20 + i*220
        pygame.draw.rect(screen, '#152136', (x, 505, 210, 172), border_radius=12)
        text(ROLE_NAMES[hero.role], x+14, 516, COLORS[hero.role], font)
        text(f'HP {hero.hp:.0f} / {hero.max_hp:.0f}', x+14, 550)
        bar(x+14, 580, 182, hero.hp/hero.max_hp, COLORS[hero.role])
        text('戦闘不能' if not hero.alive else f'次の技まで {hero.cooldown:.1f}s', x+14, 596)
        # Keep per-card labels compact; full target details appear in the event log.
        cds=[f'{SKILL_LABELS[k]}{v:.0f}' for k,v in hero.skill_cooldowns.items() if v>0]
        if hero.role=='tank' and hero.taunt_cooldown>0:
            cds.insert(0,f'挑発{hero.taunt_cooldown:.0f}')
        text((' '.join(cds[:3]) if cds else '特殊技 使用可能') if hero.alive else '—',x+14,620,'#ffcf78')
        text(hero.last.replace('minion', '小型'), x+14, 646, '#a7bbd2')
    text('BATTLE LOG', 915, 97, '#80dfff', font)
    for i, line in enumerate(battle.events[-12:]):
        text(line.replace('minion', '小型'), 910, 138+i*30, '#b4c5dc')
    text(f"API {stats['calls']} / {stats['max_calls']} 回", 920, 535)
    text(f"受理 {stats['accepted']} / 破棄 {stats['discarded']}", 920, 565)
    text(f"観測から {stats['age_ms']:.0f} ms", 920, 595)
    text(stats['status'], 920, 628, '#ffcf78')
    text('SPACE 一時停止 / 再開    ESC 終了    |    技と対象はJev、移動と射程判定はゲーム側', 26, 697)
    if paused or battle.result:
        label = battle.result or 'PAUSED'
        pygame.draw.rect(screen, '#20324b', (250, 245, 420, 85), border_radius=15)
        text(label, 275, 265, '#ffcf78', titlefont)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', choices=['jev', 'baseline'], default='jev')
    parser.add_argument('--duration', type=float, default=90)
    parser.add_argument('--max-calls', type=int, default=120)
    parser.add_argument('--interval', type=float, default=0.5)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--paused', action='store_true')
    parser.add_argument('--screenshot')
    args = parser.parse_args()
    if args.max_calls < 1 or any(not math.isfinite(v) or v <= 0 for v in (args.duration,args.interval)):
        parser.error('Limits must be positive and finite.')
    key = os.environ.pop('TYPESAFE_API_KEY', '')
    if args.controller == 'jev' and not key:
        parser.error('Run battle.cmd after jev.cmd -ConfigureKey.')
    if args.headless:
        os.environ['SDL_VIDEODRIVER'] = 'dummy'
    pygame.init()
    screen = pygame.display.set_mode((1240,730))
    pygame.display.set_caption('Jev Party - TACTICAL realtime battle')
    font_path = pygame.font.match_font('yugothic,meiryo,msgothic')
    font, small, titlefont = (pygame.font.Font(font_path, size) for size in (22,16,30))
    battle = Battle()
    client = BattleJev(key) if args.controller == 'jev' else None
    key = None
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    sent = next_call = 0.0
    paused = args.paused
    clock = pygame.time.Clock()
    accumulator = active_wall = 0.0
    previous = time.perf_counter()
    latencies = []
    stats = dict(controller=args.controller, calls=0,max_calls=args.max_calls,accepted=0,discarded=0,
                 errors=0,latency_ms=0.0,age_ms=0.0,input_tokens=0,output_tokens=0,status='準備完了')
    run_dir = ROOT/'runs'/('battle-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    run_dir.mkdir(parents=True)
    log = (run_dir/'decisions.jsonl').open('w',encoding='utf-8')
    running = True
    try:
        while running:
            now = time.perf_counter()
            elapsed, previous = now-previous, now
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type==pygame.KEYDOWN and event.key==pygame.K_ESCAPE):
                    running = False
                elif event.type==pygame.KEYDOWN and event.key==pygame.K_SPACE and not battle.result:
                    paused = not paused
            if not running:
                break
            if not paused and not battle.result:
                active_wall += elapsed
                accumulator += elapsed
                for _ in range(min(int(accumulator*30),15)):
                    battle.tick(1/30)
                    accumulator -= 1/30
                if active_wall >= args.duration and not battle.result:
                    battle.result = 'TIME LIMIT'
            if future and future.done():
                result = future.result()
                future = None
                age = time.perf_counter()-sent
                stats['age_ms'] = round(age*1000,1)
                stats['latency_ms'] = result['latency_ms']
                latencies.append(result['latency_ms'])
                for field in ('input_tokens','output_tokens'):
                    stats[field] += result.get('usage',{}).get(field,0)
                accepted = 0
                if result.get('error'):
                    stats['errors'] += 1
                    stats['status'] = result['error']
                    if result.get('fatal') or stats['errors'] >= 3:
                        battle.result = 'API ERROR'
                elif not paused and not battle.result and age <= 1.5:
                    accepted = battle.apply(result['orders'])
                    stats['status'] = '判断を反映'
                else:
                    stats['status'] = '古い判断を破棄'
                stats['accepted'] += accepted
                stats['discarded'] += len(result.get('orders',{}))-accepted
                result.update(age_ms=stats['age_ms'],accepted=accepted,applied_sim_seconds=round(battle.t,2))
                log.write(json.dumps(result,ensure_ascii=False)+'\n'); log.flush()
                print(json.dumps({'time':round(battle.t,1),'orders':result.get('orders'),
                                  'accepted':accepted,'latency_ms':result['latency_ms'],'error':result.get('error')}),flush=True)
                if stats['calls'] >= args.max_calls and not battle.result:
                    battle.result = 'API CALL LIMIT'
            if not paused and not battle.result and future is None and now >= next_call:
                state, choices = battle.snapshot()
                if choices:
                    if client:
                        sent = time.perf_counter()
                        future = executor.submit(client.decide,state,choices)
                        stats['calls'] += 1
                        stats['status'] = 'Jev 判断中'
                    else:
                        stats['accepted'] += battle.apply(baseline_orders(battle,choices))
                        stats['status'] = 'ローカル比較制御'
                    next_call = now+args.interval
            if not args.headless or args.screenshot:
                draw(screen,battle,stats,font,small,titlefont,paused)
                pygame.display.flip()
            if battle.result and args.headless:
                break
            clock.tick(30)
    finally:
        executor.shutdown(wait=True,cancel_futures=True)
        if future and future.done() and not future.cancelled():
            result = future.result()
            result.update(accepted=0,status='Stopped: discarded')
            log.write(json.dumps(result,ensure_ascii=False)+'\n')
            stats['discarded'] += len(result.get('orders',{}))
            latencies.append(result['latency_ms'])
            for field in ('input_tokens','output_tokens'):
                stats[field] += result.get('usage',{}).get(field,0)
        if args.screenshot:
            Path(args.screenshot).parent.mkdir(parents=True,exist_ok=True)
            pygame.image.save(screen,args.screenshot)
        summary = {**stats,'battle_version':BATTLE_VERSION,'result':battle.result or 'USER STOP','sim_seconds':round(battle.t,2),
                   'active_wall_seconds':round(active_wall,2),'casts':battle.casts,'skills':battle.skills,
                   'remaining_hp':{u.id:round(u.hp,1) for u in battle.units},
                   'received_damage':{key:round(value,1) for key,value in battle.received_damage.items()},
                   'interrupts':battle.interrupts,'absorbed_damage':round(battle.absorbed_damage,1),
                   'redirected_damage':round(battle.redirected_damage,1),
                   'mean_latency_ms':round(sum(latencies)/len(latencies),1) if latencies else None}
        (run_dir/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        log.close()
        if client:
            client.session.close()
        pygame.quit()
        print(json.dumps(summary,ensure_ascii=True,indent=2),flush=True)
        print(f'Logs: {run_dir}',flush=True)


if __name__=='__main__':
    main()
