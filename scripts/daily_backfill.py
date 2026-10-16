"""Ежедневный backfill: обновляет операции и пересчитывает снапшоты."""
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sync.operations import sync_operations
from invest.sync import sync_invest_operations
from invest.backfill import backfill_incremental


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
logger = logging.getLogger('daily_backfill')


def main():
    logger.info("=== Daily backfill started: %s ===", date.today())

    try:
        ops = sync_operations()
        logger.info("T-Bank operations: %s", ops)
    except Exception as e:
        logger.error("T-Bank sync failed: %s", e, exc_info=True)

    try:
        inv = sync_invest_operations()
        logger.info("T-Invest operations: %s", inv)
    except Exception as e:
        logger.error("T-Invest sync failed: %s", e, exc_info=True)

    try:
        snap = backfill_incremental()
        logger.info("Snapshots: %s", snap)
    except Exception as e:
        logger.error("Snapshot backfill failed: %s", e, exc_info=True)

    logger.info("=== Daily backfill finished ===")


if __name__ == '__main__':
    main()