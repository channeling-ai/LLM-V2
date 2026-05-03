import random
from collections import defaultdict
from typing import List, DefaultDict
import logging
import time
from core.kafka.dto.producer_message import CommentSummaryItem
from domain.comment.model.comment import Comment
from domain.comment.model.comment_type import CommentType
from domain.comment.repository.comment_repository import CommentRepository
from domain.report.repository.report_repository import ReportRepository
from domain.video.model.video import Video
from external.rag.rag_service_impl import RagServiceImpl
from external.youtube.youtube_comment_service import YoutubeCommentService

logger = logging.getLogger(__name__)

class CommentService:
    def __init__(self):
        self.rag_service = RagServiceImpl()
        self.comment_repository = CommentRepository()
        self.youtube_comment_service = YoutubeCommentService()
        self.report_repository = ReportRepository()

    async def summarize_comments_by_emotions_with_llm(self, comments_by_emotions: DefaultDict[CommentType, list[Comment]]) -> List[CommentSummaryItem]:
        result: List[CommentSummaryItem] = []

        summarize_start = time.time()
        logger.info("📝 댓글 감정별 요약 시작")

        for emotion, comments in comments_by_emotions.items():
            if not comments:
                continue

            # 해당 감정 그룹의 content만 개행으로 합치기
            contents_str = "\n".join(comment.content for comment in comments)
            # LLM 서비스 호출 -> returns list[str]
            summarized_contents = await self.rag_service.summarize_comments(contents_str, emotion.label, len(comments))

            for content in summarized_contents:
                result.append(CommentSummaryItem(
                    comment_type=emotion.value,
                    content=content
                ))

            logger.info(f"📝 [{emotion.value}] 요약 완료 - {len(summarized_contents)}개 항목 생성")

        summarize_time = time.time() - summarize_start
        logger.info(f"📝 댓글 감정별 요약 완료 ({summarize_time:.2f}초) - 총 {len(result)}개 항목")
        return result

    async def classify_comment_with_llm(self, comment: Comment) -> Comment:
        result = await self.rag_service.classify_comment(comment.content)
        # comment의 comment_type 업데이트
        comment.comment_type = result["comment_type"]
        # db 저장 후 반환 -> 그냥 반환
        return comment

    # 댓글을 분류
    def sample_comments(self, comments: list[Comment], threshold: int = 200, sample_rate: float = 0.1) -> tuple[list[Comment], bool]:
        """
        댓글이 threshold 이상일 때 sample_rate 비율로 샘플링
        
        Args:
            comments: 전체 댓글 리스트
            threshold: 샘플링 시작 기준 (기본 200개)
            sample_rate: 샘플링 비율 (기본 10%)
            
        Returns:
            (샘플링된 댓글 리스트, 샘플링 여부 플래그)
        """
        total_count = len(comments)
        
        if total_count < threshold:
            # 임계값 미만이면 전체 댓글 반환
            logger.info(f"댓글 수({total_count})가 임계값({threshold}) 미만, 전체 댓글 분석")
            return comments, False
        
        # 샘플링 수 계산 (최소 20개 보장)
        sample_size = max(20, int(total_count * sample_rate))
        sample_size = min(sample_size, total_count)  # 전체 댓글 수를 초과하지 않도록
        
        # 랜덤 샘플링
        sampled_comments = random.sample(comments, sample_size)
        
        logger.info(f"댓글 샘플링: {total_count}개 중 {sample_size}개 선택 ({sample_rate*100:.0f}%)")
        return sampled_comments, True

    async def gather_classified_comments(self, comments: list[Comment])->DefaultDict[CommentType, list[Comment]]:
        grouped = defaultdict(list)
        for comment in comments:
            result = await self.classify_comment_with_llm(comment)
            grouped[result.comment_type].append(result)

        return grouped
    
    async def gather_classified_comments_optimized(self, all_comments: list[Comment]) -> tuple[DefaultDict[CommentType, list[Comment]], DefaultDict[CommentType, list[Comment]]]:
        """
        최적화된 댓글 감정 분류 - 샘플링을 통한 성능 개선
        
        Args:
            all_comments: 전체 댓글 리스트
            
        Returns:
            (전체 감정별 분류 딕셔너리, 샘플링된 댓글만의 감정별 딕셔너리)
        """
        # 1. 샘플링 수행
        sampled_comments, is_sampled = self.sample_comments(all_comments)
        
        # 2. 샘플링된 댓글만 LLM으로 감정 분류
        llm_classify_start = time.time()
        logger.info(f"🤖 LLM 감정 분류 시작: {len(sampled_comments)}개 댓글")
        sample_grouped = defaultdict(list)
        for comment in sampled_comments:
            result = await self.classify_comment_with_llm(comment)
            sample_grouped[result.comment_type].append(result)
        llm_classify_time = time.time() - llm_classify_start
        logger.info(f"🤖 LLM 감정 분류 완료 ({llm_classify_time:.2f}초)")
        
        # 3. 샘플링하지 않은 경우 같은 데이터 두 번 반환
        if not is_sampled:
            return sample_grouped, sample_grouped
        
        # 4. 샘플링한 경우: 감정 분포 계산
        total_sampled = len(sampled_comments)
        emotion_distribution = {}
        for emotion, comments in sample_grouped.items():
            emotion_distribution[emotion] = len(comments) / total_sampled
        
        logger.info(f"샘플 감정 분포: {dict(emotion_distribution)}")
        
        # 5. 전체 댓글에 감정 분포를 확률적으로 적용
        final_grouped = defaultdict(list)
        unsampled_comments = [c for c in all_comments if c not in sampled_comments]
        
        # 샘플링된 댓글은 이미 분류된 감정 그대로 추가
        for emotion, comments in sample_grouped.items():
            final_grouped[emotion].extend(comments)
        
        # 나머지 댓글에 확률적으로 감정 할당
        for comment in unsampled_comments:
            # 가중치 랜덤 선택으로 감정 할당
            emotions = list(emotion_distribution.keys())
            weights = list(emotion_distribution.values())
            
            if emotions and weights:
                assigned_emotion = random.choices(emotions, weights=weights, k=1)[0]
                comment.comment_type = assigned_emotion
                final_grouped[assigned_emotion].append(comment)
            else:
                # 분포가 없으면 중립으로 할당
                comment.comment_type = CommentType.NEUTRAL
                final_grouped[CommentType.NEUTRAL].append(comment)
        
        # 최종 분포 로깅
        final_distribution = {emotion: len(comments) for emotion, comments in final_grouped.items()}
        logger.info(f"최종 감정 분포: {final_distribution}")
        
        # 전체 분류 결과와 샘플링된 댓글만 따로 반환
        return final_grouped, sample_grouped

    async def analyze_comments(self, video: Video, report_id: int) -> bool:
        """
        영상의 댓글을 분석하고 감정별로 요약하여 저장
        
        Args:
            video: 비디오 객체
            report_id: 리포트 ID
            
        Returns:
            성공 시 True, 실패 시 False
        """
        start_time = time.time()
        logger.info(f"💬 댓글 분석 시작 - Report ID: {report_id}")
        
        try:
            # 유튜브 영상 아이디 조회
            youtube_video_id = getattr(video, "youtube_video_id", None)
            if not youtube_video_id:
                logger.error("YouTube 영상 ID가 없습니다.")
                return False
            
            # 댓글 정보 조회 (YouTube API)
            api_start = time.time()
            comments_by_youtube = await self.youtube_comment_service.get_comments(youtube_video_id, report_id)
            api_time = time.time() - api_start
            logger.info(f"💬 YouTube 댓글 API 호출 완료 ({api_time:.2f}초) - {len(comments_by_youtube)}개 댓글")
            
            # Comment 객체로 변환
            comments_obj = await self.convert_to_comment_objects(comments_by_youtube)
            
            # 최적화된 감정 분류 사용 (LLM API 호출)
            logger.info(f"🧠 총 {len(comments_obj)}개 댓글 감정 분류 시작")
            all_classified_result, sampled_result = await self.gather_classified_comments_optimized(comments_obj)
            
            # 전체 댓글 개수 저장 (스케일링된 전체 개수)
            total_count_dict = {comment_type: len(comments) for comment_type, comments in all_classified_result.items()}
            logger.info(f"전체 댓글 감정 분포 (스케일링 포함): {total_count_dict}")
            
            # 감정별 요약 생성 (샘플링된 댓글만 사용 - 정확한 감정 분류 보장)
            summary_start = time.time()
            logger.info(f"📝 요약 생성에 사용할 샘플링된 댓글: {sum(len(c) for c in sampled_result.values())}개")
            summarized_comments = await self.summarize_comments_by_emotions_with_llm(sampled_result)
            summary_time = time.time() - summary_start
            logger.info(f"📝 댓글 요약 생성 완료 ({summary_time:.2f}초)")
            
            # 감정별 댓글 개수 업데이트 (전체 개수 사용)
            db_start = time.time()
            count_dict = total_count_dict
            await self.report_repository.update_count(report_id, count_dict)
            db_time = time.time() - db_start
            logger.info(f"🗄️ 댓글 개수 DB 저장 완료 ({db_time:.2f}초)")
            
            total_time = time.time() - start_time
            logger.info(f"💬 댓글 분석 전체 완료 ({total_time:.2f}초)")
            return True
            
        except Exception as e:
            total_time = time.time() - start_time
            logger.error(f"💬 댓글 분석 실패 ({total_time:.2f}초): {e}")
            raise

    # 유튜브 api 에서 가져온 댓글을 Comment 객체로 변환
    async def convert_to_comment_objects(self, comments: list[dict]) -> list[Comment]:
        comment_objects = []

        for data in comments:
            comment = Comment(
                comment_type=data.get("comment_type", None),
                content=data.get("content", ""),
                report_id=data.get("report_id"),
            )
            comment_objects.append(comment)
        return comment_objects
