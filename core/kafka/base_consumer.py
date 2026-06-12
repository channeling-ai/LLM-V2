import logging
from typing import Any, Dict, Optional, Callable, List
from abc import ABC, abstractmethod
from faststream.kafka import KafkaBroker
from core.config.kafka_config import kafka_config


logger = logging.getLogger(__name__)


class BaseConsumer(ABC):
    """공통 Kafka Consumer 클래스"""

    def __init__(self, broker: KafkaBroker, group_id: str = kafka_config.consumer_group_id):
        self.broker = broker
        self.config = kafka_config
        self.group_id = group_id
        # 어떤 토픽을 구독할지 핸들러를 저장하는 딕셔너리
        # 키: 토픽 이름, 값: 메시지 처리 함수
        self._message_handlers: Dict[str, Callable] = {}

    def register_handler(self, topic: str, handler: Callable[[Dict[str, Any]], None]):
        """토픽별 메시지 처리 핸들러 등록"""
        self._message_handlers[topic] = handler
        logger.info(f"핸들러 등록됨: {topic}")

    async def start_consuming(self, topics: List[str]):
        """지정된 토픽들에 대한 소비 시작"""
        for topic in topics:
            if topic in self._message_handlers:
                await self._subscribe_to_topic(topic)
            else:
                logger.warning(f"토픽 {topic}에 대한 핸들러가 없습니다")

    async def _subscribe_to_topic(self, topic: str):
        """특정 토픽 구독 설정"""
        handler = self._message_handlers[topic]

        @self.broker.subscriber(
            topic,
            group_id=self.group_id,
            auto_offset_reset=self.config.consumer_auto_offset_reset,
            auto_commit=self.config.consumer_enable_auto_commit,
            auto_commit_interval_ms=self.config.consumer_auto_commit_interval_ms,
            isolation_level="read_committed",
        )
        async def message_processor(message: Dict[str, Any]):
            try:
                await self._process_message(topic, message, handler)
            except Exception as e:
                await self._handle_error(topic, message, e)

    async def _process_message(
        self,
        topic: str,
        message: Dict[str, Any],
        handler: Callable
    ):
        """메시지 처리 및 로깅"""
        logger.info(f"메시지 수신: {topic}")

        # 메시지 검증
        if not await self._validate_message(message):
            logger.error(f"메시지 검증 실패: {topic}, {message}")
            return

        # 비즈니스 로직 처리
        await handler(message)

        logger.info(f"메시지 처리 완료: {topic}")

    async def _validate_message(self, message: Dict[str, Any]) -> bool:
        """메시지 유효성 검증 (서브클래스에서 오버라이드 가능)"""
        return isinstance(message, dict) and len(message) > 0

    async def _handle_error(self, topic: str, message: Dict[str, Any], error: Exception):
        """에러 처리 - 의도적으로 예외를 삼킴 (메시지 유실 허용, DLQ 없음)
        NOTE: auto_commit=True 설정과 함께 동작하므로 에러 발생 시 해당 메시지는 오프셋이 커밋되어 재처리되지 않음
        """
        logger.error(f"메시지 처리 실패: {topic}, 오류: {error}")

    async def stop_consuming(self):
        """소비 중단"""
        logger.info("Consumer 중단")
        # FastStream은 브로커 close로 처리됨
