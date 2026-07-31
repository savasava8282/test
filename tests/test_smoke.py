import io
import unittest
from contextlib import redirect_stdout

from weather_alert_bot.app import main


class SmokeTest(unittest.TestCase):
    def test_main(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            return_code = main()

        self.assertEqual(return_code, 0)
        self.assertEqual(output.getvalue(), "Каркас погодного бота готов.\n")


if __name__ == "__main__":
    unittest.main()
