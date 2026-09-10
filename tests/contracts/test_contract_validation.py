from dataclasses import dataclass

import pytest

from app.contracts.validation import ContractValidationError, validate_contract


@dataclass
class SampleContract:
    value: int


def test_valid_contract():
    assert validate_contract(SampleContract(1))["value"] == 1


def test_invalid_contract():
    with pytest.raises(ContractValidationError):
        validate_contract(object())
