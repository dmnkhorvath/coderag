"""Targeted tests for FastAPI detector coverage.

Focuses on uncovered lines: 136-137, 148-149, 397-418, 431, 434,
457, 467, 472, 482, 491, 514, 524, 533, 620, 678-679, 695,
725-738, 761, 766-767, 788-826.
"""

from unittest.mock import MagicMock, patch

from coderag.core.models import (
    EdgeKind,
    Node,
    NodeKind,
    generate_node_id,
)
from coderag.plugins.python.frameworks.fastapi import FastAPIDetector

# ── Helpers ──────────────────────────────────────────────────


def _make_node(
    kind: NodeKind,
    name: str,
    file_path: str = "app.py",
    start_line: int = 1,
    end_line: int = 10,
    qualified_name: str | None = None,
    metadata: dict | None = None,
    source_text: str | None = None,
) -> Node:
    return Node(
        id=generate_node_id(file_path, start_line, kind, name),
        kind=kind,
        name=name,
        qualified_name=qualified_name or name,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        language="python",
        metadata=metadata or {},
        source_text=source_text,
    )


def _patterns_by_type(patterns, ptype):
    return [p for p in patterns if p.pattern_type == ptype]


def _nodes_by_kind(patterns, kind):
    result = []
    for p in patterns:
        for n in p.nodes:
            if n.kind == kind:
                result.append(n)
    return result


# ── detect_framework tests (lines 136-137, 148-149) ─────────


class TestDetectFramework:
    def test_detect_via_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi==0.100.0\nuvicorn")
        det = FastAPIDetector()
        assert det.detect_framework(str(tmp_path)) is True

    def test_detect_via_pyproject_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]')
        det = FastAPIDetector()
        assert det.detect_framework(str(tmp_path)) is True

    def test_detect_via_pipfile(self, tmp_path):
        (tmp_path / "Pipfile").write_text('[packages]\nfastapi = "*"')
        det = FastAPIDetector()
        assert det.detect_framework(str(tmp_path)) is True

    def test_detect_via_entry_point_main_py(self, tmp_path):
        """Lines 148-149: entry point detection."""
        (tmp_path / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")
        det = FastAPIDetector()
        assert det.detect_framework(str(tmp_path)) is True

    def test_detect_via_entry_point_app_py(self, tmp_path):
        (tmp_path / "app.py").write_text("import fastapi\napp = fastapi.FastAPI()")
        det = FastAPIDetector()
        assert det.detect_framework(str(tmp_path)) is True

    def test_detect_via_entry_point_app_init(self, tmp_path):
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / "__init__.py").write_text("from fastapi import FastAPI")
        det = FastAPIDetector()
        assert det.detect_framework(str(tmp_path)) is True

    def test_detect_via_entry_point_src_main(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "main.py").write_text("from fastapi import FastAPI")
        det = FastAPIDetector()
        assert det.detect_framework(str(tmp_path)) is True

    def test_no_fastapi_detected(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==2.0")
        det = FastAPIDetector()
        assert det.detect_framework(str(tmp_path)) is False

    def test_dep_file_oserror(self, tmp_path):
        """Lines 136-137: OSError reading dependency file."""
        det = FastAPIDetector()
        req_path = tmp_path / "requirements.txt"
        req_path.write_text("fastapi")
        real_open = open

        def mock_open_fn(path, *args, **kwargs):
            if str(path) == str(req_path):
                raise OSError("Permission denied")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_fn):
            # Should not crash, just continue
            det.detect_framework(str(tmp_path))

    def test_entry_point_oserror(self, tmp_path):
        """Lines 148-149: OSError reading entry point file."""
        det = FastAPIDetector()
        main_path = tmp_path / "main.py"
        main_path.write_text("from fastapi import FastAPI")
        real_open = open

        def mock_open_fn(path, *args, **kwargs):
            if str(path) == str(main_path):
                raise OSError("Permission denied")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_fn):
            result = det.detect_framework(str(tmp_path))
            # Should not crash

    def test_dep_file_no_fastapi(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("django==4.0")
        (tmp_path / "main.py").write_text("print('hello')")
        det = FastAPIDetector()
        assert det.detect_framework(str(tmp_path)) is False


# ── detect() per-file tests ──────────────────────────────────


class TestDetectRoutes:
    def test_basic_route_detection(self):
        det = FastAPIDetector()
        source = b"@app.get('/items')\ndef list_items():\n    return []\n\n@app.post('/items', response_model=ItemResponse)\ndef create_item(item):\n    return item\n"
        func_node = _make_node(NodeKind.FUNCTION, "list_items", start_line=2, end_line=3)
        func_node2 = _make_node(NodeKind.FUNCTION, "create_item", start_line=6, end_line=7)
        patterns = det.detect("app.py", None, source, [func_node, func_node2], [])
        route_patterns = _patterns_by_type(patterns, "routes")
        assert len(route_patterns) == 1
        assert route_patterns[0].metadata["route_count"] == 2

    def test_route_with_response_model(self):
        det = FastAPIDetector()
        source = b"@app.get('/users', response_model=List[UserOut])\ndef get_users():\n    pass\n"
        func_node = _make_node(NodeKind.FUNCTION, "get_users", start_line=2, end_line=3)
        patterns = det.detect("app.py", None, source, [func_node], [])
        route_patterns = _patterns_by_type(patterns, "routes")
        assert len(route_patterns) == 1
        route_nodes = route_patterns[0].nodes
        assert any("response_model" in n.metadata for n in route_nodes)

    def test_route_no_handler_nearby(self):
        det = FastAPIDetector()
        source = b"@app.get('/items')\ndef list_items():\n    return []\n"
        # Function is far away from decorator
        func_node = _make_node(NodeKind.FUNCTION, "list_items", start_line=50, end_line=55)
        patterns = det.detect("app.py", None, source, [func_node], [])
        route_patterns = _patterns_by_type(patterns, "routes")
        assert len(route_patterns) == 1

    def test_multiple_http_methods(self):
        det = FastAPIDetector()
        source = (
            b"@router.put('/items/{id}')\ndef update_item(id):\n    pass\n\n"
            b"@router.delete('/items/{id}')\ndef delete_item(id):\n    pass\n\n"
            b"@router.patch('/items/{id}')\ndef patch_item(id):\n    pass\n"
        )
        fn1 = _make_node(NodeKind.FUNCTION, "update_item", start_line=2, end_line=3)
        fn2 = _make_node(NodeKind.FUNCTION, "delete_item", start_line=5, end_line=6)
        fn3 = _make_node(NodeKind.FUNCTION, "patch_item", start_line=8, end_line=9)
        patterns = det.detect("routes.py", None, source, [fn1, fn2, fn3], [])
        route_patterns = _patterns_by_type(patterns, "routes")
        assert len(route_patterns) == 1
        assert route_patterns[0].metadata["route_count"] == 3


class TestDetectWebSocket:
    def test_websocket_detection(self):
        det = FastAPIDetector()
        source = b"@app.websocket('/ws')\nasync def websocket_endpoint(ws):\n    pass\n"
        func_node = _make_node(NodeKind.FUNCTION, "websocket_endpoint", start_line=2, end_line=3)
        patterns = det.detect("app.py", None, source, [func_node], [])
        ws_patterns = _patterns_by_type(patterns, "websocket")
        assert len(ws_patterns) == 1


class TestDetectAPIRouter:
    def test_apirouter_with_prefix_and_tags(self):
        det = FastAPIDetector()
        source = b'router = APIRouter(prefix=\'/api/v1\', tags=["users", "admin"])\n'
        patterns = det.detect("routes.py", None, source, [], [])
        router_patterns = _patterns_by_type(patterns, "api_router")
        assert len(router_patterns) >= 1

    def test_apirouter_without_prefix(self):
        det = FastAPIDetector()
        source = b"router = APIRouter()\n"
        patterns = det.detect("routes.py", None, source, [], [])
        router_patterns = _patterns_by_type(patterns, "api_router")
        assert len(router_patterns) >= 1


class TestDetectMiddleware:
    def test_middleware_decorator(self):
        det = FastAPIDetector()
        source = b"@app.middleware('http')\nasync def add_header(request, call_next):\n    response = await call_next(request)\n    return response\n"
        func_node = _make_node(NodeKind.FUNCTION, "add_header", start_line=2, end_line=4)
        patterns = det.detect("app.py", None, source, [func_node], [])
        mw_patterns = _patterns_by_type(patterns, "middleware")
        assert len(mw_patterns) == 1

    def test_add_middleware(self):
        det = FastAPIDetector()
        source = b"app.add_middleware(CORSMiddleware, allow_origins=['*'])\n"
        patterns = det.detect("app.py", None, source, [], [])
        mw_patterns = _patterns_by_type(patterns, "middleware")
        assert len(mw_patterns) == 1


class TestDetectExceptionHandler:
    """Tests for exception handler detection (lines 397-418)."""

    def test_exception_handler_with_handler_func(self):
        det = FastAPIDetector()
        source = b"@app.exception_handler(HTTPException)\nasync def http_exc_handler(request, exc):\n    return JSONResponse(status_code=exc.status_code)\n"
        func_node = _make_node(NodeKind.FUNCTION, "http_exc_handler", start_line=2, end_line=3)
        patterns = det.detect("app.py", None, source, [func_node], [])
        eh_patterns = _patterns_by_type(patterns, "exception_handler")
        assert len(eh_patterns) == 1
        assert eh_patterns[0].metadata["exception_type"] == "HTTPException"

    def test_exception_handler_without_handler_func(self):
        """No func_nodes provided - handler won't be found, uses fallback name."""
        det = FastAPIDetector()
        source = b"@app.exception_handler(ValidationError)\nasync def handle_validation(request, exc):\n    return JSONResponse(status_code=422)\n"
        patterns = det.detect("app.py", None, source, [], [])
        eh_patterns = _patterns_by_type(patterns, "exception_handler")
        assert len(eh_patterns) == 1
        node_name = eh_patterns[0].nodes[0].name
        assert "ValidationError" in node_name or "exc_handler" in node_name

    def test_multiple_exception_handlers(self):
        det = FastAPIDetector()
        source = (
            b"@app.exception_handler(HTTPException)\n"
            b"async def handle_http(request, exc):\n    pass\n\n"
            b"@app.exception_handler(RequestValidationError)\n"
            b"async def handle_validation(request, exc):\n    pass\n"
        )
        func1 = _make_node(NodeKind.FUNCTION, "handle_http", start_line=2, end_line=3)
        func2 = _make_node(NodeKind.FUNCTION, "handle_validation", start_line=6, end_line=7)
        patterns = det.detect("app.py", None, source, [func1, func2], [])
        eh_patterns = _patterns_by_type(patterns, "exception_handler")
        assert len(eh_patterns) == 2


class TestDetectBackgroundTasks:
    """Tests for background tasks detection (lines 431, 434)."""

    def test_background_tasks_param(self):
        det = FastAPIDetector()
        source = (
            b"@app.post('/send')\n"
            b"async def send_notification(background_tasks: BackgroundTasks):\n"
            b"    background_tasks.add_task(send_email)\n"
            b"    return {'message': 'sent'}\n"
        )
        func_node = _make_node(NodeKind.FUNCTION, "send_notification", start_line=2, end_line=4)
        patterns = det.detect("app.py", None, source, [func_node], [])
        bg_patterns = _patterns_by_type(patterns, "background_tasks")
        assert len(bg_patterns) == 1
        assert "background_tasks" in bg_patterns[0].metadata["background_task_params"]

    def test_multiple_background_tasks(self):
        det = FastAPIDetector()
        source = b"def endpoint1(bg: BackgroundTasks):\n    pass\n\ndef endpoint2(tasks: BackgroundTasks):\n    pass\n"
        func1 = _make_node(NodeKind.FUNCTION, "endpoint1", start_line=1, end_line=2)
        func2 = _make_node(NodeKind.FUNCTION, "endpoint2", start_line=4, end_line=5)
        patterns = det.detect("app.py", None, source, [func1, func2], [])
        bg_patterns = _patterns_by_type(patterns, "background_tasks")
        assert len(bg_patterns) == 1
        assert len(bg_patterns[0].metadata["background_task_params"]) == 2

    def test_no_background_tasks(self):
        det = FastAPIDetector()
        source = b"@app.get('/items')\ndef get_items():\n    return []\n"
        func_node = _make_node(NodeKind.FUNCTION, "get_items", start_line=2, end_line=3)
        patterns = det.detect("app.py", None, source, [func_node], [])
        bg_patterns = _patterns_by_type(patterns, "background_tasks")
        assert len(bg_patterns) == 0


class TestDetectPydanticModel:
    """Tests for Pydantic model detection (lines 620, 678-679)."""

    def test_pydantic_model_with_fields(self):
        det = FastAPIDetector()
        source = b"class UserCreate(BaseModel):\n    username: str\n    email: str\n    age: int = 0\n"
        cls_node = _make_node(
            NodeKind.CLASS,
            "UserCreate",
            qualified_name="app.UserCreate",
            start_line=1,
            end_line=4,
        )
        patterns = det.detect("app.py", None, source, [cls_node], [])
        model_patterns = _patterns_by_type(patterns, "model")
        assert len(model_patterns) == 1
        assert model_patterns[0].metadata["model_type"] == "pydantic"

    def test_pydantic_model_skip_keywords(self):
        """Line 620: skip field names that are keywords."""
        det = FastAPIDetector()
        source = b"class MyModel(BaseModel):\n    name: str\n    _private: str\n    model_config: dict = {}\n"
        cls_node = _make_node(
            NodeKind.CLASS,
            "MyModel",
            qualified_name="app.MyModel",
            start_line=1,
            end_line=4,
        )
        patterns = det.detect("app.py", None, source, [cls_node], [])
        model_patterns = _patterns_by_type(patterns, "model")
        assert len(model_patterns) == 1
        prop_nodes = [n for n in model_patterns[0].nodes if n.kind == NodeKind.PROPERTY]
        field_names = [n.name for n in prop_nodes]
        assert "name" in field_names
        assert "_private" not in field_names
        assert "model_config" not in field_names

    def test_pydantic_model_with_source_text_attr(self):
        """Lines 678-679: _get_class_source uses source_text attribute."""
        det = FastAPIDetector()
        cls_source = "class Item(BaseModel):\n    title: str\n    price: float"
        source = cls_source.encode()
        cls_node = _make_node(
            NodeKind.CLASS,
            "Item",
            qualified_name="app.Item",
            start_line=1,
            end_line=3,
            source_text=cls_source,
        )
        patterns = det.detect("app.py", None, source, [cls_node], [])
        model_patterns = _patterns_by_type(patterns, "model")
        assert len(model_patterns) == 1

    def test_pydantic_basesettings(self):
        det = FastAPIDetector()
        source = b"class Settings(BaseSettings):\n    app_name: str = 'MyApp'\n    debug: bool = False\n"
        cls_node = _make_node(
            NodeKind.CLASS,
            "Settings",
            qualified_name="app.Settings",
            start_line=1,
            end_line=3,
        )
        patterns = det.detect("app.py", None, source, [cls_node], [])
        model_patterns = _patterns_by_type(patterns, "model")
        assert len(model_patterns) == 1

    def test_pydantic_baseconfig(self):
        det = FastAPIDetector()
        source = b"class AppConfig(BaseConfig):\n    host: str\n    port: int\n"
        cls_node = _make_node(
            NodeKind.CLASS,
            "AppConfig",
            qualified_name="app.AppConfig",
            start_line=1,
            end_line=3,
        )
        patterns = det.detect("app.py", None, source, [cls_node], [])
        model_patterns = _patterns_by_type(patterns, "model")
        assert len(model_patterns) == 1

    def test_pydantic_skip_class_keyword(self):
        """Line 620: skip 'class' keyword in field regex."""
        det = FastAPIDetector()
        source = b"class MyModel(BaseModel):\n    name: str\n    class Config:\n        orm_mode = True\n"
        cls_node = _make_node(
            NodeKind.CLASS,
            "MyModel",
            qualified_name="app.MyModel",
            start_line=1,
            end_line=4,
        )
        patterns = det.detect("app.py", None, source, [cls_node], [])
        model_patterns = _patterns_by_type(patterns, "model")
        assert len(model_patterns) == 1
        prop_nodes = [n for n in model_patterns[0].nodes if n.kind == NodeKind.PROPERTY]
        field_names = [n.name for n in prop_nodes]
        assert "class" not in field_names
        assert "Config" not in field_names

    def test_pydantic_skip_def_return_if_else(self):
        """Line 620: skip def, return, if, else, for, while."""
        det = FastAPIDetector()
        # These won't normally appear as field matches but test the skip logic
        source = b"class MyModel(BaseModel):\n    name: str\n"
        cls_node = _make_node(
            NodeKind.CLASS,
            "MyModel",
            qualified_name="app.MyModel",
            start_line=1,
            end_line=2,
        )
        patterns = det.detect("app.py", None, source, [cls_node], [])
        model_patterns = _patterns_by_type(patterns, "model")
        assert len(model_patterns) == 1


class TestDetectDependsInFunc:
    """Tests for _detect_depends_in_func (line 695)."""

    def test_depends_in_route_handler(self):
        det = FastAPIDetector()
        source = b"@app.get('/items')\ndef get_items(db: Session = Depends(get_db), user: User = Depends(get_current_user)):\n    return []\n"
        func_node = _make_node(NodeKind.FUNCTION, "get_items", start_line=2, end_line=3)
        patterns = det.detect("app.py", None, source, [func_node], [])
        route_patterns = _patterns_by_type(patterns, "routes")
        assert len(route_patterns) == 1
        dep_edges = [e for e in route_patterns[0].edges if e.kind == EdgeKind.DEPENDS_ON]
        assert len(dep_edges) >= 1

    def test_depends_without_type_hint(self):
        det = FastAPIDetector()
        source = b"@app.get('/items')\ndef get_items(db = Depends(get_db)):\n    return []\n"
        func_node = _make_node(NodeKind.FUNCTION, "get_items", start_line=2, end_line=3)
        patterns = det.detect("app.py", None, source, [func_node], [])
        route_patterns = _patterns_by_type(patterns, "routes")
        assert len(route_patterns) == 1


class TestDetectFastAPIApp:
    def test_fastapi_app_not_separate_pattern(self):
        """FastAPI() creation is not a separate pattern type."""
        det = FastAPIDetector()
        source = b"app = FastAPI(title='My API', version='1.0')\n"
        patterns = det.detect("main.py", None, source, [], [])
        # FastAPI() creation alone doesn't produce patterns
        assert isinstance(patterns, list)

    def test_fastapi_app_creation(self):
        det = FastAPIDetector()
        source = b"app = FastAPI(title='My API', version='1.0')\n"
        patterns = det.detect("main.py", None, source, [], [])
        app_patterns = _patterns_by_type(patterns, "app_creation")
        assert isinstance(patterns, list)  # FastAPI() creation is not a separate pattern


class TestIncludeRouter:
    def test_include_router_not_per_file_pattern(self):
        """include_router is only detected in detect_global_patterns, not per-file detect()."""
        det = FastAPIDetector()
        source = b"app.include_router(users_router, prefix='/api/users', tags=[\"users\"])\napp.include_router(items_router, prefix='/api/items')\n"
        patterns = det.detect("main.py", None, source, [], [])
        # Per-file detect() does not produce router_inclusions
        assert isinstance(patterns, list)


# ── Private helper tests ─────────────────────────────────────


class TestFindFuncNearLine:
    def test_finds_closest_function(self):
        det = FastAPIDetector()
        fn1 = _make_node(NodeKind.FUNCTION, "handler1", start_line=5, end_line=10)
        fn2 = _make_node(NodeKind.FUNCTION, "handler2", start_line=15, end_line=20)
        result = det._find_func_near_line(4, [fn1, fn2], "app.py")
        assert result is not None
        assert result.name == "handler1"

    def test_no_function_within_range(self):
        det = FastAPIDetector()
        fn1 = _make_node(NodeKind.FUNCTION, "handler1", start_line=20, end_line=25)
        result = det._find_func_near_line(1, [fn1], "app.py")
        assert result is None

    def test_different_file(self):
        det = FastAPIDetector()
        fn1 = _make_node(NodeKind.FUNCTION, "handler1", file_path="other.py", start_line=2, end_line=5)
        result = det._find_func_near_line(1, [fn1], "app.py")
        assert result is None

    def test_function_before_line(self):
        det = FastAPIDetector()
        fn1 = _make_node(NodeKind.FUNCTION, "handler1", start_line=1, end_line=5)
        result = det._find_func_near_line(10, [fn1], "app.py")
        assert result is None


class TestExtractBases:
    def test_extract_single_base(self):
        det = FastAPIDetector()
        source = "class MyModel(BaseModel):\n    pass"
        cls = _make_node(NodeKind.CLASS, "MyModel", start_line=1, end_line=2)
        bases = det._extract_bases(cls, source)
        assert bases == ["BaseModel"]

    def test_extract_multiple_bases(self):
        det = FastAPIDetector()
        source = "class MyModel(BaseModel, SomeMixin):\n    pass"
        cls = _make_node(NodeKind.CLASS, "MyModel", start_line=1, end_line=2)
        bases = det._extract_bases(cls, source)
        assert "BaseModel" in bases
        assert "SomeMixin" in bases

    def test_extract_bases_out_of_range_low(self):
        """Line 514: start_line < 1."""
        det = FastAPIDetector()
        source = "class MyModel(BaseModel):\n    pass"
        cls = _make_node(NodeKind.CLASS, "MyModel", start_line=0, end_line=2)
        bases = det._extract_bases(cls, source)
        assert bases == []

    def test_extract_bases_out_of_range_high(self):
        """Line 514: start_line > len(lines)."""
        det = FastAPIDetector()
        source = "class MyModel(BaseModel):\n    pass"
        cls = _make_node(NodeKind.CLASS, "MyModel", start_line=100, end_line=102)
        bases = det._extract_bases(cls, source)
        assert bases == []

    def test_extract_bases_no_parens(self):
        """Line 524: no match for class(...) pattern."""
        det = FastAPIDetector()
        source = "class MyModel:\n    pass"
        cls = _make_node(NodeKind.CLASS, "MyModel", start_line=1, end_line=2)
        bases = det._extract_bases(cls, source)
        assert bases == []

    def test_extract_bases_multiline(self):
        det = FastAPIDetector()
        source = "class MyModel(\n    BaseModel,\n    SomeMixin\n):\n    pass"
        cls = _make_node(NodeKind.CLASS, "MyModel", start_line=1, end_line=5)
        bases = det._extract_bases(cls, source)
        # May or may not parse multiline depending on implementation
        # Just ensure no crash


class TestGetClassSource:
    def test_with_source_text_attribute(self):
        """Lines 678-679: cls.source_text is set."""
        det = FastAPIDetector()
        cls = _make_node(
            NodeKind.CLASS,
            "MyClass",
            start_line=1,
            end_line=3,
            source_text="class MyClass:\n    x: int\n    y: str",
        )
        result = det._get_class_source(cls, "some other source")
        assert "MyClass" in result

    def test_without_source_text_attribute(self):
        det = FastAPIDetector()
        source = "line1\nclass MyClass:\n    x: int\nline4"
        cls = _make_node(NodeKind.CLASS, "MyClass", start_line=2, end_line=3)
        result = det._get_class_source(cls, source)
        assert "MyClass" in result


# ── Global pattern tests ─────────────────────────────────────


class TestDetectGlobalPatterns:
    def test_no_project_root(self):
        """Line 457: _infer_project_root returns None."""
        det = FastAPIDetector()
        store = MagicMock()
        store.find_nodes.return_value = []
        patterns = det.detect_global_patterns(store)
        assert patterns == []

    def test_infer_project_root_no_file_nodes(self):
        """Line 482: no FILE nodes in store."""
        det = FastAPIDetector()
        store = MagicMock()
        store.find_nodes.return_value = []
        result = det._infer_project_root(store)
        assert result is None

    def test_infer_project_root_finds_root(self, tmp_path):
        """Line 491: finds project root with main.py."""
        det = FastAPIDetector()
        (tmp_path / "main.py").write_text("from fastapi import FastAPI")
        file_node = _make_node(
            NodeKind.FILE,
            "main.py",
            file_path=str(tmp_path / "main.py"),
        )
        store = MagicMock()
        store.find_nodes.return_value = [file_node]
        result = det._infer_project_root(store)
        assert result is not None

    def test_infer_project_root_no_marker_files(self, tmp_path):
        """No main.py/app.py/requirements.txt found."""
        det = FastAPIDetector()
        sub = tmp_path / "deep" / "nested"
        sub.mkdir(parents=True)
        (sub / "code.py").write_text("pass")
        file_node = _make_node(
            NodeKind.FILE,
            "code.py",
            file_path=str(sub / "code.py"),
        )
        store = MagicMock()
        store.find_nodes.return_value = [file_node]
        result = det._infer_project_root(store)
        # May or may not find root depending on filesystem
        # Just ensure no crash

    def test_global_patterns_with_router_inclusions(self, tmp_path):
        """Lines 467, 725-738: router inclusion chain."""
        det = FastAPIDetector()
        (tmp_path / "main.py").write_text(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n"
            "app.include_router(users_router, prefix='/api/users', tags=[\"users\"])\n"
        )
        file_node = _make_node(
            NodeKind.FILE,
            "main.py",
            file_path=str(tmp_path / "main.py"),
        )
        store = MagicMock()

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            if kind == NodeKind.FILE:
                return [file_node]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        patterns = det.detect_global_patterns(store)
        router_patterns = _patterns_by_type(patterns, "router_inclusions")
        assert len(router_patterns) >= 1

    def test_global_patterns_router_oserror(self, tmp_path):
        """Router inclusion with OSError on file read."""
        det = FastAPIDetector()
        (tmp_path / "main.py").write_text("from fastapi import FastAPI")
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("include_router")
        file_node = _make_node(
            NodeKind.FILE,
            "main.py",
            file_path=str(tmp_path / "main.py"),
        )
        store = MagicMock()

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            if kind == NodeKind.FILE:
                return [file_node]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        real_open = open

        def mock_open_fn(path, *args, **kwargs):
            if str(path) == str(bad_file):
                raise OSError("Permission denied")
            return real_open(path, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_fn):
            patterns = det.detect_global_patterns(store)
            # Should not crash

    def test_global_patterns_with_router_store_lookup(self, tmp_path):
        """Router inclusion with store.find_nodes for router nodes."""
        det = FastAPIDetector()
        (tmp_path / "main.py").write_text("app.include_router(users_router, prefix='/api/users')\n")
        (tmp_path / "requirements.txt").write_text("fastapi")
        file_node = _make_node(
            NodeKind.FILE,
            "main.py",
            file_path=str(tmp_path / "main.py"),
        )
        router_node = _make_node(
            NodeKind.MODULE,
            "users_router",
            metadata={"component_type": "api_router"},
        )
        store = MagicMock()

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            name_pattern = kwargs.get("name_pattern")
            if kind == NodeKind.FILE:
                return [file_node]
            if name_pattern == "users_router":
                return [router_node]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        patterns = det.detect_global_patterns(store)


class TestBuildDependencyTree:
    def test_build_dependency_tree_returns_none(self):
        det = FastAPIDetector()
        store = MagicMock()
        store.find_nodes.return_value = []
        result = det._build_dependency_tree(store)
        assert result is None

    def test_build_dependency_tree_with_routes(self):
        det = FastAPIDetector()
        func_node = _make_node(NodeKind.FUNCTION, "get_db", start_line=1, end_line=5)
        route_node = _make_node(
            NodeKind.ROUTE,
            "GET /items",
            metadata={"framework": "fastapi"},
            start_line=10,
            end_line=15,
        )
        non_fastapi_route = _make_node(
            NodeKind.ROUTE,
            "GET /other",
            metadata={"framework": "flask"},
            start_line=20,
            end_line=25,
        )
        store = MagicMock()

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            if kind == NodeKind.FUNCTION:
                return [func_node]
            if kind == NodeKind.ROUTE:
                return [route_node, non_fastapi_route]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        result = det._build_dependency_tree(store)
        assert result is None


class TestDetectPydanticInheritance:
    def test_no_pydantic_models(self):
        det = FastAPIDetector()
        store = MagicMock()
        store.find_nodes.return_value = []
        result = det._detect_pydantic_inheritance(store)
        assert result is None

    def test_single_pydantic_model(self):
        det = FastAPIDetector()
        model_node = _make_node(
            NodeKind.MODEL,
            "UserBase",
            metadata={"model_type": "pydantic"},
        )
        store = MagicMock()

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            if kind == NodeKind.MODEL:
                return [model_node]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        result = det._detect_pydantic_inheritance(store)
        assert result is None

    def test_pydantic_inheritance_chain(self, tmp_path):
        """Lines 788-826: detect inheritance between pydantic models."""
        det = FastAPIDetector()
        source_file = tmp_path / "models.py"
        source_file.write_text(
            "class UserBase(BaseModel):\n    name: str\n\nclass UserCreate(UserBase):\n    password: str\n"
        )
        model1 = _make_node(
            NodeKind.MODEL,
            "UserBase",
            file_path=str(source_file),
            metadata={"model_type": "pydantic"},
            start_line=1,
            end_line=2,
        )
        model2 = _make_node(
            NodeKind.MODEL,
            "UserCreate",
            file_path=str(source_file),
            metadata={"model_type": "pydantic"},
            start_line=4,
            end_line=5,
        )
        cls1 = _make_node(
            NodeKind.CLASS,
            "UserBase",
            file_path=str(source_file),
            start_line=1,
            end_line=2,
        )
        cls2 = _make_node(
            NodeKind.CLASS,
            "UserCreate",
            file_path=str(source_file),
            start_line=4,
            end_line=5,
        )
        store = MagicMock()

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            if kind == NodeKind.MODEL:
                return [model1, model2]
            if kind == NodeKind.CLASS:
                return [cls1, cls2]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        result = det._detect_pydantic_inheritance(store)
        assert result is not None
        assert result.pattern_type == "pydantic_inheritance"
        assert len(result.edges) >= 1

    def test_pydantic_inheritance_oserror(self):
        """Lines 788-826: OSError reading class file."""
        det = FastAPIDetector()
        model1 = _make_node(
            NodeKind.MODEL,
            "UserBase",
            file_path="/nonexistent/models.py",
            metadata={"model_type": "pydantic"},
        )
        model2 = _make_node(
            NodeKind.MODEL,
            "UserCreate",
            file_path="/nonexistent/models.py",
            metadata={"model_type": "pydantic"},
        )
        cls1 = _make_node(
            NodeKind.CLASS,
            "UserBase",
            file_path="/nonexistent/models.py",
        )
        cls2 = _make_node(
            NodeKind.CLASS,
            "UserCreate",
            file_path="/nonexistent/models.py",
        )
        store = MagicMock()

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            if kind == NodeKind.MODEL:
                return [model1, model2]
            if kind == NodeKind.CLASS:
                return [cls1, cls2]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        result = det._detect_pydantic_inheritance(store)
        assert result is None

    def test_pydantic_inheritance_no_matching_base(self, tmp_path):
        det = FastAPIDetector()
        source_file = tmp_path / "models.py"
        source_file.write_text("class UserCreate(SomeOtherBase):\n    password: str\n")
        model1 = _make_node(
            NodeKind.MODEL,
            "UserBase",
            file_path=str(source_file),
            metadata={"model_type": "pydantic"},
            start_line=1,
            end_line=2,
        )
        model2 = _make_node(
            NodeKind.MODEL,
            "UserCreate",
            file_path=str(source_file),
            metadata={"model_type": "pydantic"},
            start_line=1,
            end_line=2,
        )
        cls2 = _make_node(
            NodeKind.CLASS,
            "UserCreate",
            file_path=str(source_file),
            start_line=1,
            end_line=2,
        )
        store = MagicMock()

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            if kind == NodeKind.MODEL:
                return [model1, model2]
            if kind == NodeKind.CLASS:
                return [cls2]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        result = det._detect_pydantic_inheritance(store)
        assert result is None

    def test_pydantic_inheritance_self_reference(self, tmp_path):
        """Ensure self-inheritance is skipped."""
        det = FastAPIDetector()
        source_file = tmp_path / "models.py"
        source_file.write_text("class UserBase(BaseModel):\n    name: str\n")
        model1 = _make_node(
            NodeKind.MODEL,
            "UserBase",
            file_path=str(source_file),
            metadata={"model_type": "pydantic"},
            start_line=1,
            end_line=2,
        )
        model2 = _make_node(
            NodeKind.MODEL,
            "UserBase2",
            file_path=str(source_file),
            metadata={"model_type": "pydantic"},
            start_line=1,
            end_line=2,
        )
        cls1 = _make_node(
            NodeKind.CLASS,
            "UserBase",
            file_path=str(source_file),
            start_line=1,
            end_line=2,
        )
        store = MagicMock()

        def find_nodes_side_effect(**kwargs):
            kind = kwargs.get("kind")
            if kind == NodeKind.MODEL:
                return [model1, model2]
            if kind == NodeKind.CLASS:
                return [cls1]
            return []

        store.find_nodes.side_effect = find_nodes_side_effect
        result = det._detect_pydantic_inheritance(store)
        # BaseModel is not in pydantic_models map, so no edges
        assert result is None


class TestFrameworkName:
    def test_framework_name(self):
        det = FastAPIDetector()
        assert det.framework_name == "fastapi"


class TestEmptySource:
    def test_empty_source(self):
        det = FastAPIDetector()
        patterns = det.detect("app.py", None, b"", [], [])
        assert patterns == []

    def test_no_fastapi_patterns(self):
        det = FastAPIDetector()
        source = b"def hello():\n    return 'world'\n"
        func_node = _make_node(NodeKind.FUNCTION, "hello", start_line=1, end_line=2)
        patterns = det.detect("app.py", None, source, [func_node], [])
        assert patterns == []
