import os
from typing import List
from pydantic_settings import BaseSettings


class KafkaConfig(BaseSettings):
    """Kafka 설정 클래스(환경 변수와 기본값 관리)"""

    # 브로커 서버 주소 등록(환경변수에서 문자열로 받음)
    bootstrap_servers: str = "localhost:9092"
    # 보안 프로토콜 설정
    security_protocol: str = "PLAINTEXT"

    # Producer 설정 (TODO: 역방향 메시지 발행 시 재설정 필요)
    # 재시도: 앱 레벨(base_producer.py)만 사용, Kafka 레벨 retries는 사용 안 함
    # 메시지 전송 확인 레벨 (0=안함, 1=리더만, all=모든 복제본)
    producer_acks: str = "all"
    # 앱 레벨 재시도 횟수 (base_producer.py 지수 백오프 참조)
    producer_retries: int = 3
    # 메시지 압축 방식 (none, gzip, snappy, lz4, zstd)
    producer_compression_type: str = "snappy"

    # Consumer 설정
    consumer_group_id: str = "llm-service-group"
    overview_consumer_group_id: str = "llm-overview-group"
    analysis_consumer_group_id: str = "llm-analysis-group"
    recommend_consumer_group_id: str = "llm-recommend-group"
    # 오프셋이 없을 때 읽기 시작 위치 (earliest=처음부터, latest=최신부터)
    consumer_auto_offset_reset: str = "earliest"
    # 오프셋 자동 커밋 여부 (True시 자동으로 읽은 위치 저장)
    consumer_enable_auto_commit: bool = True
    # 자동 커밋 간격 (밀리초, 5초마다 오프셋 커밋)
    consumer_auto_commit_interval_ms: int = 5000
    # 세션 타임아웃 (기본 10초는 LLM 처리 시간보다 짧아 리밸런싱 유발)
    consumer_session_timeout_ms: int = 60000
    # heartbeat 간격 (session_timeout_ms의 1/3 이하 권장)
    consumer_heartbeat_interval_ms: int = 20000
    # 메시지 처리 최대 허용 시간 (LLM 호출 포함 여유 있게 설정)
    consumer_max_poll_interval_ms: int = 600000
  

    # 토픽 설정
    overview_topic: str = "overview-topic"
    analysis_topic: str = "analysis-topic"
    idea_topic: str = "idea-topic"
    
    # V2 토픽 설정
    overview_topic_v2: str = "overview-topic-v2"
    analysis_topic_v2: str = "analysis-topic-v2"
    idea_topic_v2: str = "idea-topic-v2"
    report_result_v3: str = "report-result-v3"

    # 추천 리포트 토픽 (토큰 없이 생성 — Spring ↔ FastAPI)
    recommend_topic_v2: str = "recommend-report-topic-v2"
    recommend_result_v2: str = "recommend-report-result-v2"


    # V3 결과 발행 토픽 (FastAPI → Spring)
    report_result_v3: str = "report-result-v3"

    class Config:
        # 환경 변수에서 설정값을 읽어옴
        env_prefix = "KAFKA_"
        env_file = ".env"
        extra = "ignore"


# 전역에서 사용할 설정 인스턴스 (싱글톤 패턴)
kafka_config = KafkaConfig()