from pydantic import BaseModel


class DummyReportRequest(BaseModel):
    """Spring → FastAPI 더미 리포트 생성 요청 (인증 없음, videoId만)"""
    youtube_video_id: str


class Cost(BaseModel):
    """
    생성 비용. Step 1에서는 값을 채우지 않고 0으로 내려보내며 Spring은 무시한다.
    Step 2(어뷰징 제한)에서 실제 토큰 사용량을 채워 일일 예산 누적에 쓴다.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
