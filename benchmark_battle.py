"""Fast deterministic baseline checks. No API, wall-clock waiting or model changes."""
import json
from pathlib import Path
from battle import Battle, BATTLE_VERSION, baseline_orders


def run(interval, delay):
    b = Battle()
    pending = None
    next_decision = 0
    for _ in range(180*30):
        b.tick(1/30)
        if b.result:
            break
        if pending and b.t >= pending[0]:
            b.apply(pending[1])
            pending = None
        if pending is None and b.t >= next_decision:
            _, options = b.snapshot()
            orders = baseline_orders(b,options)
            if delay:
                pending = (b.t+delay, orders)
            else:
                b.apply(orders)
            next_decision = b.t+interval
    return {'version':BATTLE_VERSION,'decision_interval':interval,'fixed_response_delay':delay,
            'result':b.result or 'TIME LIMIT','sim_seconds':round(b.t,1),
            'remaining_hp':{u.id:round(u.hp,1) for u in b.units},
            'received_damage':{k:round(v,1) for k,v in b.received_damage.items()},'skills':b.skills}


if __name__=='__main__':
    results = [run(interval,delay) for interval,delay in [(0.25,0),(0.5,0),(0.5,0.25),(1,0.25)]]
    destination = Path(__file__).resolve().parent/'runs'/f'battle-{BATTLE_VERSION}-baseline.json'
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))
