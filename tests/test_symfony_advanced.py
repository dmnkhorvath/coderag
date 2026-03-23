"""Tests for the 14 new Symfony edge types.

Covers: doctrine_maps_to, twig_extends, twig_includes, twig_embeds,
twig_imports_macro, renders_controller, references_route,
form_maps_entity, form_field_maps, voter_protects, validates_with,
bundle_provides, stimulus_controls, asset_references.
"""

from __future__ import annotations

import pytest

from coderag.core.models import EdgeKind, Node, NodeKind, generate_node_id
from coderag.plugins.php.frameworks.symfony import SymfonyDetector


@pytest.fixture
def detector() -> SymfonyDetector:
    return SymfonyDetector()


def _make_class_node(file_path: str, name: str, start: int = 1, end: int = 50) -> Node:
    return Node(
        id=generate_node_id(file_path, start, NodeKind.CLASS, name),
        kind=NodeKind.CLASS,
        name=name,
        qualified_name=f"App\\Entity\\{name}",
        file_path=file_path,
        start_line=start,
        end_line=end,
        language="php",
        metadata={},
    )


def _edges_of_type(patterns, edge_type: str):
    return [e for p in patterns for e in p.edges if e.metadata.get("symfony_edge_type") == edge_type]


# =========================================================================
# 1. doctrine_maps_to
# =========================================================================


class TestDoctrineMapsto:
    """Entity maps to database table."""

    def test_explicit_table_name(self, detector: SymfonyDetector) -> None:
        src = (
            b"<?php\n"
            b"namespace App\\Entity;\n\n"
            b"use Doctrine\\ORM\\Mapping as ORM;\n\n"
            b"#[ORM\\Entity]\n"
            b"#[ORM\\Table(name: 'users')]\n"
            b"class User\n{\n"
            b"    #[ORM\\Id]\n"
            b"    #[ORM\\Column]\n"
            b"    private int $id;\n"
            b"}\n"
        )
        fp = "src/Entity/User.php"
        nodes = [_make_class_node(fp, "User")]
        patterns = detector.detect(fp, None, src, nodes, [])
        edges = _edges_of_type(patterns, "doctrine_maps_to")
        assert len(edges) >= 1
        assert edges[0].metadata["table_name"] == "users"
        assert edges[0].kind == EdgeKind.DEPENDS_ON
        assert edges[0].confidence == 0.95

    def test_convention_table_name(self, detector: SymfonyDetector) -> None:
        src = (
            b"<?php\n"
            b"namespace App\\Entity;\n\n"
            b"use Doctrine\\ORM\\Mapping as ORM;\n\n"
            b"#[ORM\\Entity]\n"
            b"class BlogPost\n{\n"
            b"    #[ORM\\Id]\n"
            b"    #[ORM\\Column]\n"
            b"    private int $id;\n"
            b"}\n"
        )
        fp = "src/Entity/BlogPost.php"
        nodes = [_make_class_node(fp, "BlogPost")]
        patterns = detector.detect(fp, None, src, nodes, [])
        edges = _edges_of_type(patterns, "doctrine_maps_to")
        assert len(edges) >= 1
        assert edges[0].metadata["table_name"] == "blog_post"


# =========================================================================
# 2-7. Twig template patterns
# =========================================================================


class TestTwigExtends:
    def test_extends_detected(self, detector: SymfonyDetector) -> None:
        src = b"{% extends 'base.html.twig' %}\n{% block body %}<h1>Hello</h1>{% endblock %}"
        fp = "templates/page.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        edges = _edges_of_type(patterns, "twig_extends")
        assert len(edges) == 1
        assert edges[0].metadata["target_template"] == "base.html.twig"
        assert edges[0].kind == EdgeKind.DEPENDS_ON
        assert edges[0].confidence == 0.98


class TestTwigIncludes:
    def test_include_detected(self, detector: SymfonyDetector) -> None:
        src = b"{% include 'partials/header.html.twig' %}\n<div>Content</div>"
        fp = "templates/page.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        edges = _edges_of_type(patterns, "twig_includes")
        assert len(edges) == 1
        assert edges[0].metadata["target_template"] == "partials/header.html.twig"
        assert edges[0].confidence == 0.98


class TestTwigEmbeds:
    def test_embed_detected(self, detector: SymfonyDetector) -> None:
        src = b"{% embed 'components/card.html.twig' %}\n{% block title %}My Card{% endblock %}\n{% endembed %}"
        fp = "templates/page.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        edges = _edges_of_type(patterns, "twig_embeds")
        assert len(edges) == 1
        assert edges[0].metadata["target_template"] == "components/card.html.twig"
        assert edges[0].confidence == 0.98


class TestTwigImportsMacro:
    def test_macro_import_detected(self, detector: SymfonyDetector) -> None:
        src = b"{% from 'macros/forms.html.twig' import input, button %}\n{{ input('email') }}"
        fp = "templates/page.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        edges = _edges_of_type(patterns, "twig_imports_macro")
        assert len(edges) == 1
        assert edges[0].metadata["target_template"] == "macros/forms.html.twig"
        assert edges[0].kind == EdgeKind.IMPORTS
        assert edges[0].confidence == 0.95


class TestRendersController:
    def test_render_controller_detected(self, detector: SymfonyDetector) -> None:
        src = b"<div>{{ render(controller('App\\\\Controller\\\\HeaderController::index')) }}</div>"
        fp = "templates/base.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        edges = _edges_of_type(patterns, "renders_controller")
        assert len(edges) == 1
        assert "HeaderController" in edges[0].metadata["controller"]
        assert edges[0].kind == EdgeKind.RENDERS
        assert edges[0].confidence == 0.90


class TestReferencesRoute:
    def test_path_function_detected(self, detector: SymfonyDetector) -> None:
        src = b"<a href=\"{{ path('app_login') }}\">Login</a>\n<a href=\"{{ url('app_home') }}\">Home</a>"
        fp = "templates/nav.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        edges = _edges_of_type(patterns, "references_route")
        assert len(edges) == 2
        route_names = {e.metadata["route_name"] for e in edges}
        assert "app_login" in route_names
        assert "app_home" in route_names
        assert edges[0].confidence == 0.95


# =========================================================================
# 8-9. Form patterns
# =========================================================================


class TestFormMapsEntity:
    def test_data_class_detected(self, detector: SymfonyDetector) -> None:
        src = (
            b"<?php\n"
            b"namespace App\\Form;\n\n"
            b"use Symfony\\Component\\Form\\AbstractType;\n"
            b"use Symfony\\Component\\Form\\FormBuilderInterface;\n"
            b"use Symfony\\Component\\OptionsResolver\\OptionsResolver;\n"
            b"use App\\Entity\\User;\n\n"
            b"class UserType extends AbstractType\n{\n"
            b"    public function buildForm(FormBuilderInterface $builder, array $options): void\n"
            b"    {\n"
            b"        $builder->add('username')\n"
            b"                ->add('email')\n"
            b"                ->add('password');\n"
            b"    }\n\n"
            b"    public function configureOptions(OptionsResolver $resolver): void\n"
            b"    {\n"
            b"        $resolver->setDefaults(['data_class' => User::class]);\n"
            b"    }\n"
            b"}\n"
        )
        fp = "src/Form/UserType.php"
        nodes = [_make_class_node(fp, "UserType")]
        patterns = detector.detect(fp, None, src, nodes, [])
        entity_edges = _edges_of_type(patterns, "form_maps_entity")
        field_edges = _edges_of_type(patterns, "form_field_maps")
        assert len(entity_edges) == 1
        assert entity_edges[0].metadata["entity_class"] == "User"
        assert entity_edges[0].confidence == 0.95
        assert len(field_edges) == 3
        field_names = {e.metadata["field_name"] for e in field_edges}
        assert field_names == {"username", "email", "password"}


# =========================================================================
# 10. voter_protects
# =========================================================================


class TestVoterProtects:
    def test_voter_instanceof_detected(self, detector: SymfonyDetector) -> None:
        src = (
            b"<?php\n"
            b"namespace App\\Security;\n\n"
            b"use Symfony\\Component\\Security\\Core\\Authorization\\Voter\\Voter;\n"
            b"use App\\Entity\\Post;\n\n"
            b"class PostVoter extends Voter\n{\n"
            b"    protected function supports(string $attribute, mixed $subject): bool\n"
            b"    {\n"
            b"        return $subject instanceof Post;\n"
            b"    }\n\n"
            b"    protected function voteOnAttribute(string $attribute, mixed $subject, TokenInterface $token): bool\n"
            b"    {\n"
            b"        return true;\n"
            b"    }\n"
            b"}\n"
        )
        fp = "src/Security/PostVoter.php"
        nodes = [_make_class_node(fp, "PostVoter")]
        patterns = detector.detect(fp, None, src, nodes, [])
        edges = _edges_of_type(patterns, "voter_protects")
        assert len(edges) >= 1
        assert edges[0].metadata["entity_class"] == "Post"
        assert edges[0].confidence == 0.85


# =========================================================================
# 11. validates_with
# =========================================================================


class TestValidatesWith:
    def test_assert_attributes_detected(self, detector: SymfonyDetector) -> None:
        src = (
            b"<?php\n"
            b"namespace App\\Entity;\n\n"
            b"use Symfony\\Component\\Validator\\Constraints as Assert;\n"
            b"use Doctrine\\ORM\\Mapping as ORM;\n\n"
            b"#[ORM\\Entity]\n"
            b"class User\n{\n"
            b"    #[Assert\\NotBlank]\n"
            b"    #[Assert\\Length(min: 3, max: 50)]\n"
            b"    private string $username;\n\n"
            b"    #[Assert\\Email]\n"
            b"    private string $email;\n"
            b"}\n"
        )
        fp = "src/Entity/User.php"
        nodes = [_make_class_node(fp, "User")]
        patterns = detector.detect(fp, None, src, nodes, [])
        edges = _edges_of_type(patterns, "validates_with")
        assert len(edges) == 3
        constraints = {e.metadata["constraint"] for e in edges}
        assert constraints == {"NotBlank", "Length", "Email"}
        assert all(e.confidence == 0.95 for e in edges)


# =========================================================================
# 12. bundle_provides
# =========================================================================


class TestBundleProvides:
    def test_bundle_class_detected(self, detector: SymfonyDetector) -> None:
        src = (
            b"<?php\n"
            b"namespace App;\n\n"
            b"use Symfony\\Component\\HttpKernel\\Bundle\\AbstractBundle;\n\n"
            b"class AppBundle extends AbstractBundle\n{\n"
            b"}\n"
        )
        fp = "src/AppBundle.php"
        nodes = [_make_class_node(fp, "AppBundle")]
        patterns = detector.detect(fp, None, src, nodes, [])
        edges = _edges_of_type(patterns, "bundle_provides")
        assert len(edges) == 1
        assert edges[0].confidence == 0.90


# =========================================================================
# 13. stimulus_controls
# =========================================================================


class TestStimulusControls:
    def test_data_controller_detected(self, detector: SymfonyDetector) -> None:
        src = b'<div data-controller="hello dropdown">\n    <button data-action="click->hello#greet">Greet</button>\n</div>'
        fp = "templates/page.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        edges = _edges_of_type(patterns, "stimulus_controls")
        assert len(edges) == 2
        ctrl_names = {e.metadata["controller_name"] for e in edges}
        assert "hello" in ctrl_names
        assert "dropdown" in ctrl_names
        assert all(e.confidence == 0.90 for e in edges)

    def test_stimulus_function_detected(self, detector: SymfonyDetector) -> None:
        src = b"{{ stimulus_controller('chart') }}"
        fp = "templates/page.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        edges = _edges_of_type(patterns, "stimulus_controls")
        assert len(edges) >= 1
        assert edges[0].metadata["controller_name"] == "chart"


# =========================================================================
# 14. asset_references
# =========================================================================


class TestAssetReferences:
    def test_encore_tags_detected(self, detector: SymfonyDetector) -> None:
        src = b"{{ encore_entry_link_tags('app') }}\n{{ encore_entry_script_tags('app') }}"
        fp = "templates/base.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        edges = _edges_of_type(patterns, "asset_references")
        assert len(edges) == 2
        assert all(e.metadata["asset_entry"] == "app" for e in edges)
        assert all(e.metadata["bundler"] == "encore" for e in edges)
        assert all(e.confidence == 0.85 for e in edges)

    def test_vite_tags_detected(self, detector: SymfonyDetector) -> None:
        src = b"{{ vite_entry_link_tags('app') }}\n{{ vite_entry_script_tags('styles') }}"
        fp = "templates/base.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        edges = _edges_of_type(patterns, "asset_references")
        assert len(edges) == 2
        entries = {e.metadata["asset_entry"] for e in edges}
        assert entries == {"app", "styles"}
        assert all(e.metadata["bundler"] == "vite" for e in edges)


# =========================================================================
# Combined: Twig file with multiple patterns
# =========================================================================


class TestTwigCombined:
    def test_multiple_patterns_in_one_template(self, detector: SymfonyDetector) -> None:
        src = (
            b"{% extends 'base.html.twig' %}\n"
            b"{% include 'partials/nav.html.twig' %}\n"
            b"{% from 'macros/forms.html.twig' import input %}\n"
            b"{% block body %}\n"
            b"<a href=\"{{ path('app_home') }}\">Home</a>\n"
            b"{{ encore_entry_script_tags('app') }}\n"
            b'<div data-controller="modal">Content</div>\n'
            b"{% endblock %}"
        )
        fp = "templates/page.html.twig"
        patterns = detector.detect(fp, None, src, [], [])
        all_edges = [e for p in patterns for e in p.edges]
        edge_types = {e.metadata.get("symfony_edge_type") for e in all_edges}
        assert "twig_extends" in edge_types
        assert "twig_includes" in edge_types
        assert "twig_imports_macro" in edge_types
        assert "references_route" in edge_types
        assert "asset_references" in edge_types
        assert "stimulus_controls" in edge_types


# =========================================================================
# Edge case: Non-twig, non-php files should be ignored
# =========================================================================


class TestFileTypeFiltering:
    def test_js_file_ignored(self, detector: SymfonyDetector) -> None:
        src = b"console.log('hello');"
        patterns = detector.detect("app.js", None, src, [], [])
        assert patterns == []

    def test_twig_file_processed(self, detector: SymfonyDetector) -> None:
        src = b"{% extends 'base.html.twig' %}"
        patterns = detector.detect("templates/page.html.twig", None, src, [], [])
        assert len(patterns) >= 1

    def test_php_file_still_works(self, detector: SymfonyDetector) -> None:
        src = (
            b"<?php\n"
            b"namespace App\\Controller;\n\n"
            b"use Symfony\\Bundle\\FrameworkBundle\\Controller\\AbstractController;\n"
            b"use Symfony\\Component\\Routing\\Attribute\\Route;\n\n"
            b"class HomeController extends AbstractController\n{\n"
            b"    #[Route('/', name: 'app_home')]\n"
            b"    public function index()\n"
            b"    {\n"
            b"        return $this->render('home/index.html.twig');\n"
            b"    }\n"
            b"}\n"
        )
        fp = "src/Controller/HomeController.php"
        nodes = [_make_class_node(fp, "HomeController")]
        patterns = detector.detect(fp, None, src, nodes, [])
        assert len(patterns) >= 1
