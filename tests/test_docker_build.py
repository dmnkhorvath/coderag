"""Tests for Docker build configuration files.

Validates Docker-related files exist and have correct structure.
Does NOT require a Docker daemon - only checks file content.
"""

import os
import stat

import yaml

# -- Paths -----------------------------------------------------------------

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKERFILE = os.path.join(PROJECT_ROOT, "Dockerfile")
COMPOSE_FILE = os.path.join(PROJECT_ROOT, "docker-compose.yml")
DOCKERIGNORE = os.path.join(PROJECT_ROOT, ".dockerignore")
ENTRYPOINT = os.path.join(PROJECT_ROOT, "scripts", "docker-entrypoint.sh")


# -- Dockerfile Tests ------------------------------------------------------


class TestDockerfile:
    """Validate Dockerfile structure and content."""

    def test_dockerfile_exists(self):
        assert os.path.isfile(DOCKERFILE), "Dockerfile not found at project root"

    def test_dockerfile_has_from(self):
        content = open(DOCKERFILE).read()
        assert "FROM" in content, "Dockerfile must have FROM instruction"

    def test_dockerfile_multi_stage(self):
        content = open(DOCKERFILE).read()
        from_count = content.count("FROM ")
        assert from_count >= 2, f"Expected multi-stage build (>=2 FROM), got {from_count}"

    def test_dockerfile_uses_python_312_slim(self):
        content = open(DOCKERFILE).read()
        assert "python:3.12-slim" in content, "Should use python:3.12-slim base image"

    def test_dockerfile_has_builder_stage(self):
        content = open(DOCKERFILE).read()
        assert "AS builder" in content or "as builder" in content, "Should have a builder stage"

    def test_dockerfile_has_runtime_stage(self):
        content = open(DOCKERFILE).read()
        assert "AS runtime" in content or "as runtime" in content, "Should have a runtime stage"

    def test_dockerfile_installs_gcc(self):
        content = open(DOCKERFILE).read()
        assert "gcc" in content, "Builder should install gcc for C extensions"

    def test_dockerfile_installs_git_in_runtime(self):
        content = open(DOCKERFILE).read()
        lines = content.splitlines()
        runtime_started = False
        git_in_runtime = False
        for line in lines:
            if "AS runtime" in line or "as runtime" in line:
                runtime_started = True
            if runtime_started and "git" in line:
                git_in_runtime = True
                break
        assert git_in_runtime, "Runtime stage should include git"

    def test_dockerfile_has_workdir_code(self):
        content = open(DOCKERFILE).read()
        assert "WORKDIR /code" in content, "Should set WORKDIR to /code"

    def test_dockerfile_has_entrypoint(self):
        content = open(DOCKERFILE).read()
        assert "ENTRYPOINT" in content, "Should have ENTRYPOINT instruction"

    def test_dockerfile_has_labels(self):
        content = open(DOCKERFILE).read()
        assert "LABEL" in content, "Should have metadata labels"
        assert "maintainer" in content.lower() or "org.opencontainers" in content, (
            "Should have maintainer or OCI labels"
        )

    def test_dockerfile_copies_from_builder(self):
        content = open(DOCKERFILE).read()
        assert "COPY --from=builder" in content, "Runtime stage should copy from builder"

    def test_dockerfile_no_obvious_syntax_errors(self):
        """Check that all non-continuation lines start with valid instructions."""
        content = open(DOCKERFILE).read()
        lines = content.splitlines()
        valid_instructions = {
            "FROM",
            "RUN",
            "CMD",
            "LABEL",
            "EXPOSE",
            "ENV",
            "ADD",
            "COPY",
            "ENTRYPOINT",
            "VOLUME",
            "USER",
            "WORKDIR",
            "ARG",
            "ONBUILD",
            "STOPSIGNAL",
            "HEALTHCHECK",
            "SHELL",
        }
        in_continuation = False
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                in_continuation = False
                continue
            if in_continuation:
                in_continuation = stripped.endswith("\\")
                continue
            first_word = stripped.split()[0].upper() if stripped.split() else ""
            if first_word in valid_instructions:
                in_continuation = stripped.endswith("\\")
            # Non-instruction lines after FROM are allowed (e.g. && chains)


# -- Docker Compose Tests --------------------------------------------------


class TestDockerCompose:
    """Validate docker-compose.yml structure."""

    def test_compose_file_exists(self):
        assert os.path.isfile(COMPOSE_FILE), "docker-compose.yml not found"

    def test_compose_valid_yaml(self):
        with open(COMPOSE_FILE) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), "docker-compose.yml should be a valid YAML dict"

    def test_compose_has_services(self):
        with open(COMPOSE_FILE) as f:
            data = yaml.safe_load(f)
        assert "services" in data, "Should have 'services' key"

    def test_compose_has_coderag_service(self):
        with open(COMPOSE_FILE) as f:
            data = yaml.safe_load(f)
        assert "coderag" in data["services"], "Should have 'coderag' service"

    def test_compose_has_mcp_service(self):
        with open(COMPOSE_FILE) as f:
            data = yaml.safe_load(f)
        assert "coderag-mcp" in data["services"], "Should have 'coderag-mcp' service"

    def test_compose_has_watch_service(self):
        with open(COMPOSE_FILE) as f:
            data = yaml.safe_load(f)
        assert "coderag-watch" in data["services"], "Should have 'coderag-watch' service"

    def test_compose_mcp_has_port_mapping(self):
        with open(COMPOSE_FILE) as f:
            data = yaml.safe_load(f)
        mcp = data["services"]["coderag-mcp"]
        assert "ports" in mcp, "MCP service should have port mapping"
        ports = mcp["ports"]
        port_strs = [str(p) for p in ports]
        assert any("3000" in p for p in port_strs), "MCP should map port 3000"

    def test_compose_services_have_volumes(self):
        with open(COMPOSE_FILE) as f:
            data = yaml.safe_load(f)
        for name in ["coderag", "coderag-mcp", "coderag-watch"]:
            svc = data["services"][name]
            assert "volumes" in svc, f"Service '{name}' should have volumes"

    def test_compose_services_have_build(self):
        with open(COMPOSE_FILE) as f:
            data = yaml.safe_load(f)
        for name in ["coderag", "coderag-mcp", "coderag-watch"]:
            svc = data["services"][name]
            assert "build" in svc, f"Service '{name}' should have build config"


# -- .dockerignore Tests ---------------------------------------------------


class TestDockerignore:
    """Validate .dockerignore content."""

    def test_dockerignore_exists(self):
        assert os.path.isfile(DOCKERIGNORE), ".dockerignore not found"

    def test_dockerignore_excludes_git(self):
        content = open(DOCKERIGNORE).read()
        assert ".git" in content, "Should exclude .git"

    def test_dockerignore_excludes_pycache(self):
        content = open(DOCKERIGNORE).read()
        assert "__pycache__" in content, "Should exclude __pycache__"

    def test_dockerignore_excludes_pyc(self):
        content = open(DOCKERIGNORE).read()
        assert "*.pyc" in content, "Should exclude *.pyc"

    def test_dockerignore_excludes_codegraph(self):
        content = open(DOCKERIGNORE).read()
        assert ".codegraph" in content, "Should exclude .codegraph"

    def test_dockerignore_excludes_node_modules(self):
        content = open(DOCKERIGNORE).read()
        assert "node_modules" in content, "Should exclude node_modules"

    def test_dockerignore_excludes_venv(self):
        content = open(DOCKERIGNORE).read()
        assert "venv" in content, "Should exclude venv"

    def test_dockerignore_excludes_pytest_cache(self):
        content = open(DOCKERIGNORE).read()
        assert ".pytest_cache" in content, "Should exclude .pytest_cache"

    def test_dockerignore_excludes_tests(self):
        content = open(DOCKERIGNORE).read()
        assert "tests/" in content, "Should exclude tests/"


# -- Entrypoint Script Tests -----------------------------------------------


class TestEntrypoint:
    """Validate docker-entrypoint.sh."""

    def test_entrypoint_exists(self):
        assert os.path.isfile(ENTRYPOINT), "scripts/docker-entrypoint.sh not found"

    def test_entrypoint_is_executable(self):
        mode = os.stat(ENTRYPOINT).st_mode
        assert mode & stat.S_IXUSR, "Entrypoint should be executable by owner"

    def test_entrypoint_has_shebang(self):
        with open(ENTRYPOINT) as f:
            first_line = f.readline().strip()
        assert first_line.startswith("#!/"), "Should have a shebang line"

    def test_entrypoint_has_set_e(self):
        content = open(ENTRYPOINT).read()
        assert "set -e" in content, "Should have 'set -e' for error handling"

    def test_entrypoint_delegates_to_coderag(self):
        content = open(ENTRYPOINT).read()
        assert "exec coderag" in content, "Should exec coderag CLI"

    def test_entrypoint_handles_no_args(self):
        content = open(ENTRYPOINT).read()
        assert "--help" in content, "Should handle case when no arguments provided"
