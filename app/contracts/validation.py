"""Validation helpers for inter-module contracts."""

from dataclasses import asdict, is_dataclass


class ContractValidationError(ValueError):
    pass


def validate_contract(value):
    if not is_dataclass(value):
        raise ContractValidationError("Contract must be a dataclass instance")
    return asdict(value)
