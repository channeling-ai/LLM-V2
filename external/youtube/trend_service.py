import os
import json
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dotenv import load_dotenv
import requests
import serpapi

load_dotenv()

class TrendService:
    """Google Trends API를 통한 트렌드 데이터 수집 서비스"""
    
    def __init__(self):
        self.serpapi_key = os.getenv('SERPAPI_KEY')
        if not self.serpapi_key:
            raise ValueError("SERPAPI_KEY environment variable is not set")

    def get_realtime_trends(
        self,
        geo: str = "KR",
        limit: int = 10,
        category: Optional[str] = None
    ) -> List[Dict]:
        """
        실시간 트렌드 데이터 수집
        
        Args:
            geo: 지역 코드 (기본값: KR - 한국)
            limit: 가져올 트렌드 개수
            category: 특정 카테고리 필터링 (선택사항)
            
        Returns:
            트렌드 데이터 리스트
        """
        try:
            # Google Trends Trending Now API 사용
            params = {
                "engine": "google_trends_trending_now",
                "geo": geo,
                "hours": 24,  # 24시간 내 트렌드
                "hl": "ko",  # 한국어
                "only_active": "true",  # 현재 활발한 트렌드만
            }
            
            if category:
                params["category_id"] = category
            
            client = serpapi.Client(api_key=self.serpapi_key)
            results = client.search(params)
            
            # 트렌드 데이터 파싱
            trends = self._parse_trending_searches(results, limit)
            
            return trends
            
        except Exception as e:
            print(f"Error fetching realtime trends: {e}")
            # 대체 방법: 인기 검색어 키워드 목록 사용
            return []
    
    def _parse_trending_searches(self, results: Dict, limit: int) -> List[Dict]:
        """트렌딩 검색어 파싱"""
        trends = []
        
        # Google Trends Trending Now API 응답 형식
        if "trending_searches" in results:
            trending_searches = results["trending_searches"]
            
            for search in trending_searches[:limit]:
                start_ts = search.get("start_timestamp")
                trend = {
                    "keyword": search.get("query", ""),
                    "search_volume": search.get("search_volume", 0),
                    "increase_percentage": search.get("increase_percentage", 0),
                    "categories": [cat.get("name", "") for cat in search.get("categories", [])],
                    "trend_breakdown": search.get("trend_breakdown", []),
                    "started_at": datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M") if start_ts else None,
                }
                trends.append(trend)
        
        return trends[:limit]
    
    


if __name__ == "__main__":
    # 테스트 코드
    try:
        service = TrendService()
        
        # 실시간 트렌드 가져오기
        trends = service.get_realtime_trends(limit=12)
        print("Realtime Trends:", json.dumps(trends, ensure_ascii=False, indent=2))
        
        
    except ValueError as e:
        print(f"Error: {e}")
        print("Please set SERPAPI_API_KEY environment variable")