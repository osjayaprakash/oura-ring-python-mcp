"""server.json must agree with the package it describes, or the MCP Registry rejects it."""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = json.loads((ROOT / "server.json").read_text())
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def _package(registry_type: str) -> dict:
    return next(p for p in SERVER["packages"] if p["registryType"] == registry_type)


def test_versions_match_pyproject():
    version = PROJECT["version"]
    assert SERVER["version"] == version
    assert _package("pypi")["version"] == version
    assert _package("oci")["identifier"].endswith(f":{version}")


def test_pypi_identifier_is_the_project_name():
    assert _package("pypi")["identifier"] == PROJECT["name"]


def test_readme_carries_mcp_name():
    readme = (ROOT / "README.md").read_text()
    assert f"<!-- mcp-name: {SERVER['name']} -->" in readme


def test_dockerfile_carries_server_name_label():
    dockerfile = (ROOT / "Dockerfile").read_text()
    label = re.search(r'io\.modelcontextprotocol\.server\.name="([^"]+)"', dockerfile)
    assert label and label.group(1) == SERVER["name"]


def _env_names(registry_type: str) -> list[str]:
    return [e["name"] for e in _package(registry_type)["environmentVariables"]]


def test_env_vars_match_between_packages():
    # The image fixes OURA_TOKEN_FILE at the mounted /tokens folder.
    assert [n for n in _env_names("pypi") if n != "OURA_TOKEN_FILE"] == _env_names("oci")


def test_env_vars_cover_the_settings():
    config = (ROOT / "src" / "oura_ring_mcp" / "config.py").read_text()
    read = set(re.findall(r'env\.get\("(OURA_[A-Z_]+)"', config))
    assert read == set(_env_names("pypi")) | {"OURA_REDIRECT_URI", "OURA_SCOPES"}


def test_docker_image_reads_tokens_from_the_mounted_folder():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "ENV OURA_TOKEN_FILE=/tokens/tokens.json" in dockerfile
    [mount] = _package("oci")["runtimeArguments"]
    assert (mount["name"], mount["value"]) == ("-v", "{token_dir}:/tokens")
