from weather_alert_bot.config import load_settings


def main() -> int:
    """Run the minimal application entry point."""
    load_settings(require_telegram_token=False)
    print("Каркас погодного бота готов.")
    return 0
