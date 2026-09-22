"""Real-time HighwayEnv + Jev. Simulation continues while HTTP runs on a worker."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import math
import os
from pathlib import Path
import time

os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'

import gymnasium as gym
import highway_env  # noqa: F401 -- registers environments
import numpy as np
import pygame
import requests

from pocs.common.paths import ROOT
STEERING = {'left_medium': -0.06, 'left_small': -0.02, 'left_tiny': -0.006,
            'straight': 0.0, 'right_tiny': 0.006, 'right_small': 0.02, 'right_medium': 0.06}
ACCELERATION = {'brake_hard': -6.0, 'brake': -3.0, 'ease_off': -1.0,
                'coast': 0.0, 'accelerate': 1.5, 'accelerate_hard': 3.0}


def control_array(action: dict) -> np.ndarray:
    # Exact conversion to HighwayEnv's normalized [acceleration, steering] input.
    return np.array([(ACCELERATION[action['acceleration']] + 6) / 9 * 2 - 1,
                     STEERING[action['steering']] / 0.12], dtype=np.float32)


def action_label(action: dict) -> str:
    return f"steer {STEERING[action['steering']]:+.3f} rad / accel {ACCELERATION[action['acceleration']]:+.1f}"


def make_env(duration: float, seed: int, offset: float = 0, heading: float = 0):
    env = gym.make('highway-v0', render_mode='rgb_array', config={
        'lanes_count': 3, 'vehicles_count': 24, 'vehicles_density': 1.0,
        'initial_lane_id': 1, 'duration': duration, 'offroad_terminal': True,
        'simulation_frequency': 30, 'policy_frequency': 30,
        'action': {'type': 'ContinuousAction', 'acceleration_range': [-6, 3],
                   'steering_range': [-0.12, 0.12], 'speed_range': [0, 35]},
        'screen_width': 1200, 'screen_height': 310, 'scaling': 10.0,
        'offscreen_rendering': True, 'real_time_rendering': False,
    })
    env.reset(seed=seed)
    env.unwrapped.vehicle.position[1] += offset
    env.unwrapped.vehicle.heading = heading
    return env


def snapshot(env) -> dict:
    """Simulator telemetry, not camera perception. Only vehicles within 150 m."""
    base = env.unwrapped
    ego = base.vehicle
    lane_count = int(base.config['lanes_count'])
    lanes = [{'lane': lane, 'center_y_m': lane * 4.0, 'front': None, 'rear': None} for lane in range(lane_count)]
    for car in base.road.vehicles:
        if car is ego or car.lane_index[:2] != ego.lane_index[:2]:
            continue
        dx = float(car.position[0] - ego.position[0])
        if abs(dx) > 150:
            continue
        lane = int(car.lane_index[2])
        if not 0 <= lane < lane_count:
            continue
        slot = 'front' if dx >= 0 else 'rear'
        gap = max(0.0, abs(dx) - (float(ego.LENGTH) + float(car.LENGTH)) / 2)
        item = {'gap_m': round(gap, 1), 'speed_mps': round(float(car.speed), 1),
                'closing_mps': round(float(ego.speed - car.speed) if dx >= 0 else float(car.speed - ego.speed), 1)}
        if lanes[lane][slot] is None or gap < lanes[lane][slot]['gap_m']:
            lanes[lane][slot] = item
    return {
        'sim_seconds': round(float(base.time), 2),
        'ego': {'lane': int(ego.lane_index[2]), 'y_m': round(float(ego.position[1]), 3),
                'heading_rad': round(float(ego.heading), 4),
                'lateral_velocity_mps': round(float(ego.velocity[1]), 3),
                'speed_mps': round(float(ego.speed), 2),
                'held_steering_rad': round(float(ego.action['steering']), 4),
                'held_acceleration_mps2': round(float(ego.action['acceleration']), 2)},
        'lanes': lanes,
        'notes': 'Straight road; lane centers y=0,4,8 m; edges y=-2,10 m. Vehicle width 2 m, length 5 m. '
                 'Positive steering turns RIGHT toward increasing y; negative turns LEFT. Heading 0 follows road. '
                 'No automatic lane following or speed controller. Commands are held until the next accepted API response. '
                 'Lane 0 is leftmost. Gaps are bumper-to-bumper; null means no car within 150 m. '
                 'Positive closing_mps means the gap is shrinking. Telemetry becomes older during API latency.',
    }


def baseline_action(state: dict) -> dict:
    """Simple comparison only; does not call Jev or secretly override it."""
    ego = state['ego']
    front = state['lanes'][ego['lane']]['front']
    steer = -0.015 * (ego['y_m'] - 4) - 0.5 * ego['heading_rad']
    steering = min(STEERING, key=lambda key: abs(STEERING[key] - steer))
    accel = 'brake' if front and front['gap_m'] < max(15, ego['speed_mps'] * 1.8) else 'accelerate' if ego['speed_mps'] < 25 else 'coast'
    return {'steering': steering, 'acceleration': accel}


class Jev:
    def __init__(self, key: str, timeout: float):
        self.session = requests.Session()
        self.session.headers['Authorization'] = f'Bearer {key}'
        self.timeout = timeout

    def decide(self, state: dict) -> dict:
        started = time.perf_counter()
        payload = {
            'model': 'jev-latest', 'state': state,
            'questions': {'steering': {
                'type': 'choice',
                'instructions': 'Select the NEW steering command for the NEXT control interval, about 0.3 seconds. '
                    'held_steering_rad describes the OLD command, NOT a requested or recommended answer. Re-evaluate from geometry. '
                    'For this experiment, return to and stay in the MIDDLE lane: target y=4 m and heading=0 rad. Do not overtake. '
                    'Positive heading/lateral velocity means drifting right; negative means drifting left. '
                    'Correct position without building excess heading. If already heading toward the center, '
                    'countersteer early to reduce that heading rather than continuing to turn toward the center. '
                    'For example y=4.2 with heading=-0.06 calls for RIGHT steering to arrest leftward drift, '
                    'even though the car is still slightly right of center. y=3.8 with heading=+0.06 calls for LEFT. '
                    'At the center with heading near zero use straight. A zero angle does not undo existing heading. '
                    'Choose a stronger correction when heading error is large. Account for roughly 0.3 seconds of network delay.',
                'criteria': {name: f'NEW front wheel angle {value:+.3f} rad; '
                             + ('decrease heading / turn LEFT.' if value < 0 else 'increase heading / turn RIGHT.' if value > 0 else 'stop turning; keep heading.')
                             for name, value in STEERING.items()},
            }, 'acceleration': {
                'type': 'choice',
                'instructions': 'Select the NEW acceleration for the NEXT interval, NOT a description of current motion. '
                    'held_acceleration_mps2 is the OLD command. It is NOT a target, and is NOT a reason to keep braking. '
                    'Target speed is 25 m/s. First identify the lead vehicle in ego.lane; cars wholly in OTHER lanes '
                    'are not obstacles to forward motion unless the ego trajectory will cross into them. '
                    'Negative closing_mps means the lead car is pulling AWAY, not approaching. '
                    'Brake for an insufficient front gap (roughly 2 * ego speed in meters), closing collision threat, '
                    'or speed above 25 m/s. Otherwise, below 24 m/s choose positive acceleration; near 25 choose coast. '
                    'Do not stop for small correctable heading errors. '
                    'Example: speed=6, front gap=90 and closing=-14 -> accelerate, even if the old acceleration=-3. '
                    'Example: speed=25, front gap=10 and closing=8 -> brake. '
                    'Steering is selected separately to return to middle lane y=4.',
                'criteria': {
                    'brake_hard': 'NEW -6 m/s^2: emergency slowing for imminent collision.',
                    'brake': 'NEW -3 m/s^2: materially too fast or insufficient gap to a relevant lead vehicle.',
                    'ease_off': 'NEW -1 m/s^2: small reduction when slightly too fast or approaching a gap limit.',
                    'coast': 'NEW 0 m/s^2: maintain an already appropriate speed; does not increase speed.',
                    'accelerate': 'NEW +1.5 m/s^2: speed below target and space ahead allows progress.',
                    'accelerate_hard': 'NEW +3 m/s^2: far below target, clear road and ample space ahead.',
                },
            }},
        }
        result = {'state': state, 'started': started}
        try:
            response = self.session.post('https://api.typesafe.ai/v1/systemone', json=payload,
                                         timeout=(self.timeout, self.timeout), allow_redirects=False)
            if response.status_code != 200:
                result['error'] = f'HTTP {response.status_code}'
                result['fatal'] = response.status_code in (400, 401, 402, 403, 404, 422, 429)
            else:
                data = response.json()
                action = {}
                confidences = []
                for field in ('steering', 'acceleration'):
                    answer = data['answers'][field]
                    value, confidence = answer['choice'], float(answer['confidence'])
                    if value not in payload['questions'][field]['criteria'] or not math.isfinite(confidence) or not 0 <= confidence <= 1:
                        raise ValueError('Invalid answer')
                    action[field] = value
                    confidences.append(confidence)
                confidence = min(confidences)
                result.update(action=action, confidence=confidence, answers=data['answers'],
                              usage=data.get('usage', {}), model=data.get('model'))
        except requests.Timeout:
            result['error'] = 'API timeout'
        except requests.RequestException:
            result['error'] = 'API connection error'
        except (ValueError, KeyError, TypeError):
            result['error'] = 'Invalid API response'
        result['latency_ms'] = round((time.perf_counter() - started) * 1000, 1)
        return result


def accept_result(result, age: float, max_age: float) -> tuple[dict | None, str]:
    if result.get('error'):
        return None, result['error']
    if age > max_age:
        return None, 'STALE: discarded'
    return result['action'], 'Applied'


def panel(screen, font, small, image, state, stats, history, paused, finished):
    screen.fill('#0b1220')
    def text(value, xy, color='#dce8f6', f=font):
        screen.blit(f.render(str(value), True, color), xy)
    text('JEV / HIGHWAY LAB', (26, 20), '#67e8f9')
    text('LIVE TELEMETRY  /  ASYNC DECISIONS', (700, 26), '#94a3b8', small)
    road = pygame.surfarray.make_surface(np.swapaxes(image, 0, 1))
    screen.blit(road, (20, 75))
    text(f"{state['ego']['speed_mps'] * 3.6:.0f} km/h", (28, 410))
    text(f"Lane {state['ego']['lane'] + 1} / 3", (225, 410))
    text(stats['action'], (410, 410), '#67e8f9', small)
    text(f"API: {stats['latency_ms']:.0f} ms", (980, 410))
    text(f"Controller: {stats['controller']}   Calls: {stats['calls']}/{stats['max_calls']}   "
         f"Applied: {stats['applied']}   Discarded: {stats['discarded']}", (28, 462), f=small)
    text(f"Simulation: {state['sim_seconds']:.1f}s   Wall: {stats['wall_seconds']:.1f}s   "
         f"Decision age: {stats['age_ms']:.0f} ms   Confidence: {stats['confidence']:.2f}", (28, 490), f=small)
    text(stats['status'], (28, 521), '#fbbf24', small)
    for i, line in enumerate(history[-4:]):
        text(line, (28, 558 + i * 25), '#94a3b8', small)
    text('SPACE pause/resume   ESC quit   |   Direct steering + acceleration; no lane-following assist', (28, 686), f=small)
    if paused or finished:
        label = finished or 'PAUSED - no new API calls'
        pygame.draw.rect(screen, '#162338', (100, 82, 1040, 58), border_radius=12)
        text(label, (125, 96), '#fbbf24')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--controller', choices=['jev', 'baseline'], default='jev')
    parser.add_argument('--duration', type=float, default=60, help='Maximum simulated AND active wall seconds')
    parser.add_argument('--interval', type=float, default=0.25, help='Minimum seconds between request starts')
    parser.add_argument('--max-age', type=float, default=1.5, help='Discard decisions older than this many wall seconds')
    parser.add_argument('--timeout', type=float, default=4.0)
    parser.add_argument('--max-calls', type=int, default=60)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--offset', type=float, default=0.65, help='Initial lateral offset from middle lane center, meters')
    parser.add_argument('--heading', type=float, default=0.03, help='Initial heading in radians; 0 points down the road')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--autostart', action='store_true', help='Start driving immediately when the window opens')
    parser.add_argument('--screenshot', help='Save final rendered screen to this PNG path')
    args = parser.parse_args()
    if any(not math.isfinite(x) or x <= 0 for x in (args.duration, args.interval, args.max_age, args.timeout)) or args.max_calls < 1:
        parser.error('Durations, interval, timeout and max-calls must be positive and finite.')
    if not math.isfinite(args.offset) or abs(args.offset) > 1 or not math.isfinite(args.heading) or abs(args.heading) > 0.1:
        parser.error('Use offset within +/-1 meter and heading within +/-0.1 radian.')
    key = os.environ.pop('TYPESAFE_API_KEY', '')
    if args.controller == 'jev' and not key:
        parser.error('No API key. Start with drive.cmd after jev.cmd -ConfigureKey.')
    if args.headless:
        os.environ['SDL_VIDEODRIVER'] = 'dummy'
    pygame.init()
    env = make_env(args.duration, args.seed, args.offset, args.heading)
    # Initialize HighwayEnv's offscreen renderer before our own display.
    image = env.render()
    # Offscreen rendering is also needed for screenshots under SDL's dummy driver.
    env.unwrapped.viewer.enabled = True
    screen = pygame.display.set_mode((1240, 730))
    pygame.display.set_caption('Jev - HighwayEnv real-time driving')
    font = pygame.font.SysFont('Segoe UI', 25)
    small = pygame.font.SysFont('Segoe UI', 18)
    clock = pygame.time.Clock()
    client = Jev(key, args.timeout) if args.controller == 'jev' else None
    key = None
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    sent = 0.0
    next_call = 0.0
    accumulator = 0.0
    active_wall = 0.0
    previous = time.perf_counter()
    held_action = {'steering': 'straight', 'acceleration': 'coast'}
    # Let the user see the window before the first paid call and initial motion.
    paused = not (args.headless or args.autostart)
    finished = ''
    running = True
    history = []
    latencies = []
    stats = dict(controller=args.controller, max_calls=args.max_calls, calls=0, applied=0, discarded=0,
                 errors=0, action=action_label(held_action), latency_ms=0.0, age_ms=0.0, confidence=0.0,
                 wall_seconds=0.0, status='Starting', input_tokens=0, output_tokens=0)
    run_dir = ROOT / 'runs' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    run_dir.mkdir(parents=True)
    log = (run_dir / 'decisions.jsonl').open('w', encoding='utf-8')
    start_x = float(env.unwrapped.vehicle.position[0])
    try:
        while running:
            now = time.perf_counter()
            elapsed = now - previous
            previous = now
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE and not finished:
                    paused = not paused
            if not running:
                break
            if not paused and not finished:
                active_wall += elapsed
                accumulator += elapsed
                # Always advance the world before applying a completed decision.
                # No HTTP wait occurs on this thread. Bound catch-up to avoid UI starvation.
                for _ in range(min(int(accumulator * 30), 15)):
                    _, _, terminated, truncated, _ = env.step(control_array(held_action))
                    accumulator -= 1 / 30
                    if terminated or truncated:
                        finished = 'CRASH' if env.unwrapped.vehicle.crashed else 'OFF ROAD' if not env.unwrapped.vehicle.on_road else 'EPISODE COMPLETE'
                        break
                if active_wall >= args.duration and not finished:
                    finished = 'TIME LIMIT'
            state = snapshot(env)
            if future and future.done():
                result = future.result()
                future = None
                age = time.perf_counter() - sent
                action, status = accept_result(result, age, args.max_age)
                if paused or finished:
                    action, status = None, 'Paused/finished: discarded'
                stats['latency_ms'] = result['latency_ms']
                stats['age_ms'] = round(age * 1000, 1)
                stats['confidence'] = result.get('confidence', 0)
                stats['status'] = status
                latencies.append(result['latency_ms'])
                for token in ('input_tokens', 'output_tokens'):
                    stats[token] += result.get('usage', {}).get(token, 0)
                if action:
                    held_action = action
                    stats['action'] = action_label(action)
                    stats['applied'] += 1
                else:
                    stats['discarded'] += 1
                if result.get('error'):
                    stats['errors'] += 1
                    if result.get('fatal') or stats['errors'] >= 3:
                        finished = f"STOPPED: {result['error']}"
                result.update(age_ms=stats['age_ms'], applied_action=action, status=status,
                              applied_sim_seconds=state['sim_seconds'])
                log.write(json.dumps(result, ensure_ascii=False) + '\n')
                log.flush()
                label = action_label(result['action']) if result.get('action') else '-'
                line = f"t={state['sim_seconds']:5.1f}s  {label}  {result['latency_ms']:6.0f}ms  {status}"
                history.append(line)
                print(line, flush=True)
                if stats['calls'] >= args.max_calls and not finished:
                    finished = 'API CALL LIMIT'
            if not finished and not paused and future is None and now >= next_call:
                if client and stats['calls'] < args.max_calls:
                    sent = time.perf_counter()
                    future = executor.submit(client.decide, state)
                    stats['calls'] += 1
                    next_call = sent + args.interval
                    stats['status'] = 'API in flight - world keeps moving'
                elif not client:
                    held_action = baseline_action(state)
                    stats['action'] = action_label(held_action)
                    stats['applied'] += 1
                    stats['status'] = 'Local baseline (no API)'
                    next_call = now + args.interval
            stats['wall_seconds'] = active_wall
            if not args.headless or args.screenshot:
                image = env.render()
                panel(screen, font, small, image, state, stats, history, paused, finished)
                pygame.display.flip()
            if finished and args.headless:
                break
            clock.tick(30)
    finally:
        # One bounded in-flight request may still complete after closing the window.
        executor.shutdown(wait=True, cancel_futures=True)
        if future and future.done() and not future.cancelled():
            result = future.result()
            result.update(applied_action=None, status='Stopped: discarded')
            log.write(json.dumps(result, ensure_ascii=False) + '\n')
            stats['discarded'] += 1
            latencies.append(result['latency_ms'])
            for token in ('input_tokens', 'output_tokens'):
                stats[token] += result.get('usage', {}).get(token, 0)
        if args.screenshot:
            dest = Path(args.screenshot)
            dest.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(screen, str(dest))
        summary = {**stats, 'seed': args.seed, 'initial_offset_m': args.offset, 'initial_heading_rad': args.heading,
                   'result': finished or 'USER STOP',
                   'sim_seconds': round(float(env.unwrapped.time), 3),
                   'distance_m': round(float(env.unwrapped.vehicle.position[0]) - start_x, 1),
                   'crashed': bool(env.unwrapped.vehicle.crashed),
                   'latency_mean_ms': round(float(np.mean(latencies)), 1) if latencies else None,
                   'latency_p95_ms': round(float(np.percentile(latencies, 95)), 1) if latencies else None}
        (run_dir / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        log.close()
        if client:
            client.session.close()
        env.close()
        pygame.quit()
        print(json.dumps(summary, indent=2), flush=True)
        print(f'Logs: {run_dir}', flush=True)


if __name__ == '__main__':
    main()
