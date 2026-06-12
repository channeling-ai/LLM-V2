import asyncio
import logging
from core.config.logging_config import setup_logging
from core.config.kafka_config import kafka_config
from core.kafka.kafka_broker import kafka_broker
from domain.report.service.report_consumer_impl_v2 import ReportConsumerImplV2 as ReportConsumerV2


setup_logging()
logger = logging.getLogger(__name__)


async def main():
    """Kafka Consumer V2 - Analysis 전용 워커"""
    logger.info("🚀 Kafka Consumer V2 - Analysis Worker 시작...")
  
    report_consumer = ReportConsumerV2(kafka_broker, group_id=kafka_config.analysis_consumer_group_id)
    report_consumer.register_handler("analysis-topic-v2", report_consumer.handle_analysis_v2)
    
    # Analysis 토픽만 구독
    topics = ["analysis-topic-v2"]
    await report_consumer.start_consuming(topics)        
    logger.info(f"📊 Analysis Worker 시작: {topics}")

    # Kafka Broker 시작
    await kafka_broker.start()
    logger.info("✅ Kafka Broker (Analysis) 시작 완료")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("⏹️  Analysis Worker 중단 요청")
    finally:
        # await report_consumer.stop_consuming()
        # await kafka_broker.close()  # 즉시 종료 - offset 커밋 실패 위험
        await kafka_broker.stop()  # graceful shutdown - 처리 중인 메시지 완료 후 offset 커밋
        logger.info("✅ Analysis Worker 중단 완료")


if __name__ == '__main__':
    asyncio.run(main())