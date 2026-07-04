import asyncio
import logging

from core.config.logging_config import setup_logging
from core.config.kafka_config import kafka_config
from core.kafka.kafka_broker import kafka_broker
from domain.dashboard.service.dashboard_consumer_impl import DashboardConsumerImpl

setup_logging()
logger = logging.getLogger(__name__)


async def main():
    """Kafka Consumer - Dashboard 전용 워커 (dashboard-topic-v2)"""
    logger.info("🚀 Kafka Consumer - Dashboard Worker 시작...")

    consumer = DashboardConsumerImpl(kafka_broker, group_id=kafka_config.dashboard_consumer_group_id)
    consumer.register_handler(kafka_config.dashboard_topic_v2, consumer.handle_dashboard)

    topics = [kafka_config.dashboard_topic_v2]
    await consumer.start_consuming(topics)
    logger.info("📋 Dashboard Worker 시작: %s", topics)

    await kafka_broker.start()
    logger.info("✅ Kafka Broker (Dashboard) 시작 완료")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("⏹️  Dashboard Worker 중단 요청")
    finally:
        await kafka_broker.stop()  # graceful shutdown
        logger.info("✅ Dashboard Worker 중단 완료")


if __name__ == '__main__':
    asyncio.run(main())
