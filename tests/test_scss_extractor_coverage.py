"""Targeted tests for SCSS extractor coverage."""

import pytest

from coderag.core.models import EdgeKind, NodeKind
from coderag.plugins.scss.extractor import SCSSExtractor


@pytest.fixture
def ext():
    return SCSSExtractor()


def _nodes_by_kind(result, kind):
    return [n for n in result.nodes if n.kind == kind]


def _edges_by_kind(result, kind):
    return [e for e in result.edges if e.kind == kind]


def _unresolved_by_kind(result, kind):
    return [u for u in result.unresolved_references if u.reference_kind == kind]


class TestUseNamespace:
    def test_use_as_namespace(self, ext):
        source = b"@use 'abstracts/variables' as vars;\n.container { color: vars.$primary; }\n"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"
        assert result.language == "scss"

    def test_use_as_star(self, ext):
        source = b"@use 'mixins' as *;\n"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"

    def test_use_with_scss_extension(self, ext):
        source = b"@use 'base/_reset.scss' as reset;\n"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"


class TestForward:
    def test_forward_statement(self, ext):
        source = b"@forward 'variables';\n@forward 'mixins';\n"
        result = ext.extract("_index.scss", source)
        imports = _nodes_by_kind(result, NodeKind.IMPORT)
        assert len(imports) >= 2
        fwd_refs = _unresolved_by_kind(result, EdgeKind.SCSS_FORWARDS)
        assert len(fwd_refs) >= 2

    def test_forward_no_path(self, ext):
        source = b"@forward;\n"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"


class TestImport:
    def test_import_url(self, ext):
        source = b"@import url('https://fonts.googleapis.com/css2?family=Roboto');\n"
        result = ext.extract("style.scss", source)
        imports = _nodes_by_kind(result, NodeKind.IMPORT)
        assert len(imports) >= 1

    def test_import_string(self, ext):
        source = b"@import 'variables';\n@import 'mixins';\n"
        result = ext.extract("style.scss", source)
        imports = _nodes_by_kind(result, NodeKind.IMPORT)
        assert len(imports) >= 2

    def test_css_import_with_media(self, ext):
        source = b"@import 'print.css' print;\n"
        result = ext.extract("style.scss", source)
        imports = _nodes_by_kind(result, NodeKind.IMPORT)
        assert len(imports) >= 1


class TestClassSelectors:
    def test_basic_class(self, ext):
        source = b".container { width: 100%; }\n"
        result = ext.extract("style.scss", source)
        classes = _nodes_by_kind(result, NodeKind.CSS_CLASS)
        assert any(n.name == ".container" for n in classes)

    def test_nesting_ampersand(self, ext):
        source = b".btn {\n  &__icon { display: block; }\n  &:hover { color: red; }\n}\n"
        result = ext.extract("style.scss", source)
        classes = _nodes_by_kind(result, NodeKind.CSS_CLASS)
        assert any(n.name == ".btn" for n in classes)

    def test_id_selector(self, ext):
        source = b"#main-content { padding: 20px; }\n"
        result = ext.extract("style.scss", source)
        ids = _nodes_by_kind(result, NodeKind.CSS_ID)
        assert any(n.name == "#main-content" for n in ids)

    def test_multiple_selectors_in_rule(self, ext):
        source = b".foo, .bar, #baz { color: red; }\n"
        result = ext.extract("style.scss", source)
        classes = _nodes_by_kind(result, NodeKind.CSS_CLASS)
        ids = _nodes_by_kind(result, NodeKind.CSS_ID)
        assert len(classes) >= 2
        assert len(ids) >= 1


class TestPlaceholders:
    def test_placeholder_definition(self, ext):
        src = b"%clearfix {\n  &::after {\n    content: '';\n    display: table;\n    clear: both;\n  }\n}\n"
        result = ext.extract("style.scss", src)
        placeholders = _nodes_by_kind(result, NodeKind.SCSS_PLACEHOLDER)
        assert len(placeholders) >= 1

    def test_placeholder_no_name(self, ext):
        source = b"% { color: red; }\n"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"


class TestVariables:
    def test_variable_definition(self, ext):
        source = b"$primary-color: #333;\n$font-size: 16px;\n"
        result = ext.extract("_variables.scss", source)
        vars_ = _nodes_by_kind(result, NodeKind.SCSS_VARIABLE)
        assert len(vars_) >= 2

    def test_variable_usage(self, ext):
        source = b"$primary: blue;\n.btn { color: $primary; }\n"
        result = ext.extract("style.scss", source)
        var_edges = _edges_by_kind(result, EdgeKind.SCSS_USES_VARIABLE)
        var_refs = _unresolved_by_kind(result, EdgeKind.SCSS_USES_VARIABLE)
        assert len(var_edges) + len(var_refs) >= 1

    def test_namespaced_variable(self, ext):
        source = b"@use 'vars' as v;\n.btn { color: v.$primary; }\n"
        result = ext.extract("style.scss", source)
        var_edges = _edges_by_kind(result, EdgeKind.SCSS_USES_VARIABLE)
        var_refs = _unresolved_by_kind(result, EdgeKind.SCSS_USES_VARIABLE)
        assert len(var_edges) + len(var_refs) >= 1

    def test_css_var_reference(self, ext):
        source = b".btn { color: var(--primary-color); }\n"
        result = ext.extract("style.scss", source)
        var_refs = _unresolved_by_kind(result, EdgeKind.CSS_USES_VARIABLE)
        assert len(var_refs) >= 1


class TestMixins:
    def test_mixin_definition(self, ext):
        src = b"@mixin flex-center($direction: row) {\n  display: flex;\n  justify-content: center;\n  align-items: center;\n  flex-direction: $direction;\n}\n"
        result = ext.extract("_mixins.scss", src)
        mixins = _nodes_by_kind(result, NodeKind.SCSS_MIXIN)
        assert len(mixins) >= 1
        assert any("flex-center" in n.name for n in mixins)

    def test_include_mixin(self, ext):
        src = b".container {\n  @include flex-center;\n  @include responsive(md);\n}\n"
        result = ext.extract("style.scss", src)
        includes = _unresolved_by_kind(result, EdgeKind.SCSS_INCLUDES_MIXIN)
        inc_edges = _edges_by_kind(result, EdgeKind.SCSS_INCLUDES_MIXIN)
        assert len(includes) + len(inc_edges) >= 2

    def test_mixin_no_name(self, ext):
        source = b"@mixin { display: block; }\n"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"

    def test_include_no_name(self, ext):
        source = b".x { @include; }\n"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"


class TestFunctions:
    def test_function_definition(self, ext):
        src = b"@function rem($px) {\n  @return $px / 16 * 1rem;\n}\n"
        result = ext.extract("_functions.scss", src)
        funcs = _nodes_by_kind(result, NodeKind.SCSS_FUNCTION)
        assert len(funcs) >= 1

    def test_function_call(self, ext):
        source = b".text { font-size: rem(14); }\n"
        result = ext.extract("style.scss", source)
        fn_refs = _unresolved_by_kind(result, EdgeKind.SCSS_USES_FUNCTION)
        fn_edges = _edges_by_kind(result, EdgeKind.SCSS_USES_FUNCTION)
        assert len(fn_refs) + len(fn_edges) >= 1

    def test_builtin_function_var(self, ext):
        source = b".btn { color: var(--accent); }\n"
        result = ext.extract("style.scss", source)
        css_refs = _unresolved_by_kind(result, EdgeKind.CSS_USES_VARIABLE)
        assert len(css_refs) >= 1

    def test_function_no_name(self, ext):
        source = b"@function { @return 1; }\n"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"


class TestExtend:
    def test_extend_class(self, ext):
        src = b".error {\n  border: 1px solid red;\n}\n.serious-error {\n  @extend .error;\n  font-weight: bold;\n}\n"
        result = ext.extract("style.scss", src)
        extends = _unresolved_by_kind(result, EdgeKind.SCSS_EXTENDS)
        ext_edges = _edges_by_kind(result, EdgeKind.SCSS_EXTENDS)
        assert len(extends) + len(ext_edges) >= 1

    def test_extend_placeholder(self, ext):
        src = b"%message-shared {\n  border: 1px solid #ccc;\n  padding: 10px;\n}\n.success {\n  @extend %message-shared;\n  border-color: green;\n}\n"
        result = ext.extract("style.scss", src)
        extends = _unresolved_by_kind(result, EdgeKind.SCSS_EXTENDS)
        ext_edges = _edges_by_kind(result, EdgeKind.SCSS_EXTENDS)
        assert len(extends) + len(ext_edges) >= 1

    def test_extend_no_target(self, ext):
        source = b".x { @extend; }\n"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"


class TestAnimationRefs:
    def test_animation_name_reference(self, ext):
        src = b"@keyframes fadeIn {\n  from { opacity: 0; }\n  to { opacity: 1; }\n}\n.fade { animation: fadeIn 0.3s ease-in; }\n"
        result = ext.extract("style.scss", src)
        kf = _nodes_by_kind(result, NodeKind.CSS_KEYFRAMES)
        assert len(kf) >= 1
        anim_edges = _edges_by_kind(result, EdgeKind.CSS_KEYFRAMES_USED_BY)
        anim_refs = _unresolved_by_kind(result, EdgeKind.CSS_KEYFRAMES_USED_BY)
        assert len(anim_edges) + len(anim_refs) >= 1

    def test_animation_name_property(self, ext):
        source = b".slide { animation-name: slideIn; }\n"
        result = ext.extract("style.scss", source)
        anim_refs = _unresolved_by_kind(result, EdgeKind.CSS_KEYFRAMES_USED_BY)
        assert len(anim_refs) >= 1

    def test_animation_duration_skipped(self, ext):
        """Duration values like 0.3s should not be treated as animation names."""
        source = b".fade { animation: 0.3s ease-in; }\n"
        result = ext.extract("style.scss", source)
        anim_refs = _unresolved_by_kind(result, EdgeKind.CSS_KEYFRAMES_USED_BY)
        # No animation name should be extracted from just a duration
        names = [r.reference_name for r in anim_refs]
        for name in names:
            assert not name[0].isdigit()


class TestCustomProperties:
    def test_custom_property_definition(self, ext):
        src = b":root {\n  --primary: #007bff;\n  --spacing: 8px;\n}\n"
        result = ext.extract("style.scss", src)
        vars_ = _nodes_by_kind(result, NodeKind.CSS_VARIABLE)
        assert len(vars_) >= 2

    def test_css_variable_resolution(self, ext):
        src = b":root {\n  --accent: #ff0000;\n}\n.btn { color: var(--accent); }\n"
        result = ext.extract("style.scss", src)
        vars_ = _nodes_by_kind(result, NodeKind.CSS_VARIABLE)
        assert len(vars_) >= 1
        var_edges = _edges_by_kind(result, EdgeKind.CSS_USES_VARIABLE)
        var_refs = _unresolved_by_kind(result, EdgeKind.CSS_USES_VARIABLE)
        assert len(var_edges) + len(var_refs) >= 1


class TestMediaQueries:
    def test_media_query(self, ext):
        src = b"@media (max-width: 768px) {\n  .container { width: 100%; }\n}\n"
        result = ext.extract("style.scss", src)
        media = _nodes_by_kind(result, NodeKind.CSS_MEDIA_QUERY)
        assert len(media) >= 1

    def test_nested_media_with_selectors(self, ext):
        src = b"@media screen and (min-width: 768px) {\n  .desktop-only { display: block; }\n  #sidebar { width: 300px; }\n}\n"
        result = ext.extract("style.scss", src)
        media = _nodes_by_kind(result, NodeKind.CSS_MEDIA_QUERY)
        assert len(media) >= 1
        # Media query children use CONTAINS edges
        contain_edges = _edges_by_kind(result, EdgeKind.CONTAINS)
        assert len(contain_edges) >= 1


class TestFontFace:
    def test_font_face(self, ext):
        src = b"@font-face {\n  font-family: 'CustomFont';\n  src: url('fonts/custom.woff2') format('woff2');\n}\n"
        result = ext.extract("style.scss", src)
        fonts = _nodes_by_kind(result, NodeKind.CSS_FONT_FACE)
        assert len(fonts) >= 1


class TestLayer:
    def test_layer_with_rules(self, ext):
        src = b"@layer base {\n  .reset { margin: 0; }\n}\n"
        result = ext.extract("style.scss", src)
        layers = _nodes_by_kind(result, NodeKind.CSS_LAYER)
        assert len(layers) >= 1

    def test_layer_contains_edges(self, ext):
        src = b"@layer utilities {\n  .flex { display: flex; }\n  .grid { display: grid; }\n}\n"
        result = ext.extract("style.scss", src)
        # Layer children use CONTAINS edges
        contain_edges = _edges_by_kind(result, EdgeKind.CONTAINS)
        assert len(contain_edges) >= 1


class TestNesting:
    def test_nested_rules(self, ext):
        src = b".parent {\n  color: red;\n  .child {\n    color: blue;\n    .grandchild { color: green; }\n  }\n}\n"
        result = ext.extract("style.scss", src)
        classes = _nodes_by_kind(result, NodeKind.CSS_CLASS)
        assert len(classes) >= 3
        nesting_edges = _edges_by_kind(result, EdgeKind.SCSS_NESTS)
        assert len(nesting_edges) >= 1


class TestLargeSource:
    def test_large_rule_source_truncated(self, ext):
        pad = "x" * 50
        lines_list = [f"  prop-{i}: value-{i}; /* {pad} */" for i in range(100)]
        big_body = "\n".join(lines_list)
        source = (".huge-class {\n" + big_body + "\n}").encode()
        result = ext.extract("style.scss", source)
        classes = _nodes_by_kind(result, NodeKind.CSS_CLASS)
        assert len(classes) >= 1


class TestEdgeCases:
    def test_empty_source(self, ext):
        result = ext.extract("empty.scss", b"")
        assert result.file_path == "empty.scss"
        assert result.language == "scss"

    def test_comment_only(self, ext):
        result = ext.extract("comment.scss", b"/* just a comment */")
        assert len(result.errors) == 0

    def test_empty_class_selector(self, ext):
        source = b". { color: red; }"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"

    def test_empty_id_selector(self, ext):
        source = b"# { color: red; }"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"

    def test_declaration_no_property(self, ext):
        source = b".x { : red; }"
        result = ext.extract("style.scss", source)
        assert result.file_path == "style.scss"

    def test_minified_file_skipped(self, ext):
        source = b".a{color:red}" * 200
        result = ext.extract("style.min.scss", source)
        assert result.file_path == "style.min.scss"

    def test_oversized_file_skipped(self, ext):
        source = b"/* padding */\n" * 200000
        result = ext.extract("huge.scss", source)
        if result.errors:
            assert any(
                "large" in e.message.lower() or "skip" in e.message.lower() or "size" in e.message.lower()
                for e in result.errors
            )

    def test_keyframes_resolution(self, ext):
        src = b"@keyframes spin {\n  from { transform: rotate(0deg); }\n  to { transform: rotate(360deg); }\n}\n.spinner { animation: spin 1s linear infinite; }\n"
        result = ext.extract("style.scss", src)
        kf = _nodes_by_kind(result, NodeKind.CSS_KEYFRAMES)
        assert len(kf) >= 1
        kf_edges = _edges_by_kind(result, EdgeKind.CSS_KEYFRAMES_USED_BY)
        kf_refs = _unresolved_by_kind(result, EdgeKind.CSS_KEYFRAMES_USED_BY)
        assert len(kf_edges) + len(kf_refs) >= 1

    def test_scss_variable_in_mixin_body(self, ext):
        src = b"$gap: 10px;\n@mixin grid-layout {\n  display: grid;\n  gap: $gap;\n}\n"
        result = ext.extract("style.scss", src)
        mixins = _nodes_by_kind(result, NodeKind.SCSS_MIXIN)
        assert len(mixins) >= 1
        vars_ = _nodes_by_kind(result, NodeKind.SCSS_VARIABLE)
        assert len(vars_) >= 1

    def test_nested_mixin_include(self, ext):
        src = b".card {\n  @include shadow;\n  .card-body {\n    @include padding(lg);\n  }\n}\n"
        result = ext.extract("style.scss", src)
        includes = _unresolved_by_kind(result, EdgeKind.SCSS_INCLUDES_MIXIN)
        inc_edges = _edges_by_kind(result, EdgeKind.SCSS_INCLUDES_MIXIN)
        assert len(includes) + len(inc_edges) >= 2

    def test_use_with_configuration(self, ext):
        src = b"@use 'library' with ($black: #222, $border-radius: 0.1rem);\n"
        result = ext.extract("style.scss", src)
        assert result.file_path == "style.scss"

    def test_forward_with_show_hide(self, ext):
        src = b"@forward 'functions' show color-mix, color-contrast;\n@forward 'variables' hide $internal-var;\n"
        result = ext.extract("style.scss", src)
        imports = _nodes_by_kind(result, NodeKind.IMPORT)
        assert len(imports) >= 2

    def test_interpolation_in_selector(self, ext):
        src = b"$name: foo;\n.icon-#{$name} { display: block; }\n"
        result = ext.extract("style.scss", src)
        assert result.file_path == "style.scss"

    def test_each_loop(self, ext):
        src = b"@each $size in sm, md, lg {\n  .text-#{$size} { font-size: 1rem; }\n}\n"
        result = ext.extract("style.scss", src)
        assert result.file_path == "style.scss"

    def test_for_loop(self, ext):
        src = b"@for $i from 1 through 12 {\n  .col-#{$i} { width: 100% / 12 * $i; }\n}\n"
        result = ext.extract("style.scss", src)
        assert result.file_path == "style.scss"

    def test_if_else(self, ext):
        src = b"@mixin theme($dark: false) {\n  @if $dark {\n    background: black;\n  } @else {\n    background: white;\n  }\n}\n"
        result = ext.extract("style.scss", src)
        mixins = _nodes_by_kind(result, NodeKind.SCSS_MIXIN)
        assert len(mixins) >= 1
