import asyncio
import logging
from core.config.logging_config import setup_logging
from core.config.kafka_config import kafka_config
from core.kafka.kafka_broker import kafka_broker
from domain.report.service.report_consumer_impl_v2 import ReportConsumerImplV2 as ReportConsumerV2


setup_logging()
logger = logging.getLogger(__name__)


async def main():
    """Kafka Consumer V2 - Overview 전용 워커"""
    logger.info("🚀 Kafka Consumer V2 - Overview Worker 시작...")
  
    report_consumer = ReportConsumerV2(kafka_broker, group_id=kafka_config.overview_consumer_group_id)
    report_consumer.register_handler("overview-topic-v2", report_consumer.handle_overview_v2)
    
    # Overview 토픽만 구독
    topics = ["overview-topic-v2"]
    await report_consumer.start_consuming(topics)        
    logger.info(f"📋 Overview Worker 시작: {topics}")

    # Kafka Broker 시작
    await kafka_broker.start()
    logger.info("✅ Kafka Broker (Overview) 시작 완료")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("⏹️  Overview Worker 중단 요청")
    finally:
        # await report_consumer.stop_consuming()
        # await kafka_broker.close()  # 즉시 종료 - offset 커밋 실패 위험
        await kafka_broker.stop()  # graceful shutdown - 처리 중인 메시지 완료 후 offset 커밋
        logger.info("✅ Overview Worker 중단 완료")


if __name__ == '__main__':
    asyncio.run(main())