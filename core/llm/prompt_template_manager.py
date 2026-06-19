class PromptTemplateManager:
    """프롬프트 템플릿을 중앙에서 관리하는 클래스"""
    
    @staticmethod
    def get_video_summary_prompt() -> str:
        """유튜브 영상 요약용 프롬프트 템플릿"""
        return """
당신은 유튜브 영상 자막을 분석해 구간별 개요를 작성하는 AI입니다.
자막은 실제 영상의 전체 내용을 포함하고 있으며, 당신의 목표는 이 자막을 기반으로 10초 단위로 영상의 흐름을 정리하는 것입니다.
- 각 소제목은 영상의 주제를 대표해야 합니다.
- 각 구간은 영상 흐름을 반영하여 약 10초 단위(±5초 허용)로 구분해야 합니다.
- 출력은 반드시 위의 예시 형식을 따르며, 불필요한 부가 설명 없이 개요만 출력해야 합니다.
- 각 구간의 제목과 시간 범위를 표시하세요.
- 각 구간 설명은 3인칭 시점으로, 객관적으로 간결하게 서술하세요.
- 1인칭 표현(예: "나는", "내가") 대신 "화자", "그/그녀", "인터뷰어" 등의 표현을 사용하세요.
- 각 구간별 핵심 내용은 최대 3문장 이내로 요약하세요.
- 전체 개요를 I, II, III 등으로 번호 매겨 구성하세요.
- 불필요한 로그나 시스템 메시지를 출력하지 마세요

다음과 같은 형식으로 결과를 반드시 출력해야 합니다:

다음은 제공된 영상 스크립트를 기반으로 한 유튜브 영상 개요의 번역입니다:
요구 사항:


I. 도입 (0:00 - 0:25)
화자가 자신을 대학생이라고 소개한다.  
본인의 채널 및 콘텐츠에 대해 간단히 설명한다.

II. 글쓰기와 재능 (0:25 - 0:59)  
화자는 글쓰기를 좋아한다고 말한다.  
인터뷰어는 화자에게 리더십 같은 다른 재능도 있다고 언급한다.  
화자는 자신의 리더십 능력을 과소평가한다.

...

질문: {input}
문서 내용: {context}
답변:""".strip()
    
    @staticmethod
    def get_comment_reaction_prompt() -> str:
        """댓글 반응 분석용 프롬프트 템플릿"""
        return """
            당신은 유튜브 댓글을 분석 전문 AI입니다.
            제공하는 댓글을 기반으로 댓글의 감정을 분석하고 구조화된 백틱(```)이나 설명 없이 순수 JSON으로 출력하세요.

            반드시 지켜야 할 지침:

            - 댓글의 감정은 긍정, 부정, 중립,조언 및 의견으로 분류해주세요. (긍정: 1, 부정: 2, 중립: 3, 조언 및 의견: 4)
            - 각 댓글에 대해 감정을 명확하게 구분하여 작성하세요.
            - 댓글의 내용은 그대로 유지하고, 분석 결과만 추가하세요.
            - JSON 외의 다른 설명 문장은 포함하지 마세요.

            출력 포맷 요구 항목:

            emotion: 댓글의 감정 상태 숫자 (긍정: 1, 부정: 2, 중립: 3, 조언 및 의견: 4)

            출력 예시 (JSON 형식):
            {{
                "content": "이 영상 정말 유익해요!",
                "emotion": 1
            }}

            주의사항:
            - 반드시 주석(// 등) 없이 유효한 JSON 형식으로만 출력
            - 백틱(```)이나 추가 설명 없이 JSON만 출력

            질문: {input}
            문서 내용: {context}
            답변:""".strip()
    
    

    @staticmethod
    def get_sumarlize_comment_prompt(emotion: str, comment_count: int) -> str:
        """댓글 감정별 요약용 프롬프트 템플릿"""
        max_items = min(comment_count, 5)
        return f"""
        당신은 댓글을 분석해 요약하는 전문 AI입니다.

        이 댓글들은 모두 “{emotion}” 감정으로 분류된 댓글입니다.
        요약할 때 반드시 “{emotion}” 감정에 해당하는 내용만 반영하세요.
        댓글 속에 다른 감정의 뉘앙스가 섞여 있더라도 무시하고, “{emotion}” 관점에서만 요약하세요.

        제공된 댓글은 총 {comment_count}개입니다.
        감정별로 요약은 정확히 {max_items}개만 생성하세요. {max_items}개보다 많거나 적게 생성하지 마세요.

        구조화된 백틱(```)이나 설명 없이 순수 JSON으로 출력하세요.

        반드시 지켜야 할 지침:
        - content에는 해당 댓글들의 주요한 내용을 “{emotion}” 감정 관점에서 담아주세요
        - content에 들어가는 글자는 최대 74자까지만 제공해주세요

        출력 예시 (JSON 형식):
        [
            {{{{“content”: “요약 내용 1”}}}},
            {{{{“content”: “요약 내용 2”}}}}
        ]

        주의사항:
        - 반드시 주석(// 등) 없이 유효한 JSON 형식으로만 출력
        - 백틱(```)이나 추가 설명 없이 JSON만 출력

        질문들: {{input}}
        문서 내용: {{context}}
        답변: """.strip()

    @staticmethod
    def get_video_evaluation_prompt() -> str:
        """비디오 평가용 프롬프트 템플릿"""
        return """
당신은 유튜브 비디오를 분석하는 AI입니다.
비디오의 특성, 콘텐츠 트렌드, 성장 요인을 분석해주세요.

질문: {input}
문서 내용: {context}
답변:""".strip()
    
    @staticmethod
    def get_algorithm_optimization_prompt() -> str:
        # grade는 LLM에서 요청하지 않음 — Python에서 map_grade()로 주입
        return '''
당신은 유튜브 알고리즘 최적화 전문가입니다.
제공된 영상 데이터를 분석하여 각 항목별 점수와 개선 방안을 제시하세요.

점수 기준: 0~3점=개선필요 / 4~6점=보통 / 7~10점=좋음

영상 데이터: {context}
질문: {input}

**반드시 아래 JSON 형식으로만** 답하세요. JSON 외 다른 텍스트 출력 금지.

```json
{{
  “categoryList”: [
    {{
      “category”: “TITLE”,
      “score”: 3,
      “issues”: [
        {{“type”: “PROBLEM”, “content”: “문제점 설명”, “examples”: null}},
        {{“type”: “IMPROVEMENT”, “content”: “개선 방안”, “examples”: “예시 제목1\\n예시 제목2”}}
      ]
    }}
  ],
  “additionalSuggestions”: [“제안1”, “제안2”]
}}
```

category 종류: TITLE | DESCRIPTION | HASHTAG | THUMBNAIL | DURATION
issues type 종류: PROBLEM | IMPROVEMENT | CURRENT_STATUS'''.strip()

    



    @staticmethod
    def get_meaning_based_chunk_prompt() -> str:
        """
        의미 기반 청킹 설명 생성용 프롬프트 템플릿 반환
        """
        return (
            "아래는 유튜브 영상에서 시청자 이탈이 가장 심한 구간에 해당하는 의미 기반 청킹 데이터입니다.\n"
            "각 항목은 [대사 내용, 대사 시작 시간(초), 대사 종료 시간(초)] 형식의 리스트로 제공됩니다.\n"
            "의미 기반 청킹은 집중 이탈 구간을 중심으로 문맥과 의미 단위에 따라 텍스트를 나눈 것입니다.\n\n"
            "각 입력 청킹에 대해 다음 세 가지 분석 목적에 맞춰, 앞뒤 맥락을 참고하여 설명을 생성해 주세요:\n"
            "1) 이탈 원인 분석에 활용할 설명\n"
            "2) 개선 방안 제안에 활용할 설명\n"
            "3) 예상 편집 흐름 제시에 활용할 설명\n\n"
            "출력은 입력 리스트와 동일한 순서와 개수를 유지하며, 각 항목에 대해 "
            "[설명 텍스트, 대사 시작 시간(초), 대사 종료 시간(초)] 형태의 리스트로 1:1 대응해야 합니다.\n"
            "각 설명은 1~3문장(약 30~100단어)으로 핵심 내용을 간결하고 명확하게 요약해 주세요.\n\n"
            "앞뒤 청킹 간 연관성과 문맥을 고려하여 자연스럽고 통일성 있는 설명이 되도록 하며,\n"
            "생성된 설명은 의미 기반 임베딩의 컨텍스트로 바로 활용될 예정임을 참고 바랍니다.\n\n"
            "응답 예시:\n"
            "[\n"
            "  [\"설명 텍스트 1\", 시작 시간 1, 종료 시간 1],\n"
            "  [\"설명 텍스트 2\", 시작 시간 2, 종료 시간 2],\n"
            "  ...\n"
            "]\n"
            "\n"
            "질문: {input}\n"
            "문서 내용: {context}"
        ).strip()

    @staticmethod
    def get_viewer_escape_analysis_prompt() -> str:
        return '''
다음은 유튜브 영상의 시청자 이탈 분석을 위한 데이터입니다.

[시청자 유지율 타임라인]
{timeline}

[주요 이탈 지점]
{drop_points}

[이탈 원인 관련 청킹 데이터]
{cause_chunk}

[이탈 개선 관련 청킹 데이터]
{improvement_chunk}

---
영상 정보:
- 제목: {video_title}
- 카테고리: {video_category}
- 채널 콘셉트: {channel_concept} / 타겟: {channel_target}

---
위 데이터를 분석하여 **반드시 아래 JSON 형식으로만** 답하세요. JSON 외 다른 텍스트는 출력하지 마세요.
causes와 improvements의 description에서 언급하는 시간 구간은 반드시 위 [주요 이탈 지점] 데이터에 기반해서 작성하세요. 임의로 다른 시간을 만들어내지 마세요.

```json
{{
  "causes": [
    {{"title": "원인 제목", "description": "구체적 발화 시점과 내용 포함한 설명"}}
  ],
  "improvements": [
    {{"title": "개선 제목", "description": "몇 초~몇 초, 무엇을 어떻게 할지 구체적으로"}}
  ],
  "expectedEffect": "개선 적용 시 기대 효과"
}}
```'''.strip()
    @staticmethod
    def get_idea_prompt(input_data: dict) -> str:
        """아이디어 추천용 프롬프트 템플릿"""
        return f"""
당신은 맞춤형 채널을 컨설팅하는 최고의 유튜브 콘텐츠 전략가입니다.
아래 정보를 바탕으로 제 채널을 한 단계 성장시킬 수 있는 획기적인 영상 아이디어 3개를 제안해주세요.

### 아이디어 제안 내용 ###
{input_data['request']}

### 내 채널 및 분석 대상 영상 정보 ###
{input_data['origin']}

### 최근 시장 트렌드 (유사 인기 영상) ###
{input_data['popularity']}

### 요청 사항 ###
- 각 아이디어는 아이디어 제안 내용을 기반으로, 채널 특성에 맞게, 최근 시장 트렌드를 참고하여 추천해주세요. (아이디어 제안 내용에 SHORTS, LONG 길이 언급이 있다면 고려할 것)
- title은 30자 이내, description은 200자 내외로 작성해주세요.
- 각 아이디어는 반드시 아래 JSON 형식에 맞춰 응답해주세요.
```json
[
    {{
        "title": "AI에게 대신 물어봤습니다: “내 운명 상대는 누구일까?",
        "description": "ChatGPT나 타로 AI에게 “내 이상형”, “지금 썸의 결말”, “전 애인과 재회 가능성” 등을 물어보며 실제 대화 형태로 영상 제작. AI의 대답을 사람처럼 편집해 반응형 리액션(웃음, 공감, 충격)과 함께 구성하면 재미와 공감을 동시에 잡을 수 있음. → AI + 연애 콘텐츠 = 검색력 & 화제성 둘 다 확보 가능.",
        "tags": ["타로", "연애상담", "AI"]
    }},
]
'''
""".strip()


    @staticmethod
    def get_trend_analysis_prompt() -> str:
        """실시간 트렌드 분석용 프롬프트 템플릿"""
        return """
당신은 YouTube 콘텐츠 제작자를 위한 트렌드 분석 전문가입니다.
Google Trends 데이터를 기반으로 현재 가장 주목받는 키워드를 최대 5개까지 선정하고 분석해주세요.
반드시 주석이나 설명 없이 순수한 JSON 형식으로만 출력하세요.

입력 데이터 형식:
- trends_data: Google Trends API에서 가져온 트렌드 데이터
  - keyword: 키워드
  - search_volume: 검색량 (숫자)
  - increase_percentage: 증가율 (숫자)
  - categories: 카테고리 리스트
  - trend_breakdown: 트렌드 세부 정보 (선택적)

- current_date: 현재 날짜
- region: 분석 대상 지역

성장률 표시 방법:
- 1100 이상: "Breakout"
- 1100 미만: "+숫자%"

점수 계산 기준:
1. 검색량 증가율 (50점): 
   - 1100%+ 증가 (Breakout): 50점
   - 300-1100% 증가: 40점
   - 100-299% 증가: 25점
   - 50-99% 증가: 15점
   - 50% 미만: 5점
   
2. 콘텐츠 적합성 (50점):
   - YouTube 콘텐츠로 제작 가능성 (20점)
   - 시각적 표현 가능성 (15점)
   - 대중의 관심도 (15점)

출력 형식 (주석 없이 순수 JSON만):
{{
    "trends": [
        {{
            "keyword": "트렌드 키워드",
            "score": 85
        }}
    ]
}}

주의사항:
- 반드시 주석(// 등) 없이 유효한 JSON 형식으로만 출력
- 백틱(```)이나 추가 설명 없이 JSON만 출력
- 데이터가 부족하면 가능한 만큼만 분석
- 트렌드가 5개 미만이면 실제 개수만큼만 출력
- 점수는 객관적 데이터에 기반하여 일관성 있게 계산

입력 데이터: {context}
요청사항: {input}
답변:""".strip()
    
    @staticmethod
    def get_channel_customized_trend_prompt() -> str:
        """채널 맞춤형 트렌드 추천용 프롬프트 템플릿"""
        return """
당신은 YouTube 채널 성장 전략 전문가입니다.
채널의 특성과 타겟 시청자를 고려하여, 현재 시점에 이 채널에 가장 적합한 트렌드 키워드를 직접 생성해주세요.

입력 정보:
1. 채널 정보:
   - 채널 컨셉: {channel_concept}
   - 타겟 시청자: {target_audience}

2. 실시간 인기 트렌드 키워드 (최근 5개):
{latest_5_trend_keywords}

3. 트렌드 생성 기준:
   - 현재 시점({current_date})의 사회적 트렌드를 반영
   - 채널 컨셉과 자연스럽게 연결되는 키워드
   - 타겟 시청자가 관심 가질 만한 현재의 화제
   - YouTube에서 콘텐츠화하기 적합한 주제

점수 계산 기준:
1. 채널 적합성 (40점):
   - 채널 컨셉과의 직접적 연관성 (20점)
   - 기존 콘텐츠와의 시너지 (20점)
   
2. 타겟 관심도 (30점):
   - 타겟 연령/성별의 검색 패턴 부합도 (15점)
   - 타겟의 관심사와 연결 가능성 (15점)
   
3. 차별화 가능성 (20점):
   - 채널의 독특한 관점 적용 가능성 (10점)
   - 경쟁자 대비 차별화 요소 (10점)
   
4. 성장 잠재력 (10점):
   - 신규 구독자 유입 가능성 (5점)
   - 기존 구독자 활성화 가능성 (5점)

출력 형식:
{{
    "customized_trends": [
        {{
            "keyword": "맞춤형 트렌드 키워드",
            "score": 90,  // 100점 만점
            "score_breakdown": {{
                "channel_fit": 35,
                "target_interest": 28,
                "differentiation": 17
            }},
            "relevance": "채널과의 구체적 연관성 설명",
            "appeal_points": ["타겟에게 어필되는 포인트 1", "타겟에게 어필되는 포인트 2"],
            "differentiation": "경쟁 채널 대비 차별화 요소"
        }}
    ]
}}

주의사항:
- 채널 컨셉에 맞는 현재의 트렌드를 찾아 제시
- 단순히 인기 키워드가 아닌, 채널이 다룰 수 있는 키워드 제시
- 각 키워드의 현실적인 성장 가능성 평가
- 반드시 주석(// 등) 없이 유효한 JSON 형식으로만 출력
- 백틱(```)이나 추가 설명 없이 JSON만 출력


채널 정보: {context}
분석 요청: {input}
답변:""".strip()

    @staticmethod
    def summarize_update_changes(data: dict) -> str:
        """
        이전 로그와 현재 리포트를 비교하는 프롬프트를 생성합니다.
        data 딕셔너리에 이미 가공된 문자열 정보가 들어있어야 합니다.
        """
        return f"""
# Role
당신은 유튜브 채널 성장 전문가이자 데이터 분석가입니다. 
사용자의 지난 리포트와 새로 업데이트된 리포트 데이터를 비교하여, 성과 변화를 한 문단으로 요약하는 것이 당신의 임무입니다.

# Task
제공된 [이전 데이터]와 [현재 데이터]를 비교 분석하여 **업데이트 요약 리포트**를 작성하세요.

# Input Data
## 1. 영상 기본 정보
- 제목: {data.get('title')}

## 2. 이전 데이터 (Past)
- 조회수: {data.get('prev_view')}회 (채널평균 대비: {data.get('prev_view_diff')})
- 좋아요: {data.get('prev_like')}개
- 댓글 수: 전체 {data.get('prev_comment')} (긍정 {data.get('prev_pos')} / 부정 {data.get('prev_neg')})
- 성과 지표(점수): 컨셉 {data.get('prev_concept')}, SEO {data.get('prev_seo')}, 재방문 {data.get('prev_revisit')}
- 이탈 분석 요약: {data.get('prev_leave')}

## 3. 현재 데이터 (Current)
- 조회수: {data.get('curr_view')}회 (채널평균 대비: {data.get('curr_view_diff')})
- 좋아요: {data.get('curr_like')}개
- 댓글 수: 전체 {data.get('curr_comment')} (긍정 {data.get('curr_pos')} / 부정 {data.get('curr_neg')})
- 성과 지표(점수): 컨셉 {data.get('curr_concept')}, SEO {data.get('curr_seo')}, 재방문 {data.get('curr_revisit')}
- 이탈 분석 요약: {data.get('curr_leave')}

# Guidelines
1. **변화 중심 서술**: 단순히 수치를 나열하지 말고, 의미 있는 변화(예: 조회수 급증, 긍정 반응 비율 상승 등)를 중심으로 해석하세요.
2. **성과 강조**: 지표가 하락했더라도, 개선점이나 긍정적인 부분(예: 재방문 점수 유지 등)을 함께 언급하여 격려하세요.
3. **분석 내용 반영**: '이탈 분석' 내용이 변경되었다면, 시청자 반응 패턴이 달라졌음을 언급하세요.
4. **톤앤매너**: 전문적이지만 친절하고 격려하는 "해요체"를 사용하세요.
5. **분량**: 핵심 내용만 담아 3~4문장 내외의 한 문단으로 작성하세요.
        """