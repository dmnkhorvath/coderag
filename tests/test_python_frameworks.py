import os
import pytest
from unittest.mock import MagicMock, patch
from coderag.core.models import Node, NodeKind, Edge, EdgeKind, FrameworkPattern
from coderag.plugins.python.frameworks.flask import FlaskDetector
from coderag.plugins.python.frameworks.fastapi import FastAPIDetector
from coderag.plugins.python.frameworks.django import DjangoDetector

@pytest.fixture
def flask_detector():
    return FlaskDetector()

@pytest.fixture
def fastapi_detector():
    return FastAPIDetector()

@pytest.fixture
def django_detector():
    return DjangoDetector()

def test_flask_detect_framework_oserror(flask_detector, tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.touch()
    req_file.chmod(0o000)

    app_file = tmp_path / "app.py"
    app_file.touch()
    app_file.chmod(0o000)

    assert flask_detector.detect_framework(str(tmp_path)) is False

    req_file.chmod(0o644)
    app_file.chmod(0o644)

def test_flask_detect_extensions_and_templates(flask_detector):
    source = b'''
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
db = SQLAlchemy(app)

@app.route('/')
def index():
    return render_template('index.html')
'''
    patterns = flask_detector.detect("app.py", None, source, [], [])

    ext_patterns = [p for p in patterns if p.pattern_type == "extension"]
    assert len(ext_patterns) > 0
    assert ext_patterns[0].metadata["extension_name"] == "SQLAlchemy"
    assert ext_patterns[0].metadata["variable_name"] == "db"

    tpl_patterns = [p for p in patterns if p.pattern_type == "templates"]
    assert len(tpl_patterns) > 0
    assert "index.html" in tpl_patterns[0].metadata["templates"]

def test_flask_global_patterns(flask_detector, tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    app_file = app_dir / "app.py"
    app_file.write_text('''
from flask import Flask
from .views import bp

app = Flask(__name__)
app.register_blueprint(bp, url_prefix='/api')
''')

    store = MagicMock()
    file_node = Node(id="1", kind=NodeKind.FILE, name="app.py", qualified_name="app.py", file_path=str(app_file), start_line=1, end_line=1, language="python")
    bp_node = Node(id="2", kind=NodeKind.MODULE, name="bp", qualified_name="views.bp", file_path=str(app_dir / "views.py"), start_line=1, end_line=1, language="python", metadata={"component_type": "blueprint"})

    def mock_find_nodes(**kwargs):
        if kwargs.get("kind") == NodeKind.FILE:
            return [file_node]
        if kwargs.get("kind") == NodeKind.MODULE and kwargs.get("name_pattern") == "bp":
            return [bp_node]
        return []

    store.find_nodes.side_effect = mock_find_nodes

    patterns = flask_detector.detect_global_patterns(store)
    assert len(patterns) > 0
    assert patterns[0].pattern_type == "blueprint_registrations"
    assert len(patterns[0].nodes) == 1
    assert patterns[0].nodes[0].metadata["blueprint_variable"] == "bp"
    assert patterns[0].nodes[0].metadata["url_prefix"] == "/api"
    assert len(patterns[0].edges) == 1
    assert patterns[0].edges[0].target_id == "2"

def test_fastapi_detect_framework_oserror(fastapi_detector, tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.touch()
    req_file.chmod(0o000)

    app_file = tmp_path / "main.py"
    app_file.touch()
    app_file.chmod(0o000)

    assert fastapi_detector.detect_framework(str(tmp_path)) is False

    req_file.chmod(0o644)
    app_file.chmod(0o644)

def test_fastapi_detect_patterns(fastapi_detector):
    source = b'''
from fastapi import FastAPI, Depends, APIRouter
from pydantic import BaseModel, BaseSettings

class Settings(BaseSettings):
    app_name: str = "API"

class User(BaseModel):
    name: str

app = FastAPI()
router = APIRouter()

def get_db():
    pass

@app.get("/users", response_model=User)
def get_users(db = Depends(get_db)):
    pass

app.include_router(router)
'''
    nodes = [
        Node(id="1", kind=NodeKind.CLASS, name="Settings", qualified_name="Settings", file_path="main.py", start_line=4, end_line=5, language="python"),
        Node(id="2", kind=NodeKind.CLASS, name="User", qualified_name="User", file_path="main.py", start_line=7, end_line=8, language="python"),
        Node(id="3", kind=NodeKind.FUNCTION, name="get_users", qualified_name="get_users", file_path="main.py", start_line=16, end_line=18, language="python")
    ]

    patterns = fastapi_detector.detect("main.py", None, source, nodes, [])

    model_patterns = [p for p in patterns if p.pattern_type == "model"]
    assert len(model_patterns) > 0

    route_patterns = [p for p in patterns if p.pattern_type == "routes"]
    assert len(route_patterns) > 0
    assert route_patterns[0].nodes[0].metadata["url_pattern"] == "/users"

    router_patterns = [p for p in patterns if p.pattern_type == "api_router"]
    assert len(router_patterns) > 0

def test_fastapi_global_patterns(fastapi_detector, tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    app_file = app_dir / "main.py"
    app_file.write_text('''
from fastapi import FastAPI
from .routers import users

app = FastAPI()
app.include_router(users.router, prefix="/users")
''')

    store = MagicMock()
    file_node = Node(id="1", kind=NodeKind.FILE, name="main.py", qualified_name="main.py", file_path=str(app_file), start_line=1, end_line=1, language="python")
    router_node = Node(id="2", kind=NodeKind.MODULE, name="router", qualified_name="users.router", file_path=str(app_dir / "routers.py"), start_line=1, end_line=1, language="python", metadata={"component_type": "router"})

    def mock_find_nodes(**kwargs):
        if kwargs.get("kind") == NodeKind.FILE:
            return [file_node]
        if kwargs.get("kind") == NodeKind.MODULE and kwargs.get("name_pattern") == "users.router":
            return [router_node]
        return []

    store.find_nodes.side_effect = mock_find_nodes

    patterns = fastapi_detector.detect_global_patterns(store)
    assert len(patterns) > 0

def test_django_detect_framework_oserror(django_detector, tmp_path):
    req_file = tmp_path / "requirements.txt"
    req_file.touch()
    req_file.chmod(0o000)

    app_file = tmp_path / "manage.py"
    app_file.touch()
    app_file.chmod(0o000)

    assert django_detector.detect_framework(str(tmp_path)) is False

    req_file.chmod(0o644)
    app_file.chmod(0o644)

def test_django_detect_patterns(django_detector):
    source = b'''
from django.db import models
from django.urls import path
from rest_framework import serializers, viewsets
from django.core.management.base import BaseCommand
from django.dispatch import receiver
from django.contrib import admin

class MyModel(models.Model):
    name = models.CharField(max_length=100)
    other = models.ForeignKey('OtherModel', on_delete=models.CASCADE)

class MySerializer(serializers.ModelSerializer):
    class Meta:
        model = MyModel

class MyViewSet(viewsets.ModelViewSet):
    queryset = MyModel.objects.all()

urlpatterns = [
    path('api/', include('api.urls')),
    path('items/', MyViewSet.as_view({'get': 'list'})),
]

@receiver(post_save, sender=MyModel)
def my_handler(sender, **kwargs):
    pass

@admin.register(MyModel)
class MyModelAdmin(admin.ModelAdmin):
    pass

class Command(BaseCommand):
    def handle(self, *args, **options):
        pass
'''
    nodes = [
        Node(id="1", kind=NodeKind.CLASS, name="MyModel", qualified_name="MyModel", file_path="app.py", start_line=8, end_line=10, language="python"),
        Node(id="2", kind=NodeKind.CLASS, name="MySerializer", qualified_name="MySerializer", file_path="app.py", start_line=12, end_line=14, language="python"),
        Node(id="3", kind=NodeKind.CLASS, name="MyViewSet", qualified_name="MyViewSet", file_path="app.py", start_line=16, end_line=17, language="python"),
        Node(id="4", kind=NodeKind.FUNCTION, name="my_handler", qualified_name="my_handler", file_path="app.py", start_line=25, end_line=26, language="python"),
        Node(id="5", kind=NodeKind.CLASS, name="MyModelAdmin", qualified_name="MyModelAdmin", file_path="app.py", start_line=29, end_line=30, language="python"),
        Node(id="6", kind=NodeKind.CLASS, name="Command", qualified_name="Command", file_path="app.py", start_line=32, end_line=34, language="python"),
    ]

    patterns = django_detector.detect("app.py", None, source, nodes, [])

    model_patterns = [p for p in patterns if p.pattern_type == "model"]
    assert len(model_patterns) > 0

    drf_patterns = [p for p in patterns if p.pattern_type == "serializer"]
    assert len(drf_patterns) > 0

    view_patterns = [p for p in patterns if p.pattern_type == "controller"]
    assert len(view_patterns) > 0

    url_patterns = [p for p in patterns if p.pattern_type == "routes"]
    assert len(url_patterns) > 0

    signal_patterns = [p for p in patterns if p.pattern_type == "signal"]
    assert len(signal_patterns) > 0

    admin_patterns = [p for p in patterns if p.pattern_type == "admin"]
    assert len(admin_patterns) > 0

    cmd_patterns = [p for p in patterns if p.pattern_type == "management_command"]
    assert len(cmd_patterns) > 0

def test_django_global_patterns(django_detector, tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    app_file = app_dir / "urls.py"
    app_file.write_text('''
from django.urls import path, include

urlpatterns = [
    path('api/', include('api.urls')),
]
''')

    store = MagicMock()
    file_node = Node(id="1", kind=NodeKind.FILE, name="urls.py", qualified_name="urls.py", file_path=str(app_file), start_line=1, end_line=1, language="python")

    def mock_find_nodes(**kwargs):
        if kwargs.get("kind") == NodeKind.FILE:
            return [file_node]
        return []

    store.find_nodes.side_effect = mock_find_nodes

    patterns = django_detector.detect_global_patterns(store)
    assert isinstance(patterns, list)
