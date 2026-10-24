"""Round3: comparison must see fields the Round2 fingerprint ignored."""
from fusion_mvp.workbench.record_compare import raw_semantic_fp, std_semantic_fp


def _row(**kw):
    base = {
        "id": "T1",
        "longitude": "120.2",
        "latitude": "36.1",
        "altitude": "80",
        "speed": "5",
        "heading": "90",
        "created_at": "2026/6/24 8:00:00.1",
        "source": "rid",
        "type": "",
        "aerial_sn": "",
        "detector": "D1",
        "source_data": '{"a":1,"b":2}',
        "uav_type": "",
        "model": "",
        "brand": "",
        "model_number": "",
        "base_latitude": "",
        "base_longitude": "",
        "azimuth_angle": "",
        "target_distance": "",
        "sensors": "",
        "freq": "",
        "district": "qd",
        "tenant_region_code": "",
        "height": "20",
        "is_cooperation": "0",
        "created_time": "2026/6/24 8:00:00.1",
    }
    base.update(kw)
    return base


def _obs(**kw):
    base = {
        "source": "rid",
        "detectorId": "D1",
        "sourceTrackId": "T1",
        "aircraftId": "U001",
        "measurementTime": "2026-06-24T08:00:00.123456+08:00",
        "receivedAt": "2026-06-24T08:00:00.123456+08:00",
        "timeBasis": "measurement",
        "longitude": 120.2,
        "latitude": 36.1,
        "altitude": 80.0,
        "altitudeDatum": "unknown",
        "speed": 5.0,
        "heading": 90.0,
        "verticalSpeed": 0.0,
        "qualityFlags": ["aircraftId_unconfirmed"],
        "observationId": "imp-1",
        "rawRef": {"sheet": "S", "row": 2},
    }
    base.update(kw)
    return base


def test_raw_semantic_sees_altitude_speed_height_created_time():
    a = raw_semantic_fp(_row())
    assert raw_semantic_fp(_row(altitude="180")) != a
    assert raw_semantic_fp(_row(speed="25")) != a
    assert raw_semantic_fp(_row(height="120")) != a
    assert raw_semantic_fp(_row(created_time="2026/6/24 8:00:10.1")) != a


def test_std_sees_identity_heading_vs_datum():
    a = std_semantic_fp(_obs())
    assert std_semantic_fp(_obs(aircraftId="U002")) != a
    assert std_semantic_fp(_obs(heading=270.0)) != a
    assert std_semantic_fp(_obs(verticalSpeed=5.0)) != a
    assert std_semantic_fp(_obs(altitudeDatum="wgs84")) != a


def test_offset_same_clock_not_equal_same_instant_is():
    a = std_semantic_fp(_obs())
    shifted = std_semantic_fp(_obs(measurementTime="2026-06-24T08:00:00.123456+00:00", receivedAt="2026-06-24T08:00:00.123456+00:00"))
    assert shifted != a
    same = std_semantic_fp(_obs(measurementTime="2026-06-24T00:00:00.123456+00:00", receivedAt="2026-06-24T00:00:00.123456+00:00"))
    assert same == a


def test_tiny_coordinate_not_rounded_away():
    a = std_semantic_fp(_obs())
    assert std_semantic_fp(_obs(longitude=120.20000001)) != a


def test_json_value_differs_key_order_same():
    a = raw_semantic_fp(_row())
    assert raw_semantic_fp(_row(source_data='{"b":2,"a":1}')) == a
    assert raw_semantic_fp(_row(source_data='{"a":9,"b":2}')) != a


def test_one_and_one_point_zero_numeric_equal():
    assert raw_semantic_fp(_row(is_cooperation="1")) == raw_semantic_fp(_row(is_cooperation="1.0"))


def test_missing_column_not_equivalent():
    row = _row()
    del row["height"]
    assert raw_semantic_fp(row) != raw_semantic_fp(_row())


def test_unparsed_time_marks_incomplete():
    from fusion_mvp.workbench.record_compare import compare_incomplete, raw_semantic_record

    rec = raw_semantic_record(_row(created_at="not-a-date"))
    assert compare_incomplete(rec)


def test_same_instant_different_date_text_is_equal():
    a = raw_semantic_fp(_row(created_at="24/6/2026 08:00:30", created_time="24/6/2026 08:00:30.242716"))
    b = raw_semantic_fp(_row(created_at="2026-06-24 08:00:30", created_time="2026-06-24 08:00:30.242716"))
    assert a == b


def test_binary_float_text_is_not_strictly_equal():
    from fusion_mvp.workbench.record_compare import cell_diff_class

    a = raw_semantic_fp(_row(latitude="36.093662"))
    b = raw_semantic_fp(_row(latitude="36.093662000000002"))
    assert a != b
    assert cell_diff_class("latitude", "36.093662", "36.093662000000002") == "binary_float_vs_decimal_text"
