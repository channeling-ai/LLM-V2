from core.kafka.message_key import to_message_key


def test_int_id_to_utf8_bytes():
    assert to_message_key(10) == b"10"


def test_str_id_to_utf8_bytes():
    assert to_message_key("10") == b"10"


def test_none_means_no_key():
    assert to_message_key(None) is None
