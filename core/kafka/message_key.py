from typing import Any, Optional


def to_message_key(value: Any) -> Optional[bytes]:
    """
    엔티티 id를 Kafka 메시지 키(bytes)로 변환.
    같은 키는 항상 같은 파티션 → 같은 엔티티 결과를 한 컨슈머가 순서대로 처리.
    broker에 key_serializer가 없어 bytes로 넘겨야 함. None이면 키 없이 발행.
    """
    if value is None:
        return None
    return str(value).encode("utf-8")
