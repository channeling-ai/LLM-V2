from typing import Optional

from pydantic import BaseModel


class DummyReportRequest(BaseModel):
    """Spring → FastAPI 더미 리포트 생성 요청 (인증 없음, videoId만)"""
    youtube_video_id: str


class VideoInfo(BaseModel):
    """
    체험용 리포트 화면에 띄울 영상 메타.
    Spring의 DummyReportResDTO.VideoInfo가 이 snake_case 키를 그대로 읽는다.
    리포트 생성일자(created_at)는 캐시 적중 시각과 구분해야 해서 Spring이 채운다 — 여기서 보내지 않는다.
    """
    video_title: Optional[str] = None
    video_thumbnail_url: Optional[str] = None
    # 롱폼/숏폼: 일반 리포트와 동일하게 카테고리 ID 기준 (SHORTS=42), 재생시간이 아니다
    video_type: Optional[str] = None
    video_created_date: Optional[str] = None
    channel_name: Optional[str] = None


class Cost(BaseModel):
    """
    생성 비용. 요청 1건이 실제로 쓴 채팅 모델 토큰과 그 환산 금액이다.
    Spring이 일일 예산 상한(Step 2)에 누적한다.
    임베딩 비용은 포함하지 않는다 — 더미/추천 경로는 skip_vector_save=True라 임베딩 호출이 없다.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
