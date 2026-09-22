import os
os.environ['SDL_VIDEODRIVER'] = 'dummy'
import unittest
from unittest.mock import Mock

from pocs.driving.app import ACCELERATION, STEERING, Jev, accept_result, control_array, make_env


class DrivingTests(unittest.TestCase):
    def test_simulator_receives_exact_physical_commands(self):
        env = make_env(10, 7)
        try:
            for steer in STEERING:
                for accel in ACCELERATION:
                    actual = env.unwrapped.action_type.get_action(control_array({'steering': steer, 'acceleration': accel}))
                    self.assertAlmostEqual(actual['steering'], STEERING[steer], places=6)
                    self.assertAlmostEqual(actual['acceleration'], ACCELERATION[accel], places=5)
        finally:
            env.close()

    def test_steering_moves_car_without_lane_controller(self):
        env = make_env(10, 7)
        try:
            base = env.unwrapped
            base.road.vehicles = [base.vehicle]
            start_y = base.vehicle.position[1]
            for _ in range(10):
                env.step(control_array({'steering': 'right_small', 'acceleration': 'coast'}))
            self.assertGreater(base.vehicle.position[1], start_y)
            self.assertGreater(base.vehicle.heading, 0)
            heading = base.vehicle.heading
            env.step(control_array({'steering': 'straight', 'acceleration': 'coast'}))
            self.assertAlmostEqual(base.vehicle.heading, heading)
            self.assertFalse(hasattr(base.vehicle, 'target_lane_index'))
        finally:
            env.close()

    def test_stale_and_failed_decisions_are_not_applied(self):
        action = {'steering': 'left_small', 'acceleration': 'brake'}
        self.assertIsNone(accept_result({'action': action}, 2.0, 1.5)[0])
        self.assertIsNone(accept_result({'error': 'API timeout'}, 0.2, 1.5)[0])
        self.assertEqual(accept_result({'action': action}, 0.2, 1.5)[0], action)

    def test_two_api_answers_become_direct_controls(self):
        client = Jev('synthetic-test-only', 1)
        response = Mock(status_code=200)
        response.json.return_value = {'answers': {
            'steering': {'choice': 'left_tiny', 'confidence': 0.9},
            'acceleration': {'choice': 'brake', 'confidence': 0.8},
        }}
        client.session.post = Mock(return_value=response)
        result = client.decide({'ego': {}})
        self.assertEqual(result['action'], {'steering': 'left_tiny', 'acceleration': 'brake'})
        response.json.return_value['answers']['steering']['choice'] = 'unknown'
        self.assertEqual(client.decide({})['error'], 'Invalid API response')
        client.session.close()


if __name__ == '__main__':
    unittest.main()
