import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from core.config.logging_config import setup_logging
from core.config.database_config import test_pg_connection
from core.cache.redis_client import get_redis_client, RedisClient
from core.kafka.kafka_broker import kafka_broker
from domain.idea.controller.idea_controller import router as idea_router
from domain.report.controller.dummy_report_controller import router as dummy_report_router
from domain.trend_keyword.controller.trend_keyword_controller import router as trend_router

from response.api_response import ApiResponse
from response.code.status.success_status import SuccessStatus
from external.log.discord_config import setup_logging as setup_discord_logging
'''
서버 시작 명령어: fastapi dev main.py
'''

setup_logging()
setup_discord_logging()

app = FastAPI(title="Channeling LLM API", version="1.0.0")

logger = logging.getLogger(__name__)
# 라우터 등록
app.include_router(idea_router)
app.include_router(trend_router)
app.include_router(dummy_report_router)

@app.on_event("startup")
async def on_startup():
    logger.info("서버 시작 중...")

    # DB 연결 테스트
    if await test_pg_connection():
        logger.info("PostgreSQL DB에 연결 완료")
    else:
        logger.error("PostgreSQL DB 연결 실패")

    # Redis 연결 테스트
    redis_client = await get_redis_client()
    if redis_client:
        logger.info("Redis 캐시 연결 완료")
    else:
        logger.warning("Redis 캐시 없이 실행 (캐싱 비활성화)")

    # kafka 브로커 시작
    await kafka_broker.start()
    logger.info("Kafka 브로커 시작 완료")

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("서버 종료 중...")

    # Redis 연결 종료
    await RedisClient.close()
    logger.info("Redis 연결 종료 완료")

    # kafka 브로커 종료
    await kafka_broker.close()
    logger.info("Kafka 브로커 종료 완료")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"{type(exc).__name__}: {exc}",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"endpoint": f"{request.method} {request.url.path}"},
    )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


@app.get("/health")
async def health_check():
    """Docker 헬스체크용 엔드포인트"""
    return ApiResponse.on_success(SuccessStatus._OK, {"status": "UP"})


