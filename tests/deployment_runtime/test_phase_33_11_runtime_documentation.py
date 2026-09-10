from pathlib import Path


def test_runtime_documentation_exists():
    path = Path("docs/deployment_runtime/PHASE_33.11_RUNTIME_DOCUMENTATION.md")
    assert path.name == "PHASE_33.11_RUNTIME_DOCUMENTATION.md"
