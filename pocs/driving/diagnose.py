"""Replay one recorded state with controlled changes; no simulator or UI."""
import copy
import json
import os
from pathlib import Path
from pocs.driving.app import Jev

from pocs.common.paths import ROOT as root
logs = sorted((root / 'runs').glob('[0-9]*/decisions.jsonl'), reverse=True)
rows = [json.loads(line) for line in logs[0].read_text(encoding='utf-8').splitlines()]
original = next(row['state'] for row in rows if row['state']['sim_seconds'] >= 8)
client = Jev(os.environ.pop('TYPESAFE_API_KEY'), 4)
post = client.session.post
captured = {}

def capture(*args, **kwargs):
    response = post(*args, **kwargs)
    if response.status_code == 200:
        captured['answers'] = response.json().get('answers', {})
    return response

client.session.post = capture
cases = {'recorded_state': copy.deepcopy(original),
         'no_other_vehicles': copy.deepcopy(original),
         'no_vehicles_and_no_held_brake': copy.deepcopy(original),
         'straight_empty_road': copy.deepcopy(original)}
for name, state in cases.items():
    if name != 'recorded_state':
        for lane in state['lanes']:
            lane['front'] = lane['rear'] = None
    if name in ('no_vehicles_and_no_held_brake', 'straight_empty_road'):
        state['ego']['held_acceleration_mps2'] = 0
    if name == 'straight_empty_road':
        state['ego'].update(lane=1, y_m=4.0, heading_rad=0.0,
                            lateral_velocity_mps=0.0, held_steering_rad=0.0)
results = []
try:
    for name, state in cases.items():
        captured.clear()
        result = client.decide(state)
        report = {'case': name, 'state': state, 'answers': captured.get('answers'),
                  'error': result.get('error'), 'latency_ms': result['latency_ms']}
        results.append(report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
finally:
    client.session.close()
    (root / 'runs' / 'braking-diagnosis.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
