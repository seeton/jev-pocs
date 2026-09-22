"""Fixed, deterministic policy using ONLY the same state and legal choices as Jev.

No game objects, future information or controller-dependent combat rules.
Thresholds are a single hand-written policy, not an optimal-policy claim.
"""
import math


def tactical_orders(state, choices):
    units = {u['id']: u for u in state['units']}
    allies = [u for u in units.values() if u['team']=='party' and u['hp']>0]
    enemies = [u for u in units.values() if u['team']=='enemy' and u['hp']>0]
    def gap(a,b):
        return math.dist(a['position'],b['position'])
    def incoming(ally):
        return sum((e.get('base_attack_damage') or 0)*(0.55 if e.get('debuff_seconds',0)>0 else 1)
                   for e in enemies if e.get('windup_target')==ally['id'] and e.get('windup_seconds',0)>0)
    def pressure(ally):
        return sum(e.get('current_target')==ally['id'] for e in enemies)
    def need(ally):
        return (ally['max_hp']-ally['hp'])/ally['max_hp'] + incoming(ally)/max(ally['hp'],1)
    orders={}
    for hero, options in choices.items():
        actor=units[hero]
        candidates=[]
        def propose(action, score):
            if action in options:
                candidates.append((score,action))
        propose('wait',0)
        # Ordinary single-target attacks: finish enemies, avoid unnecessary travel.
        for enemy in enemies:
            propose(f"attack:{enemy['id']}",25+(1-enemy['hp']/enemy['max_hp'])*15-
                    gap(actor,enemy)*0.015+(5 if enemy['role']=='minion' else 0))
        if hero=='tank':
            for enemy in enemies:
                victim=units.get(enemy.get('windup_target'))
                if victim and enemy.get('windup_seconds',0)>0.15:
                    propose(f"interrupt:{enemy['id']}",100+incoming(victim)/max(victim['hp'],1)*30)
            for ally in allies:
                if ally['id']!=hero and actor['hp']>55 and (incoming(ally)>0 or (pressure(ally)>0 and ally['hp']/ally['max_hp']<0.5)):
                    propose(f"cover:{ally['id']}",70+need(ally)*10)
            if any(pressure(a)>0 and a['id']!=hero for a in allies):
                propose('taunt',60)
            if incoming(actor)>0 or (pressure(actor)>0 and actor['hp']<actor['max_hp']*0.7):
                propose('guard',75)
        elif hero=='archer':
            if incoming(actor)>actor['hp']*0.45 or (pressure(actor)>0 and actor['hp']/actor['max_hp']<0.4):
                propose('stealth',100)
            for enemy in enemies:
                if enemy.get('current_target')==hero and gap(actor,enemy)<110:
                    propose(f"retreat:{enemy['id']}",65+incoming(actor)/max(actor['hp'],1)*10)
        elif hero=='mage':
            for enemy in enemies:
                count=sum(gap(enemy,e)<=95 for e in enemies)
                propose(f"aoe:{enemy['id']}",25+count*12+(1-enemy['hp']/enemy['max_hp'])*5)
                if enemy.get('current_target') and (enemy['role']=='boss' or incoming(units[enemy['current_target']])>30):
                    propose(f"debuff:{enemy['id']}",65 if enemy['role']=='boss' else 47)
                if enemy.get('current_target') and gap(enemy,units[enemy['current_target']])>85:
                    propose(f"root:{enemy['id']}",42 if enemy['role']=='boss' else 35)
            for ally in allies:
                if ally['id']=='healer' and any(need(a)>0.5 for a in allies):
                    propose('buff:healer',68)
                elif ally['id']=='archer':
                    propose('buff:archer',46)
        elif hero=='healer':
            for ally in allies:
                missing=ally['max_hp']-ally['hp']
                threat=incoming(ally)
                if threat>0:
                    propose(f"barrier:{ally['id']}",85+threat/max(ally['hp'],1)*20)
                elif pressure(ally)>0 and ally['hp']/ally['max_hp']<0.6:
                    propose(f"barrier:{ally['id']}",55+need(ally)*10)
                if missing>=8:
                    propose(f"heal:{ally['id']}",35+need(ally)*25)
                if missing>=45 and ally['hp']/ally['max_hp']<0.45:
                    propose(f"rescue:{ally['id']}",80+need(ally)*20)
        orders[hero]=max(candidates,key=lambda entry:(entry[0],entry[1]))[1] if candidates else 'wait'
    return orders
