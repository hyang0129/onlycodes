import pytest
from myapp.utils import validate_input, format_json


def test_format_json_basic():
    result = format_json({"key": "value"})
    assert '"key": "value"' in result


def test_validate_input_valid():
    assert validate_input(5, 1, 10) is True


def test_validate_input_out_of_range():
    # INTENTIONAL FAILURE: function raises ValueError, test expects False
    assert validate_input(15, 1, 10) is False
