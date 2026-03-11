# JavaScript & TypeScript Parsing for Code Knowledge Graph Construction

## Comprehensive Technical Research Document

**Date**: 2026-03-10  
**Purpose**: Inform the design of a custom repository parser for building code knowledge graphs from JavaScript and TypeScript codebases  
**Scope**: ES Modules/CommonJS detection, JSX/TSX parsing, TypeScript constructs, dynamic imports, module resolution, framework patterns, and build tool configuration

---

## Table of Contents

1. [ES Modules vs CommonJS Detection and Handling](#1-es-modules-vs-commonjs-detection-and-handling)
2. [JSX/TSX Parsing Considerations](#2-jsxtsx-parsing-considerations)
3. [TypeScript-Specific Constructs](#3-typescript-specific-constructs)
4. [Dynamic Imports and Require Patterns](#4-dynamic-imports-and-require-patterns)
5. [Module Path Resolution](#5-module-path-resolution)
6. [Framework-Specific Patterns](#6-framework-specific-patterns)
7. [Build Tool Configuration as Metadata](#7-build-tool-configuration-as-metadata)

---

## 1. ES Modules vs CommonJS Detection and Handling

### 1.1 Module System Overview

JavaScript has two primary module systems that a parser must handle:

| Feature | ES Modules (ESM) | CommonJS (CJS) |
|---------|------------------|------------------|
| Syntax | `import`/`export` | `require()`/`module.exports` |
| Loading | Asynchronous | Synchronous |
| Binding | Live bindings (read-only) | Value copies |
| Static analysis | Fully static | Dynamic (runtime) |
| Tree-shaking | Supported | Limited/impossible |
| Top-level await | Supported | Not supported |
| `this` at top level | `undefined` | `module.exports` |
| File extensions | `.mjs`, `.js` (with type:module) | `.cjs`, `.js` (default) |

### 1.2 Detection Strategy

Module system detection requires a multi-layered approach combining file-level, project-level, and AST-level signals:

#### Layer 1: File Extension Detection

~~~python
def detect_module_system_by_extension(filepath: str) -> str | None:
    """Definitive detection based on file extension."""
    if filepath.endswith(".mjs"):
        return "esm"
    elif filepath.endswith(".cjs"):
        return "commonjs"
    elif filepath.endswith(".mts"):
        return "esm"  # TypeScript ESM
    elif filepath.endswith(".cts"):
        return "commonjs"  # TypeScript CJS
    return None  # Ambiguous - need further analysis
~~~

#### Layer 2: package.json "type" Field

The nearest `package.json` with a `"type"` field determines the default for `.js` files:

~~~python
import json
from pathlib import Path

def find_package_json_type(filepath: str) -> str:
    """Walk up directory tree to find nearest package.json type field."""
    current = Path(filepath).parent
    while current != current.parent:
        pkg_json = current / "package.json"
        if pkg_json.exists():
            try:
                data = json.loads(pkg_json.read_text())
                return data.get("type", "commonjs")  # Default is commonjs
            except (json.JSONDecodeError, IOError):
                pass
        current = current.parent
    return "commonjs"  # Node.js default
~~~

**Important**: In monorepos, different packages may have different `type` settings. Each workspace package can override the root `package.json`.

#### Layer 3: AST-Level Detection via Tree-sitter

Even with file extension and package.json signals, AST analysis provides the ground truth:

~~~python
def detect_module_system_from_ast(tree, source_code: bytes) -> dict:
    """Analyze AST to detect module system usage."""
    signals = {
        "has_esm_import": False,
        "has_esm_export": False,
        "has_require": False,
        "has_module_exports": False,
        "has_exports_assignment": False,
        "has_dynamic_import": False,  # Can appear in both systems
        "has_import_meta": False,     # ESM-only
        "has_dirname": False,         # CJS-only (__dirname)
        "has_filename": False,        # CJS-only (__filename)
    }
    # ... Tree-sitter query analysis
    return signals
~~~

### 1.3 Tree-sitter Queries for ESM Detection

#### ES Module Import Patterns

~~~scm
;; Standard named import: import { foo, bar } from './module'
(import_statement
  (import_clause
    (named_imports
      (import_specifier
        name: (identifier) @import.name
        alias: (identifier)? @import.alias
      )
    )
  )
  source: (string) @import.source
) @import.esm_named

;; Default import: import foo from './module'
(import_statement
  (import_clause
    (identifier) @import.default
  )
  source: (string) @import.source
) @import.esm_default

;; Namespace import: import * as foo from './module'
(import_statement
  (import_clause
    (namespace_import
      (identifier) @import.namespace
    )
  )
  source: (string) @import.source
) @import.esm_namespace

;; Side-effect import: import './module'
(import_statement
  source: (string) @import.source
  !import_clause
) @import.esm_side_effect

;; Combined default + named: import React, { useState } from 'react'
(import_statement
  (import_clause
    (identifier) @import.default
    (named_imports
      (import_specifier
        name: (identifier) @import.name
      )
    )
  )
  source: (string) @import.source
) @import.esm_combined
~~~

#### TypeScript Type-Only Imports

~~~scm
;; Type-only import: import type { Foo } from './types'
(import_statement
  "type" @import.type_only_marker
  (import_clause
    (named_imports
      (import_specifier
        name: (identifier) @import.name
      )
    )
  )
  source: (string) @import.source
) @import.type_only

;; Inline type import: import { type Foo, bar } from './module'
;; Note: tree-sitter-typescript represents inline type with "type" keyword
;; inside the import_specifier
(import_statement
  (import_clause
    (named_imports
      (import_specifier
        "type" @import.inline_type_marker
        name: (identifier) @import.name
      )
    )
  )
  source: (string) @import.source
) @import.mixed_type
~~~

**Graph Implications for Type-Only Imports**:
- Type-only imports create "type_depends_on" edges (not runtime "depends_on")
- They are erased at compile time and do not affect the runtime dependency graph
- Important for distinguishing build-time vs runtime dependencies

#### ES Module Export Patterns

~~~scm
;; Named export declaration: export function foo() {} / export class Bar {}
(export_statement
  declaration: [
    (function_declaration
      name: (identifier) @export.name) @export.func_decl
    (class_declaration
      name: (identifier) @export.name) @export.class_decl
    (lexical_declaration
      (variable_declarator
        name: (identifier) @export.name)) @export.var_decl
  ]
) @export.named_decl

;; Named export list: export { foo, bar as baz }
(export_statement
  (export_clause
    (export_specifier
      name: (identifier) @export.local_name
      alias: (identifier)? @export.exported_name
    )
  )
) @export.named_list

;; Default export: export default expression
(export_statement
  "default" @export.is_default
  [
    (identifier) @export.value
    (function_declaration
      name: (identifier)? @export.name) @export.func
    (class_declaration
      name: (identifier)? @export.name) @export.class
    (call_expression) @export.call
    (arrow_function) @export.arrow
    (object) @export.object
  ]
) @export.default

;; TypeScript type-only export: export type { Foo }
(export_statement
  "type" @export.type_only_marker
  (export_clause
    (export_specifier
      name: (identifier) @export.name
    )
  )
) @export.type_only
~~~

### 1.4 Tree-sitter Queries for CommonJS Detection

~~~scm
;; require() call: const foo = require('./module')
(call_expression
  function: (identifier) @_func
  (#eq? @_func "require")
  arguments: (arguments
    (string) @require.source
  )
) @require.call

;; Destructured require: const { foo, bar } = require('./module')
(variable_declarator
  name: (object_pattern
    (shorthand_property_identifier_pattern) @require.binding
  )
  value: (call_expression
    function: (identifier) @_func
    (#eq? @_func "require")
    arguments: (arguments
      (string) @require.source
    )
  )
) @require.destructured

;; module.exports assignment: module.exports = { foo, bar }
(assignment_expression
  left: (member_expression
    object: (identifier) @_obj
    (#eq? @_obj "module")
    property: (property_identifier) @_prop
    (#eq? @_prop "exports")
  )
  right: (_) @cjs_export.value
) @cjs_export.module_exports

;; exports.foo = bar
(assignment_expression
  left: (member_expression
    object: (identifier) @_obj
    (#eq? @_obj "exports")
    property: (property_identifier) @cjs_export.name
  )
  right: (_) @cjs_export.value
) @cjs_export.named

;; module.exports.foo = bar
(assignment_expression
  left: (member_expression
    object: (member_expression
      object: (identifier) @_obj
      (#eq? @_obj "module")
      property: (property_identifier) @_prop
      (#eq? @_prop "exports")
    )
    property: (property_identifier) @cjs_export.name
  )
  right: (_) @cjs_export.value
) @cjs_export.module_exports_named

;; require.resolve(): require.resolve('./module')
(call_expression
  function: (member_expression
    object: (identifier) @_obj
    (#eq? @_obj "require")
    property: (property_identifier) @_prop
    (#eq? @_prop "resolve")
  )
  arguments: (arguments
    (string) @require.resolve_source
  )
) @require.resolve
~~~

### 1.5 Re-export Patterns

Re-exports are critical for knowledge graph construction as they create transitive dependency edges:

~~~scm
;; Re-export all: export * from './module'
(export_statement
  (namespace_export) @reexport.star
  source: (string) @reexport.source
) @reexport.all

;; Re-export named: export { foo, bar } from './module'
(export_statement
  (export_clause
    (export_specifier
      name: (identifier) @reexport.name
      alias: (identifier)? @reexport.alias
    )
  )
  source: (string) @reexport.source
) @reexport.named

;; Re-export default as named: export { default as foo } from './module'
;; This is captured by the named re-export query above
;; where @reexport.name = "default" and @reexport.alias = "foo"

;; Re-export all as namespace: export * as ns from './module'
(export_statement
  (namespace_export
    (identifier) @reexport.namespace_name
  )
  source: (string) @reexport.source
) @reexport.namespace
~~~

**Graph Implications for Re-exports**:

| Re-export Pattern | Graph Edge Type | Notes |
|---|---|---|
| `export * from './mod'` | `reexports_all` -> target file | Creates implicit edges for all exports of target |
| `export { foo } from './mod'` | `reexports_named` -> target file + symbol | Selective re-export, specific symbol tracking |
| `export { default as Foo } from './mod'` | `reexports_default_as` -> target file | Renames default export |
| `export * as ns from './mod'` | `reexports_namespace` -> target file | Wraps all exports under namespace |

### 1.6 Default vs Named Exports - Graph Implications

**Default Exports**:
- A file can have exactly one default export
- The importing file chooses the local name: `import MyName from './mod'`
- Graph node: `file:./mod::default` with edge to the actual declaration
- Challenge: The exported name is determined by the importer, not the exporter
- Detection: Look for `export default` or `export { foo as default }`

**Named Exports**:
- A file can have multiple named exports
- The name is fixed: `import { exactName } from './mod'`
- Graph node: `file:./mod::exactName` with stable identity
- Easier to track through re-export chains

**Unified Import/Export Graph Normalization**:

~~~python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class ModuleSystem(Enum):
    ESM = "esm"
    COMMONJS = "commonjs"
    MIXED = "mixed"  # File uses both systems
    UNKNOWN = "unknown"

class ImportKind(Enum):
    DEFAULT = "default"
    NAMED = "named"
    NAMESPACE = "namespace"
    SIDE_EFFECT = "side_effect"
    TYPE_ONLY = "type_only"
    DYNAMIC = "dynamic"
    REQUIRE = "require"
    REQUIRE_DESTRUCTURED = "require_destructured"

class ExportKind(Enum):
    DEFAULT = "default"
    NAMED = "named"
    NAMED_DECLARATION = "named_declaration"
    REEXPORT_ALL = "reexport_all"
    REEXPORT_NAMED = "reexport_named"
    REEXPORT_NAMESPACE = "reexport_namespace"
    CJS_MODULE_EXPORTS = "cjs_module_exports"
    CJS_EXPORTS_PROPERTY = "cjs_exports_property"
    TYPE_ONLY = "type_only"

@dataclass
class ImportEdge:
    """Unified import representation for the knowledge graph."""
    source_file: str          # File containing the import
    target_specifier: str     # Raw module specifier (e.g., './foo', 'react')
    resolved_path: str | None # Resolved absolute file path
    kind: ImportKind
    imported_names: list[str] # Names being imported
    local_names: list[str]    # Local binding names
    module_system: ModuleSystem
    is_type_only: bool = False
    is_dynamic: bool = False
    line_number: int = 0

@dataclass
class ExportEdge:
    """Unified export representation for the knowledge graph."""
    source_file: str          # File containing the export
    kind: ExportKind
    exported_name: str | None # Name as seen by importers
    local_name: str | None    # Name within the file
    declaration_type: str | None  # 'function', 'class', 'variable', etc.
    reexport_source: str | None   # For re-exports: the source module
    module_system: ModuleSystem
    is_type_only: bool = False
    line_number: int = 0
~~~

### 1.7 Mixed Module Systems

Some files legitimately use both module systems:

~~~javascript
// Mixed: ESM imports with CJS interop
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const nativeModule = require('./native-addon.node');

export { nativeModule };
~~~

Detection strategy for mixed files:

~~~python
def classify_module_system(signals: dict) -> ModuleSystem:
    """Classify file module system from AST signals."""
    has_esm = signals["has_esm_import"] or signals["has_esm_export"]
    has_cjs = signals["has_require"] or signals["has_module_exports"]
    
    if has_esm and has_cjs:
        # Check if CJS usage is via createRequire (legitimate ESM pattern)
        if signals.get("has_create_require"):
            return ModuleSystem.ESM
        return ModuleSystem.MIXED
    elif has_esm:
        return ModuleSystem.ESM
    elif has_cjs:
        return ModuleSystem.COMMONJS
    else:
        return ModuleSystem.UNKNOWN
~~~


---

## 2. JSX/TSX Parsing Considerations

### 2.1 Grammar Architecture

Tree-sitter handles JSX and TSX through separate but related grammars:

| Grammar | Package | JSX Support | TypeScript Support |
|---------|---------|-------------|--------------------|
| `tree-sitter-javascript` | `tree-sitter-javascript` | Built-in | No |
| `tree-sitter-typescript` | `tree-sitter-typescript/typescript` | No | Yes |
| `tree-sitter-tsx` | `tree-sitter-typescript/tsx` | Built-in | Yes |

**Critical Design Decision**: For `.tsx` files, you MUST use the TSX grammar, not the TypeScript grammar. The TypeScript grammar will fail to parse JSX syntax. Similarly, `.jsx` files should use the JavaScript grammar (which includes JSX support).

~~~python
def select_grammar(filepath: str) -> str:
    """Select the correct Tree-sitter grammar for a file."""
    ext = filepath.rsplit(".", 1)[-1].lower()
    grammar_map = {
        "js": "javascript",    # Includes JSX support
        "jsx": "javascript",   # Same grammar as .js
        "mjs": "javascript",   # ES module JS
        "cjs": "javascript",   # CommonJS JS
        "ts": "typescript",    # Pure TypeScript (no JSX)
        "tsx": "tsx",          # TypeScript + JSX
        "mts": "typescript",   # ES module TS
        "cts": "typescript",   # CommonJS TS
    }
    return grammar_map.get(ext, "javascript")
~~~

### 2.2 JSX Node Types in Tree-sitter

The following JSX-specific node types are available in both `tree-sitter-javascript` and `tree-sitter-tsx`:

| Node Type | Description | Example |
|-----------|-------------|----------|
| `jsx_element` | Complete JSX element with open/close tags | `<Div>...</Div>` |
| `jsx_self_closing_element` | Self-closing JSX element | `<Input />` |
| `jsx_opening_element` | Opening tag of a JSX element | `<Div className="x">` |
| `jsx_closing_element` | Closing tag of a JSX element | `</Div>` |
| `jsx_attribute` | Attribute on a JSX element | `className="x"` |
| `jsx_expression` | JavaScript expression in JSX | `{value}` |
| `jsx_namespace_name` | Namespaced JSX name | `xml:lang` |
| `jsx_text` | Text content within JSX (TSX only) | Plain text between tags |

### 2.3 Extracting Component Usage as Graph Edges

#### Distinguishing Custom Components from HTML Elements

React uses a naming convention to distinguish custom components from HTML elements:
- **Uppercase first letter** = Custom component: `<MyComponent />`
- **Lowercase first letter** = HTML element: `<div />`
- **Dot notation** = Namespaced component (always custom): `<UI.Button />`

~~~scm
;; Custom component usage (uppercase first letter)
(jsx_opening_element
  name: (identifier) @component.name
  (#match? @component.name "^[A-Z]")
) @component.usage

;; Self-closing custom component
(jsx_self_closing_element
  name: (identifier) @component.name
  (#match? @component.name "^[A-Z]")
) @component.usage_self_closing

;; Namespaced component: <UI.Button />
(jsx_opening_element
  name: (member_expression
    object: (identifier) @component.namespace
    property: (property_identifier) @component.member
  )
) @component.namespaced

(jsx_self_closing_element
  name: (member_expression
    object: (identifier) @component.namespace
    property: (property_identifier) @component.member
  )
) @component.namespaced_self_closing

;; HTML elements (lowercase) - for completeness/filtering
(jsx_opening_element
  name: (identifier) @html.tag
  (#match? @html.tag "^[a-z]")
) @html.element
~~~

**Graph Edge Generation**:

~~~python
def extract_component_edges(file_path: str, jsx_usages: list, imports: list) -> list:
    """Generate graph edges from JSX component usage."""
    edges = []
    # Build import lookup: local_name -> (source_file, imported_name)
    import_map = {}
    for imp in imports:
        for local, original in zip(imp.local_names, imp.imported_names):
            import_map[local] = (imp.resolved_path, original)
    
    for usage in jsx_usages:
        component_name = usage["name"]
        if component_name in import_map:
            resolved_path, original_name = import_map[component_name]
            edges.append({
                "type": "renders_component",
                "source": file_path,
                "target": resolved_path,
                "component_name": original_name,
                "local_name": component_name,
                "line": usage["line"],
            })
        else:
            # Component defined in same file or globally available
            edges.append({
                "type": "renders_component",
                "source": file_path,
                "target": file_path,  # Same file
                "component_name": component_name,
                "line": usage["line"],
            })
    return edges
~~~

### 2.4 Props as Interface Contracts

Props define the interface contract between parent and child components. Extracting props creates "passes_prop" edges in the graph:

~~~scm
;; Extract all props passed to a component
(jsx_opening_element
  name: (identifier) @component.name
  (#match? @component.name "^[A-Z]")
  (jsx_attribute
    (property_identifier) @prop.name
    [
      (string) @prop.string_value
      (jsx_expression
        [
          (identifier) @prop.variable_ref
          (member_expression) @prop.member_ref
          (call_expression) @prop.call_ref
          (arrow_function) @prop.callback
        ]
      )
    ]?
  )
) @component.with_props

;; Spread props: <Component {...props} />
(jsx_opening_element
  name: (identifier) @component.name
  (#match? @component.name "^[A-Z]")
  (jsx_expression
    (spread_element
      (identifier) @prop.spread_source
    )
  )
) @component.spread_props

;; Boolean shorthand props: <Component disabled />
(jsx_opening_element
  name: (identifier) @component.name
  (#match? @component.name "^[A-Z]")
  (jsx_attribute
    (property_identifier) @prop.boolean_name
    !value
  )
) @component.boolean_prop
~~~

**TypeScript Props Interface Extraction**:

~~~scm
;; Props type definition: interface MyComponentProps { ... }
(interface_declaration
  name: (type_identifier) @props.interface_name
  (#match? @props.interface_name "Props$")
  body: (interface_body
    (property_signature
      name: (property_identifier) @props.prop_name
      type: (type_annotation (_) @props.prop_type)
    )
  )
) @props.interface

;; Props type alias: type MyComponentProps = { ... }
(type_alias_declaration
  name: (type_identifier) @props.type_name
  (#match? @props.type_name "Props$")
  value: (object_type
    (property_signature
      name: (property_identifier) @props.prop_name
      type: (type_annotation (_) @props.prop_type)
    )
  )
) @props.type_alias

;; Function component with typed props
;; const MyComponent: React.FC<Props> = ({ prop1, prop2 }) => ...
(lexical_declaration
  (variable_declarator
    name: (identifier) @component.name
    (#match? @component.name "^[A-Z]")
    type: (type_annotation
      (generic_type
        name: (_) @component.fc_type
        (type_arguments
          (_) @component.props_type
        )
      )
    )
  )
) @component.typed_fc

;; Function component with props parameter type
;; function MyComponent(props: MyProps) { ... }
(function_declaration
  name: (identifier) @component.name
  (#match? @component.name "^[A-Z]")
  parameters: (formal_parameters
    (required_parameter
      pattern: (identifier) @component.props_param
      type: (type_annotation (_) @component.props_type)
    )
  )
) @component.func_with_props

;; Destructured props in function component
;; function MyComponent({ prop1, prop2 }: MyProps) { ... }
(function_declaration
  name: (identifier) @component.name
  (#match? @component.name "^[A-Z]")
  parameters: (formal_parameters
    (required_parameter
      pattern: (object_pattern
        (shorthand_property_identifier_pattern) @component.destructured_prop
      )
      type: (type_annotation (_) @component.props_type)
    )
  )
) @component.func_destructured_props
~~~

### 2.5 Higher-Order Components (HOCs) and Render Props

#### HOC Detection

HOCs are functions that take a component and return a new component. They create "wraps_component" edges:

~~~scm
;; HOC pattern: const Enhanced = withSomething(BaseComponent)
(lexical_declaration
  (variable_declarator
    name: (identifier) @hoc.result_name
    (#match? @hoc.result_name "^[A-Z]")
    value: (call_expression
      function: (identifier) @hoc.wrapper_name
      (#match? @hoc.wrapper_name "^with[A-Z]")
      arguments: (arguments
        (identifier) @hoc.wrapped_component
        (#match? @hoc.wrapped_component "^[A-Z]")
      )
    )
  )
) @hoc.usage

;; Chained HOCs: const Enhanced = compose(withA, withB)(Component)
(lexical_declaration
  (variable_declarator
    name: (identifier) @hoc.result_name
    value: (call_expression
      function: (call_expression
        function: (identifier) @hoc.compose_fn
        (#match? @hoc.compose_fn "^compose$")
      )
      arguments: (arguments
        (identifier) @hoc.base_component
      )
    )
  )
) @hoc.composed

;; HOC definition: function withSomething(WrappedComponent) { ... }
(function_declaration
  name: (identifier) @hoc.def_name
  (#match? @hoc.def_name "^with[A-Z]")
  parameters: (formal_parameters
    (identifier) @hoc.param_component
  )
) @hoc.definition
~~~

#### Render Props Detection

~~~scm
;; Render prop pattern: <DataProvider render={(data) => <Child data={data} />} />
(jsx_attribute
  (property_identifier) @render_prop.name
  (#match? @render_prop.name "^(render|children)$")
  (jsx_expression
    (arrow_function) @render_prop.callback
  )
) @render_prop.usage

;; Children as function: <DataProvider>{(data) => <Child />}</DataProvider>
(jsx_element
  (jsx_opening_element
    name: (identifier) @render_prop.provider
    (#match? @render_prop.provider "^[A-Z]")
  )
  (jsx_expression
    (arrow_function) @render_prop.children_fn
  )
) @render_prop.children_as_function
~~~

### 2.6 React.lazy and Dynamic Component Loading

~~~scm
;; React.lazy: const LazyComponent = React.lazy(() => import('./Component'))
(lexical_declaration
  (variable_declarator
    name: (identifier) @lazy.component_name
    value: (call_expression
      function: (member_expression
        object: (identifier) @_react
        (#eq? @_react "React")
        property: (property_identifier) @_lazy
        (#eq? @_lazy "lazy")
      )
      arguments: (arguments
        (arrow_function
          body: (call_expression
            function: (import) @lazy.dynamic_import
            arguments: (arguments
              (string) @lazy.source
            )
          )
        )
      )
    )
  )
) @lazy.definition

;; Standalone lazy: const LazyComp = lazy(() => import('./Comp'))
(lexical_declaration
  (variable_declarator
    name: (identifier) @lazy.component_name
    value: (call_expression
      function: (identifier) @_lazy
      (#eq? @_lazy "lazy")
      arguments: (arguments
        (arrow_function
          body: (call_expression
            function: (import)
            arguments: (arguments
              (string) @lazy.source
            )
          )
        )
      )
    )
  )
) @lazy.standalone
~~~

**Graph Implications for Lazy Components**:
- Create `lazy_loads` edge type (distinct from regular `depends_on`)
- These are code-split boundaries - important for understanding bundle structure
- The dynamic import path is usually statically resolvable (string literal)
- Mark the edge as `async: true` to indicate runtime loading

### 2.7 Component Hierarchy Reconstruction

To build a complete component tree from JSX analysis:

~~~python
from dataclasses import dataclass, field

@dataclass
class ComponentNode:
    """Represents a React component in the knowledge graph."""
    name: str
    file_path: str
    kind: str  # "function", "class", "arrow", "forwardRef", "memo"
    props_type: str | None = None  # TypeScript props interface/type name
    props: list[dict] = field(default_factory=list)  # [{name, type, required}]
    hooks_used: list[str] = field(default_factory=list)
    children_components: list[str] = field(default_factory=list)  # Components rendered
    is_default_export: bool = False
    is_lazy: bool = False
    is_memo: bool = False
    is_forward_ref: bool = False
    hoc_wrappers: list[str] = field(default_factory=list)
    context_consumed: list[str] = field(default_factory=list)
    context_provided: list[str] = field(default_factory=list)
    line_number: int = 0

def detect_component_kind(node) -> str | None:
    """Detect if a Tree-sitter node defines a React component."""
    # Function declaration with uppercase name
    if node.type == "function_declaration":
        name_node = node.child_by_field_name("name")
        if name_node and name_node.text[0:1].isupper():
            return "function"
    
    # Arrow function assigned to uppercase variable
    if node.type == "lexical_declaration":
        for declarator in node.children:
            if declarator.type == "variable_declarator":
                name_node = declarator.child_by_field_name("name")
                value_node = declarator.child_by_field_name("value")
                if (name_node and name_node.text[0:1].isupper() and
                    value_node and value_node.type == "arrow_function"):
                    return "arrow"
    
    # Class extending React.Component or Component
    if node.type in ("class_declaration", "abstract_class_declaration"):
        name_node = node.child_by_field_name("name")
        if name_node and name_node.text[0:1].isupper():
            # Check for React.Component/PureComponent in heritage
            for child in node.children:
                if child.type == "class_heritage":
                    heritage_text = child.text.decode()
                    if "Component" in heritage_text or "PureComponent" in heritage_text:
                        return "class"
    
    return None
~~~


---

## 3. TypeScript-Specific Constructs

TypeScript adds 64 additional named node types beyond JavaScript (183 vs 119). This section documents how to extract each major construct via Tree-sitter and what graph nodes/edges each should produce.

### 3.1 Interfaces

**Tree-sitter Node Types**:
- `interface_declaration`: fields=`[body, name, type_parameters]`, children=`[extends_type_clause]`
- `interface_body`: children=`[call_signature, construct_signature, export_statement, index_signature, method_signature, property_signature]`
- `extends_type_clause`: fields=`[type]`

#### Extraction Queries

~~~scm
;; Interface declaration with optional extends and type parameters
(interface_declaration
  name: (type_identifier) @interface.name
  type_parameters: (type_parameters
    (type_parameter
      name: (type_identifier) @interface.type_param
      constraint: (constraint (_) @interface.type_constraint)?
      value: (default_type (_) @interface.type_default)?
    )
  )?
  (extends_type_clause
    (_) @interface.extends
  )?
  body: (interface_body) @interface.body
) @interface.def

;; Interface property signatures
(interface_body
  (property_signature
    name: (property_identifier) @interface_prop.name
    "?"? @interface_prop.optional
    type: (type_annotation (_) @interface_prop.type)
  )
) @interface_prop.container

;; Interface method signatures
(interface_body
  (method_signature
    name: (property_identifier) @interface_method.name
    type_parameters: (type_parameters)? @interface_method.generics
    parameters: (formal_parameters) @interface_method.params
    return_type: (type_annotation (_) @interface_method.return_type)?
  )
) @interface_method.container

;; Interface index signatures: [key: string]: value
(interface_body
  (index_signature
    name: (identifier) @index_sig.key_name
    index_type: (type_annotation (_) @index_sig.key_type)
    type: (type_annotation (_) @index_sig.value_type)
  )
) @index_sig.container

;; Interface call signatures: (arg: Type): ReturnType
(interface_body
  (call_signature
    parameters: (formal_parameters) @call_sig.params
    return_type: (type_annotation (_) @call_sig.return_type)?
  )
) @call_sig.container

;; Interface construct signatures: new (arg: Type): Instance
(interface_body
  (construct_signature
    parameters: (formal_parameters) @construct_sig.params
    type: (type_annotation (_) @construct_sig.return_type)?
  )
) @construct_sig.container
~~~

**Graph Nodes and Edges**:

| Source | Edge Type | Target | Notes |
|--------|-----------|--------|-------|
| Interface | `extends_interface` | Parent Interface | Multiple inheritance allowed |
| Interface | `has_property` | Property | With type, optional flag |
| Interface | `has_method` | Method Signature | With params, return type |
| Class | `implements` | Interface | Via `implements_clause` |
| Interface | `has_type_parameter` | Type Parameter | Generic interfaces |

~~~python
@dataclass
class InterfaceNode:
    name: str
    file_path: str
    type_parameters: list[dict]  # [{name, constraint, default}]
    extends: list[str]           # Parent interface names
    properties: list[dict]       # [{name, type, optional, readonly}]
    methods: list[dict]          # [{name, params, return_type, type_params}]
    index_signatures: list[dict] # [{key_name, key_type, value_type}]
    call_signatures: list[dict]  # [{params, return_type}]
    is_exported: bool = False
    line_number: int = 0
~~~

### 3.2 Generics

**Tree-sitter Node Types**:
- `generic_type`: fields=`[name, type_arguments]` — Usage: `Array<string>`
- `type_parameters`: Container for type parameter declarations
- `type_parameter`: Contains `type_identifier`, optional `constraint`, optional `default_type`
- `type_arguments`: Container for type arguments at usage site
- `constraint`: children=`[type]` — The `extends` constraint on a type parameter
- `default_type`: The default value for a type parameter

#### Extraction Queries

~~~scm
;; Generic type parameter declarations (on functions, classes, interfaces, type aliases)
(type_parameters
  (type_parameter
    name: (type_identifier) @generic.param_name
    constraint: (constraint (_) @generic.constraint)?
    value: (default_type (_) @generic.default)?
  ) @generic.param
) @generic.params

;; Generic type usage: Array<string>, Map<K, V>, Promise<T>
(generic_type
  name: (type_identifier) @generic_usage.name
  (type_arguments
    (_) @generic_usage.arg
  )
) @generic_usage.ref

;; Generic function declaration
(function_declaration
  name: (identifier) @generic_func.name
  type_parameters: (type_parameters
    (type_parameter
      name: (type_identifier) @generic_func.type_param
    )
  )
) @generic_func.def

;; Generic arrow function
;; Note: In TSX, <T> can be ambiguous with JSX. TSX grammar handles this.
(arrow_function
  type_parameters: (type_parameters
    (type_parameter
      name: (type_identifier) @generic_arrow.type_param
    )
  )
) @generic_arrow.def

;; Generic class declaration
(class_declaration
  name: (identifier) @generic_class.name
  type_parameters: (type_parameters
    (type_parameter
      name: (type_identifier) @generic_class.type_param
      constraint: (constraint (_) @generic_class.constraint)?
    )
  )
) @generic_class.def

;; Generic method call: foo<string>(arg)
(call_expression
  function: (identifier) @generic_call.name
  (type_arguments
    (_) @generic_call.type_arg
  )
) @generic_call.invocation
~~~

**Graph Implications**:
- Generic type parameters create `has_type_parameter` edges from the declaring entity
- Constraints create `constrained_by` edges: `T -> constraint_type`
- Generic type usages create `instantiates_generic` edges with specific type arguments
- Important for understanding type relationships and API contracts

### 3.3 Decorators

**Tree-sitter Node Types**:
- `decorator`: children=`[call_expression, identifier, member_expression, parenthesized_expression]`

Decorators appear in two forms:
1. **Simple decorator**: `@Injectable` — child is `identifier`
2. **Factory decorator**: `@Component({...})` — child is `call_expression`
3. **Member decorator**: `@Reflect.metadata(...)` — child is `member_expression`

#### Extraction Queries

~~~scm
;; Class decorator (simple): @Injectable
(class_declaration
  decorator: (decorator
    (identifier) @class_decorator.name
  )
  name: (identifier) @class_decorator.class_name
) @class_decorator.def

;; Class decorator (factory): @Component({ selector: 'app-root' })
(class_declaration
  decorator: (decorator
    (call_expression
      function: (identifier) @class_decorator.name
      arguments: (arguments) @class_decorator.args
    )
  )
  name: (identifier) @class_decorator.class_name
) @class_decorator.factory

;; Method decorator: @Get('/path')
(method_definition
  decorator: (decorator
    (call_expression
      function: (identifier) @method_decorator.name
      arguments: (arguments) @method_decorator.args
    )
  )
  name: (property_identifier) @method_decorator.method_name
) @method_decorator.def

;; Method decorator (simple): @Override
(method_definition
  decorator: (decorator
    (identifier) @method_decorator.name
  )
  name: (property_identifier) @method_decorator.method_name
) @method_decorator.simple

;; Property decorator: @Inject(TOKEN)
(public_field_definition
  decorator: (decorator
    (call_expression
      function: (identifier) @prop_decorator.name
      arguments: (arguments) @prop_decorator.args
    )
  )
  name: (property_identifier) @prop_decorator.prop_name
) @prop_decorator.def

;; Parameter decorator: constructor(@Inject(TOKEN) private service: Service)
;; Note: Tree-sitter represents parameter decorators within formal_parameters
(required_parameter
  decorator: (decorator
    (call_expression
      function: (identifier) @param_decorator.name
      arguments: (arguments) @param_decorator.args
    )
  )
  pattern: (identifier) @param_decorator.param_name
) @param_decorator.def

;; Abstract class with decorators
(abstract_class_declaration
  decorator: (decorator
    (call_expression
      function: (identifier) @abstract_decorator.name
      arguments: (arguments) @abstract_decorator.args
    )
  )
  name: (identifier) @abstract_decorator.class_name
) @abstract_decorator.def
~~~

**Decorator Argument Extraction** (for framework-specific analysis):

~~~python
def extract_decorator_metadata(decorator_node, source: bytes) -> dict:
    """Extract decorator name and arguments for framework analysis."""
    result = {"name": None, "args": None, "kind": None}
    
    for child in decorator_node.children:
        if child.type == "identifier":
            result["name"] = child.text.decode()
            result["kind"] = "simple"
        elif child.type == "call_expression":
            func = child.child_by_field_name("function")
            args = child.child_by_field_name("arguments")
            if func:
                result["name"] = func.text.decode()
            if args:
                result["args"] = args.text.decode()
            result["kind"] = "factory"
        elif child.type == "member_expression":
            result["name"] = child.text.decode()
            result["kind"] = "member"
    
    return result
~~~

**Graph Implications**:
- Decorators create `decorated_by` edges from the target to the decorator
- Framework decorators (Angular `@Component`, NestJS `@Controller`) create additional semantic edges
- Decorator arguments often contain metadata critical for framework pattern detection
- TC39 Stage 3 decorators have slightly different semantics but same AST structure


### 3.4 Type Guards

Type guards narrow types at runtime and create implicit type relationships in the graph.

**Tree-sitter Node Types**:
- `type_predicate`: fields=`[name, type]` — The `param is Type` return type
- `as_expression`: children=`[expression, type]` — Type assertion `expr as Type`
- `type_assertion`: children=`[expression, type_arguments]` — Legacy `<Type>expr`

#### Extraction Queries

~~~scm
;; User-defined type guard: function isFoo(x: any): x is Foo
(function_declaration
  name: (identifier) @type_guard.name
  parameters: (formal_parameters
    (required_parameter
      pattern: (identifier) @type_guard.param
    )
  )
  return_type: (type_annotation
    (type_predicate
      name: (identifier) @type_guard.narrowed_param
      type: (_) @type_guard.narrowed_type
    )
  )
) @type_guard.def

;; Arrow function type guard
(variable_declarator
  name: (identifier) @type_guard.name
  value: (arrow_function
    return_type: (type_annotation
      (type_predicate
        name: (identifier) @type_guard.narrowed_param
        type: (_) @type_guard.narrowed_type
      )
    )
  )
) @type_guard.arrow_def

;; typeof checks: typeof x === 'string'
(binary_expression
  left: (unary_expression
    operator: "typeof"
    argument: (identifier) @typeof_guard.variable
  )
  operator: ["===" "=="]
  right: (string) @typeof_guard.type_string
) @typeof_guard.check

;; instanceof checks: x instanceof Foo
(binary_expression
  left: (identifier) @instanceof_guard.variable
  operator: "instanceof"
  right: (identifier) @instanceof_guard.class_name
) @instanceof_guard.check

;; 'in' operator guard: 'prop' in obj
(binary_expression
  left: (string) @in_guard.property
  operator: "in"
  right: (identifier) @in_guard.object
) @in_guard.check

;; Type assertions: expr as Type
(as_expression
  (identifier) @assertion.expr
  (type_identifier) @assertion.target_type
) @assertion.as

;; Non-null assertion: expr!
(non_null_expression
  (identifier) @non_null.expr
) @non_null.assertion
~~~

**Graph Implications**:
- Type guard functions create `narrows_to` edges: `guard_function -> target_type`
- `instanceof` checks create implicit `checked_against` edges to classes
- Type assertions create `asserted_as` edges (weaker than type guard edges)
- These edges help understand type flow and runtime type checking patterns

### 3.5 Enums

**Tree-sitter Node Types**:
- `enum_declaration`: fields=`[body, name]`
- `enum_body`: fields=`[name]`, children=`[enum_assignment]`
- `enum_assignment`: fields=`[name, value]`

#### Extraction Queries

~~~scm
;; Enum declaration with members
(enum_declaration
  name: (identifier) @enum.name
  body: (enum_body
    (property_identifier) @enum.member_name
  )
) @enum.def

;; Enum with explicit values
(enum_declaration
  name: (identifier) @enum.name
  body: (enum_body
    (enum_assignment
      name: (property_identifier) @enum.member_name
      value: (_) @enum.member_value
    )
  )
) @enum.with_values

;; Const enum (detected by preceding 'const' keyword)
;; Note: Tree-sitter may represent this differently; check for "const" child
(enum_declaration
  name: (identifier) @const_enum.name
  body: (enum_body) @const_enum.body
) @const_enum.def
;; Filter in post-processing by checking if source text starts with "const enum"

;; Enum member access: MyEnum.Value
(member_expression
  object: (identifier) @enum_access.enum_name
  property: (property_identifier) @enum_access.member_name
) @enum_access.usage
;; Note: Requires cross-referencing with known enum names to distinguish from
;; regular member access. Build an enum registry during extraction.
~~~

**Enum Classification**:

~~~python
def classify_enum(enum_node, source: bytes) -> dict:
    """Classify enum type and extract members."""
    text = source[enum_node.start_byte:enum_node.end_byte].decode()
    is_const = text.strip().startswith("const enum")
    
    members = []
    body = enum_node.child_by_field_name("body")
    if body:
        for child in body.children:
            if child.type == "property_identifier":
                # Auto-numbered member
                members.append({"name": child.text.decode(), "value": None, "kind": "auto"})
            elif child.type == "enum_assignment":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")
                value_text = value_node.text.decode() if value_node else None
                # Determine enum kind from value
                kind = "numeric"
                if value_text and (value_text.startswith('"') or value_text.startswith("'")):
                    kind = "string"
                elif value_text and not value_text.isdigit():
                    kind = "computed"
                members.append({
                    "name": name_node.text.decode() if name_node else "?",
                    "value": value_text,
                    "kind": kind,
                })
    
    return {
        "is_const": is_const,
        "is_string_enum": all(m["kind"] == "string" for m in members if m["value"]),
        "is_numeric_enum": all(m["kind"] in ("numeric", "auto") for m in members),
        "has_computed": any(m["kind"] == "computed" for m in members),
        "members": members,
    }
~~~

**Graph Nodes and Edges**:

| Source | Edge Type | Target | Notes |
|--------|-----------|--------|-------|
| Enum | `has_member` | Enum Member | With value and kind |
| Function/Variable | `uses_enum` | Enum | When enum is referenced |
| Enum Member | `has_value` | Literal | For explicit values |

### 3.6 Type Aliases

**Tree-sitter Node Types**:
- `type_alias_declaration`: fields=`[name, type_parameters, value]`
- `union_type`: children=`[type]` — `A | B | C`
- `intersection_type`: children=`[type]` — `A & B & C`
- `conditional_type`: fields=`[alternative, consequence, left, right]` — `T extends U ? X : Y`
- `mapped_type`: (Note: listed as missing in node types, may be represented differently)
- `template_literal_type`: children=`[string_fragment, template_type]`

#### Extraction Queries

~~~scm
;; Simple type alias: type Name = string
(type_alias_declaration
  name: (type_identifier) @type_alias.name
  value: (_) @type_alias.value
) @type_alias.def

;; Generic type alias: type Container<T> = { value: T }
(type_alias_declaration
  name: (type_identifier) @type_alias.name
  type_parameters: (type_parameters
    (type_parameter
      name: (type_identifier) @type_alias.type_param
    )
  )
  value: (_) @type_alias.value
) @type_alias.generic

;; Union type: type Result = Success | Failure
(type_alias_declaration
  name: (type_identifier) @union.name
  value: (union_type
    (_) @union.member
  )
) @union.def

;; Intersection type: type Combined = A & B
(type_alias_declaration
  name: (type_identifier) @intersection.name
  value: (intersection_type
    (_) @intersection.member
  )
) @intersection.def

;; Conditional type: type IsString<T> = T extends string ? true : false
(type_alias_declaration
  name: (type_identifier) @conditional.name
  value: (conditional_type
    left: (_) @conditional.check_type
    right: (_) @conditional.extends_type
    consequence: (_) @conditional.true_type
    alternative: (_) @conditional.false_type
  )
) @conditional.def

;; Template literal type: type EventName = `on${string}`
(type_alias_declaration
  name: (type_identifier) @template_type.name
  value: (template_literal_type) @template_type.value
) @template_type.def

;; Indexed access type: type PropType = Obj["key"]
(type_alias_declaration
  name: (type_identifier) @indexed.name
  value: (index_type_query) @indexed.value
) @indexed.def
~~~

**Graph Implications for Type Aliases**:
- Union types create `union_of` edges to each constituent type
- Intersection types create `intersection_of` edges to each constituent type
- Conditional types create `conditional_on` edges with true/false branches
- Type aliases that reference other types create `references_type` edges
- Mapped types create `maps_over` edges to the source type

### 3.7 Utility Types

TypeScript built-in utility types appear as `generic_type` nodes in the AST. They should be recognized and their semantics understood for graph construction:

~~~scm
;; Utility type usage: Partial<T>, Required<T>, Pick<T, K>, etc.
(generic_type
  name: (type_identifier) @utility.name
  (#match? @utility.name "^(Partial|Required|Readonly|Pick|Omit|Record|Exclude|Extract|NonNullable|Parameters|ConstructorParameters|ReturnType|InstanceType|ThisParameterType|OmitThisParameter|ThisType|Awaited|Uppercase|Lowercase|Capitalize|Uncapitalize)$")
  (type_arguments
    (_) @utility.type_arg
  )
) @utility.usage
~~~

**Utility Type Semantic Map**:

| Utility Type | Semantics | Graph Edge |
|---|---|---|
| `Partial<T>` | All properties optional | `derives_partial` -> T |
| `Required<T>` | All properties required | `derives_required` -> T |
| `Readonly<T>` | All properties readonly | `derives_readonly` -> T |
| `Pick<T, K>` | Subset of properties | `picks_from` -> T (with keys K) |
| `Omit<T, K>` | Exclude properties | `omits_from` -> T (with keys K) |
| `Record<K, V>` | Map type | `record_of` -> K, V |
| `Exclude<T, U>` | Remove from union | `excludes_from` -> T |
| `Extract<T, U>` | Extract from union | `extracts_from` -> T |
| `ReturnType<T>` | Function return type | `return_type_of` -> T |
| `Parameters<T>` | Function parameters | `parameters_of` -> T |
| `InstanceType<T>` | Constructor instance | `instance_of` -> T |
| `Awaited<T>` | Unwrap Promise | `awaited_type_of` -> T |

### 3.8 Declaration Merging

TypeScript allows multiple declarations with the same name to merge:

#### Interface Merging

~~~typescript
// Both declarations merge into a single interface
interface User {
  name: string;
}
interface User {
  age: number;
}
// Result: User has both name and age
~~~

**Detection Strategy**:

~~~python
def detect_declaration_merging(file_declarations: list[dict]) -> list[dict]:
    """Detect merged declarations within a file."""
    name_groups = {}
    for decl in file_declarations:
        key = (decl["name"], decl["kind"])
        name_groups.setdefault(key, []).append(decl)
    
    merged = []
    for (name, kind), decls in name_groups.items():
        if len(decls) > 1:
            merged.append({
                "name": name,
                "kind": kind,
                "declaration_count": len(decls),
                "lines": [d["line"] for d in decls],
                "merge_type": classify_merge(kind),
            })
    return merged

def classify_merge(kind: str) -> str:
    """Classify the type of declaration merging."""
    merge_rules = {
        "interface": "interface_merging",      # Interfaces merge members
        "namespace": "namespace_merging",      # Namespaces merge members
        "enum": "enum_merging",                # Enums can merge (rare)
        "function": "function_overloading",    # Function overloads
        "class": "module_augmentation",        # Via declare module
    }
    return merge_rules.get(kind, "unknown")
~~~

#### Module Augmentation

~~~scm
;; Module augmentation: declare module 'express' { interface Request { user: User } }
(ambient_declaration
  (internal_module
    name: (string) @augment.module_name
    body: (statement_block
      (interface_declaration
        name: (type_identifier) @augment.interface_name
      )
    )
  )
) @augment.module

;; Global augmentation: declare global { interface Window { myProp: string } }
(ambient_declaration
  (internal_module
    name: (identifier) @_global
    (#eq? @_global "global")
    body: (statement_block) @augment.global_body
  )
) @augment.global
~~~

**Graph Implications**:
- Merged interfaces create `merges_with` edges between declaration sites
- Module augmentation creates `augments_module` edges to the target module
- Global augmentation creates `augments_global` edges
- The graph should represent the merged result as a single logical node with multiple source locations

### 3.9 Ambient Declarations

**Tree-sitter Node Types**:
- `ambient_declaration`: children=`[declaration, property_identifier, statement_block, type]`

~~~scm
;; declare function: declare function foo(x: string): void
(ambient_declaration
  (function_signature
    name: (identifier) @ambient.func_name
    parameters: (formal_parameters) @ambient.params
    return_type: (type_annotation (_) @ambient.return_type)?
  )
) @ambient.function

;; declare class: declare class Foo { ... }
(ambient_declaration
  (class_declaration
    name: (identifier) @ambient.class_name
  )
) @ambient.class

;; declare const/let/var: declare const VERSION: string
(ambient_declaration
  (lexical_declaration
    (variable_declarator
      name: (identifier) @ambient.var_name
      type: (type_annotation (_) @ambient.var_type)
    )
  )
) @ambient.variable

;; declare enum: declare enum Direction { Up, Down }
(ambient_declaration
  (enum_declaration
    name: (identifier) @ambient.enum_name
  )
) @ambient.enum

;; declare module: declare module 'foo' { ... }
(ambient_declaration
  (internal_module
    name: (string) @ambient.module_name
    body: (statement_block) @ambient.module_body
  )
) @ambient.module

;; declare namespace: declare namespace Foo { ... }
(ambient_declaration
  (internal_module
    name: (identifier) @ambient.namespace_name
    body: (statement_block) @ambient.namespace_body
  )
) @ambient.namespace
~~~

**Graph Implications for .d.ts Files**:
- `.d.ts` files contain only ambient declarations (type information, no runtime code)
- All declarations in `.d.ts` files are implicitly ambient
- Create `declares_type_for` edges from `.d.ts` files to the modules they describe
- Important for understanding third-party library type interfaces

### 3.10 Namespaces

**Tree-sitter Node Types**:
- `internal_module`: fields=`[body, name]` — Represents both `namespace` and `module` keywords

~~~scm
;; Namespace declaration: namespace MyNamespace { ... }
(internal_module
  name: (identifier) @namespace.name
  body: (statement_block) @namespace.body
) @namespace.def

;; Nested namespace: namespace Outer.Inner { ... }
(internal_module
  name: (nested_identifier
    (identifier) @namespace.outer
    (identifier) @namespace.inner
  )
  body: (statement_block) @namespace.body
) @namespace.nested

;; Exported namespace member
(internal_module
  body: (statement_block
    (export_statement
      declaration: (_) @namespace.exported_member
    )
  )
) @namespace.with_exports
~~~

**Note**: The `module` keyword (legacy) and `namespace` keyword produce the same `internal_module` node type. Distinguish by checking the source text if needed.

### 3.11 Abstract Classes

**Tree-sitter Node Types**:
- `abstract_class_declaration`: fields=`[body, decorator, name, type_parameters]`, children=`[class_heritage]`
- `abstract_method_signature`: fields=`[name, parameters, return_type, type_parameters]`, children=`[accessibility_modifier, override_modifier]`

~~~scm
;; Abstract class declaration
(abstract_class_declaration
  name: (identifier) @abstract_class.name
  type_parameters: (type_parameters)? @abstract_class.generics
  (class_heritage
    (extends_clause
      value: (_) @abstract_class.extends
    )?
    (implements_clause
      (_) @abstract_class.implements
    )?
  )?
  body: (class_body) @abstract_class.body
) @abstract_class.def

;; Abstract method signature
(abstract_method_signature
  (accessibility_modifier)? @abstract_method.access
  name: (property_identifier) @abstract_method.name
  type_parameters: (type_parameters)? @abstract_method.generics
  parameters: (formal_parameters) @abstract_method.params
  return_type: (type_annotation (_) @abstract_method.return_type)?
) @abstract_method.def

;; Concrete class extending abstract class
(class_declaration
  name: (identifier) @concrete.name
  (class_heritage
    (extends_clause
      value: (identifier) @concrete.extends_abstract
    )
  )
) @concrete.def
;; Cross-reference with known abstract classes to create proper edges
~~~

**Graph Implications**:
- Abstract classes create `abstract_class` nodes (cannot be instantiated directly)
- Abstract methods create `must_implement` edges to concrete subclasses
- `extends` from concrete to abstract creates `extends_abstract` edge type
- Important for understanding class hierarchies and contract enforcement

### 3.12 Function and Method Overloads

**Tree-sitter Node Types**:
- `function_signature`: fields=`[name, parameters, return_type, type_parameters]` — Overload signature
- `function_declaration`: The implementation signature

TypeScript overloads appear as multiple `function_signature` nodes followed by a single `function_declaration`:

~~~scm
;; Function overload signatures
(function_signature
  name: (identifier) @overload.name
  parameters: (formal_parameters) @overload.params
  return_type: (type_annotation (_) @overload.return_type)?
) @overload.signature

;; The implementation follows the overload signatures
(function_declaration
  name: (identifier) @overload.impl_name
  parameters: (formal_parameters) @overload.impl_params
  return_type: (type_annotation (_) @overload.impl_return_type)?
  body: (statement_block) @overload.impl_body
) @overload.implementation

;; Method overloads in classes/interfaces
(method_signature
  name: (property_identifier) @method_overload.name
  parameters: (formal_parameters) @method_overload.params
  return_type: (type_annotation (_) @method_overload.return_type)?
) @method_overload.signature
~~~

**Overload Detection Strategy**:

~~~python
def detect_overloads(declarations: list[dict]) -> list[dict]:
    """Group overload signatures with their implementation."""
    overload_groups = {}
    
    for decl in declarations:
        if decl["kind"] == "function_signature":
            name = decl["name"]
            overload_groups.setdefault(name, {"signatures": [], "implementation": None})
            overload_groups[name]["signatures"].append(decl)
        elif decl["kind"] == "function_declaration":
            name = decl["name"]
            if name in overload_groups:
                overload_groups[name]["implementation"] = decl
    
    return [
        {
            "name": name,
            "signature_count": len(group["signatures"]),
            "has_implementation": group["implementation"] is not None,
            "signatures": group["signatures"],
            "implementation": group["implementation"],
        }
        for name, group in overload_groups.items()
        if len(group["signatures"]) > 0
    ]
~~~

**Graph Implications**:
- Overloaded functions create a single function node with multiple signature edges
- Each signature creates a `has_overload_signature` edge with parameter types and return type
- The implementation creates a `has_implementation` edge
- Callers should be matched against the most specific applicable signature

### 3.13 Accessibility Modifiers

~~~scm
;; Public/private/protected members
(method_definition
  (accessibility_modifier) @access.modifier
  name: (property_identifier) @access.method_name
) @access.method

(public_field_definition
  (accessibility_modifier) @access.modifier
  name: (property_identifier) @access.field_name
) @access.field

;; Constructor parameter properties: constructor(private name: string)
(required_parameter
  (accessibility_modifier) @access.modifier
  pattern: (identifier) @access.param_name
  type: (type_annotation (_) @access.param_type)?
) @access.constructor_param
~~~

**Graph Implications**:
- Accessibility modifiers affect edge visibility in the graph
- `private` members should only have incoming edges from within the same class
- `protected` members can have edges from subclasses
- `public` members (default) can have edges from anywhere
- Constructor parameter properties simultaneously create a parameter and a class field


---

## 4. Dynamic Imports and Require Patterns

### 4.1 Static vs Dynamic Import Classification

For knowledge graph construction, the critical question is: can we resolve the import target at parse time?

| Pattern | Resolvable? | Confidence | Example |
|---------|-------------|------------|----------|
| `import { x } from './foo'` | Yes | 100% | Static ESM import |
| `import('./foo')` | Yes | 100% | Dynamic import with string literal |
| `require('./foo')` | Yes | 100% | Static require |
| `import(variable)` | No | 0% | Fully dynamic |
| `require(variable)` | No | 0% | Fully dynamic |
| `` import(`./locale/${lang}`) `` | Partial | ~60% | Template literal - directory known |
| `require('./handlers/' + name)` | Partial | ~50% | Concatenation - prefix known |
| `require.resolve('./foo')` | Yes | 100% | Path resolution only |
| `import.meta.glob('./pages/*.vue')` | Yes | 95% | Vite glob - pattern known |
| `require.context('./dir', true, /\.js$/)` | Yes | 95% | Webpack context - pattern known |

**Typical Resolvability in Real Codebases**: Research and industry experience suggest that 85-95% of imports in well-structured codebases are statically resolvable. The remaining 5-15% are typically:
- Plugin/extension loading systems
- Locale/i18n file loading
- Dynamic route-based code splitting
- Configuration-driven module loading

### 4.2 Tree-sitter Queries for Dynamic Imports

#### Static Dynamic Import (Resolvable)

~~~scm
;; Dynamic import with string literal: import('./module')
(call_expression
  function: (import)
  arguments: (arguments
    (string) @dynamic_import.source
  )
) @dynamic_import.static

;; Dynamic import with template literal (partially resolvable)
(call_expression
  function: (import)
  arguments: (arguments
    (template_string) @dynamic_import.template
  )
) @dynamic_import.template_literal

;; Dynamic import with variable (not resolvable)
(call_expression
  function: (import)
  arguments: (arguments
    (identifier) @dynamic_import.variable
  )
) @dynamic_import.variable_ref

;; Dynamic import with expression (not resolvable)
(call_expression
  function: (import)
  arguments: (arguments
    (binary_expression) @dynamic_import.expression
  )
) @dynamic_import.computed
~~~

#### Conditional Require Patterns

~~~scm
;; Conditional require in if statement
(if_statement
  condition: (_) @conditional_require.condition
  consequence: (_
    (expression_statement
      (assignment_expression
        right: (call_expression
          function: (identifier) @_func
          (#eq? @_func "require")
          arguments: (arguments
            (string) @conditional_require.source
          )
        )
      )
    )
  )
) @conditional_require.if_block

;; Ternary require: const mod = condition ? require('a') : require('b')
(variable_declarator
  name: (identifier) @ternary_require.name
  value: (ternary_expression
    consequence: (call_expression
      function: (identifier) @_func1
      (#eq? @_func1 "require")
      arguments: (arguments (string) @ternary_require.source_a)
    )
    alternative: (call_expression
      function: (identifier) @_func2
      (#eq? @_func2 "require")
      arguments: (arguments (string) @ternary_require.source_b)
    )
  )
) @ternary_require.def

;; Try-catch require (optional dependency)
(try_statement
  body: (statement_block
    (expression_statement
      (assignment_expression
        right: (call_expression
          function: (identifier) @_func
          (#eq? @_func "require")
          arguments: (arguments
            (string) @optional_require.source
          )
        )
      )
    )
  )
  (catch_clause) @optional_require.fallback
) @optional_require.try_block
~~~

**Graph Implications for Conditional Requires**:
- Both branches of conditional requires should create edges, marked as `conditional: true`
- Try-catch requires create `optional_depends_on` edges
- The condition expression can be stored as metadata for analysis

### 4.3 Webpack-Specific Patterns

#### require.context()

~~~scm
;; require.context('./dir', recursive, /pattern/)
(call_expression
  function: (member_expression
    object: (identifier) @_req
    (#eq? @_req "require")
    property: (property_identifier) @_ctx
    (#eq? @_ctx "context")
  )
  arguments: (arguments
    (string) @webpack_context.directory
    (true)? @webpack_context.recursive
    (regex)? @webpack_context.pattern
  )
) @webpack_context.call
~~~

**Handling Strategy**:

~~~python
import re
from pathlib import Path

def resolve_require_context(
    directory: str,
    recursive: bool,
    pattern: str | None,
    base_path: str
) -> list[str]:
    """Resolve webpack require.context to actual file paths."""
    search_dir = Path(base_path).parent / directory
    if not search_dir.exists():
        return []
    
    regex = re.compile(pattern) if pattern else re.compile(r"\.\w+$")
    results = []
    
    if recursive:
        for path in search_dir.rglob("*"):
            if path.is_file() and regex.search(str(path)):
                results.append(str(path))
    else:
        for path in search_dir.iterdir():
            if path.is_file() and regex.search(str(path)):
                results.append(str(path))
    
    return results
~~~

#### Webpack Magic Comments

~~~scm
;; Dynamic import with webpack magic comments
;; import(/* webpackChunkName: "my-chunk" */ './module')
(call_expression
  function: (import)
  arguments: (arguments
    (comment)? @webpack_magic.comment
    (string) @webpack_magic.source
  )
) @webpack_magic.import
~~~

### 4.4 Vite-Specific Patterns

#### import.meta.glob

~~~scm
;; import.meta.glob('./pages/*.vue')
(call_expression
  function: (member_expression
    object: (member_expression
      object: (identifier) @_import
      (#eq? @_import "import")
      property: (property_identifier) @_meta
      (#eq? @_meta "meta")
    )
    property: (property_identifier) @_glob
    (#eq? @_glob "glob")
  )
  arguments: (arguments
    [
      (string) @vite_glob.pattern
      (array
        (string) @vite_glob.pattern
      )
    ]
  )
) @vite_glob.call

;; import.meta.glob with options: import.meta.glob('./pages/*.vue', { eager: true })
(call_expression
  function: (member_expression
    object: (member_expression
      object: (identifier) @_import
      property: (property_identifier) @_meta
    )
    property: (property_identifier) @_glob
    (#eq? @_glob "glob")
  )
  arguments: (arguments
    (string) @vite_glob_opts.pattern
    (object) @vite_glob_opts.options
  )
) @vite_glob_opts.call

;; import.meta.env access
(member_expression
  object: (member_expression
    object: (identifier) @_import
    (#eq? @_import "import")
    property: (property_identifier) @_meta
    (#eq? @_meta "meta")
  )
  property: (property_identifier) @import_meta.property
) @import_meta.access
~~~

**Handling Strategy for import.meta.glob**:

~~~python
import glob as glob_module
from pathlib import Path

def resolve_vite_glob(
    patterns: list[str],
    base_path: str,
    eager: bool = False
) -> list[dict]:
    """Resolve Vite import.meta.glob patterns to file paths."""
    results = []
    base_dir = Path(base_path).parent
    
    for pattern in patterns:
        # Vite glob uses fast-glob syntax (similar to standard glob)
        # Resolve relative to the importing file
        full_pattern = str(base_dir / pattern)
        matched_files = glob_module.glob(full_pattern, recursive=True)
        
        for filepath in matched_files:
            results.append({
                "path": filepath,
                "pattern": pattern,
                "eager": eager,
                "import_type": "eager" if eager else "lazy",
            })
    
    return results
~~~

### 4.5 import.meta Properties

`import.meta` is an ESM-only feature that provides metadata about the current module:

| Property | Description | Graph Relevance |
|----------|-------------|------------------|
| `import.meta.url` | File URL of current module | Identifies ESM context |
| `import.meta.resolve()` | Resolve module specifier | Module resolution |
| `import.meta.glob()` | Vite glob import | Batch dependency edges |
| `import.meta.env` | Vite environment variables | Configuration metadata |
| `import.meta.hot` | Vite HMR API | Development-only |
| `import.meta.dirname` | Node.js 21.2+ | Directory path (ESM equivalent of __dirname) |
| `import.meta.filename` | Node.js 21.2+ | File path (ESM equivalent of __filename) |

### 4.6 Dynamic Import Graph Edge Classification

~~~python
from enum import Enum

class DynamicImportResolvability(Enum):
    STATIC = "static"           # String literal - fully resolvable
    TEMPLATE_PREFIX = "prefix"  # Template with known prefix
    GLOB_PATTERN = "glob"       # Glob pattern - resolvable to file set
    CONDITIONAL = "conditional" # Multiple possible targets
    UNRESOLVABLE = "unresolvable"  # Fully dynamic

@dataclass
class DynamicImportEdge:
    source_file: str
    raw_specifier: str
    resolvability: DynamicImportResolvability
    resolved_paths: list[str]  # Empty if unresolvable
    is_lazy: bool = True       # Dynamic imports are lazy by default
    chunk_name: str | None = None  # Webpack chunk name
    is_eager: bool = False     # Vite eager option
    condition: str | None = None   # For conditional imports
    line_number: int = 0
~~~


---

## 5. Module Path Resolution

Module path resolution is the process of converting a module specifier (e.g., `'./utils'`, `'react'`, `'@company/shared'`) into an actual file path on disk. This is essential for building accurate dependency edges in the knowledge graph.

### 5.1 Node.js Resolution Algorithm

Node.js uses a well-defined algorithm (documented in the Node.js docs) that differs between CommonJS and ESM:

#### CommonJS Resolution (require())

~~~
require(X) from module at path Y:

1. If X is a core module (fs, path, http, etc.):
   a. Return the core module
   b. STOP

2. If X begins with '/' or './' or '../':
   a. LOAD_AS_FILE(Y + X)
   b. LOAD_AS_DIRECTORY(Y + X)
   c. THROW "not found"

3. If X begins with '#':
   a. LOAD_PACKAGE_IMPORTS(X, dirname(Y))

4. LOAD_PACKAGE_SELF(X, dirname(Y))
5. LOAD_NODE_MODULES(X, dirname(Y))
6. THROW "not found"

LOAD_AS_FILE(X):
  1. If X is a file, load X. STOP
  2. If X.js is a file, load X.js. STOP
  3. If X.json is a file, load X.json. STOP
  4. If X.node is a file, load X.node. STOP

LOAD_AS_DIRECTORY(X):
  1. If X/package.json exists and has "main" field M:
     a. LOAD_AS_FILE(X/M)
     b. LOAD_INDEX(X/M)
  2. LOAD_INDEX(X)

LOAD_INDEX(X):
  1. If X/index.js is a file, load X/index.js. STOP
  2. If X/index.json is a file, load X/index.json. STOP
  3. If X/index.node is a file, load X/index.node. STOP

LOAD_NODE_MODULES(X, START):
  1. let DIRS = NODE_MODULES_PATHS(START)
  2. for each DIR in DIRS:
     a. LOAD_PACKAGE_EXPORTS(X, DIR)
     b. LOAD_AS_FILE(DIR/X)
     c. LOAD_AS_DIRECTORY(DIR/X)

NODE_MODULES_PATHS(START):
  1. let PARTS = path split(START)
  2. let I = count of PARTS - 1
  3. let DIRS = []
  4. while I >= 0:
     a. if PARTS[I] = "node_modules" CONTINUE
     b. DIR = path join(PARTS[0..I] + "node_modules")
     c. DIRS = DIRS + DIR
     d. I = I - 1
  5. return DIRS + GLOBAL_FOLDERS
~~~

#### ESM Resolution

ESM resolution is stricter than CJS:
- File extensions are REQUIRED (no automatic `.js` appending)
- No `index.js` automatic resolution for directories
- No `require.extensions` or `require.cache`
- `package.json` `"exports"` field takes precedence over `"main"`

### 5.2 Python Implementation of Module Resolver

~~~python
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

# Node.js core modules (not exhaustive - add as needed)
NODE_CORE_MODULES = {
    "assert", "buffer", "child_process", "cluster", "console", "constants",
    "crypto", "dgram", "dns", "domain", "events", "fs", "http", "https",
    "module", "net", "os", "path", "perf_hooks", "process", "punycode",
    "querystring", "readline", "repl", "stream", "string_decoder", "sys",
    "timers", "tls", "tty", "url", "util", "v8", "vm", "worker_threads",
    "zlib",
}

# Also handle node: prefix
def is_core_module(specifier: str) -> bool:
    """Check if a module specifier refers to a Node.js core module."""
    if specifier.startswith("node:"):
        return True
    return specifier in NODE_CORE_MODULES

@dataclass
class ResolverConfig:
    """Configuration for the module resolver."""
    project_root: str
    ts_config_paths: dict[str, list[str]] = field(default_factory=dict)
    ts_base_url: str | None = None
    webpack_aliases: dict[str, str] = field(default_factory=dict)
    vite_aliases: dict[str, str] = field(default_factory=dict)
    package_json_cache: dict[str, dict] = field(default_factory=dict)

    # File extensions to try, in order
    js_extensions: tuple = (".js", ".jsx", ".mjs", ".cjs")
    ts_extensions: tuple = (".ts", ".tsx", ".mts", ".cts", ".d.ts")
    all_extensions: tuple = (
        ".ts", ".tsx", ".mts", ".cts",
        ".js", ".jsx", ".mjs", ".cjs",
        ".json", ".node",
    )
    index_files: tuple = (
        "index.ts", "index.tsx", "index.js", "index.jsx",
        "index.mts", "index.mjs", "index.json",
    )


class ModuleResolver:
    """Resolve JS/TS module specifiers to file paths."""

    def __init__(self, config: ResolverConfig):
        self.config = config

    def resolve(
        self,
        specifier: str,
        from_file: str,
    ) -> Optional[str]:
        """Resolve a module specifier to an absolute file path.
        
        Args:
            specifier: The module specifier (e.g., './utils', 'react', '@co/pkg')
            from_file: The absolute path of the file containing the import
        
        Returns:
            Absolute file path or None if unresolvable
        """
        # 1. Core modules
        if is_core_module(specifier):
            return f"node:{specifier.removeprefix('node:')}"

        # 2. Relative paths
        if specifier.startswith(".") or specifier.startswith("/"):
            return self._resolve_relative(specifier, from_file)

        # 3. TypeScript path mappings
        resolved = self._resolve_ts_paths(specifier, from_file)
        if resolved:
            return resolved

        # 4. Bundler aliases (webpack/vite)
        resolved = self._resolve_aliases(specifier, from_file)
        if resolved:
            return resolved

        # 5. Package imports (# prefix)
        if specifier.startswith("#"):
            return self._resolve_package_imports(specifier, from_file)

        # 6. node_modules resolution
        return self._resolve_node_modules(specifier, from_file)

    def _resolve_relative(self, specifier: str, from_file: str) -> Optional[str]:
        """Resolve a relative module specifier."""
        base_dir = Path(from_file).parent
        target = (base_dir / specifier).resolve()

        # Try exact path first
        if target.is_file():
            return str(target)

        # Try with extensions
        for ext in self.config.all_extensions:
            candidate = target.with_suffix(ext)
            if candidate.is_file():
                return str(candidate)
            # Also try: ./foo -> ./foo.ts (not just replacing suffix)
            candidate = Path(str(target) + ext)
            if candidate.is_file():
                return str(candidate)

        # Try as directory with index file
        if target.is_dir():
            # Check package.json main/exports first
            pkg_main = self._resolve_package_main(target)
            if pkg_main:
                return pkg_main
            # Try index files
            for index in self.config.index_files:
                candidate = target / index
                if candidate.is_file():
                    return str(candidate)

        return None

    def _resolve_ts_paths(
        self, specifier: str, from_file: str
    ) -> Optional[str]:
        """Resolve using TypeScript path mappings from tsconfig.json."""
        if not self.config.ts_config_paths:
            return None

        base_url = Path(
            self.config.ts_base_url or self.config.project_root
        )

        for pattern, targets in self.config.ts_config_paths.items():
            # Handle exact match: "@utils": ["./src/utils"]
            if pattern == specifier:
                for target in targets:
                    resolved = self._resolve_relative(
                        target, str(base_url / "dummy.ts")
                    )
                    if resolved:
                        return resolved

            # Handle wildcard: "@utils/*": ["./src/utils/*"]
            if pattern.endswith("/*"):
                prefix = pattern[:-2]
                if specifier.startswith(prefix + "/"):
                    remainder = specifier[len(prefix) + 1:]
                    for target in targets:
                        target_path = target.replace("*", remainder)
                        resolved = self._resolve_relative(
                            target_path, str(base_url / "dummy.ts")
                        )
                        if resolved:
                            return resolved

        return None

    def _resolve_aliases(
        self, specifier: str, from_file: str
    ) -> Optional[str]:
        """Resolve using webpack/vite aliases."""
        all_aliases = {
            **self.config.webpack_aliases,
            **self.config.vite_aliases,
        }

        for alias, target in all_aliases.items():
            if specifier == alias:
                return self._resolve_relative(target, from_file)
            if specifier.startswith(alias + "/"):
                remainder = specifier[len(alias) + 1:]
                full_target = str(Path(target) / remainder)
                return self._resolve_relative(full_target, from_file)

        return None

    def _resolve_node_modules(
        self, specifier: str, from_file: str
    ) -> Optional[str]:
        """Resolve from node_modules directories."""
        # Split scoped packages: @scope/package/path -> (@scope/package, path)
        parts = specifier.split("/")
        if specifier.startswith("@") and len(parts) >= 2:
            package_name = "/".join(parts[:2])
            subpath = "/".join(parts[2:]) if len(parts) > 2 else None
        else:
            package_name = parts[0]
            subpath = "/".join(parts[1:]) if len(parts) > 1 else None

        # Walk up directory tree looking for node_modules
        current = Path(from_file).parent
        while True:
            nm_dir = current / "node_modules" / package_name
            if nm_dir.is_dir():
                # Check package.json exports field first
                pkg_json = nm_dir / "package.json"
                if pkg_json.is_file():
                    resolved = self._resolve_package_exports(
                        pkg_json, subpath
                    )
                    if resolved:
                        return resolved

                # Subpath resolution
                if subpath:
                    resolved = self._resolve_relative(
                        f"./{subpath}", str(nm_dir / "dummy.ts")
                    )
                    if resolved:
                        return resolved

                # Main field / index resolution
                resolved = self._resolve_package_main(nm_dir)
                if resolved:
                    return resolved

            if current == current.parent:
                break
            current = current.parent

        return None

    def _resolve_package_main(self, package_dir: Path) -> Optional[str]:
        """Resolve package entry point from package.json main/module fields."""
        pkg_json = package_dir / "package.json"
        if not pkg_json.is_file():
            return None

        try:
            data = json.loads(pkg_json.read_text())
        except (json.JSONDecodeError, IOError):
            return None

        # Priority: types > typings > module > main
        # (types/typings for TypeScript resolution)
        for field_name in ("types", "typings", "module", "main"):
            main = data.get(field_name)
            if main:
                resolved = self._resolve_relative(
                    f"./{main}", str(package_dir / "dummy.ts")
                )
                if resolved:
                    return resolved

        # Fallback to index files
        for index in self.config.index_files:
            candidate = package_dir / index
            if candidate.is_file():
                return str(candidate)

        return None

    def _resolve_package_exports(
        self, pkg_json_path: Path, subpath: str | None
    ) -> Optional[str]:
        """Resolve using package.json 'exports' field (conditional exports)."""
        try:
            data = json.loads(pkg_json_path.read_text())
        except (json.JSONDecodeError, IOError):
            return None

        exports = data.get("exports")
        if not exports:
            return None

        package_dir = pkg_json_path.parent
        entry_point = f"./{subpath}" if subpath else "."

        resolved_target = self._match_exports(exports, entry_point)
        if resolved_target:
            full_path = (package_dir / resolved_target).resolve()
            if full_path.is_file():
                return str(full_path)

        return None

    def _match_exports(
        self, exports: dict | str | list, entry_point: str
    ) -> Optional[str]:
        """Match an entry point against the exports map."""
        # String shorthand: "exports": "./index.js"
        if isinstance(exports, str):
            if entry_point == ".":
                return exports
            return None

        # Array: try each in order
        if isinstance(exports, list):
            for item in exports:
                result = self._match_exports(item, entry_point)
                if result:
                    return result
            return None

        # Object: could be path map or condition map
        if isinstance(exports, dict):
            # Check if keys are entry points (start with .)
            if any(k.startswith(".") for k in exports):
                # Path map: { ".": "./index.js", "./utils": "./src/utils.js" }
                target = exports.get(entry_point)
                if target:
                    return self._match_exports(target, ".")
                # Wildcard patterns: "./locale/*": "./locale/*.js"
                for pattern, target in exports.items():
                    if "*" in pattern:
                        prefix = pattern.split("*")[0]
                        if entry_point.startswith(prefix):
                            remainder = entry_point[len(prefix):]
                            if isinstance(target, str):
                                return target.replace("*", remainder)
            else:
                # Condition map: { "import": "./esm.js", "require": "./cjs.js" }
                # Priority: types > import > require > default
                for condition in ("types", "import", "require", "default"):
                    if condition in exports:
                        result = self._match_exports(
                            exports[condition], entry_point
                        )
                        if result:
                            return result

        return None

    def _resolve_package_imports(
        self, specifier: str, from_file: str
    ) -> Optional[str]:
        """Resolve #imports from package.json imports field."""
        # Find nearest package.json
        current = Path(from_file).parent
        while True:
            pkg_json = current / "package.json"
            if pkg_json.is_file():
                try:
                    data = json.loads(pkg_json.read_text())
                    imports = data.get("imports", {})
                    if specifier in imports:
                        target = imports[specifier]
                        if isinstance(target, str):
                            return self._resolve_relative(
                                target, str(current / "dummy.ts")
                            )
                        elif isinstance(target, dict):
                            resolved = self._match_exports(target, ".")
                            if resolved:
                                return self._resolve_relative(
                                    resolved, str(current / "dummy.ts")
                                )
                except (json.JSONDecodeError, IOError):
                    pass
            if current == current.parent:
                break
            current = current.parent
        return None
~~~

### 5.3 TypeScript Path Mapping

TypeScript `tsconfig.json` provides path mapping that overrides standard resolution:

~~~json
{
  "compilerOptions": {
    "baseUrl": "./src",
    "paths": {
      "@components/*": ["components/*"],
      "@utils/*": ["utils/*", "shared/utils/*"],
      "@config": ["config/index"],
      "~/*": ["./*"]
    },
    "rootDirs": ["src", "generated"]
  }
}
~~~

**Parsing tsconfig.json for Path Mappings**:

~~~python
def load_ts_config(project_root: str) -> dict:
    """Load and resolve tsconfig.json, handling extends."""
    tsconfig_path = Path(project_root) / "tsconfig.json"
    if not tsconfig_path.exists():
        return {}

    config = _load_tsconfig_with_extends(tsconfig_path)
    compiler_options = config.get("compilerOptions", {})

    return {
        "base_url": _resolve_base_url(
            compiler_options.get("baseUrl"), project_root
        ),
        "paths": compiler_options.get("paths", {}),
        "root_dirs": [
            str((Path(project_root) / d).resolve())
            for d in compiler_options.get("rootDirs", [])
        ],
        "module_resolution": compiler_options.get(
            "moduleResolution", "node"
        ),
        "strict": compiler_options.get("strict", False),
        "target": compiler_options.get("target", "es5"),
        "module": compiler_options.get("module", "commonjs"),
    }

def _load_tsconfig_with_extends(tsconfig_path: Path) -> dict:
    """Recursively load tsconfig.json handling 'extends' field."""
    try:
        # tsconfig.json may have comments - strip them
        text = tsconfig_path.read_text()
        # Simple comment stripping (for production, use a proper JSON5 parser)
        import re
        text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        config = json.loads(text)
    except (json.JSONDecodeError, IOError):
        return {}

    # Handle extends
    extends = config.pop("extends", None)
    if extends:
        if not extends.endswith(".json"):
            extends += ".json"
        parent_path = (tsconfig_path.parent / extends).resolve()
        parent_config = _load_tsconfig_with_extends(parent_path)
        # Deep merge: child overrides parent
        _deep_merge(parent_config, config)
        return parent_config

    return config

def _deep_merge(base: dict, override: dict) -> None:
    """Deep merge override into base dict."""
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value

def _resolve_base_url(
    base_url: str | None, project_root: str
) -> str | None:
    if base_url is None:
        return None
    return str((Path(project_root) / base_url).resolve())
~~~

### 5.4 Package.json "exports" Field (Conditional Exports)

The `exports` field in `package.json` is the modern way to define package entry points:

~~~json
{
  "name": "my-package",
  "exports": {
    ".": {
      "types": "./dist/index.d.ts",
      "import": "./dist/esm/index.js",
      "require": "./dist/cjs/index.js",
      "default": "./dist/esm/index.js"
    },
    "./utils": {
      "types": "./dist/utils.d.ts",
      "import": "./dist/esm/utils.js",
      "require": "./dist/cjs/utils.js"
    },
    "./locale/*": "./locale/*.js",
    "./package.json": "./package.json"
  }
}
~~~

**Key Rules**:
1. `exports` takes precedence over `main`, `module`, `types` when present
2. Only explicitly listed paths are accessible (encapsulation)
3. Condition order matters: first match wins
4. Wildcard `*` enables subpath patterns
5. `null` targets explicitly exclude a path

**Condition Priority for Knowledge Graph** (resolve in this order):
1. `types` — TypeScript type definitions (for type-level edges)
2. `import` — ESM entry point
3. `require` — CJS entry point
4. `default` — Fallback

### 5.5 Monorepo Considerations

Monorepos introduce additional resolution complexity:

#### Workspace Package Resolution

~~~json
// Root package.json
{
  "workspaces": [
    "packages/*",
    "apps/*"
  ]
}
~~~

~~~python
def discover_workspace_packages(project_root: str) -> dict[str, str]:
    """Discover all workspace packages and their paths."""
    root_pkg = Path(project_root) / "package.json"
    if not root_pkg.exists():
        return {}

    data = json.loads(root_pkg.read_text())
    workspace_globs = data.get("workspaces", [])

    # Handle yarn workspaces object format
    if isinstance(workspace_globs, dict):
        workspace_globs = workspace_globs.get("packages", [])

    packages = {}
    for pattern in workspace_globs:
        for pkg_dir in Path(project_root).glob(pattern):
            pkg_json = pkg_dir / "package.json"
            if pkg_json.is_file():
                try:
                    pkg_data = json.loads(pkg_json.read_text())
                    name = pkg_data.get("name")
                    if name:
                        packages[name] = str(pkg_dir)
                except (json.JSONDecodeError, IOError):
                    pass

    return packages


def resolve_workspace_package(
    specifier: str,
    workspace_packages: dict[str, str],
) -> Optional[str]:
    """Resolve a specifier to a workspace package."""
    parts = specifier.split("/")
    # Handle scoped packages
    if specifier.startswith("@") and len(parts) >= 2:
        package_name = "/".join(parts[:2])
        subpath = "/".join(parts[2:]) if len(parts) > 2 else None
    else:
        package_name = parts[0]
        subpath = "/".join(parts[1:]) if len(parts) > 1 else None

    if package_name in workspace_packages:
        pkg_dir = workspace_packages[package_name]
        if subpath:
            # Resolve subpath within workspace package
            return str(Path(pkg_dir) / subpath)
        return pkg_dir

    return None
~~~

#### Monorepo Tools

| Tool | Config File | Workspace Definition | Resolution Strategy |
|------|-------------|---------------------|---------------------|
| npm workspaces | `package.json` | `"workspaces"` array | Symlinks in root `node_modules` |
| Yarn workspaces | `package.json` | `"workspaces"` array/object | Hoisted `node_modules` |
| pnpm workspaces | `pnpm-workspace.yaml` | `packages` array | Content-addressable store + symlinks |
| Lerna | `lerna.json` | `"packages"` array | Delegates to npm/yarn/pnpm |
| Turborepo | `turbo.json` | Uses npm/yarn/pnpm workspaces | Build orchestration only |
| Nx | `nx.json` + `workspace.json` | `"projects"` map | Custom resolution + caching |

### 5.6 Barrel Files

Barrel files (`index.ts` that re-exports everything from a directory) are extremely common in JS/TS projects:

~~~typescript
// src/components/index.ts (barrel file)
export { Button } from './Button';
export { Input } from './Input';
export { Modal } from './Modal';
export type { ButtonProps } from './Button';
export * from './forms';
~~~

**Detection Strategy**:

~~~python
def is_barrel_file(file_path: str, exports: list[dict]) -> bool:
    """Detect if a file is a barrel file (primarily re-exports)."""
    if not Path(file_path).name.startswith("index"):
        return False

    total_exports = len(exports)
    reexports = sum(
        1 for e in exports
        if e["kind"] in (
            "reexport_all", "reexport_named", "reexport_namespace"
        )
    )

    # A barrel file is primarily re-exports (>80%)
    if total_exports > 0 and reexports / total_exports > 0.8:
        return True

    return False
~~~

**Graph Implications for Barrel Files**:
- Barrel files create transitive dependency chains that can obscure direct relationships
- Option 1: Preserve barrel file nodes and create `reexports` edges through them
- Option 2: "Flatten" barrel files by resolving re-exports to their original sources
- Recommended: Do both — maintain barrel file nodes but also create direct `resolved_reexport` edges
- Barrel files are important for understanding public API surfaces of directories/packages

~~~python
def flatten_barrel_reexports(
    barrel_file: str,
    barrel_exports: list[dict],
    resolver: ModuleResolver,
) -> list[dict]:
    """Resolve barrel file re-exports to their original source files."""
    flattened = []
    for export in barrel_exports:
        if export.get("reexport_source"):
            source_path = resolver.resolve(
                export["reexport_source"], barrel_file
            )
            if source_path:
                if export["kind"] == "reexport_all":
                    # Need to recursively resolve the target's exports
                    flattened.append({
                        "original_source": source_path,
                        "via_barrel": barrel_file,
                        "kind": "reexport_all",
                        "names": "*",  # All exports from source
                    })
                else:
                    flattened.append({
                        "original_source": source_path,
                        "via_barrel": barrel_file,
                        "kind": "reexport_named",
                        "names": export.get("exported_name"),
                    })
    return flattened
~~~


---

## 6. Framework-Specific Patterns

Framework-specific patterns create implicit relationships that are invisible to pure syntactic analysis. Detecting these patterns is essential for building a semantically rich knowledge graph.

### 6.1 React

#### Component Hierarchy

React component hierarchy is defined by JSX nesting (covered in Section 2). Additional patterns:

~~~scm
;; React.memo wrapped component
(lexical_declaration
  (variable_declarator
    name: (identifier) @memo.name
    value: (call_expression
      function: (member_expression
        object: (identifier) @_react
        (#eq? @_react "React")
        property: (property_identifier) @_memo
        (#eq? @_memo "memo")
      )
      arguments: (arguments
        [(identifier) @memo.wrapped
         (arrow_function) @memo.inline
         (function_expression) @memo.inline_func]
      )
    )
  )
) @memo.def

;; Standalone memo: const Comp = memo(BaseComp)
(lexical_declaration
  (variable_declarator
    name: (identifier) @memo.name
    value: (call_expression
      function: (identifier) @_memo
      (#eq? @_memo "memo")
      arguments: (arguments
        (identifier) @memo.wrapped
      )
    )
  )
) @memo.standalone

;; React.forwardRef
(lexical_declaration
  (variable_declarator
    name: (identifier) @forward_ref.name
    value: (call_expression
      function: [(member_expression
        object: (identifier) @_react
        (#eq? @_react "React")
        property: (property_identifier) @_fref
        (#eq? @_fref "forwardRef")
      ) (identifier) @_fref2 (#eq? @_fref2 "forwardRef")]
      arguments: (arguments
        [(arrow_function) @forward_ref.render
         (function_expression) @forward_ref.render_func]
      )
    )
  )
) @forward_ref.def
~~~

#### Hooks Dependencies

Hooks create implicit data flow edges:

~~~scm
;; useState: const [state, setState] = useState(initialValue)
(lexical_declaration
  (variable_declarator
    name: (array_pattern
      (identifier) @use_state.value
      (identifier) @use_state.setter
    )
    value: (call_expression
      function: (identifier) @_hook
      (#eq? @_hook "useState")
      arguments: (arguments
        (_)? @use_state.initial
      )
    )
  )
) @use_state.def

;; useEffect/useLayoutEffect/useMemo/useCallback with dependency array
(call_expression
  function: (identifier) @effect_hook.name
  (#match? @effect_hook.name "^(useEffect|useLayoutEffect|useMemo|useCallback)$")
  arguments: (arguments
    [(arrow_function) @effect_hook.callback
     (function_expression) @effect_hook.callback_func]
    (array
      (_)* @effect_hook.dependency
    )?
  )
) @effect_hook.call

;; useRef: const ref = useRef(initialValue)
(lexical_declaration
  (variable_declarator
    name: (identifier) @use_ref.name
    value: (call_expression
      function: (identifier) @_hook
      (#eq? @_hook "useRef")
    )
  )
) @use_ref.def

;; useReducer: const [state, dispatch] = useReducer(reducer, initialState)
(lexical_declaration
  (variable_declarator
    name: (array_pattern
      (identifier) @use_reducer.state
      (identifier) @use_reducer.dispatch
    )
    value: (call_expression
      function: (identifier) @_hook
      (#eq? @_hook "useReducer")
      arguments: (arguments
        (identifier) @use_reducer.reducer
        (_)? @use_reducer.initial_state
      )
    )
  )
) @use_reducer.def

;; Custom hook usage: const result = useCustomHook(args)
(call_expression
  function: (identifier) @custom_hook.name
  (#match? @custom_hook.name "^use[A-Z]")
) @custom_hook.call

;; Custom hook definition: function useCustomHook() { ... }
(function_declaration
  name: (identifier) @custom_hook_def.name
  (#match? @custom_hook_def.name "^use[A-Z]")
) @custom_hook_def.def
~~~

**Graph Edges for Hooks**:

| Hook | Edge Type | Source | Target |
|------|-----------|--------|--------|
| `useState` | `manages_state` | Component | State variable |
| `useEffect` | `has_side_effect` | Component | Effect (with deps) |
| `useContext` | `consumes_context` | Component | Context |
| `useReducer` | `uses_reducer` | Component | Reducer function |
| `useRef` | `holds_ref` | Component | Ref |
| `useMemo`/`useCallback` | `memoizes` | Component | Computation |
| Custom hook | `uses_hook` | Component | Custom hook |

#### Context Providers and Consumers

~~~scm
;; createContext: const MyContext = createContext(defaultValue)
(lexical_declaration
  (variable_declarator
    name: (identifier) @context.name
    value: (call_expression
      function: [(identifier) @_fn (#eq? @_fn "createContext")
                 (member_expression
                   object: (identifier) @_react (#eq? @_react "React")
                   property: (property_identifier) @_fn2 (#eq? @_fn2 "createContext")
                 )]
    )
  )
) @context.def

;; Context.Provider usage in JSX
(jsx_opening_element
  name: (member_expression
    object: (identifier) @provider.context_name
    property: (property_identifier) @_provider
    (#eq? @_provider "Provider")
  )
  (jsx_attribute
    (property_identifier) @_value
    (#eq? @_value "value")
    (jsx_expression (_) @provider.value)
  )?
) @provider.usage

;; useContext consumer
(call_expression
  function: (identifier) @_hook
  (#eq? @_hook "useContext")
  arguments: (arguments
    (identifier) @consumer.context_name
  )
) @consumer.usage
~~~

### 6.2 Next.js

#### File-Based Routing Detection

Next.js uses the filesystem as the routing API. Detection requires understanding the project structure:

~~~python
from pathlib import Path
import re

def detect_nextjs_routes(project_root: str) -> list[dict]:
    """Detect Next.js routes from file structure."""
    routes = []
    
    # App Router (Next.js 13+): app/ directory
    app_dir = Path(project_root) / "app"
    if app_dir.exists():
        routes.extend(_scan_app_router(app_dir, "/"))
    
    # Also check src/app/
    src_app_dir = Path(project_root) / "src" / "app"
    if src_app_dir.exists():
        routes.extend(_scan_app_router(src_app_dir, "/"))
    
    # Pages Router (legacy): pages/ directory
    pages_dir = Path(project_root) / "pages"
    if pages_dir.exists():
        routes.extend(_scan_pages_router(pages_dir, "/"))
    
    src_pages_dir = Path(project_root) / "src" / "pages"
    if src_pages_dir.exists():
        routes.extend(_scan_pages_router(src_pages_dir, "/"))
    
    return routes

def _scan_app_router(directory: Path, route_prefix: str) -> list[dict]:
    """Scan Next.js App Router directory structure."""
    routes = []
    special_files = {
        "page": "route_page",
        "layout": "layout",
        "loading": "loading",
        "error": "error_boundary",
        "not-found": "not_found",
        "template": "template",
        "default": "default",
    }
    
    for item in sorted(directory.iterdir()):
        if item.is_file():
            stem = item.stem
            ext = item.suffix
            if ext in (".tsx", ".ts", ".jsx", ".js"):
                if stem in special_files:
                    routes.append({
                        "file": str(item),
                        "route": route_prefix,
                        "type": special_files[stem],
                        "router": "app",
                    })
                elif stem == "route":
                    routes.append({
                        "file": str(item),
                        "route": route_prefix,
                        "type": "api_route",
                        "router": "app",
                    })
        elif item.is_dir():
            dir_name = item.name
            # Skip special directories
            if dir_name.startswith("_") or dir_name.startswith("."):
                continue
            
            # Dynamic segments: [param]
            if dir_name.startswith("[") and dir_name.endswith("]"):
                segment = f":{dir_name[1:-1]}"
            # Catch-all: [...param]
            elif dir_name.startswith("[...") and dir_name.endswith("]"):
                segment = f"*{dir_name[4:-1]}"
            # Route groups: (group) - no URL segment
            elif dir_name.startswith("(") and dir_name.endswith(")"):
                segment = ""  # No URL contribution
            # Parallel routes: @slot
            elif dir_name.startswith("@"):
                segment = ""  # Parallel route slot
            else:
                segment = dir_name
            
            child_prefix = f"{route_prefix}{segment}/" if segment else route_prefix
            routes.extend(_scan_app_router(item, child_prefix))
    
    return routes

def _scan_pages_router(directory: Path, route_prefix: str) -> list[dict]:
    """Scan Next.js Pages Router directory structure."""
    routes = []
    
    for item in sorted(directory.iterdir()):
        if item.is_file():
            ext = item.suffix
            if ext not in (".tsx", ".ts", ".jsx", ".js"):
                continue
            stem = item.stem
            if stem == "_app" or stem == "_document" or stem == "_error":
                routes.append({
                    "file": str(item),
                    "route": None,
                    "type": stem[1:],  # "app", "document", "error"
                    "router": "pages",
                })
            elif stem == "index":
                routes.append({
                    "file": str(item),
                    "route": route_prefix.rstrip("/") or "/",
                    "type": "page",
                    "router": "pages",
                })
            elif stem.startswith("[") and stem.endswith("]"):
                param = stem[1:-1]
                routes.append({
                    "file": str(item),
                    "route": f"{route_prefix}:{param}",
                    "type": "dynamic_page",
                    "router": "pages",
                })
            else:
                routes.append({
                    "file": str(item),
                    "route": f"{route_prefix}{stem}",
                    "type": "page",
                    "router": "pages",
                })
        elif item.is_dir():
            if item.name == "api":
                routes.extend(_scan_pages_api(item, "/api/"))
            elif not item.name.startswith("_"):
                routes.extend(
                    _scan_pages_router(item, f"{route_prefix}{item.name}/")
                )
    
    return routes
~~~

#### Server Components vs Client Components

~~~scm
;; "use client" directive detection
(program
  (expression_statement
    (string) @directive.value
    (#match? @directive.value "^[\"\']use client[\"\']$")
  ) @directive.statement
) @directive.client_component

;; "use server" directive detection
(program
  (expression_statement
    (string) @directive.value
    (#match? @directive.value "^[\"\']use server[\"\']$")
  ) @directive.statement
) @directive.server_action
~~~

**Graph Implications**:
- Files with `"use client"` are client component boundaries
- Files without the directive in App Router are server components by default
- Server-to-client boundary creates `client_boundary` edges
- Server actions (`"use server"`) create `server_action` edges

#### Next.js API Routes

~~~scm
;; App Router API route handlers: export async function GET(request) {}
(export_statement
  declaration: (function_declaration
    name: (identifier) @api_handler.method
    (#match? @api_handler.method "^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$")
  )
) @api_handler.def

;; Pages Router API handler: export default function handler(req, res) {}
(export_statement
  "default" @api_handler.default
  (function_declaration
    name: (identifier) @api_handler.name
  )
) @api_handler.pages_def
~~~

### 6.3 Vue.js

#### Single File Components (.vue)

Vue SFCs require special handling as they contain multiple languages in one file:

~~~html
<template>
  <div>{{ message }}</div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
const message = ref('Hello')
</script>

<style scoped>
div { color: red; }
</style>
~~~

**Parsing Strategy**:

~~~python
import re
from dataclasses import dataclass

@dataclass
class VueSFCBlock:
    tag: str           # "template", "script", "style"
    content: str       # Block content
    lang: str | None   # "ts", "scss", etc.
    attrs: dict        # All attributes
    start_line: int
    end_line: int

def parse_vue_sfc(file_content: str) -> list[VueSFCBlock]:
    """Parse a Vue SFC into its constituent blocks."""
    blocks = []
    # Match top-level tags: <template>, <script>, <style>
    pattern = re.compile(
        r'<(template|script|style)([^>]*)>(.*?)</\1>',
        re.DOTALL
    )
    
    for match in pattern.finditer(file_content):
        tag = match.group(1)
        attrs_str = match.group(2)
        content = match.group(3)
        
        # Parse attributes
        attrs = {}
        for attr_match in re.finditer(r'(\w+)(?:=["\']([^"\']*)["\'])?', attrs_str):
            attrs[attr_match.group(1)] = attr_match.group(2) or True
        
        start_line = file_content[:match.start()].count('\n') + 1
        end_line = file_content[:match.end()].count('\n') + 1
        
        blocks.append(VueSFCBlock(
            tag=tag,
            content=content,
            lang=attrs.get("lang"),
            attrs=attrs,
            start_line=start_line,
            end_line=end_line,
        ))
    
    return blocks

def extract_vue_script(sfc_blocks: list[VueSFCBlock]) -> tuple[str, str]:
    """Extract the script block and determine its grammar."""
    for block in sfc_blocks:
        if block.tag == "script":
            lang = block.attrs.get("lang", "js")
            is_setup = "setup" in block.attrs
            grammar = "tsx" if lang == "tsx" else "typescript" if lang == "ts" else "javascript"
            return block.content, grammar
    return "", "javascript"
~~~

#### Composition API Patterns

~~~scm
;; defineComponent
(call_expression
  function: (identifier) @_fn
  (#eq? @_fn "defineComponent")
  arguments: (arguments
    (object) @vue_component.options
  )
) @vue_component.def

;; defineProps (script setup)
(call_expression
  function: (identifier) @_fn
  (#eq? @_fn "defineProps")
  arguments: (arguments)? @vue_props.args
) @vue_props.def

;; defineProps with type parameter: defineProps<{ msg: string }>()
(call_expression
  function: (identifier) @_fn
  (#eq? @_fn "defineProps")
  (type_arguments
    (_) @vue_props.type
  )
) @vue_props.typed

;; defineEmits
(call_expression
  function: (identifier) @_fn
  (#eq? @_fn "defineEmits")
) @vue_emits.def

;; defineExpose
(call_expression
  function: (identifier) @_fn
  (#eq? @_fn "defineExpose")
  arguments: (arguments
    (object) @vue_expose.members
  )
) @vue_expose.def

;; Composable usage (Vue equivalent of custom hooks)
(call_expression
  function: (identifier) @composable.name
  (#match? @composable.name "^use[A-Z]")
) @composable.call
~~~

### 6.4 Angular

Angular relies heavily on decorators for its module system:

#### Component Detection

~~~scm
;; @Component decorator
(class_declaration
  decorator: (decorator
    (call_expression
      function: (identifier) @_dec
      (#eq? @_dec "Component")
      arguments: (arguments
        (object
          (pair
            key: (property_identifier) @component_meta.key
            value: (_) @component_meta.value
          )
        )
      )
    )
  )
  name: (identifier) @angular_component.name
) @angular_component.def
~~~

**Key metadata to extract from @Component**:
- `selector`: CSS selector for the component (e.g., `'app-header'`)
- `templateUrl` / `template`: Template file or inline template
- `styleUrls` / `styles`: Style files or inline styles
- `standalone`: Whether it's a standalone component (Angular 14+)
- `imports`: Standalone component imports

#### Module System

~~~scm
;; @NgModule decorator
(class_declaration
  decorator: (decorator
    (call_expression
      function: (identifier) @_dec
      (#eq? @_dec "NgModule")
      arguments: (arguments
        (object) @ng_module.config
      )
    )
  )
  name: (identifier) @ng_module.name
) @ng_module.def

;; @Injectable decorator
(class_declaration
  decorator: (decorator
    (call_expression
      function: (identifier) @_dec
      (#eq? @_dec "Injectable")
      arguments: (arguments
        (object
          (pair
            key: (property_identifier) @_key
            (#eq? @_key "providedIn")
            value: (_) @injectable.scope
          )
        )?
      )
    )
  )
  name: (identifier) @injectable.name
) @injectable.def

;; @Directive decorator
(class_declaration
  decorator: (decorator
    (call_expression
      function: (identifier) @_dec
      (#eq? @_dec "Directive")
      arguments: (arguments
        (object) @directive.config
      )
    )
  )
  name: (identifier) @angular_directive.name
) @angular_directive.def

;; @Pipe decorator
(class_declaration
  decorator: (decorator
    (call_expression
      function: (identifier) @_dec
      (#eq? @_dec "Pipe")
      arguments: (arguments
        (object
          (pair
            key: (property_identifier) @_key
            (#eq? @_key "name")
            value: (string) @pipe.name
          )
        )
      )
    )
  )
  name: (identifier) @angular_pipe.class_name
) @angular_pipe.def
~~~

#### Dependency Injection

~~~scm
;; Constructor injection
(method_definition
  name: (property_identifier) @_ctor
  (#eq? @_ctor "constructor")
  parameters: (formal_parameters
    (required_parameter
      (accessibility_modifier)? @di.access
      decorator: (decorator
        (call_expression
          function: (identifier) @di.decorator_name
          arguments: (arguments) @di.decorator_args
        )
      )?
      pattern: (identifier) @di.param_name
      type: (type_annotation (_) @di.service_type)
    )
  )
) @di.constructor

;; @Inject decorator for non-class tokens
(required_parameter
  decorator: (decorator
    (call_expression
      function: (identifier) @_inject
      (#eq? @_inject "Inject")
      arguments: (arguments
        (_) @inject.token
      )
    )
  )
  pattern: (identifier) @inject.param_name
) @inject.def
~~~

**Angular Graph Edges**:

| Source | Edge Type | Target |
|--------|-----------|--------|
| NgModule | `declares` | Component/Directive/Pipe |
| NgModule | `imports_module` | NgModule |
| NgModule | `exports_module` | Component/Directive/Pipe |
| NgModule | `provides` | Service |
| Component | `injects` | Service |
| Component | `uses_template` | Template file |
| Component | `uses_style` | Style file |
| Standalone Component | `imports` | Component/Directive/Pipe |

### 6.5 Express / Fastify

#### Route Detection

~~~scm
;; Express route: app.get('/path', handler)
(call_expression
  function: (member_expression
    object: (identifier) @express.app_var
    property: (property_identifier) @express.method
    (#match? @express.method "^(get|post|put|patch|delete|all|use|options|head)$")
  )
  arguments: (arguments
    (string) @express.path
    (_)+ @express.handlers
  )
) @express.route

;; Express Router: router.get('/path', handler)
(call_expression
  function: (member_expression
    object: (identifier) @router.var
    property: (property_identifier) @router.method
    (#match? @router.method "^(get|post|put|patch|delete|all|use)$")
  )
  arguments: (arguments
    (string) @router.path
  )
) @router.route

;; Router creation: const router = express.Router()
(lexical_declaration
  (variable_declarator
    name: (identifier) @router_create.name
    value: (call_expression
      function: (member_expression
        object: (identifier) @_express
        property: (property_identifier) @_router
        (#eq? @_router "Router")
      )
    )
  )
) @router_create.def

;; Middleware: app.use(middleware) or app.use('/path', middleware)
(call_expression
  function: (member_expression
    object: (identifier) @middleware.app_var
    property: (property_identifier) @_use
    (#eq? @_use "use")
  )
  arguments: (arguments
    (string)? @middleware.path
    (_) @middleware.handler
  )
) @middleware.usage
~~~

#### Fastify Route Detection

~~~scm
;; Fastify route: fastify.get('/path', options, handler)
(call_expression
  function: (member_expression
    object: (identifier) @fastify.app_var
    property: (property_identifier) @fastify.method
    (#match? @fastify.method "^(get|post|put|patch|delete|all|head|options)$")
  )
  arguments: (arguments
    (string) @fastify.path
  )
) @fastify.route

;; Fastify route with schema: fastify.route({ method, url, schema, handler })
(call_expression
  function: (member_expression
    object: (identifier) @fastify.app_var
    property: (property_identifier) @_route
    (#eq? @_route "route")
  )
  arguments: (arguments
    (object) @fastify.route_config
  )
) @fastify.route_object

;; Fastify plugin registration: fastify.register(plugin, options)
(call_expression
  function: (member_expression
    object: (identifier) @fastify.app_var
    property: (property_identifier) @_register
    (#eq? @_register "register")
  )
  arguments: (arguments
    (_) @fastify.plugin
    (object)? @fastify.plugin_options
  )
) @fastify.register
~~~

### 6.6 NestJS

NestJS combines Angular-style decorators with Express/Fastify:

#### Controller and Route Detection

~~~scm
;; @Controller decorator
(class_declaration
  decorator: (decorator
    (call_expression
      function: (identifier) @_dec
      (#eq? @_dec "Controller")
      arguments: (arguments
        (string)? @nest_controller.path
      )
    )
  )
  name: (identifier) @nest_controller.name
  body: (class_body) @nest_controller.body
) @nest_controller.def

;; HTTP method decorators: @Get, @Post, @Put, @Delete, @Patch
(method_definition
  decorator: (decorator
    (call_expression
      function: (identifier) @nest_route.method
      (#match? @nest_route.method "^(Get|Post|Put|Delete|Patch|Head|Options|All)$")
      arguments: (arguments
        (string)? @nest_route.path
      )
    )
  )
  name: (property_identifier) @nest_route.handler_name
) @nest_route.def

;; @Module decorator
(class_declaration
  decorator: (decorator
    (call_expression
      function: (identifier) @_dec
      (#eq? @_dec "Module")
      arguments: (arguments
        (object) @nest_module.config
      )
    )
  )
  name: (identifier) @nest_module.name
) @nest_module.def

;; Guards: @UseGuards(AuthGuard)
(decorator
  (call_expression
    function: (identifier) @_dec
    (#eq? @_dec "UseGuards")
    arguments: (arguments
      (_) @nest_guard.guard_class
    )
  )
) @nest_guard.usage

;; Interceptors: @UseInterceptors(LoggingInterceptor)
(decorator
  (call_expression
    function: (identifier) @_dec
    (#eq? @_dec "UseInterceptors")
    arguments: (arguments
      (_) @nest_interceptor.class
    )
  )
) @nest_interceptor.usage

;; Pipes: @UsePipes(ValidationPipe)
(decorator
  (call_expression
    function: (identifier) @_dec
    (#eq? @_dec "UsePipes")
    arguments: (arguments
      (_) @nest_pipe.class
    )
  )
) @nest_pipe.usage
~~~

**NestJS Module Config Extraction**:

~~~python
def extract_nest_module_config(config_node, source: bytes) -> dict:
    """Extract NestJS @Module configuration."""
    config = {
        "imports": [],      # Other modules
        "controllers": [],  # Route controllers
        "providers": [],    # Injectable services
        "exports": [],      # Exported providers
    }
    
    for child in config_node.children:
        if child.type == "pair":
            key_node = child.child_by_field_name("key")
            value_node = child.child_by_field_name("value")
            if key_node and value_node:
                key = key_node.text.decode()
                if key in config and value_node.type == "array":
                    for item in value_node.children:
                        if item.type == "identifier":
                            config[key].append(item.text.decode())
    
    return config
~~~

**NestJS Graph Edges**:

| Source | Edge Type | Target |
|--------|-----------|--------|
| Module | `imports_module` | Module |
| Module | `has_controller` | Controller |
| Module | `provides` | Service |
| Module | `exports_provider` | Service |
| Controller | `has_route` | Route handler |
| Controller | `injects` | Service |
| Route | `guarded_by` | Guard |
| Route | `intercepted_by` | Interceptor |
| Route | `piped_through` | Pipe |


---

## 7. Build Tool Configuration as Metadata

Build tool configuration files contain critical metadata that informs module resolution, project structure understanding, and dependency graph construction. These files should be parsed early in the analysis pipeline to configure the resolver and annotate graph nodes.

### 7.1 tsconfig.json

**What We Can Learn**:

| Field | Graph Relevance | Usage |
|-------|----------------|-------|
| `compilerOptions.paths` | Module resolution aliases | Configure resolver path mappings |
| `compilerOptions.baseUrl` | Base for non-relative imports | Resolver base directory |
| `compilerOptions.rootDirs` | Virtual directory merging | Multiple source roots |
| `compilerOptions.moduleResolution` | Resolution algorithm | `node`, `node16`, `bundler`, `classic` |
| `compilerOptions.module` | Module system output | `commonjs`, `esnext`, `node16` |
| `compilerOptions.target` | JS version target | Affects available APIs |
| `compilerOptions.strict` | Strictness level | Type safety metadata |
| `compilerOptions.jsx` | JSX handling | `react`, `react-jsx`, `preserve` |
| `compilerOptions.declaration` | .d.ts generation | Type export surface |
| `compilerOptions.composite` | Project references | Monorepo structure |
| `compilerOptions.outDir` | Output directory | Distinguish source from build |
| `compilerOptions.rootDir` | Source root | Source file boundary |
| `include` | Files to compile | Scope of analysis |
| `exclude` | Files to skip | Filter out test/build files |
| `references` | Project references | Monorepo dependency graph |
| `extends` | Config inheritance | Configuration hierarchy |

**Programmatic Parsing**:

~~~python
import json
import re
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class TSConfigMetadata:
    """Extracted metadata from tsconfig.json."""
    config_path: str
    base_url: str | None = None
    paths: dict[str, list[str]] = field(default_factory=dict)
    root_dirs: list[str] = field(default_factory=list)
    module_resolution: str = "node"
    module_system: str = "commonjs"
    target: str = "es5"
    strict: bool = False
    jsx: str | None = None
    composite: bool = False
    declaration: bool = False
    out_dir: str | None = None
    root_dir: str | None = None
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    project_references: list[str] = field(default_factory=list)
    extends_from: str | None = None

def parse_tsconfig(tsconfig_path: str) -> TSConfigMetadata:
    """Parse tsconfig.json with extends resolution and comment stripping."""
    path = Path(tsconfig_path)
    config = _load_tsconfig_recursive(path)
    co = config.get("compilerOptions", {})
    project_root = str(path.parent)
    
    # Resolve baseUrl to absolute path
    base_url = None
    if co.get("baseUrl"):
        base_url = str((path.parent / co["baseUrl"]).resolve())
    
    # Resolve rootDirs to absolute paths
    root_dirs = [
        str((path.parent / d).resolve())
        for d in co.get("rootDirs", [])
    ]
    
    # Resolve project references
    refs = []
    for ref in config.get("references", []):
        ref_path = ref.get("path", "")
        refs.append(str((path.parent / ref_path).resolve()))
    
    return TSConfigMetadata(
        config_path=tsconfig_path,
        base_url=base_url,
        paths=co.get("paths", {}),
        root_dirs=root_dirs,
        module_resolution=co.get("moduleResolution", "node").lower(),
        module_system=co.get("module", "commonjs").lower(),
        target=co.get("target", "es5").lower(),
        strict=co.get("strict", False),
        jsx=co.get("jsx"),
        composite=co.get("composite", False),
        declaration=co.get("declaration", False),
        out_dir=co.get("outDir"),
        root_dir=co.get("rootDir"),
        include_patterns=config.get("include", []),
        exclude_patterns=config.get("exclude", []),
        project_references=refs,
        extends_from=config.get("_extends_from"),
    )

def _load_tsconfig_recursive(path: Path) -> dict:
    """Load tsconfig.json handling extends, comments, and trailing commas."""
    text = path.read_text(encoding="utf-8")
    # Strip single-line comments
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    # Strip multi-line comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Strip trailing commas (common in tsconfig)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    
    config = json.loads(text)
    
    extends = config.pop("extends", None)
    if extends:
        config["_extends_from"] = extends
        # Resolve extends path
        if extends.startswith("."):
            parent_path = (path.parent / extends).resolve()
            if not parent_path.suffix:
                parent_path = parent_path.with_suffix(".json")
        else:
            # npm package: e.g., "@tsconfig/node18/tsconfig.json"
            parent_path = path.parent / "node_modules" / extends
            if parent_path.is_dir():
                parent_path = parent_path / "tsconfig.json"
        
        if parent_path.exists():
            parent_config = _load_tsconfig_recursive(parent_path)
            _deep_merge(parent_config, config)
            return parent_config
    
    return config
~~~

#### TypeScript Project References (Monorepo)

Project references create a build dependency graph:

~~~json
// packages/app/tsconfig.json
{
  "compilerOptions": { "composite": true },
  "references": [
    { "path": "../shared" },
    { "path": "../ui-components" }
  ]
}
~~~

**Graph Implications**: Project references create `project_depends_on` edges between TypeScript sub-projects, forming a build-order DAG.

### 7.2 package.json

**What We Can Learn**:

| Field | Graph Relevance | Usage |
|-------|----------------|-------|
| `name` | Package identity | Node identifier for the package |
| `version` | Package version | Metadata annotation |
| `type` | Module system | `"module"` (ESM) or `"commonjs"` (default) |
| `main` | CJS entry point | Package resolution |
| `module` | ESM entry point | Bundler resolution |
| `types`/`typings` | Type entry point | TypeScript resolution |
| `exports` | Conditional exports | Modern package resolution |
| `imports` | Package imports (#) | Internal alias resolution |
| `dependencies` | Runtime deps | Dependency graph edges |
| `devDependencies` | Dev-only deps | Build/test dependency edges |
| `peerDependencies` | Peer deps | Compatibility constraint edges |
| `optionalDependencies` | Optional deps | Weak dependency edges |
| `workspaces` | Monorepo packages | Workspace discovery |
| `scripts` | Build/test commands | Build pipeline metadata |
| `engines` | Runtime requirements | Compatibility metadata |
| `bin` | CLI entry points | Executable entry points |
| `files` | Published files | Public API surface |
| `sideEffects` | Tree-shaking hints | Import optimization |
| `browserslist` | Target browsers | Environment metadata |

**Programmatic Parsing**:

~~~python
@dataclass
class PackageMetadata:
    """Extracted metadata from package.json."""
    package_path: str
    name: str | None = None
    version: str | None = None
    module_type: str = "commonjs"  # "module" or "commonjs"
    main: str | None = None
    module_entry: str | None = None
    types: str | None = None
    exports: dict | str | None = None
    imports: dict | None = None
    dependencies: dict[str, str] = field(default_factory=dict)
    dev_dependencies: dict[str, str] = field(default_factory=dict)
    peer_dependencies: dict[str, str] = field(default_factory=dict)
    workspaces: list[str] = field(default_factory=list)
    scripts: dict[str, str] = field(default_factory=dict)
    side_effects: bool | list[str] | None = None
    bin_entries: dict[str, str] = field(default_factory=dict)

def parse_package_json(pkg_path: str) -> PackageMetadata:
    """Parse package.json and extract graph-relevant metadata."""
    data = json.loads(Path(pkg_path).read_text())
    
    # Handle workspaces (can be array or object with packages key)
    workspaces = data.get("workspaces", [])
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages", [])
    
    # Handle bin (can be string or object)
    bin_entries = data.get("bin", {})
    if isinstance(bin_entries, str):
        bin_entries = {data.get("name", ""): bin_entries}
    
    return PackageMetadata(
        package_path=pkg_path,
        name=data.get("name"),
        version=data.get("version"),
        module_type=data.get("type", "commonjs"),
        main=data.get("main"),
        module_entry=data.get("module"),
        types=data.get("types") or data.get("typings"),
        exports=data.get("exports"),
        imports=data.get("imports"),
        dependencies=data.get("dependencies", {}),
        dev_dependencies=data.get("devDependencies", {}),
        peer_dependencies=data.get("peerDependencies", {}),
        workspaces=workspaces,
        scripts=data.get("scripts", {}),
        side_effects=data.get("sideEffects"),
        bin_entries=bin_entries,
    )
~~~

#### Dependency Classification for Graph

~~~python
from enum import Enum

class DependencyKind(Enum):
    RUNTIME = "runtime"           # dependencies
    DEVELOPMENT = "development"   # devDependencies
    PEER = "peer"                 # peerDependencies
    OPTIONAL = "optional"         # optionalDependencies
    WORKSPACE = "workspace"       # Monorepo workspace package
    BUILTIN = "builtin"           # Node.js core modules

def classify_dependency(
    specifier: str,
    package_metadata: PackageMetadata,
    workspace_packages: dict[str, str],
) -> DependencyKind:
    """Classify a dependency by its relationship type."""
    if is_core_module(specifier):
        return DependencyKind.BUILTIN
    
    # Extract package name from specifier
    parts = specifier.split("/")
    if specifier.startswith("@") and len(parts) >= 2:
        pkg_name = "/".join(parts[:2])
    else:
        pkg_name = parts[0]
    
    if pkg_name in workspace_packages:
        return DependencyKind.WORKSPACE
    if pkg_name in package_metadata.dependencies:
        return DependencyKind.RUNTIME
    if pkg_name in package_metadata.dev_dependencies:
        return DependencyKind.DEVELOPMENT
    if pkg_name in package_metadata.peer_dependencies:
        return DependencyKind.PEER
    
    return DependencyKind.RUNTIME  # Default assumption
~~~

### 7.3 Webpack Configuration

Webpack configs are JavaScript/TypeScript files that export a configuration object. They cannot be parsed as JSON — they require AST analysis:

**Key Fields to Extract**:

| Field | Graph Relevance |
|-------|----------------|
| `resolve.alias` | Module resolution aliases |
| `resolve.extensions` | File extension resolution order |
| `resolve.modules` | Additional module directories |
| `entry` | Application entry points |
| `externals` | Excluded dependencies |
| `module.rules` | File processing pipeline |
| `plugins` | Build plugins (framework detection) |

**Tree-sitter Extraction Strategy**:

~~~scm
;; Webpack config: module.exports = { ... } or export default { ... }
;; Look for resolve.alias in the config object

;; resolve.alias property
(pair
  key: (property_identifier) @_resolve
  (#eq? @_resolve "resolve")
  value: (object
    (pair
      key: (property_identifier) @_alias
      (#eq? @_alias "alias")
      value: (object
        (pair
          key: (property_identifier) @webpack_alias.key
          value: (_) @webpack_alias.value
        )
      )
    )
  )
) @webpack_resolve.config

;; entry points
(pair
  key: (property_identifier) @_entry
  (#eq? @_entry "entry")
  value: [
    (string) @webpack_entry.single
    (object
      (pair
        key: (property_identifier) @webpack_entry.name
        value: (_) @webpack_entry.path
      )
    )
    (array
      (string) @webpack_entry.multi
    )
  ]
) @webpack_entry.config

;; externals
(pair
  key: (property_identifier) @_externals
  (#eq? @_externals "externals")
  value: (_) @webpack_externals.value
) @webpack_externals.config
~~~

**Practical Extraction Approach**:

~~~python
def extract_webpack_aliases(config_path: str) -> dict[str, str]:
    """Extract webpack resolve.alias from config file using Tree-sitter."""
    # Parse the webpack config file as JavaScript/TypeScript
    source = Path(config_path).read_bytes()
    
    # Determine grammar based on extension
    ext = Path(config_path).suffix
    grammar = "typescript" if ext in (".ts", ".mts") else "javascript"
    
    # Use Tree-sitter to parse and extract
    # ... (standard Tree-sitter parsing)
    
    # Alternative: For complex configs, use a regex-based heuristic
    # This handles most common patterns
    aliases = {}
    text = source.decode()
    
    # Look for resolve.alias or resolve: { alias: { ... } }
    import re
    alias_block = re.search(
        r'alias\s*:\s*\{([^}]+)\}',
        text,
        re.DOTALL
    )
    if alias_block:
        for match in re.finditer(
            r"['\"]?(@?[\w/-]+)['\"]?\s*:\s*['\"]([^'\"]+)['\"]",
            alias_block.group(1)
        ):
            aliases[match.group(1)] = match.group(2)
    
    return aliases
~~~

### 7.4 Vite Configuration

Vite configs (`vite.config.ts` / `vite.config.js`) follow a similar pattern:

**Key Fields to Extract**:

| Field | Graph Relevance |
|-------|----------------|
| `resolve.alias` | Module resolution aliases |
| `resolve.extensions` | Extension resolution order |
| `plugins` | Framework detection (React, Vue, etc.) |
| `build.rollupOptions.external` | Excluded dependencies |
| `build.rollupOptions.input` | Entry points |
| `server.proxy` | API proxy targets |
| `define` | Global constant replacements |

~~~scm
;; Vite defineConfig call
(call_expression
  function: (identifier) @_fn
  (#eq? @_fn "defineConfig")
  arguments: (arguments
    (object) @vite.config
  )
) @vite.define_config

;; Vite plugins array - detect framework
(pair
  key: (property_identifier) @_plugins
  (#eq? @_plugins "plugins")
  value: (array
    (call_expression
      function: (identifier) @vite_plugin.name
    )
  )
) @vite_plugin.config
~~~

**Framework Detection from Vite Plugins**:

~~~python
VITE_PLUGIN_FRAMEWORK_MAP = {
    "react": "react",
    "reactRefresh": "react",
    "vue": "vue",
    "svelte": "svelte",
    "solid": "solid",
    "preact": "preact",
    "qwikVite": "qwik",
}

def detect_framework_from_vite(plugins: list[str]) -> str | None:
    """Detect the frontend framework from Vite plugin names."""
    for plugin in plugins:
        for key, framework in VITE_PLUGIN_FRAMEWORK_MAP.items():
            if key.lower() in plugin.lower():
                return framework
    return None
~~~

### 7.5 Rollup Configuration

Rollup configs (`rollup.config.js` / `rollup.config.mjs`) are relevant for library projects:

| Field | Graph Relevance |
|-------|----------------|
| `input` | Entry points |
| `external` | External dependencies |
| `output.format` | Output module format (cjs, esm, umd, iife) |
| `plugins` | Build pipeline |

### 7.6 Configuration Discovery and Priority

~~~python
def discover_build_configs(project_root: str) -> dict:
    """Discover all build tool configuration files in a project."""
    root = Path(project_root)
    configs = {
        "tsconfig": None,
        "package_json": None,
        "webpack": None,
        "vite": None,
        "rollup": None,
        "next": None,
        "babel": None,
        "eslint": None,
    }
    
    # tsconfig.json (check multiple locations)
    for name in ("tsconfig.json", "tsconfig.build.json", "jsconfig.json"):
        path = root / name
        if path.exists():
            configs["tsconfig"] = str(path)
            break
    
    # package.json
    pkg = root / "package.json"
    if pkg.exists():
        configs["package_json"] = str(pkg)
    
    # Webpack
    for name in (
        "webpack.config.js", "webpack.config.ts",
        "webpack.config.mjs", "webpack.config.cjs",
    ):
        path = root / name
        if path.exists():
            configs["webpack"] = str(path)
            break
    
    # Vite
    for name in (
        "vite.config.ts", "vite.config.js",
        "vite.config.mts", "vite.config.mjs",
    ):
        path = root / name
        if path.exists():
            configs["vite"] = str(path)
            break
    
    # Rollup
    for name in (
        "rollup.config.js", "rollup.config.mjs",
        "rollup.config.ts",
    ):
        path = root / name
        if path.exists():
            configs["rollup"] = str(path)
            break
    
    # Next.js
    for name in ("next.config.js", "next.config.mjs", "next.config.ts"):
        path = root / name
        if path.exists():
            configs["next"] = str(path)
            break
    
    return configs

def detect_project_type(configs: dict, package_data: dict | None) -> dict:
    """Detect project type and framework from configuration."""
    result = {
        "language": "javascript",  # or "typescript"
        "module_system": "commonjs",  # or "esm"
        "framework": None,
        "build_tool": None,
        "is_monorepo": False,
        "is_library": False,
    }
    
    # TypeScript detection
    if configs.get("tsconfig"):
        result["language"] = "typescript"
    
    # Module system from package.json
    if package_data:
        result["module_system"] = package_data.get("type", "commonjs")
        result["is_monorepo"] = bool(package_data.get("workspaces"))
        result["is_library"] = bool(
            package_data.get("main") or package_data.get("exports")
        )
    
    # Framework detection
    if configs.get("next"):
        result["framework"] = "nextjs"
    elif configs.get("vite"):
        result["build_tool"] = "vite"
    elif configs.get("webpack"):
        result["build_tool"] = "webpack"
    elif configs.get("rollup"):
        result["build_tool"] = "rollup"
    
    # Framework from dependencies
    if package_data:
        deps = {
            **package_data.get("dependencies", {}),
            **package_data.get("devDependencies", {}),
        }
        if "next" in deps:
            result["framework"] = "nextjs"
        elif "nuxt" in deps or "nuxt3" in deps:
            result["framework"] = "nuxt"
        elif "@angular/core" in deps:
            result["framework"] = "angular"
        elif "vue" in deps:
            result["framework"] = "vue"
        elif "react" in deps:
            result["framework"] = "react"
        elif "svelte" in deps:
            result["framework"] = "svelte"
        elif "express" in deps:
            result["framework"] = "express"
        elif "fastify" in deps:
            result["framework"] = "fastify"
        elif "@nestjs/core" in deps:
            result["framework"] = "nestjs"
    
    return result
~~~

### 7.7 Unified Configuration Pipeline

The recommended order for configuration parsing in the knowledge graph builder:

~~~
1. Discover all config files (discover_build_configs)
2. Parse package.json first (project identity, dependencies, module type)
3. Parse tsconfig.json (path mappings, project references, compiler options)
4. Parse build tool config (aliases, entry points, externals)
5. Detect project type and framework
6. Configure module resolver with all gathered information
7. Begin file discovery and AST analysis
~~~

~~~python
def build_resolver_from_configs(project_root: str) -> ModuleResolver:
    """Build a fully configured module resolver from project configs."""
    configs = discover_build_configs(project_root)
    
    # Parse package.json
    pkg_data = None
    if configs["package_json"]:
        pkg_data = parse_package_json(configs["package_json"])
    
    # Parse tsconfig.json
    ts_config = None
    if configs["tsconfig"]:
        ts_config = parse_tsconfig(configs["tsconfig"])
    
    # Extract bundler aliases
    webpack_aliases = {}
    if configs["webpack"]:
        webpack_aliases = extract_webpack_aliases(configs["webpack"])
    
    vite_aliases = {}
    if configs["vite"]:
        vite_aliases = extract_vite_aliases(configs["vite"])
    
    # Build resolver config
    resolver_config = ResolverConfig(
        project_root=project_root,
        ts_config_paths=ts_config.paths if ts_config else {},
        ts_base_url=ts_config.base_url if ts_config else None,
        webpack_aliases=webpack_aliases,
        vite_aliases=vite_aliases,
    )
    
    return ModuleResolver(resolver_config)
~~~

---

## Summary: Recommended Extraction Pipeline

Based on this research, the recommended pipeline for building a JS/TS code knowledge graph is:

### Phase 1: Project Discovery and Configuration
1. Discover and parse `package.json` (identity, deps, module type, workspaces)
2. Discover and parse `tsconfig.json` (paths, references, compiler options)
3. Discover and parse build tool configs (aliases, entry points)
4. Detect project type, framework, and module system
5. Build configured module resolver

### Phase 2: File Discovery
1. Use `include`/`exclude` from tsconfig.json to scope analysis
2. Respect `.gitignore` patterns
3. Classify files by extension (`.ts`, `.tsx`, `.js`, `.jsx`, `.vue`, etc.)
4. Identify special files (barrel files, config files, test files)
5. For Vue SFCs, extract script blocks for separate parsing

### Phase 3: Structural Extraction (Tree-sitter)
1. Select correct grammar per file (JavaScript, TypeScript, TSX)
2. Extract imports/exports (ESM and CJS, unified into ImportEdge/ExportEdge)
3. Extract type declarations (interfaces, type aliases, enums)
4. Extract class hierarchies (extends, implements, abstract)
5. Extract function/method signatures (including overloads)
6. Extract decorators and their arguments
7. Extract JSX component usage and props

### Phase 4: Module Resolution
1. Resolve all import specifiers to absolute file paths
2. Handle TypeScript path mappings and bundler aliases
3. Resolve node_modules with package.json exports support
4. Handle workspace packages in monorepos
5. Classify dynamic imports by resolvability
6. Flatten barrel file re-exports

### Phase 5: Framework Pattern Detection
1. Detect framework from dependencies and config files
2. Apply framework-specific extractors:
   - React: hooks, context, component hierarchy, memo/forwardRef
   - Next.js: file-based routes, server/client components, API routes
   - Vue: SFC parsing, Composition API, defineProps/defineEmits
   - Angular: decorators, modules, DI, component metadata
   - Express/Fastify: routes, middleware chains
   - NestJS: modules, controllers, providers, guards
3. Generate framework-specific graph edges

### Phase 6: Graph Construction
1. Create nodes for all discovered entities
2. Create edges from resolved imports/exports
3. Add type relationship edges (extends, implements, union_of, etc.)
4. Add framework-specific semantic edges
5. Annotate nodes with metadata (module system, accessibility, decorators)
6. Validate graph integrity (dangling references, circular dependencies)

### Node Types for JS/TS Knowledge Graph

| Node Type | Description |
|-----------|-------------|
| File | Source file with module system, framework role |
| Package | npm package or workspace package |
| Function | Function declaration or expression |
| Class | Class declaration (concrete or abstract) |
| Interface | TypeScript interface |
| TypeAlias | TypeScript type alias |
| Enum | TypeScript enum |
| Variable | Exported variable/constant |
| Component | React/Vue/Angular component |
| Route | HTTP route (Express/Fastify/Next.js) |
| Hook | React hook (built-in or custom) |
| Context | React context |
| Module | Angular NgModule or NestJS Module |
| Service | Injectable service (Angular/NestJS) |
| Decorator | Decorator definition |
| Namespace | TypeScript namespace |
| Overload | Function overload signature |

### Edge Types for JS/TS Knowledge Graph

| Edge Type | Source | Target | Description |
|-----------|--------|--------|-------------|
| `imports` | File | File | Static import dependency |
| `imports_type` | File | File | Type-only import (erased at runtime) |
| `dynamic_imports` | File | File | Dynamic import() |
| `reexports` | File | File | Re-export relationship |
| `extends` | Class/Interface | Class/Interface | Inheritance |
| `implements` | Class | Interface | Interface implementation |
| `calls` | Function | Function | Function call |
| `instantiates` | Any | Class | Constructor call |
| `renders` | Component | Component | JSX component usage |
| `passes_prop` | Component | Component | Prop data flow |
| `uses_hook` | Component | Hook | Hook dependency |
| `provides_context` | Component | Context | Context provider |
| `consumes_context` | Component | Context | Context consumer |
| `injects` | Class | Service | Dependency injection |
| `decorated_by` | Any | Decorator | Decorator application |
| `has_route` | Controller/File | Route | Route definition |
| `guards` | Guard | Route | Route protection |
| `union_of` | TypeAlias | Type | Union type member |
| `intersection_of` | TypeAlias | Type | Intersection type member |
| `type_parameter` | Generic | TypeParam | Generic type parameter |
| `narrows_to` | TypeGuard | Type | Type narrowing |
| `merges_with` | Interface | Interface | Declaration merging |
| `augments` | Declaration | Module | Module augmentation |
| `overloads` | Function | Signature | Overload signature |
| `lazy_loads` | Component | File | React.lazy boundary |
| `workspace_dep` | Package | Package | Monorepo workspace dependency |

