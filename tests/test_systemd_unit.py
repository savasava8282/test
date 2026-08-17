from pathlib import Path
import re
import unittest


UNIT_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "systemd"
    / "weather-alert-bot.service"
)


def directive(unit_text: str, section: str, name: str) -> str:
    current_section = None
    for raw_line in unit_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1]
            continue
        if current_section == section and line.startswith(f"{name}="):
            return line.split("=", 1)[1]
    raise AssertionError(f"Missing {name}= in [{section}]")


class SystemdUnitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.unit_text = UNIT_PATH.read_text(encoding="utf-8")

    def test_unit_exists_and_has_expected_service_shape(self) -> None:
        self.assertTrue(UNIT_PATH.is_file())
        self.assertEqual(
            directive(self.unit_text, "Service", "WorkingDirectory"),
            "/root/projects/test",
        )
        self.assertEqual(
            directive(self.unit_text, "Service", "EnvironmentFile"),
            "/root/.config/weather-alert-bot/env",
        )
        self.assertEqual(
            directive(self.unit_text, "Service", "ExecStart"),
            "/usr/bin/python3 -m weather_alert_bot --run-scheduler",
        )
        self.assertEqual(directive(self.unit_text, "Service", "Type"), "simple")
        self.assertEqual(directive(self.unit_text, "Service", "Restart"), "on-failure")
        self.assertEqual(directive(self.unit_text, "Service", "RestartSec"), "30s")
        self.assertEqual(directive(self.unit_text, "Service", "KillSignal"), "SIGTERM")
        self.assertEqual(directive(self.unit_text, "Service", "TimeoutStopSec"), "90s")

    def test_unit_starts_after_network_online_and_is_enabled_for_multi_user(self) -> None:
        self.assertEqual(directive(self.unit_text, "Unit", "Wants"), "network-online.target")
        self.assertEqual(directive(self.unit_text, "Unit", "After"), "network-online.target")
        self.assertEqual(directive(self.unit_text, "Install", "WantedBy"), "multi-user.target")

    def test_unit_has_source_checkout_import_path_without_shell_wrapper(self) -> None:
        self.assertEqual(
            directive(self.unit_text, "Service", "Environment"),
            "PYTHONPATH=/root/projects/test/src",
        )
        self.assertIn("Environment=PYTHONUNBUFFERED=1", self.unit_text)
        self.assertNotRegex(self.unit_text, r"ExecStart=.*(?:sh -c|bash -c|nohup)")
        self.assertNotIn("&", self.unit_text)
        self.assertNotRegex(self.unit_text.lower(), r"(?:cron|daemon|tmux|screen)")

    def test_unit_does_not_contain_secrets(self) -> None:
        self.assertNotIn("TELEGRAM_BOT_TOKEN=", self.unit_text)
        self.assertNotRegex(self.unit_text, r"\b\d{9,}:[A-Za-z0-9_-]{20,}\b")


if __name__ == "__main__":
    unittest.main()
