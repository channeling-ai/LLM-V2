from typing import List
from datetime import datetime
from domain.content_chunk.repository.content_chunk_repository import ContentChunkRepository

from core.llm.prompt_template_manager import PromptTemplateManager
from core.enums.source_type import SourceTypeEnum
from external.rag.rag_service_impl import RagServiceImpl
import json


content_chunk_repo = ContentChunkRepository()
rag_service = RagServiceImpl()


#이진 탐색 사용해서 시작하는 인덱스 구하기
def binary_search_le(script, target_sec: float) -> int:
    left, right = 0, len(script) - 1
    best_idx = -1  # 없을 경우 -1

    while left <= right:
        mid = (left + right) // 2
        if script[mid]['start_time'] <= target_sec:
            best_idx = mid       # 유효 후보
            left = mid + 1       # 더 오른쪽으로
        else:
            right = mid - 1      # 더 왼쪽으로

    return best_idx


async def create_time_chunks_with_focus(
    video_id: str,
    video_length_sec: int,
    script: List[dict],
    analytics: List[List[float]],
    worst_ratio: float
) -> List[dict]:
        
    base_chunk_ratio= 0.02  # 전체 영상 길이의 2%를 기본 청킹 크기로 사용
    fine_chunk_ratio = 0.006 # 전체 영상 길이의 0.6%를 집중 청킹 크기로 사용
    focus_range_ratio = 0.02  # 집중 청킹 적용 범위는 최악 이탈 지점 앞뒤 2%
        
    # 가장 이탈이 심한 시점(비율)을 실제 초 단위로 변환
    worst_sec = int(worst_ratio * video_length_sec)
    # 기본 청킹 단위(초) 계산 기본 = 전체 길이의 2% -> 최소 7초, 
    base_chunk_size_sec = max(7 , int(base_chunk_ratio * video_length_sec))
    # 집중 청킹 단위(초) 계산 (더 세밀하게 쪼갤 크기) = 전체 길이의 0.6%, 최소 5초, 최대 1분
    focus_chunk_size_sec = max(5, min(int(fine_chunk_ratio * video_length_sec), 60))
    # 영상의 총 집중 시간 앞뒤 2% = 2*2 =4%  , 최소 10초, 최대 5분
    total_focus_size =  max(10, min(int(focus_range_ratio * video_length_sec *2), 300))


    # 집중 청킹 시작 시간 -> 0보다는 큼
    start_focus_time = max(0, worst_sec - total_focus_size // 2)
    # 집중 청킹 끝 시간 -> 총 길이보다는 작음
    end_focus_time = min(video_length_sec, worst_sec + total_focus_size // 2)

    current_time = 0  # 현재 청킹 시작 시간 (초)


    while current_time < video_length_sec:
        # 현재 구간이 집중 범위 안이면 더 작은 단위로 쪼갬
        if  start_focus_time <= current_time <= end_focus_time:
            chunk_size = focus_chunk_size_sec
            is_in_focus = True
        else:
            # 아니면 기본 크기로 청킹
            chunk_size = base_chunk_size_sec
            is_in_focus = False

            
        # 1. 청크 끝 시간 계산
        chunk_end_time = min(current_time + chunk_size, video_length_sec)

        # 2. 시작 인덱스 찾기 (이진 탐색)
        start_idx = max(binary_search_le(script, current_time),0)
        # 3. 청킹 범위 안의 스크립트 수집
        chunk_texts = []
        #current 시간 에 가장 가까운 대본의 인덱스 가져와서, 청킹 단위 까지 합치기
        for i in range(start_idx , len(script)):
            current = script[i]
            if current["start_time"] < chunk_end_time and current["end_time"] > current_time:
                chunk_texts.append(current["text"])
            else:
                if current["start_time"] > chunk_end_time:
                    break

        chunk_text = " ".join(chunk_texts).strip()

        # 3) rows 평균 계산
        # row 정보는 0.01 단위 이므로, 비율 단위로 바꿔야 함
        start_ratio = current_time / video_length_sec
        end_ratio = chunk_end_time / video_length_sec
        # row를 돌면서, current 부터 청킹 끝나는 시간에 해당하는 row들을 가지고 옴 (row는 100개 고정이어서 그냥 for문)
        target_rows = [r for r in analytics if start_ratio <= r[0] <= end_ratio]
        if target_rows:
            avg_audienceWatchRatio  = sum(r[1] for r in target_rows) / len(target_rows)
            avg_relativeRetentionPerformance = sum(r[2] for r in target_rows) / len(target_rows)
        else:
            avg_audienceWatchRatio  = 0
            avg_relativeRetentionPerformance = 0

        chunk_meta={
            'chunk_type': 'time',        # 청킹 타입
            'time_start': current_time,         # 구간 시작 시간 (초)
            'time_end': chunk_end_time,             # 구간 끝 시간 (초)
            'audienceWatchRatio': avg_audienceWatchRatio,    # 평균 시청률
            'relativeRetentionPerformance': avg_relativeRetentionPerformance,  # 평균 상대 유지율
            'is_focus_zone': is_in_focus, # 집중 구간 여부
            'created_at' : datetime.now().isoformat()
            }
        # # 저장

        await content_chunk_repo.save_context(
            source_type=SourceTypeEnum.VIEWER_ESCAPE_ANALYSIS.value.upper(),
            source_id=int(video_id),
            context= chunk_text,
            meta= chunk_meta
        )

        current_time += chunk_size
    




async def create_meaning_chunks_with_focus(
    video_id: str,
    video_length_sec: int,
    script: List[dict],
    analytics: List[List[float]],
    worst_ratio: float
) -> List[dict]:
        
    base_chunk_ratio= 0.02  # 전체 영상 길이의 2%를 기본 청킹 크기로 사용
    fine_chunk_ratio = 0.006 # 전체 영상 길이의 0.6%를 집중 청킹 크기로 사용
    focus_range_ratio = 0.02  # 집중 청킹 적용 범위는 최악 이탈 지점 앞뒤 2%
        
    # 가장 이탈이 심한 시점(비율)을 실제 초 단위로 변환
    worst_sec = int(worst_ratio * video_length_sec)
    # 기본 청킹 단위(초) 계산 기본 = 전체 길이의 2% -> 최소 7초, 
    base_chunk_size_sec = max(7 , int(base_chunk_ratio * video_length_sec))
    # 집중 청킹 단위(초) 계산 (더 세밀하게 쪼갤 크기) = 전체 길이의 0.6%, 최소 5초, 최대 1분
    focus_chunk_size_sec = max(5, min(int(fine_chunk_ratio * video_length_sec), 60))
    # 영상의 총 집중 시간 앞뒤 2% = 2*2 =4%  , 최소 10초, 최대 5분
    total_focus_size =  max(10, min(int(focus_range_ratio * video_length_sec *2), 300))


    # 집중 청킹 시작 시간 -> 0보다는 큼
    start_focus_time = max(0, worst_sec - total_focus_size // 2)
    # 집중 청킹 끝 시간 -> 총 길이보다는 작음
    end_focus_time = min(video_length_sec, worst_sec + total_focus_size // 2)

    current_time = 0  # 현재 청킹 시작 시간 (초)

    chunk_list = []
    row_list = []
    while current_time < video_length_sec:
        # 현재 구간이 집중 범위 안이면 더 작은 단위로 쪼갬
        if  start_focus_time <= current_time <= end_focus_time:
            chunk_size = focus_chunk_size_sec
            is_in_focus = True
                
            # 1. 청크 끝 시간 계산
            chunk_end_time = min(current_time + chunk_size, video_length_sec)

            # 2. 시작 인덱스 찾기 (이진 탐색)
            start_idx = max(binary_search_le(script, current_time),0)
            # 3. 청킹 범위 안의 스크립트 수집
            chunk_texts = []
            #current 시간 에 가장 가까운 대본의 인덱스 가져와서, 청킹 단위 까지 합치기
            for i in range(start_idx , len(script)):
                current = script[i]
                if current["start_time"] < chunk_end_time and current["end_time"] > current_time:
                    chunk_texts.append(current["text"])
                else:
                    if current["start_time"] > chunk_end_time:
                        break

            chunk_text = " ".join(chunk_texts).strip()
            print(chunk_text)
            chunk_list.append([chunk_text, current_time, chunk_end_time])
            # 3) rows 평균 계산
            # row 정보는 0.01 단위 이므로, 비율 단위로 바꿔야 함
            start_ratio = current_time / video_length_sec
            end_ratio = chunk_end_time / video_length_sec
            # row를 돌면서, current 부터 청킹 끝나는 시간에 해당하는 row들을 가지고 옴 (row는 100개 고정이어서 그냥 for문)
            target_rows = [r for r in analytics if start_ratio <= r[0] <= end_ratio]
            if target_rows:
                avg_audienceWatchRatio  = sum(r[1] for r in target_rows) / len(target_rows)
                avg_relativeRetentionPerformance = sum(r[2] for r in target_rows) / len(target_rows)
            else:
                avg_audienceWatchRatio  = 0
                avg_relativeRetentionPerformance = 0

            row_list.append([avg_audienceWatchRatio, avg_relativeRetentionPerformance])
            
        else:
            chunk_size = base_chunk_size_sec

        current_time += chunk_size
    context = json.dumps(chunk_list, ensure_ascii=False)

    retry = 3
    for attempt in range(retry + 1):
        try:
            query="이 데이터의 내용을 설명해줘"
            summary = await rag_service.execute_llm_chain(context, query, PromptTemplateManager.get_meaning_based_chunk_prompt())
            summary_list = json.loads(summary)
            if isinstance(summary_list, list):
                break
        except json.JSONDecodeError:
            print(f"⚠️ JSON 파싱 실패 (시도 {attempt + 1}/{retry + 1})")




    for i in range(len(summary_list)):
        print(summary_list[i][0],summary_list[i][1], summary_list[i][2],  row_list[i][0], row_list[i][1])
        chunk_meta={
        'chunk_type': 'mean',        # 청킹 타입
        'time_start': summary_list[i][1],         # 구간 시작 시간 (초)
        'time_end': summary_list[i][2],             # 구간 끝 시간 (초)
        'audienceWatchRatio': row_list[i][0],    # 평균 시청률
        'relativeRetentionPerformance': row_list[i][1],  # 평균 상대 유지율
        'is_focus_zone': is_in_focus, # 집중 구간 여부
        'created_at' : datetime.now().isoformat()
        }

        # # 저장
        await content_chunk_repo.save_context(
            source_type=SourceTypeEnum.VIEWER_ESCAPE_ANALYSIS.value.upper(),
            source_id=int(video_id),
            context= summary_list[i][0],
            meta= chunk_meta
        )
