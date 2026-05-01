from app.db.models import TrafficLight
from app.rating.traffic_light import compute_rating


def test_rating_green_when_all_pass_and_confidence_high() -> None:
    out = compute_rating([0.9, 0.88, 0.91], [True, True], [False], threshold=0.75)
    assert out.traffic_light == TrafficLight.green
    assert not out.manual_review_required


def test_rating_yellow_on_low_confidence() -> None:
    out = compute_rating([0.9, 0.5], [True, True], [False], threshold=0.75)
    assert out.traffic_light == TrafficLight.yellow


def test_rating_red_on_attribute_fail() -> None:
    out = compute_rating([0.9], [False], [False], threshold=0.75)
    assert out.traffic_light == TrafficLight.red


def test_rating_red_on_citation_flag() -> None:
    out = compute_rating([0.9], [True], [True], threshold=0.75)
    assert out.traffic_light == TrafficLight.red
