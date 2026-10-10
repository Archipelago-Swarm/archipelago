from pathlib import Path

import pytest
from archipelago_contracts import SequenceTracker, parse_json

FIXTURES = Path(__file__).resolve().parents[2] / "packages/contracts/fixtures"
GOOD = sorted((FIXTURES / "good").glob("*.json"))
BAD = sorted((FIXTURES / "bad").glob("*.json"))


@pytest.mark.parametrize("path", GOOD, ids=lambda p: p.stem)
def test_good_fixture_validates(path: Path) -> None:
    record = parse_json(path.read_text())
    assert record.kind == path.stem  # type: ignore[attr-defined]


@pytest.mark.parametrize("path", BAD, ids=lambda p: p.stem)
def test_bad_fixture_rejected(path: Path) -> None:
    with pytest.raises(ValueError):  # pydantic ValidationError subclasses ValueError
        parse_json(path.read_text())


def test_every_record_kind_has_good_fixture() -> None:
    from archipelago_contracts import RECORDS

    assert {p.stem for p in GOOD} == set(RECORDS)


def test_sequence_tracker_rejects_stale_and_duplicate() -> None:
    t = SequenceTracker()
    assert t.accept("r", "n1", 0)
    assert t.accept("r", "n1", 2)
    assert not t.accept("r", "n1", 2)  # duplicate
    assert not t.accept("r", "n1", 1)  # stale
    assert t.accept("r", "n2", 0)  # independent source
    assert t.accept("r2", "n1", 0)  # independent run
