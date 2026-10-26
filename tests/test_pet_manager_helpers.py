import unittest

from pet_manager import wheel_steps


class WheelRoutingTests(unittest.TestCase):
    def test_standard_wheel_direction(self):
        self.assertEqual(wheel_steps(120), -1)
        self.assertEqual(wheel_steps(-120), 1)

    def test_high_resolution_touchpad_delta_is_not_dropped(self):
        self.assertEqual(wheel_steps(1), -1)
        self.assertEqual(wheel_steps(-1), 1)
        self.assertEqual(wheel_steps(30), -1)

    def test_large_delta_is_bounded(self):
        self.assertEqual(wheel_steps(12000), -5)
        self.assertEqual(wheel_steps(-12000), 5)


if __name__ == "__main__":
    unittest.main()
