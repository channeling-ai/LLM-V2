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
    생성 비용. Step 1에서는 값을 채우지 않고 0으로 내려보내며 Spring은 무시한다.
    Step 2(어뷰징 제한)에서 실제 토큰 사용량을 채워 일일 예산 누적에 쓴다.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
