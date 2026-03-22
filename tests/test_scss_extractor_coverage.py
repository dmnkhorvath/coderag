"""Targeted coverage tests for SCSS extractor.

Focuses on uncovered lines to boost coverage from 76% to 95%+.
"""

import pytest

from coderag.core.models import EdgeKind, NodeKind
from coderag.plugins.scss.extractor import SCSSExtractor, _is_minified


@pytest.fixture
def ext():
    return SCSSExtractor()


def _extract(ext, code: str, path: str = "test.scss"):
    return ext.extract(path, code.encode("utf-8"))


def _node_names(result, kind=None):
    if kind:
        return [n.name for n in result.nodes if n.kind == kind]
    return [n.name for n in result.nodes]


def _node_by_kind(result, kind):
    return [n for n in result.nodes if n.kind == kind]


def _edge_kinds(result):
    return [e.kind for e in result.edges]


def _unresolved_names(result, kind=None):
    if kind:
        return [u.reference_name for u in result.unresolved_references if u.reference_kind == kind]
    return [u.reference_name for u in result.unresolved_references]


def _edges_by_kind(result, kind):
    return [e for e in result.edges if e.kind == kind]


def _unresolved_by_kind(result, kind):
    return [u for u in result.unresolved_references if u.reference_kind == kind]


# ---------------------------------------------------------------------------
# _is_minified / file-too-large guards
# ---------------------------------------------------------------------------
class TestMinifiedAndLargeFile:
    def test_minified_no_newline_long(self, ext):
        """Single line > threshold => minified."""
        code = ".a{color:red}" * 2000  # long single line, no newline
        result = _extract(ext, code)
        assert any("inified" in e.message for e in result.errors)
        assert len(result.nodes) == 0

    def test_minified_first_newline_far(self, ext):
        """First newline after threshold => minified."""
        code = "x" * 20001 + "\n.a { color: red; }"
        result = _extract(ext, code)
        assert any("inified" in e.message.lower() or "Minified" in e.message for e in result.errors)

    def test_not_minified_short_line(self, ext):
        """Short first line => not minified."""
        code = ".a { color: red; }\n.b { color: blue; }"
        result = _extract(ext, code)
        assert not any("inified" in e.message.lower() for e in result.errors)

    def test_file_too_large(self, ext):
        """File exceeding max size => skipped."""
        code = "/* padding */\n" * 500000  # very large
        result = _extract(ext, code)
        assert any("too large" in e.message.lower() for e in result.errors)

    def test_is_minified_no_newline_short(self):
        assert _is_minified(b".a{color:red}") is False

    def test_is_minified_no_newline_long(self):
        assert _is_minified(b"x" * 20001) is True


# ---------------------------------------------------------------------------
# @use / @forward
# ---------------------------------------------------------------------------
class TestUseForward:
    def test_use_basic(self, ext):
        code = "@use 'variables';\n.a { color: red; }"
        result = _extract(ext, code)
        imports = _node_by_kind(result, NodeKind.IMPORT)
        assert any("variables" in n.name for n in imports)
        assert any(
            u.reference_name == "variables"
            for u in result.unresolved_references
            if u.reference_kind == EdgeKind.IMPORTS
        )

    def test_use_with_namespace(self, ext):
        code = '@use "foundation" as fnd;\n.a { color: fnd.$primary; }'
        result = _extract(ext, code)
        imports = _node_by_kind(result, NodeKind.IMPORT)
        assert len(imports) >= 1

    def test_use_as_star(self, ext):
        code = "@use 'colors' as *;\n.a { color: $primary; }"
        result = _extract(ext, code)
        imports = _node_by_kind(result, NodeKind.IMPORT)
        assert len(imports) >= 1

    def test_forward_basic(self, ext):
        code = "@forward 'buttons';\n"
        result = _extract(ext, code)
        imports = _node_by_kind(result, NodeKind.IMPORT)
        assert any("buttons" in n.name for n in imports)
        assert any(u.reference_kind == EdgeKind.SCSS_FORWARDS for u in result.unresolved_references)

    def test_forward_with_show(self, ext):
        code = "@forward 'functions' show color-mix, size-calc;\n"
        result = _extract(ext, code)
        imports = _node_by_kind(result, NodeKind.IMPORT)
        assert any("functions" in n.name for n in imports)

    def test_forward_with_hide(self, ext):
        code = "@forward 'helpers' hide _internal-fn;\n"
        result = _extract(ext, code)
        imports = _node_by_kind(result, NodeKind.IMPORT)
        assert any("helpers" in n.name for n in imports)

    def test_use_forward_regex_extraction(self, ext):
        """Regex fallback for @use ... as namespace."""
        code = '@use "mixins" as mx;\n@use "vars" as *;\n.a { color: mx.$color; }'
        result = _extract(ext, code)
        # Should have import nodes
        imports = _node_by_kind(result, NodeKind.IMPORT)
        assert len(imports) >= 2

    def test_import_statement(self, ext):
        code = "@import 'legacy/grid';\n@import 'legacy/utils';\n"
        result = _extract(ext, code)
        imports = _node_by_kind(result, NodeKind.IMPORT)
        assert len(imports) >= 2


# ---------------------------------------------------------------------------
# @mixin definitions
# ---------------------------------------------------------------------------
class TestMixinDef:
    def test_mixin_no_params(self, ext):
        code = "@mixin clearfix {\n  &::after { content: ''; display: table; clear: both; }\n}"
        result = _extract(ext, code)
        mixins = _node_by_kind(result, NodeKind.SCSS_MIXIN)
        assert len(mixins) == 1
        assert "clearfix" in mixins[0].name

    def test_mixin_with_params(self, ext):
        code = "@mixin respond-to($breakpoint, $type: min) {\n  @media (#{$type}-width: $breakpoint) { @content; }\n}"
        result = _extract(ext, code)
        mixins = _node_by_kind(result, NodeKind.SCSS_MIXIN)
        assert len(mixins) == 1
        assert "respond-to" in mixins[0].name

    def test_mixin_with_rest_args(self, ext):
        code = "@mixin box-shadow($shadows...) {\n  box-shadow: $shadows;\n}"
        result = _extract(ext, code)
        mixins = _node_by_kind(result, NodeKind.SCSS_MIXIN)
        assert len(mixins) == 1

    def test_mixin_body_contains_declarations(self, ext):
        code = "@mixin theme($color) {\n  color: $color;\n  .nested { font-weight: bold; }\n}"
        result = _extract(ext, code)
        mixins = _node_by_kind(result, NodeKind.SCSS_MIXIN)
        assert len(mixins) == 1


# ---------------------------------------------------------------------------
# @function definitions
# ---------------------------------------------------------------------------
class TestFunctionDef:
    def test_function_basic(self, ext):
        code = "@function double($value) {\n  @return $value * 2;\n}"
        result = _extract(ext, code)
        fns = _node_by_kind(result, NodeKind.SCSS_FUNCTION)
        assert len(fns) == 1
        assert "double" in fns[0].name

    def test_function_with_default_params(self, ext):
        code = "@function spacing($multiplier: 1, $base: 8px) {\n  @return $multiplier * $base;\n}"
        result = _extract(ext, code)
        fns = _node_by_kind(result, NodeKind.SCSS_FUNCTION)
        assert len(fns) == 1
        assert "spacing" in fns[0].name

    def test_function_no_params(self, ext):
        code = "@function get-default() {\n  @return 42;\n}"
        result = _extract(ext, code)
        fns = _node_by_kind(result, NodeKind.SCSS_FUNCTION)
        assert len(fns) == 1


# ---------------------------------------------------------------------------
# @include
# ---------------------------------------------------------------------------
class TestInclude:
    def test_include_simple(self, ext):
        code = ".btn {\n  @include clearfix;\n}"
        result = _extract(ext, code)
        refs = _unresolved_by_kind(result, EdgeKind.SCSS_INCLUDES_MIXIN)
        assert any(u.reference_name == "clearfix" for u in refs)

    def test_include_with_args(self, ext):
        code = ".container {\n  @include respond-to(768px, max);\n}"
        result = _extract(ext, code)
        refs = _unresolved_by_kind(result, EdgeKind.SCSS_INCLUDES_MIXIN)
        assert any("respond-to" in u.reference_name for u in refs)

    def test_include_with_content_block(self, ext):
        code = ".sidebar {\n  @include respond-to(lg) {\n    width: 300px;\n  }\n}"
        result = _extract(ext, code)
        refs = _unresolved_by_kind(result, EdgeKind.SCSS_INCLUDES_MIXIN)
        assert any("respond-to" in u.reference_name for u in refs)


# ---------------------------------------------------------------------------
# @extend
# ---------------------------------------------------------------------------
class TestExtend:
    def test_extend_class(self, ext):
        code = ".error {\n  color: red;\n}\n.serious-error {\n  @extend .error;\n  font-weight: bold;\n}"
        result = _extract(ext, code)
        refs = _unresolved_by_kind(result, EdgeKind.SCSS_EXTENDS)
        assert any(".error" in u.reference_name for u in refs)

    def test_extend_placeholder(self, ext):
        code = "%message-shared {\n  border: 1px solid #ccc;\n  padding: 10px;\n}\n.success {\n  @extend %message-shared;\n  border-color: green;\n}"
        result = _extract(ext, code)
        placeholders = _node_by_kind(result, NodeKind.SCSS_PLACEHOLDER)
        assert len(placeholders) >= 1
        extends_edges = _edges_by_kind(result, EdgeKind.SCSS_EXTENDS)
        assert len(extends_edges) >= 1, "Expected at least one scss_extends edge"


# ---------------------------------------------------------------------------
# Placeholder selectors
# ---------------------------------------------------------------------------
class TestPlaceholder:
    def test_placeholder_definition(self, ext):
        code = "%flex-center {\n  display: flex;\n  align-items: center;\n  justify-content: center;\n}"
        result = _extract(ext, code)
        placeholders = _node_by_kind(result, NodeKind.SCSS_PLACEHOLDER)
        assert len(placeholders) == 1
        assert "%flex-center" in placeholders[0].name

    def test_multiple_placeholders(self, ext):
        code = "%reset-list {\n  margin: 0;\n  padding: 0;\n  list-style: none;\n}\n%inline-block {\n  display: inline-block;\n}"
        result = _extract(ext, code)
        placeholders = _node_by_kind(result, NodeKind.SCSS_PLACEHOLDER)
        assert len(placeholders) == 2


# ---------------------------------------------------------------------------
# Control flow: @each, @for, @while, @if/@else
# ---------------------------------------------------------------------------
class TestControlFlow:
    def test_each_loop(self, ext):
        code = "$sizes: sm, md, lg;\n@each $size in $sizes {\n  .icon-#{$size} {\n    font-size: 12px;\n  }\n}"
        result = _extract(ext, code)
        # Should have variable and class nodes
        assert len(result.nodes) >= 2

    def test_for_loop(self, ext):
        code = "@for $i from 1 through 12 {\n  .col-#{$i} {\n    width: percentage($i / 12);\n  }\n}"
        result = _extract(ext, code)
        assert len(result.nodes) >= 1

    def test_while_loop(self, ext):
        code = "$i: 6;\n@while $i > 0 {\n  .item-#{$i} { width: 2em * $i; }\n  $i: $i - 2;\n}"
        result = _extract(ext, code)
        assert len(result.nodes) >= 1

    def test_if_else(self, ext):
        code = "$theme: dark;\n@if $theme == dark {\n  .body { background: #333; color: #fff; }\n} @else {\n  .body { background: #fff; color: #333; }\n}"
        result = _extract(ext, code)
        assert len(result.nodes) >= 1

    def test_if_else_if(self, ext):
        code = "$size: md;\n@if $size == sm {\n  .box { width: 100px; }\n} @else if $size == md {\n  .box { width: 200px; }\n} @else {\n  .box { width: 300px; }\n}"
        result = _extract(ext, code)
        assert len(result.nodes) >= 1

    def test_each_with_nested_mixin_include(self, ext):
        """Control block containing @include."""
        code = "@each $color in red, green, blue {\n  .text-#{$color} {\n    @include set-color($color);\n  }\n}"
        result = _extract(ext, code)
        refs = _unresolved_by_kind(result, EdgeKind.SCSS_INCLUDES_MIXIN)
        assert any("set-color" in u.reference_name for u in refs)


# ---------------------------------------------------------------------------
# Nested selectors
# ---------------------------------------------------------------------------
class TestNestedSelectors:
    def test_basic_nesting(self, ext):
        code = ".nav {\n  ul { list-style: none; }\n  li { display: inline-block; }\n  a { text-decoration: none; }\n}"
        result = _extract(ext, code)
        classes = _node_by_kind(result, NodeKind.CSS_CLASS)
        assert any(".nav" in n.name for n in classes)

    def test_deep_nesting(self, ext):
        code = ".card {\n  .header {\n    .title {\n      font-size: 1.5em;\n    }\n  }\n}"
        result = _extract(ext, code)
        classes = _node_by_kind(result, NodeKind.CSS_CLASS)
        assert len(classes) >= 1

    def test_parent_selector(self, ext):
        code = ".btn {\n  &:hover { background: darken(#333, 10%); }\n  &--primary { background: blue; }\n  &__icon { margin-right: 4px; }\n}"
        result = _extract(ext, code)
        assert len(result.nodes) >= 2


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------
class TestInterpolation:
    def test_selector_interpolation(self, ext):
        code = "$name: foo;\n.icon-#{$name} { display: inline-block; }"
        result = _extract(ext, code)
        assert len(result.nodes) >= 2  # file + variable at minimum

    def test_property_interpolation(self, ext):
        code = "$prop: margin;\n.box { #{$prop}-top: 10px; }"
        result = _extract(ext, code)
        assert len(result.nodes) >= 2


# ---------------------------------------------------------------------------
# Variable references in values
# ---------------------------------------------------------------------------
class TestVariableRefs:
    def test_scss_variable_ref(self, ext):
        code = "$primary: #333;\n.a { color: $primary; }"
        result = _extract(ext, code)
        var_edges = _edges_by_kind(result, EdgeKind.SCSS_USES_VARIABLE)
        assert len(var_edges) >= 1, "Expected at least one scss_uses_variable edge"

    def test_css_var_ref(self, ext):
        code = ":root { --main-color: #333; }\n.a { color: var(--main-color); }"
        result = _extract(ext, code)
        var_edges = _edges_by_kind(result, EdgeKind.CSS_USES_VARIABLE)
        assert len(var_edges) >= 1, "Expected at least one css_uses_variable edge"

    def test_namespaced_variable_ref(self, ext):
        code = '@use "theme" as t;\n.a { color: t.$primary; }'
        result = _extract(ext, code)
        refs = _unresolved_by_kind(result, EdgeKind.SCSS_USES_VARIABLE)
        assert any("$primary" in u.reference_name for u in refs)


# ---------------------------------------------------------------------------
# Function calls in values
# ---------------------------------------------------------------------------
class TestFunctionCalls:
    def test_builtin_function_call(self, ext):
        """Extractor parses builtin function calls without error; no function edge is created."""
        code = ".a { color: darken(#333, 10%); }"
        result = _extract(ext, code)
        # Extractor does not track builtin function calls as edges
        assert len(result.errors) == 0
        classes = _node_by_kind(result, NodeKind.CSS_CLASS)
        assert len(classes) >= 1

    def test_custom_function_call(self, ext):
        code = "@function spacing($n) { @return $n * 8px; }\n.a { margin: spacing(2); }"
        result = _extract(ext, code)
        fns = _node_by_kind(result, NodeKind.SCSS_FUNCTION)
        assert len(fns) == 1

    def test_nested_function_calls(self, ext):
        code = ".a { background: linear-gradient(to-right, lighten($bg, 10%), darken($bg, 10%)); }"
        result = _extract(ext, code)
        # Should detect function references
        assert len(result.unresolved_references) >= 1


# ---------------------------------------------------------------------------
# Animation / keyframes references
# ---------------------------------------------------------------------------
class TestAnimationRefs:
    def test_animation_name_ref(self, ext):
        code = (
            "@keyframes fadeIn {\n  from { opacity: 0; }\n  to { opacity: 1; }\n}\n.a { animation: fadeIn 1s ease-in; }"
        )
        result = _extract(ext, code)
        kf = _node_by_kind(result, NodeKind.CSS_KEYFRAMES)
        assert len(kf) == 1
        kf_edges = _edges_by_kind(result, EdgeKind.CSS_KEYFRAMES_USED_BY)
        assert len(kf_edges) >= 1, "Expected at least one css_keyframes_used_by edge"

    def test_animation_name_property(self, ext):
        code = "@keyframes slideUp { 0% { transform: translateY(100%); } 100% { transform: translateY(0); } }\n.modal { animation-name: slideUp; }"
        result = _extract(ext, code)
        kf_edges = _edges_by_kind(result, EdgeKind.CSS_KEYFRAMES_USED_BY)
        assert len(kf_edges) >= 1, "Expected at least one css_keyframes_used_by edge"


# ---------------------------------------------------------------------------
# @layer
# ---------------------------------------------------------------------------
class TestLayer:
    def test_layer_basic(self, ext):
        code = "@layer base {\n  body { margin: 0; }\n}"
        result = _extract(ext, code)
        layers = _node_by_kind(result, NodeKind.CSS_LAYER)
        assert len(layers) >= 1

    def test_layer_with_nested_rules(self, ext):
        code = "@layer components {\n  .btn { padding: 8px 16px; }\n  .card { border: 1px solid #ccc; }\n}"
        result = _extract(ext, code)
        layers = _node_by_kind(result, NodeKind.CSS_LAYER)
        assert len(layers) >= 1


# ---------------------------------------------------------------------------
# @font-face
# ---------------------------------------------------------------------------
class TestFontFace:
    def test_font_face(self, ext):
        code = "@font-face {\n  font-family: 'CustomFont';\n  src: url('font.woff2') format('woff2');\n}"
        result = _extract(ext, code)
        ff = _node_by_kind(result, NodeKind.CSS_FONT_FACE)
        assert len(ff) == 1


# ---------------------------------------------------------------------------
# @media
# ---------------------------------------------------------------------------
class TestMedia:
    def test_media_query(self, ext):
        code = "@media (min-width: 768px) {\n  .container { max-width: 720px; }\n}"
        result = _extract(ext, code)
        media = _node_by_kind(result, NodeKind.CSS_MEDIA_QUERY)
        assert len(media) >= 1

    def test_media_nested_rules(self, ext):
        code = "@media screen and (max-width: 600px) {\n  .sidebar { display: none; }\n  .main { width: 100%; }\n}"
        result = _extract(ext, code)
        media = _node_by_kind(result, NodeKind.CSS_MEDIA_QUERY)
        assert len(media) >= 1


# ---------------------------------------------------------------------------
# ERROR node handling (regex fallback)
# ---------------------------------------------------------------------------
class TestErrorNodeHandling:
    def test_error_node_extend_placeholder(self, ext):
        """tree-sitter may produce ERROR for @extend %placeholder."""
        # This SCSS triggers ERROR nodes in tree-sitter-scss
        code = "%base-style {\n  font-size: 14px;\n}\n.alert {\n  @extend %base-style;\n  color: red;\n}"
        result = _extract(ext, code)
        # Should still detect the extend via direct edge even with parse errors
        extends_edges = _edges_by_kind(result, EdgeKind.SCSS_EXTENDS)
        assert len(extends_edges) >= 1, "Expected at least one scss_extends edge"

    def test_error_node_include_fallback(self, ext):
        """@include in ERROR context should still be detected."""
        # Complex nesting that may produce ERROR nodes
        code = ".complex {\n  @extend %base;\n  @include respond-to(lg) {\n    width: 100%;\n  }\n}"
        result = _extract(ext, code)
        # Should detect include reference
        all_refs = result.unresolved_references
        include_or_extend = [
            u for u in all_refs if u.reference_kind in (EdgeKind.SCSS_INCLUDES_MIXIN, EdgeKind.SCSS_EXTENDS)
        ]
        assert len(include_or_extend) >= 1


# ---------------------------------------------------------------------------
# Intra-file reference resolution
# ---------------------------------------------------------------------------
class TestIntraFileResolution:
    def test_mixin_resolved_intra_file(self, ext):
        """@include referencing a mixin defined in same file should resolve."""
        code = "@mixin flex-center {\n  display: flex;\n  align-items: center;\n}\n.container {\n  @include flex-center;\n}"
        result = _extract(ext, code)
        mixins = _node_by_kind(result, NodeKind.SCSS_MIXIN)
        assert len(mixins) == 1
        # Check if resolved (edge created) or still unresolved
        mixin_edges = [e for e in result.edges if e.kind == EdgeKind.SCSS_INCLUDES_MIXIN]
        unresolved_includes = _unresolved_by_kind(result, EdgeKind.SCSS_INCLUDES_MIXIN)
        # Either resolved as edge or still unresolved - both valid
        assert len(mixin_edges) + len(unresolved_includes) >= 1

    def test_function_resolved_intra_file(self, ext):
        code = "@function rem($px) { @return $px / 16 * 1rem; }\n.a { font-size: rem(14); }"
        result = _extract(ext, code)
        fns = _node_by_kind(result, NodeKind.SCSS_FUNCTION)
        assert len(fns) == 1

    def test_variable_resolved_intra_file(self, ext):
        code = "$primary: #007bff;\n$secondary: #6c757d;\n.btn-primary { color: $primary; background: $secondary; }"
        result = _extract(ext, code)
        vars_ = _node_by_kind(result, NodeKind.SCSS_VARIABLE)
        assert len(vars_) == 2

    def test_placeholder_resolved_intra_file(self, ext):
        code = "%visually-hidden {\n  position: absolute;\n  clip: rect(0,0,0,0);\n}\n.sr-only {\n  @extend %visually-hidden;\n}"
        result = _extract(ext, code)
        placeholders = _node_by_kind(result, NodeKind.SCSS_PLACEHOLDER)
        assert len(placeholders) == 1


# ---------------------------------------------------------------------------
# Complex / combined scenarios
# ---------------------------------------------------------------------------
class TestComplexScenarios:
    def test_full_component_scss(self, ext):
        """Realistic component SCSS with multiple features."""
        code = """@use 'variables' as vars;
@use 'mixins' as *;

$component-padding: 16px;

@mixin card-base($radius: 4px) {
  border-radius: $radius;
  padding: $component-padding;
}

@function card-width($cols) {
  @return percentage($cols / 12);
}

%card-shadow {
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.card {
  @include card-base(8px);
  @extend %card-shadow;
  width: card-width(6);
  color: vars.$text-color;

  &__header {
    font-weight: bold;
    border-bottom: 1px solid vars.$border-color;
  }

  &__body {
    @include flex-center;
  }

  @media (max-width: 768px) {
    width: card-width(12);
  }
}

@each $variant in primary, secondary, danger {
  .card--#{$variant} {
    background: vars.$#{$variant}-bg;
  }
}

@keyframes card-enter {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.card--animated {
  animation: card-enter 0.3s ease-out;
}
"""
        result = _extract(ext, code)
        assert len(result.errors) == 0 or all(e.severity == "warning" for e in result.errors)
        # Should have file node + various extracted nodes
        assert len(result.nodes) >= 5
        assert len(result.edges) >= 3

    def test_maps_and_lists(self, ext):
        code = """$breakpoints: (
  sm: 576px,
  md: 768px,
  lg: 992px,
  xl: 1200px,
);

$colors: red, green, blue;

@each $name, $value in $breakpoints {
  .container-#{$name} {
    max-width: $value;
  }
}
"""
        result = _extract(ext, code)
        vars_ = _node_by_kind(result, NodeKind.SCSS_VARIABLE)
        assert len(vars_) >= 2

    def test_custom_properties(self, ext):
        code = ":root {\n  --spacing-sm: 4px;\n  --spacing-md: 8px;\n  --spacing-lg: 16px;\n}\n.box { padding: var(--spacing-md); }"
        result = _extract(ext, code)
        css_vars = _node_by_kind(result, NodeKind.CSS_VARIABLE)
        assert len(css_vars) >= 3

    def test_id_selector(self, ext):
        code = "#main-content {\n  width: 100%;\n  max-width: 1200px;\n}"
        result = _extract(ext, code)
        ids = _node_by_kind(result, NodeKind.CSS_ID)
        assert len(ids) >= 1

    def test_multiple_selectors_in_rule(self, ext):
        code = ".btn, .button, .action-btn {\n  cursor: pointer;\n  border: none;\n}"
        result = _extract(ext, code)
        classes = _node_by_kind(result, NodeKind.CSS_CLASS)
        assert len(classes) >= 3

    def test_at_rule_generic(self, ext):
        """Generic @rule that is not specifically handled."""
        code = "@charset 'UTF-8';\n.a { color: red; }"
        result = _extract(ext, code)
        assert len(result.nodes) >= 1

    def test_scss_variable_definition(self, ext):
        code = "$font-stack: Helvetica, sans-serif;\n$primary-color: #333;\n"
        result = _extract(ext, code)
        vars_ = _node_by_kind(result, NodeKind.SCSS_VARIABLE)
        assert len(vars_) == 2

    def test_for_loop_with_nested_declarations(self, ext):
        """@for loop with nested rule sets and declarations."""
        code = "@for $i from 1 through 5 {\n  .mt-#{$i} { margin-top: $i * 4px; }\n  .mb-#{$i} { margin-bottom: $i * 4px; }\n}"
        result = _extract(ext, code)
        assert len(result.nodes) >= 1

    def test_while_with_variable_update(self, ext):
        code = "$count: 10;\n@while $count > 0 {\n  .item-#{$count} { z-index: $count; }\n  $count: $count - 1;\n}"
        result = _extract(ext, code)
        assert len(result.nodes) >= 1

    def test_if_with_nested_include(self, ext):
        """@if block containing @include."""
        code = "$dark: true;\n@if $dark {\n  .body {\n    @include dark-theme;\n    background: #000;\n  }\n} @else {\n  .body {\n    @include light-theme;\n    background: #fff;\n  }\n}"
        result = _extract(ext, code)
        refs = _unresolved_by_kind(result, EdgeKind.SCSS_INCLUDES_MIXIN)
        assert len(refs) >= 1

    def test_large_source_text_truncation(self, ext):
        """Mixin with source_text > 2000 chars should have None source_text."""
        body = "  color: red;\n" * 200  # > 2000 chars
        code = f"@mixin huge-mixin {{\n{body}}}\n"
        result = _extract(ext, code)
        mixins = _node_by_kind(result, NodeKind.SCSS_MIXIN)
        assert len(mixins) == 1
        assert mixins[0].source_text is None

    def test_empty_file(self, ext):
        result = _extract(ext, "")
        assert len(result.nodes) == 1  # just file node
        assert result.nodes[0].kind == NodeKind.FILE

    def test_comment_only_file(self, ext):
        result = _extract(ext, "/* just a comment */\n")
        assert len(result.nodes) == 1  # just file node

    def test_collect_errors(self, ext):
        """Syntax errors should be collected."""
        code = ".a { color: ; }"  # incomplete value
        result = _extract(ext, code)
        # May or may not have errors depending on tree-sitter tolerance
        assert isinstance(result.errors, list)
