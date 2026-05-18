from abc import ABC, abstractmethod
from typing import Any, Dict, List
from domain.channel.model.channel import Channel
from domain.idea.dto.idea_dto import IdeaRequest
from domain.log.model.report_log import ReportLog
from domain.report.model.report import Report


class RagService(ABC):
    """RAG 서비스 추상 클래스"""
    
    @abstractmethod
    async def summarize_video(self, video_id: str) -> str:
        """비디오 요약 (Redis 캐싱 적용)"""
        pass
    
    @abstractmethod
    def classify_comment(self, comment: str) -> Dict[str, Any]:
        """댓글 감정 분류"""
        pass
    
    @abstractmethod
    def summarize_comments(self, comments: str, emotion: str, comment_count: int) -> List[str]:
        """댓글 감정별 요약"""
        pass
    
    @abstractmethod
    async def analyze_idea(self, idea_req: IdeaRequest, channel: Channel, summary: str) -> List[Dict[str, Any]]:
        """아이디어 분석"""
        pass
    
    @abstractmethod
    def analyze_algorithm_optimization(self, video_id: str) -> str:
        """알고리즘 최적화 분석"""
        pass

    @abstractmethod
    def execute_llm_chain(self, context: str, query: str, prompt_template: str) -> str:
        """LLM 체인 실행"""
        pass

    @abstractmethod
    def execute_llm_direct(self, prompt: str) -> str:
        """LLM 직접 실행"""
        pass

    @abstractmethod
    def analyze_realtime_trends(self, limit: int = 6, geo: str = "KR") -> Dict:
        """실시간 트렌드 분석, 유튜브 컨텐츠에 적합한 형태로 반환"""
        pass

    @abstractmethod
    def analyze_channel_trends(self, channel_concept: str, target_audience: str) -> Dict:
        """채널 맞춤형 트렌드 분석"""
        pass
