from __future__ import annotations

from src.order_logger import OrderLogger
from src.scheduler import SimpleScheduler
from src.toss_api_client import TossApiClient


def main() -> None:
    logger = OrderLogger()
    client = TossApiClient()
    scheduler = SimpleScheduler(interval_seconds=60)

    def tick() -> None:
        account = client.get_account()
        logger.append({'event': 'heartbeat', 'account': account})
        print('tick', account)

    try:
        scheduler.run(tick)
    except KeyboardInterrupt:
        scheduler.stop()


if __name__ == '__main__':
    main()
