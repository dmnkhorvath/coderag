# Tree-sitter Deep Dive: PHP, JavaScript & TypeScript Parsing

> Technical Research for Code Knowledge Graph Builder Design
> Date: 2026-03-10

---

## Table of Contents

1. [Overview](#1-overview)
2. [Tree-sitter Node Types by Language](#2-tree-sitter-node-types-by-language)
3. [Tree-sitter Query Syntax & Key Queries](#3-tree-sitter-query-syntax--key-queries)
4. [Incremental Parsing](#4-incremental-parsing)
5. [py-tree-sitter Python Bindings](#5-py-tree-sitter-python-bindings)
6. [Tree-sitter Limitations](#6-tree-sitter-limitations)
7. [Grammar Repositories](#7-grammar-repositories)
8. [Implications for Knowledge Graph Builder](#8-implications-for-knowledge-graph-builder)

---

## 1. Overview

Tree-sitter is a parser generator tool and incremental parsing library. It builds a **Concrete Syntax Tree (CST)** for source files and efficiently updates the tree as the source is edited. Originally designed for syntax highlighting in the Atom editor, it has become the de facto standard for structural code analysis in editors (Neovim, Helix, Zed), code intelligence platforms (GitHub Semantic, Sourcegraph), and AI-assisted coding tools.

### Key Properties

| Property | Description |
|---|---|
| **Parser Type** | GLR (Generalized LR) with incremental capability |
| **Output** | Concrete Syntax Tree (CST), not Abstract Syntax Tree (AST) |
| **Error Recovery** | Built-in; produces trees even for syntactically invalid code |
| **Incremental** | Re-parses only changed regions; sub-millisecond updates |
| **Language Support** | 165+ languages via community grammars |
| **Query System** | S-expression pattern matching with captures and predicates |
| **Thread Safety** | Parsers are not thread-safe; Trees and Nodes are read-only and safe |
| **Memory Model** | C-based with bindings; Nodes hold pointers back to Tree |

### Named vs Anonymous Nodes

Tree-sitter distinguishes two categories of CST nodes:

- **Named nodes**: Correspond to explicit grammar rules (e.g., `class_declaration`, `function_definition`, `identifier`). Accessed via `node.named_children` or `node.child_by_field_name()`.
- **Anonymous nodes**: Correspond to literal strings in grammar rules — operators (`+`, `*`, `=>`), punctuation (`(`, `)`, `;`), and keywords (`class`, `function`, `if`). Accessed via `node.children` (which includes both named and anonymous).

**Critical for knowledge graph work**: Anonymous nodes carry semantic information (e.g., which operator is used in a binary expression). Always use `node.children` when you need operator/keyword information, not just `node.named_children`.

---

## 2. Tree-sitter Node Types by Language

### 2.1 Summary Statistics

| Metric | PHP | JavaScript | TypeScript |
|---|---|---|---|
| **Total Node Types** | 305 | 226 | 324 |
| **Named Node Types** | 162 | 119 | 183 |
| **Anonymous Node Types** | 143 | 107 | 141 |
| **Supertype Categories** | 4 | 3 | 3 |
| **Grammar Repository** | tree-sitter/tree-sitter-php | tree-sitter/tree-sitter-javascript | tree-sitter/tree-sitter-typescript |

### 2.2 PHP Node Types

#### Supertypes (Abstract Categories)
| Supertype | Description | Example Subtypes |
|---|---|---|
| `_statement` | All statement types | `expression_statement`, `if_statement`, `for_statement`, `return_statement`, `class_declaration`, `function_definition` |
| `_expression` | All expression types | `assignment_expression`, `binary_expression`, `call_expression`, `member_access_expression`, `array_creation_expression` |
| `_literal` | Literal values | `integer`, `float`, `string`, `boolean`, `null`, `heredoc`, `nowdoc` |
| `_type` | Type annotations | `named_type`, `primitive_type`, `nullable_type`, `union_type`, `intersection_type`, `optional_type` |

#### Key Named Node Types for Knowledge Graph

**Declarations & Definitions:**
- `class_declaration` — fields: `name`, `body`, `modifier` (abstract/final), `base_clause` (extends), `class_interface_clause` (implements)
- `interface_declaration` — fields: `name`, `body`, `base_clause` (extends)
- `trait_declaration` — fields: `name`, `body`
- `enum_declaration` — fields: `name`, `body`, `base_clause`, `class_interface_clause`
- `function_definition` — fields: `name`, `parameters`, `body`, `return_type`
- `method_declaration` — fields: `name`, `parameters`, `body`, `return_type`, `modifier` (visibility, static, abstract)
- `property_declaration` — fields: `type`, `modifier`
- `const_declaration` — constant definitions
- `namespace_definition` — fields: `name`, `body`
- `namespace_use_declaration` — use statements for namespaces

**Expressions (Call Sites & References):**
- `function_call_expression` — fields: `function`, `arguments`
- `member_call_expression` — fields: `object`, `name`, `arguments`
- `scoped_call_expression` — fields: `scope`, `name`, `arguments` (static method calls)
- `object_creation_expression` — `new` expressions
- `member_access_expression` — property access (`->` operator)
- `scoped_property_access_expression` — static property access (`::`)
- `class_constant_access_expression` — `Class::CONSTANT`

**Imports & Includes:**
- `namespace_use_declaration` — `use` statements
- `namespace_use_clause` — individual use clauses
- `namespace_aliasing_clause` — `as` aliases
- `include_expression` / `include_once_expression` / `require_expression` / `require_once_expression`

**Type System:**
- `named_type` — class/interface type references
- `primitive_type` — `int`, `string`, `bool`, `float`, `array`, `void`, `null`, `mixed`, `never`
- `nullable_type` — `?Type`
- `union_type` — `Type1|Type2`
- `intersection_type` — `Type1&Type2`
- `type_list` — parameter/return type lists

**Other Important:**
- `attribute_list` / `attribute` — PHP 8 attributes (decorators)
- `visibility_modifier` — `public`, `protected`, `private`
- `use_declaration` — trait use within classes
- `anonymous_function_creation_expression` — closures
- `arrow_function` — short closures (`fn() =>`)

### 2.3 JavaScript Node Types

#### Supertypes
| Supertype | Description | Example Subtypes |
|---|---|---|
| `statement` | All statement types | `expression_statement`, `if_statement`, `for_statement`, `return_statement`, `class_declaration` |
| `expression` | All expression types | `assignment_expression`, `binary_expression`, `call_expression`, `member_expression`, `new_expression` |
| `declaration` | Declaration types | `class_declaration`, `function_declaration`, `variable_declaration`, `lexical_declaration` |

#### Key Named Node Types for Knowledge Graph

**Declarations:**
- `class_declaration` — fields: `name`, `body`, `superclass` (extends)
- `function_declaration` — fields: `name`, `parameters`, `body`
- `generator_function_declaration` — `function*` declarations
- `variable_declaration` / `lexical_declaration` — `var` / `let`/`const`
- `variable_declarator` — individual binding with `name` and `value` fields
- `method_definition` — fields: `name`, `parameters`, `body`
- `field_definition` — class fields

**Expressions (Call Sites):**
- `call_expression` — fields: `function`, `arguments`
- `new_expression` — `new Constructor()` calls
- `member_expression` — property access (`.` and `[]`)
- `subscript_expression` — bracket access
- `assignment_expression` — fields: `left`, `right`
- `augmented_assignment_expression` — `+=`, `-=`, etc.

**Imports & Exports:**
- `import_statement` — full import declaration
- `import_clause` — what is imported
- `import_specifier` — named imports `{ name }`
- `namespace_import` — `* as name`
- `export_statement` — export declaration
- `export_clause` — `export { ... }`
- `export_specifier` — individual export names

**Functions:**
- `arrow_function` — `() => {}`
- `function_expression` — `function() {}`
- `generator_function` — `function*() {}`

**Other Important:**
- `decorator` — `@decorator` syntax (stage 3 proposal)
- `template_string` — template literals
- `tagged_template_expression` — tagged templates
- `spread_element` — `...args`
- `rest_pattern` — `...rest` in parameters
- `computed_property_name` — `[expr]: value`
- `jsx_element` / `jsx_self_closing_element` — JSX support

### 2.4 TypeScript Node Types

TypeScript's grammar extends JavaScript's grammar, adding 64+ additional node types for the type system.

#### Additional Node Types (Beyond JavaScript)

**Type Declarations:**
- `interface_declaration` — fields: `name`, `body`, `type_parameters`, extends via `extends_type_clause`
- `type_alias_declaration` — `type Name = ...`
- `enum_declaration` — fields: `name`, `body`
- `enum_body` / `enum_assignment` — enum members
- `abstract_class_declaration` — `abstract class`
- `module` — TypeScript namespaces/modules (`namespace X {}` or `module X {}`)

**Type Annotations:**
- `type_annotation` — `: Type` annotations on variables, parameters, properties
- `return_type` — function return type annotations (`: ReturnType`)
- `type_parameters` — `<T, U>` generic parameters
- `type_arguments` — `<string, number>` generic arguments
- `constraint` — `extends` constraints on type parameters
- `default_type` — default type parameter values

**Type Expressions:**
- `union_type` — `A | B`
- `intersection_type` — `A & B`
- `conditional_type` — `A extends B ? C : D`
- `mapped_type` — `{ [K in keyof T]: V }`
- `indexed_access_type` — `T[K]`
- `template_literal_type` — `` `prefix${Type}suffix` ``
- `infer_type` — `infer U` in conditional types
- `type_predicate` — `x is Type` return type
- `asserts` — `asserts x is Type`
- `literal_type` — literal types (`"hello"`, `42`, `true`)
- `lookup_type` — type lookups
- `readonly_type` — `readonly Type`
- `tuple_type` — `[A, B, C]`
- `rest_type` — `...Type` in tuples
- `optional_type` — `Type?` in tuples
- `parenthesized_type` — `(Type)`
- `existential_type` — `*` (Flow compatibility)

**TypeScript-Specific Expressions:**
- `as_expression` — `expr as Type`
- `satisfies_expression` — `expr satisfies Type`
- `non_null_expression` — `expr!`
- `type_assertion` — `<Type>expr`
- `instantiation_expression` — `fn<Type>`

**Access Modifiers:**
- `accessibility_modifier` — `public`, `protected`, `private`
- `override_modifier` — `override`
- `readonly` — `readonly` modifier

**Other:**
- `ambient_declaration` — `declare` statements
- `internal_module` — `namespace` blocks
- `import_require_clause` — `import x = require('...')`
- `implements_clause` — `implements Interface`
- `extends_clause` — `extends BaseClass`

### 2.5 Grammar Structure Differences

| Feature | PHP | JavaScript | TypeScript |
|---|---|---|---|
| **Class Inheritance** | `base_clause` field | `superclass` field | `extends_clause` (from JS) |
| **Interface Implementation** | `class_interface_clause` | N/A | `implements_clause` |
| **Traits** | `trait_declaration`, `use_declaration` | N/A | N/A |
| **Namespaces** | `namespace_definition` | N/A | `module` / `internal_module` |
| **Type Annotations** | `named_type`, `primitive_type` (PHP 7+) | N/A | Full type system nodes |
| **Visibility** | `visibility_modifier` node | N/A (no syntax) | `accessibility_modifier` |
| **Imports** | `namespace_use_declaration` | `import_statement` | `import_statement` (extended) |
| **Decorators/Attributes** | `attribute_list` (PHP 8) | `decorator` (stage 3) | `decorator` |
| **Enums** | `enum_declaration` (PHP 8.1) | N/A | `enum_declaration` |
| **Generics** | N/A | N/A | `type_parameters`, `type_arguments` |


---

## 3. Tree-sitter Query Syntax & Key Queries

### 3.1 Query Syntax Reference

Tree-sitter queries use **S-expression** syntax for pattern matching against the CST.

#### Core Syntax Elements

| Element | Syntax | Description |
|---|---|---|
| **Node match** | `(node_type)` | Match a node by type |
| **Capture** | `@name` | Capture matched node for extraction |
| **Field** | `field_name:` | Match child by field name |
| **Anonymous node** | `"+"` or `"class"` | Match literal/keyword tokens |
| **Wildcard** | `(_)` | Match any single named node |
| **Alternation** | `[node_a node_b]` | Match any of listed types |
| **Quantifiers** | `(node)+`, `(node)*`, `(node)?` | One+, zero+, optional |
| **Anchor** | `.` | Anchor to first/last child position |
| **Negation** | `#not-eq?` | Negate a predicate |

#### Predicates

| Predicate | Usage | Description |
|---|---|---|
| `#eq?` | `(#eq? @cap "value")` | Exact text match |
| `#not-eq?` | `(#not-eq? @cap "value")` | Negated exact match |
| `#match?` | `(#match? @cap "regex")` | Regex match on node text |
| `#not-match?` | `(#not-match? @cap "regex")` | Negated regex match |
| `#any-of?` | `(#any-of? @cap "a" "b" "c")` | Match any of listed strings |
| `#is?` | `(#is? @cap type)` | Check node property |
| `#set!` | `(#set! key value)` | Set metadata on match |

### 3.2 Key Queries for Knowledge Graph Extraction

#### Class Declarations with Names and Parent Classes

**PHP:**
```scm
;; Class with optional extends and implements
(class_declaration
  name: (name) @class.name
  (base_clause (name) @class.extends)?
  (class_interface_clause (name) @class.implements)?
  body: (declaration_list) @class.body
) @class.def

;; Abstract/Final classes
(class_declaration
  (class_modifier) @class.modifier
  name: (name) @class.name
) @class.def

;; Trait declarations
(trait_declaration
  name: (name) @trait.name
  body: (declaration_list) @trait.body
) @trait.def

;; Interface declarations
(interface_declaration
  name: (name) @interface.name
  (base_clause (name) @interface.extends)?
  body: (declaration_list) @interface.body
) @interface.def
```

**JavaScript:**
```scm
;; Class with optional superclass
(class_declaration
  name: (identifier) @class.name
  (class_heritage (extends_clause (identifier) @class.extends))?
  body: (class_body) @class.body
) @class.def

;; Class expressions (assigned to variables)
(variable_declarator
  name: (identifier) @class.name
  value: (class
    (class_heritage (extends_clause (_) @class.extends))?
    body: (class_body) @class.body
  )
) @class.expr
```

**TypeScript:**
```scm
;; Class with extends, implements, and type parameters
(class_declaration
  name: (type_identifier) @class.name
  (type_parameters) @class.type_params
  (extends_clause (identifier) @class.extends)?
  (implements_clause (type_identifier) @class.implements)?
  body: (class_body) @class.body
) @class.def

;; Abstract class
(abstract_class_declaration
  name: (type_identifier) @class.name
  (type_parameters) @class.type_params
  (extends_clause (_) @class.extends)?
  (implements_clause (_) @class.implements)?
  body: (class_body) @class.body
) @class.def

;; Interface declarations
(interface_declaration
  name: (type_identifier) @interface.name
  (type_parameters) @interface.type_params
  (extends_type_clause (_) @interface.extends)?
  body: (object_type) @interface.body
) @interface.def

;; Type alias declarations
(type_alias_declaration
  name: (type_identifier) @type_alias.name
  (type_parameters) @type_alias.type_params
  value: (_) @type_alias.value
) @type_alias.def
```

#### Function/Method Declarations with Parameters and Return Types

**PHP:**
```scm
;; Standalone function
(function_definition
  name: (name) @func.name
  parameters: (formal_parameters) @func.params
  return_type: (_)? @func.return_type
  body: (compound_statement) @func.body
) @func.def

;; Class method
(method_declaration
  (visibility_modifier) @method.visibility
  (static_modifier)? @method.static
  name: (name) @method.name
  parameters: (formal_parameters) @method.params
  return_type: (_)? @method.return_type
  body: (compound_statement) @method.body
) @method.def

;; Constructor
(method_declaration
  name: (name) @method.name
  (#eq? @method.name "__construct")
  parameters: (formal_parameters) @constructor.params
) @constructor.def

;; Individual parameters with types
(simple_parameter
  type: (_)? @param.type
  name: (variable_name) @param.name
  default_value: (_)? @param.default
) @param.def
```

**JavaScript:**
```scm
;; Function declaration
(function_declaration
  name: (identifier) @func.name
  parameters: (formal_parameters) @func.params
  body: (statement_block) @func.body
) @func.def

;; Arrow function assigned to variable
(lexical_declaration
  (variable_declarator
    name: (identifier) @func.name
    value: (arrow_function
      parameters: (_) @func.params
      body: (_) @func.body
    )
  )
) @func.def

;; Method definition in class
(method_definition
  name: (property_identifier) @method.name
  parameters: (formal_parameters) @method.params
  body: (statement_block) @method.body
) @method.def
```

**TypeScript:**
```scm
;; Function with type annotations
(function_declaration
  name: (identifier) @func.name
  (type_parameters)? @func.type_params
  parameters: (formal_parameters) @func.params
  return_type: (type_annotation)? @func.return_type
  body: (statement_block) @func.body
) @func.def

;; Method with accessibility modifier
(method_definition
  (accessibility_modifier)? @method.visibility
  (override_modifier)? @method.override
  name: (property_identifier) @method.name
  (type_parameters)? @method.type_params
  parameters: (formal_parameters) @method.params
  return_type: (type_annotation)? @method.return_type
  body: (statement_block) @method.body
) @method.def

;; Typed parameters
(required_parameter
  pattern: (identifier) @param.name
  type: (type_annotation) @param.type
) @param.def

(optional_parameter
  pattern: (identifier) @param.name
  type: (type_annotation)? @param.type
  value: (_)? @param.default
) @param.def
```

#### Import/Require Statements

**PHP:**
```scm
;; use statements
(namespace_use_declaration
  (namespace_use_clause
    (qualified_name) @import.path
    (namespace_aliasing_clause (name) @import.alias)?
  )
) @import.def

;; use function / use const
(namespace_use_declaration
  "function" @import.kind
  (namespace_use_clause
    (qualified_name) @import.path
  )
) @import.def

;; require/include
(expression_statement
  (require_expression (_) @import.path)
) @import.require

(expression_statement
  (include_expression (_) @import.path)
) @import.include
```

**JavaScript:**
```scm
;; ES module imports
(import_statement
  (import_clause
    [(identifier) @import.default
     (named_imports
       (import_specifier
         name: (identifier) @import.name
         alias: (identifier)? @import.alias
       )
     )
     (namespace_import (identifier) @import.namespace)
    ]
  )
  source: (string) @import.source
) @import.def

;; Dynamic import
(call_expression
  function: (import) @import.dynamic
  arguments: (arguments (string) @import.source)
) @import.dynamic_call

;; CommonJS require
(call_expression
  function: (identifier) @_func
  (#eq? @_func "require")
  arguments: (arguments (string) @import.source)
) @import.require
```

**TypeScript:**
```scm
;; Same as JavaScript plus:
;; Type-only imports
(import_statement
  "type" @import.type_only
  (import_clause
    (named_imports
      (import_specifier
        name: (identifier) @import.name
      )
    )
  )
  source: (string) @import.source
) @import.type_import

;; import = require()
(import_require_clause
  (identifier) @import.name
  source: (string) @import.source
) @import.require
```

#### Export Statements

**JavaScript / TypeScript:**
```scm
;; Named exports
(export_statement
  (export_clause
    (export_specifier
      name: (identifier) @export.name
      alias: (identifier)? @export.alias
    )
  )
) @export.named

;; Default export
(export_statement
  "default" @export.default
  value: (_) @export.value
) @export.default_decl

;; Export declaration (export class/function/const)
(export_statement
  declaration: (_) @export.declaration
) @export.decl

;; Re-exports
(export_statement
  source: (string) @export.source
) @export.reexport
```

#### Call Sites (Function Calls, Method Calls)

**PHP:**
```scm
;; Function call
(function_call_expression
  function: [(name) (qualified_name)] @call.function
  arguments: (arguments) @call.args
) @call.site

;; Method call (instance)
(member_call_expression
  object: (_) @call.object
  name: (name) @call.method
  arguments: (arguments) @call.args
) @call.site

;; Static method call
(scoped_call_expression
  scope: (name) @call.class
  name: (name) @call.method
  arguments: (arguments) @call.args
) @call.site

;; Constructor call
(object_creation_expression
  (name) @call.class
  (arguments)? @call.args
) @call.new
```

**JavaScript:**
```scm
;; Simple function call
(call_expression
  function: (identifier) @call.function
  arguments: (arguments) @call.args
) @call.site

;; Method call
(call_expression
  function: (member_expression
    object: (_) @call.object
    property: (property_identifier) @call.method
  )
  arguments: (arguments) @call.args
) @call.method_site

;; Chained method call
(call_expression
  function: (member_expression
    object: (call_expression) @call.chain_prev
    property: (property_identifier) @call.method
  )
  arguments: (arguments) @call.args
) @call.chained

;; new Constructor()
(new_expression
  constructor: (_) @call.constructor
  arguments: (arguments)? @call.args
) @call.new
```

**TypeScript:**
```scm
;; Same as JavaScript, plus generic call
(call_expression
  function: (identifier) @call.function
  (type_arguments) @call.type_args
  arguments: (arguments) @call.args
) @call.generic_site
```

#### Inheritance Relationships (extends, implements)

**PHP:**
```scm
;; Class extends
(class_declaration
  name: (name) @child.name
  (base_clause (name) @parent.name)
) @extends.rel

;; Class implements
(class_declaration
  name: (name) @class.name
  (class_interface_clause (name) @interface.name)
) @implements.rel

;; Interface extends interface
(interface_declaration
  name: (name) @child.name
  (base_clause (name) @parent.name)
) @extends.rel

;; Trait use
(use_declaration
  (name) @trait.name
) @uses_trait.rel
```

**JavaScript:**
```scm
(class_declaration
  name: (identifier) @child.name
  (class_heritage
    (extends_clause (_) @parent.name)
  )
) @extends.rel
```

**TypeScript:**
```scm
;; extends
(class_declaration
  name: (type_identifier) @child.name
  (extends_clause (_) @parent.name)
) @extends.rel

;; implements
(class_declaration
  name: (type_identifier) @class.name
  (implements_clause (_) @interface.name)
) @implements.rel

;; Interface extends
(interface_declaration
  name: (type_identifier) @child.name
  (extends_type_clause (_) @parent.name)
) @extends.rel
```

#### Decorators / Attributes

**PHP (Attributes):**
```scm
(attribute_list
  (attribute
    (name) @decorator.name
    (arguments)? @decorator.args
  )
) @decorator.def
```

**JavaScript / TypeScript (Decorators):**
```scm
(decorator
  (call_expression
    function: (identifier) @decorator.name
    arguments: (arguments) @decorator.args
  )
) @decorator.call

(decorator
  (identifier) @decorator.name
) @decorator.ref
```

#### Namespace Declarations (PHP)

```scm
(namespace_definition
  name: (namespace_name) @namespace.name
  body: (compound_statement)? @namespace.body
) @namespace.def

;; Bracketed namespace
(namespace_definition
  name: (namespace_name) @namespace.name
  body: (declaration_list) @namespace.body
) @namespace.def
```

#### TypeScript Type Annotations

```scm
;; Variable type annotation
(variable_declarator
  name: (identifier) @var.name
  type: (type_annotation (_) @var.type)
) @var.typed

;; Function return type
(function_declaration
  name: (identifier) @func.name
  return_type: (type_annotation (_) @func.return_type)
) @func.typed

;; Property type
(public_field_definition
  name: (property_identifier) @prop.name
  type: (type_annotation (_) @prop.type)
) @prop.typed

;; Generic constraints
(type_parameter
  name: (type_identifier) @generic.name
  constraint: (constraint (_) @generic.constraint)?
  value: (default_type (_) @generic.default)?
) @generic.param
```

---

## 4. Incremental Parsing

### 4.1 How It Works

Tree-sitter's incremental parsing is its defining feature. When source code changes, instead of re-parsing the entire file, Tree-sitter:

1. **Receives edit information** describing what changed (byte offsets and row/column positions)
2. **Marks affected subtrees** as needing re-parse
3. **Reuses unchanged subtrees** from the previous parse
4. **Re-parses only the minimal region** affected by the edit

Internally, Tree-sitter maintains a parse tree where each node stores its byte range. When an edit is applied, it walks the tree to find nodes whose ranges overlap with the edit, marks them dirty, and during the next parse, only regenerates those portions.

### 4.2 The Edit API

```python
import tree_sitter
from tree_sitter_language_pack import get_parser

parser = get_parser("python")

# Initial parse
source = b"def hello():\n    print('world')\n"
tree = parser.parse(source)

# Simulate editing: change 'world' to 'earth'
# 'world' starts at byte 22, ends at byte 27
new_source = b"def hello():\n    print('earth')\n"

# Tell the tree about the edit BEFORE re-parsing
tree.edit(
    start_byte=22,
    old_end_byte=27,
    new_end_byte=27,
    start_point=(1, 11),      # row, column of edit start
    old_end_point=(1, 16),    # row, column of old edit end
    new_end_point=(1, 16),    # row, column of new edit end
)

# Re-parse with the old tree — only changed region is re-parsed
new_tree = parser.parse(new_source, tree)

# Find what changed between old and new tree
changed_ranges = tree.changed_ranges(new_tree)
for r in changed_ranges:
    print(f"Changed: bytes {r.start_byte}-{r.end_byte}, "
          f"rows {r.start_point[0]}-{r.end_point[0]}")
```

### 4.3 Edit Parameters Explained

| Parameter | Type | Description |
|---|---|---|
| `start_byte` | int | Byte offset where the edit begins |
| `old_end_byte` | int | Byte offset where the old text ended |
| `new_end_byte` | int | Byte offset where the new text ends |
| `start_point` | (int, int) | (row, column) where edit begins |
| `old_end_point` | (int, int) | (row, column) where old text ended |
| `new_end_point` | (int, int) | (row, column) where new text ends |

**For insertions**: `old_end_byte == start_byte` (nothing was removed)
**For deletions**: `new_end_byte == start_byte` (nothing was added)
**For replacements**: All three differ

### 4.4 Repository-Level Incremental Strategy

For a code knowledge graph builder processing entire repositories:

```python
import os
import hashlib
from pathlib import Path

class IncrementalRepoParser:
    """Parse only changed files in a repository."""

    def __init__(self):
        self.file_hashes = {}   # path -> content hash
        self.file_trees = {}    # path -> last Tree object
        self.parsers = {}       # language -> Parser

    def get_changed_files(self, repo_path: str) -> tuple[list, list]:
        """Detect files that changed since last parse."""
        changed = []
        current_files = set()

        for root, dirs, files in os.walk(repo_path):
            # Skip hidden dirs, node_modules, vendor
            dirs[:] = [d for d in dirs if not d.startswith('.')
                       and d not in ('node_modules', 'vendor', '__pycache__')]
            for f in files:
                path = os.path.join(root, f)
                current_files.add(path)

                content = Path(path).read_bytes()
                content_hash = hashlib.sha256(content).hexdigest()

                if path not in self.file_hashes or self.file_hashes[path] != content_hash:
                    changed.append(path)
                    self.file_hashes[path] = content_hash

        # Detect deleted files
        deleted = set(self.file_hashes.keys()) - current_files
        for d in deleted:
            del self.file_hashes[d]
            self.file_trees.pop(d, None)

        return changed, list(deleted)

    def parse_file(self, path: str, content: bytes, language: str):
        """Parse a file, using incremental parsing if previous tree exists."""
        parser = self.parsers.get(language)
        if not parser:
            from tree_sitter_language_pack import get_parser
            parser = get_parser(language)
            self.parsers[language] = parser

        old_tree = self.file_trees.get(path)
        # For file-level changes, full re-parse is typical.
        # Incremental parsing is most beneficial for editor-style edits.
        tree = parser.parse(content, old_tree)
        self.file_trees[path] = tree
        return tree
```

**Important**: For a knowledge graph builder that processes git diffs (file-level changes), the primary optimization is **skipping unchanged files entirely** rather than using Tree-sitter's character-level incremental parsing. The incremental API is most beneficial for editor integrations where individual keystrokes modify the buffer.

### 4.5 Performance Characteristics

| Operation | Typical Performance | Notes |
|---|---|---|
| **Initial parse (small file, <500 LOC)** | 1-5 ms | Virtually instant |
| **Initial parse (medium file, ~2K LOC)** | 5-20 ms | Still very fast |
| **Initial parse (large file, ~10K LOC)** | 50-100 ms | Acceptable for batch processing |
| **Incremental re-parse (single edit)** | <1 ms | Sub-millisecond for character edits |
| **Incremental re-parse (multi-edit)** | 1-5 ms | Depends on edit spread |
| **Memory per tree** | ~2-10x source size | Trees are relatively compact |
| **Query execution** | <1 ms per query per file | Pattern matching is very fast |
| **Batch: 1000 files** | 5-30 seconds | Depends on file sizes |
| **Batch: 10,000 files** | 30-120 seconds | Parallelizable across files |

**Memory**: A parsed tree typically uses 2-10x the source file size in memory. For a 100KB source file, expect 200KB-1MB for the tree. Trees can be dropped after query extraction to free memory.

**Parallelization**: Each `Parser` instance is NOT thread-safe, but you can create separate `Parser` instances per thread. Trees and Nodes are read-only and thread-safe. For repository-scale parsing, use a thread pool with per-thread parsers.

---

## 5. py-tree-sitter Python Bindings

### 5.1 Installation

```bash
# Recommended: tree-sitter + language pack (no compilation needed)
pip install tree-sitter tree-sitter-language-pack

# Versions as of 2026-03:
# tree-sitter >= 0.25.2
# tree-sitter-language-pack >= 0.13.0
# Requires Python >= 3.10 (CPython only)
```

### 5.2 Loading Language Grammars

#### Using tree-sitter-language-pack (Recommended)

```python
from tree_sitter_language_pack import get_parser, get_language, get_binding

# Get a pre-configured parser
php_parser = get_parser("php")
js_parser = get_parser("javascript")
ts_parser = get_parser("typescript")

# Or get just the Language object
php_lang = get_language("php")
js_lang = get_language("javascript")
ts_lang = get_language("typescript")

# Or get the raw C binding (PyCapsule)
php_binding = get_binding("php")
```

#### Using Individual Grammar Packages

```python
import tree_sitter
import tree_sitter_php
import tree_sitter_javascript
import tree_sitter_typescript

# Create parser and set language
parser = tree_sitter.Parser()
parser.language = tree_sitter.Language(tree_sitter_php.language())

# For TypeScript (has both typescript and tsx)
ts_lang = tree_sitter.Language(tree_sitter_typescript.language_typescript())
tsx_lang = tree_sitter.Language(tree_sitter_typescript.language_tsx())
```

### 5.3 Core API

#### Parser

```python
from tree_sitter_language_pack import get_parser

parser = get_parser("typescript")

# Parse bytes
source = b"const x: number = 42;"
tree = parser.parse(source)

# Parse with encoding callback (for large files or streaming)
def read_callback(byte_offset, point):
    row, col = point
    return source[byte_offset:byte_offset + 1024]

tree = parser.parse(read_callback)

# Incremental parse
new_tree = parser.parse(new_source, old_tree=tree)

# Set timeout (microseconds) — 0 means no timeout
parser.timeout_micros = 1_000_000  # 1 second

# Set included ranges (for embedded languages)
import tree_sitter
parser.included_ranges = [
    tree_sitter.Range(
        start_point=(5, 0), end_point=(10, 0),
        start_byte=100, end_byte=250
    )
]
```

#### Tree

```python
tree = parser.parse(source)

# Root node
root = tree.root_node
print(root.type)           # "program" or "translation_unit"
print(root.start_byte)     # 0
print(root.end_byte)       # len(source)
print(root.start_point)    # (0, 0)
print(root.end_point)      # (row, col)

# S-expression representation (useful for debugging)
print(root.sexp())
# (program (lexical_declaration (variable_declarator name: (identifier) ...

# Edit notification (for incremental parsing)
tree.edit(
    start_byte=10,
    old_end_byte=15,
    new_end_byte=20,
    start_point=(0, 10),
    old_end_point=(0, 15),
    new_end_point=(0, 20),
)

# Detect changes between trees
changed = old_tree.changed_ranges(new_tree)

# Walk the tree
cursor = tree.walk()
```

#### Node

```python
node = tree.root_node

# Identity
node.type              # "class_declaration"
node.id                # Unique numeric ID
node.is_named          # True for named nodes, False for anonymous
node.is_missing        # True if inserted by error recovery
node.has_error         # True if subtree contains errors
node.is_error          # True if this is an ERROR node

# Position
node.start_byte        # Start byte offset
node.end_byte          # End byte offset
node.start_point       # (row, column) tuple
node.end_point         # (row, column) tuple
node.byte_range        # (start_byte, end_byte)
node.range             # Range object

# Text (requires source bytes)
node.text              # bytes — the source text of this node
                       # (only if tree was parsed from bytes, not callback)

# Children
node.children          # All children (named + anonymous)
node.named_children    # Only named children
node.child_count       # Total child count
node.named_child_count # Named child count
node.child(index)      # Get child by index
node.named_child(index)# Get named child by index

# Field access
node.child_by_field_name("name")    # Get child by field name
node.children_by_field_name("item") # Get all children with field name
node.field_name_for_child(index)    # Get field name for child at index

# Navigation
node.parent            # Parent node
node.next_sibling      # Next sibling (including anonymous)
node.prev_sibling      # Previous sibling
node.next_named_sibling  # Next named sibling
node.prev_named_sibling  # Previous named sibling

# Descendant lookup
node.descendant_for_byte_range(start, end)
node.named_descendant_for_byte_range(start, end)
node.descendant_for_point_range(start_point, end_point)
node.named_descendant_for_point_range(start_point, end_point)
```

#### TreeCursor (Efficient Traversal)

```python
cursor = tree.walk()

# Navigation
cursor.goto_first_child()   # Returns True if child exists
cursor.goto_next_sibling()  # Returns True if sibling exists
cursor.goto_parent()        # Returns True if parent exists

# Current node info
cursor.node                 # Current Node object
cursor.field_name           # Field name of current node (or None)
cursor.depth                # Depth in tree

# Efficient depth-first traversal
def walk_tree(cursor, depth=0):
    yield cursor.node, depth
    if cursor.goto_first_child():
        yield from walk_tree(cursor, depth + 1)
        while cursor.goto_next_sibling():
            yield from walk_tree(cursor, depth + 1)
        cursor.goto_parent()
```

#### Query

```python
from tree_sitter_language_pack import get_language, get_parser

lang = get_language("typescript")
parser = get_parser("typescript")

# Create a query
query = lang.query("""
(class_declaration
  name: (type_identifier) @class.name
  (implements_clause
    (type_identifier) @class.implements
  )?
  body: (class_body) @class.body
) @class.def
""")

# Parse source
source = b"""
export class UserService implements IUserService {
    private db: Database;

    async getUser(id: string): Promise<User> {
        return this.db.find(id);
    }
}
"""
tree = parser.parse(source)

# Execute query — returns list of (pattern_index, captures_dict)
matches = query.matches(tree.root_node)
for pattern_idx, captures in matches:
    for name, nodes in captures.items():
        for node in nodes:
            print(f"  {name}: {node.text.decode()}")

# Alternative: captures() returns flat list of (node, capture_name)
captures = query.captures(tree.root_node)
for node, name in captures:
    print(f"{name}: {node.text.decode()} at {node.start_point}")
```

### 5.4 Complete Working Example: Extract Knowledge Graph Entities

```python
"""Extract classes, functions, imports, and relationships from TypeScript."""
from tree_sitter_language_pack import get_parser, get_language
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ClassEntity:
    name: str
    file: str
    line: int
    extends: Optional[str] = None
    implements: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)

@dataclass
class FunctionEntity:
    name: str
    file: str
    line: int
    params: list[str] = field(default_factory=list)
    return_type: Optional[str] = None

@dataclass
class ImportEntity:
    source: str
    names: list[str]
    file: str
    line: int
    is_type_only: bool = False

def extract_entities(source: bytes, filename: str, language: str = "typescript"):
    """Extract all knowledge graph entities from source code."""
    lang = get_language(language)
    parser = get_parser(language)
    tree = parser.parse(source)

    classes = []
    functions = []
    imports = []

    # --- Class extraction query ---
    class_query = lang.query("""
    (class_declaration
      name: (type_identifier) @class.name
      body: (class_body) @class.body
    ) @class.def
    """)

    for pattern_idx, captures in class_query.matches(tree.root_node):
        name_nodes = captures.get("class.name", [])
        def_nodes = captures.get("class.def", [])
        if not name_nodes:
            continue

        name_node = name_nodes[0]
        def_node = def_nodes[0] if def_nodes else name_node

        cls = ClassEntity(
            name=name_node.text.decode(),
            file=filename,
            line=name_node.start_point[0] + 1,
        )

        # Check for extends/implements
        for child in def_node.children:
            if child.type == "extends_clause":
                for c in child.named_children:
                    cls.extends = c.text.decode()
            elif child.type == "implements_clause":
                for c in child.named_children:
                    cls.implements.append(c.text.decode())

        # Extract method names from body
        body_nodes = captures.get("class.body", [])
        if body_nodes:
            for child in body_nodes[0].named_children:
                if child.type == "method_definition":
                    method_name = child.child_by_field_name("name")
                    if method_name:
                        cls.methods.append(method_name.text.decode())

        classes.append(cls)

    # --- Function extraction query ---
    func_query = lang.query("""
    (function_declaration
      name: (identifier) @func.name
      parameters: (formal_parameters) @func.params
      return_type: (type_annotation)? @func.return
    ) @func.def
    """)

    for pattern_idx, captures in func_query.matches(tree.root_node):
        name_nodes = captures.get("func.name", [])
        if not name_nodes:
            continue

        name_node = name_nodes[0]
        func = FunctionEntity(
            name=name_node.text.decode(),
            file=filename,
            line=name_node.start_point[0] + 1,
        )

        param_nodes = captures.get("func.params", [])
        if param_nodes:
            for child in param_nodes[0].named_children:
                pattern = child.child_by_field_name("pattern")
                if pattern:
                    func.params.append(pattern.text.decode())

        return_nodes = captures.get("func.return", [])
        if return_nodes:
            func.return_type = return_nodes[0].text.decode().lstrip(": ")

        functions.append(func)

    # --- Import extraction query ---
    import_query = lang.query("""
    (import_statement
      source: (string) @import.source
    ) @import.def
    """)

    for pattern_idx, captures in import_query.matches(tree.root_node):
        source_nodes = captures.get("import.source", [])
        def_nodes = captures.get("import.def", [])
        if not source_nodes:
            continue

        source_text = source_nodes[0].text.decode().strip("'\"")
        def_node = def_nodes[0]

        names = []
        is_type_only = False
        for child in def_node.children:
            if child.type == "import_clause":
                for ic in child.named_children:
                    if ic.type == "identifier":
                        names.append(ic.text.decode())
                    elif ic.type == "named_imports":
                        for spec in ic.named_children:
                            if spec.type == "import_specifier":
                                name = spec.child_by_field_name("name")
                                if name:
                                    names.append(name.text.decode())
                    elif ic.type == "namespace_import":
                        for ns in ic.named_children:
                            names.append(f"* as {ns.text.decode()}")
            elif child.text == b"type":
                is_type_only = True

        imports.append(ImportEntity(
            source=source_text,
            names=names,
            file=filename,
            line=def_node.start_point[0] + 1,
            is_type_only=is_type_only,
        ))

    return classes, functions, imports


# --- Usage Example ---
if __name__ == "__main__":
    sample_ts = b"""
import { Injectable } from '@nestjs/common';
import { Repository } from 'typeorm';
import type { User } from './user.entity';

@Injectable()
export class UserService extends BaseService implements IUserService {
    constructor(private readonly repo: Repository<User>) {
        super();
    }

    async findById(id: string): Promise<User | null> {
        return this.repo.findOne({ where: { id } });
    }

    async create(data: CreateUserDto): Promise<User> {
        const user = this.repo.create(data);
        return this.repo.save(user);
    }
}

function validateEmail(email: string): boolean {
    return /^[^@]+@[^@]+$/.test(email);
}
"""

    classes, functions, imports = extract_entities(sample_ts, "user.service.ts")

    print("=== Classes ===")
    for c in classes:
        print(f"  {c.name} (line {c.line})")
        if c.extends: print(f"    extends: {c.extends}")
        if c.implements: print(f"    implements: {c.implements}")
        print(f"    methods: {c.methods}")

    print("\n=== Functions ===")
    for f in functions:
        print(f"  {f.name}({', '.join(f.params)}) -> {f.return_type} (line {f.line})")

    print("\n=== Imports ===")
    for i in imports:
        type_str = " [type-only]" if i.is_type_only else ""
        print(f"  from '{i.source}': {i.names}{type_str} (line {i.line})")
```

---

## 6. Tree-sitter Limitations

### 6.1 Fundamental Limitations (All Languages)

#### Syntax-Only, No Semantic Analysis

Tree-sitter is a **parser**, not a **compiler** or **type checker**. It operates purely on syntax.

| What Tree-sitter CAN do | What Tree-sitter CANNOT do |
|---|---|
| Parse syntactically valid code into a CST | Resolve types or infer types |
| Identify class/function declarations | Determine which overload is called |
| Extract import statements | Resolve import paths to actual files |
| Find call sites syntactically | Determine the actual target of a call (dynamic dispatch) |
| Detect extends/implements keywords | Verify type compatibility |
| Parse type annotations (TS) | Evaluate conditional types or mapped types |
| Handle syntactically invalid code (error recovery) | Understand runtime behavior |

#### Anonymous Node Information Loss

As documented by the Cubix Framework analysis, Tree-sitter's anonymous nodes (operators, keywords, punctuation) are often skipped by default traversal methods. However, **this is addressable in py-tree-sitter**:

```python
# WRONG: Only named children (loses operators)
for child in node.named_children:
    pass

# RIGHT: All children including operators
for child in node.children:
    if not child.is_named:
        # This is an operator, keyword, or punctuation
        print(f"Anonymous: '{child.type}' = '{child.text.decode()}'")
```

For a knowledge graph builder, this means:
- Binary expression operators ARE accessible via `node.children`
- Visibility keywords ARE accessible
- You just need to be explicit about accessing them

#### CST vs AST: Flat Children Lists

Tree-sitter produces a CST, not an AST. Key differences:
- Children are flat lists without categorical grouping
- `choice()` alternatives in the grammar don't produce wrapper nodes
- Hidden rules (prefixed with `_`) are suppressed in output
- You must use **field names** to navigate structure reliably

#### No Roundtripping

Tree-sitter is one-way: source -> tree. There is no built-in pretty-printer to go tree -> source. For a knowledge graph builder, this is not a limitation since we only need to extract information, not transform code.

#### Error Recovery Opacity

When Tree-sitter encounters syntax errors, it inserts `ERROR` and `MISSING` nodes. The error recovery strategy is not always predictable:
- `ERROR` nodes may contain large subtrees
- Recovery points can be surprising
- Partial parses may misclassify nodes near errors

**Mitigation**: Check `node.has_error` before trusting extracted data from a subtree.

### 6.2 PHP-Specific Limitations

| Limitation | Impact | Workaround |
|---|---|---|
| **Dynamic method calls** (`$obj->$method()`) | Cannot determine call target | Log as "dynamic_call" edge with unknown target |
| **Variable variables** (`$$var`) | Cannot resolve variable name | Skip or mark as unresolvable |
| **Magic methods** (`__call`, `__get`) | Invisible call routing | Document known magic method patterns |
| **String class references** (`$class = 'Foo'; new $class()`) | Cannot resolve class name | Mark as dynamic instantiation |
| **eval() and include with variables** | Cannot determine included code | Mark as dynamic include |
| **Traits with conflict resolution** | Complex `insteadof`/`as` clauses | Parse trait use declarations carefully |
| **Reserved word constants** (issue #295) | Constant names matching reserved words cause parse errors | Known grammar bug; affects edge cases |
| **PHP/HTML mixed mode** | PHP embedded in HTML requires special handling | Use `tree-sitter-php` which handles `<?php` tags |
| **Heredoc/Nowdoc** | Complex string syntax | Parsed correctly but content is opaque |

### 6.3 JavaScript-Specific Limitations

| Limitation | Impact | Workaround |
|---|---|---|
| **Dynamic property access** (`obj[expr]`) | Cannot determine property name | Mark as dynamic access |
| **Prototype manipulation** (`Foo.prototype.bar = ...`) | Implicit class modification | Pattern-match prototype assignments |
| **`apply`/`call`/`bind`** | Changes `this` context | Cannot resolve statically |
| **Computed property names** (`{[expr]: val}`) | Cannot determine key | Mark as computed |
| **Tagged template literals** (issues #337, #364) | Escape sequences too restricted; extending grammars fail | Known grammar bugs |
| **Optional chaining with reserved words** (issues #377, #378) | `obj?.class` fails to parse | Known grammar bug |
| **JSX text with ampersand** (issue #366) | `&` breaks jsx_text parsing | Known grammar bug |
| **ASI edge cases** (issue #354) | Arrow functions followed by parenthesized expressions | Edge case parsing errors |
| **`String.raw`** (issue #362) | Not supported | Known limitation |
| **Default export classification** (issue #323) | Anonymous function declarations misclassified as expressions | Known grammar bug |
| **Float vs Int distinction** (issue #374) | `number` node doesn't distinguish `1` from `1.5` | Check text content |
| **Destructuring complexity** | Deeply nested destructuring is syntactically correct but hard to extract | Walk the pattern tree recursively |
| **Proxy/Reflect** | Invisible interception | Cannot detect statically |

### 6.4 TypeScript-Specific Limitations

| Limitation | Impact | Workaround |
|---|---|---|
| **Type inference** | Tree-sitter sees annotations, not inferred types | Only explicit types are extractable |
| **Conditional types** (`A extends B ? C : D`) | Parsed syntactically but not evaluated | Store as type expression string |
| **Mapped types** (`{ [K in keyof T]: V }`) | Parsed but not resolved | Store as type expression string |
| **Template literal types** | Parsed but not evaluated | Store as type expression string |
| **Declaration merging** | Multiple declarations of same interface merge | Must aggregate across declarations |
| **Module augmentation** | `declare module` extends existing types | Track augmentation declarations |
| **`keyof import()` syntax** (issue #352) | Parse error on valid syntax | Known grammar bug |
| **`export type *`** (issue #358) | Not parsed correctly | Known grammar bug |
| **Type arguments on tagged templates** (issues #342, #350) | Missing type argument support | Known grammar bug |
| **LaTeX strings** (issue #353) | Breaks syntax highlighting | Edge case |
| **Infinite recursion in type queries** (issue #346) | Can cause parser hang | Known grammar bug |
| **Overloaded functions** | Multiple signatures for same function | Collect all signature nodes |
| **Ambient declarations** (`declare`) | Type-only, no implementation | Mark as ambient in graph |
| **Generic type resolution** | `Array<T>` -- what is T? | Cannot resolve; store generic reference |
| **Enum const evaluation** | `enum { A = 1 + 2 }` | Cannot evaluate expressions |

### 6.5 Cross-Language Limitations for Knowledge Graph Building

| Challenge | Description | Strategy |
|---|---|---|
| **Cross-file resolution** | Tree-sitter parses one file at a time | Build import graph, resolve references in post-processing |
| **Dynamic dispatch** | `obj.method()` -- which class's method? | Use type annotations where available; mark as ambiguous otherwise |
| **Monkey patching** | Runtime modifications to classes/prototypes | Cannot detect; document as limitation |
| **Reflection/metaprogramming** | `Reflect`, `eval`, PHP `ReflectionClass` | Cannot analyze; mark as opaque |
| **Configuration-driven behavior** | DI containers, route configs | Parse config files separately |
| **Generated code** | Code generated at build time | Parse generated output, not templates |
| **Aliased re-exports** | `export { Foo as Bar }` | Track alias chains |

---

## 7. Grammar Repositories

### 7.1 Repository Overview

| Grammar | Repository | Stars | Forks | Open Issues | License | Created | Last Updated |
|---|---|---|---|---|---|---|---|
| **PHP** | [tree-sitter/tree-sitter-php](https://github.com/tree-sitter/tree-sitter-php) | 211 | 69 | 1 | MIT | 2017-11 | 2026-02 |
| **JavaScript** | [tree-sitter/tree-sitter-javascript](https://github.com/tree-sitter/tree-sitter-javascript) | 465 | 172 | 21 | MIT | 2014-07 | 2025-11 |
| **TypeScript** | [tree-sitter/tree-sitter-typescript](https://github.com/tree-sitter/tree-sitter-typescript) | 499 | 152 | 44 | MIT | 2017-02 | 2025-08 |

### 7.2 PHP Grammar (tree-sitter-php)

**Quality: HIGH** -- Very mature with only 1 open issue.

- **Coverage**: PHP 5.x through PHP 8.3+ syntax
- **Features**: Full support for classes, interfaces, traits, enums, attributes, union/intersection types, named arguments, fibers, readonly properties, match expressions
- **Structure**: Contains two sub-grammars: `php` (with `<?php` tags) and `php_only` (without tags)
- **Known Issues**:
  - #295: Constants with reserved word names cause parse errors (edge case)
- **Maintenance**: Actively maintained, last push Feb 2026
- **Completeness**: ~99% of PHP syntax covered

### 7.3 JavaScript Grammar (tree-sitter-javascript)

**Quality: HIGH** -- The oldest and most battle-tested grammar.

- **Coverage**: ES2015+ through ES2024 syntax
- **Features**: Full support for classes, modules, async/await, generators, destructuring, optional chaining, nullish coalescing, private fields, static blocks, decorators (stage 3)
- **JSX**: Built-in JSX support
- **Known Issues** (notable):
  - #377/#378: Reserved words after optional chaining (`?.`) not recognized as property identifiers
  - #366: Ampersand breaks jsx_text
  - #364: Grammars extending JS fail to parse template literals
  - #362: `String.raw` not supported
  - #337: Escape sequences too restricted for tagged templates
  - #323: Default export of anonymous function misclassified
- **Maintenance**: Actively maintained, last push Nov 2025
- **Completeness**: ~97% of JS syntax covered; edge cases around template literals and optional chaining

### 7.4 TypeScript Grammar (tree-sitter-typescript)

**Quality: HIGH** -- Extends the JavaScript grammar with full type system support.

- **Coverage**: TypeScript 4.x through 5.x syntax
- **Structure**: Contains two sub-grammars: `typescript` and `tsx`
- **Features**: Full type annotation support, generics, conditional types, mapped types, template literal types, satisfies operator, const type parameters, decorators
- **Known Issues** (notable):
  - #352: `keyof import('a').A` parse error
  - #358: `export type *` not parsed
  - #350/#342: Type arguments on tagged template calls missing
  - #346: Infinite recursion in type query rules (potential hang)
  - #348: `export type * as Name from './module'` produces ERROR
- **Maintenance**: Actively maintained, last push Aug 2025
- **Completeness**: ~96% of TS syntax covered; edge cases around advanced type expressions and export syntax
- **Dependency**: Inherits from tree-sitter-javascript; JS grammar updates may need to be pulled in

### 7.5 Grammar Update Frequency

| Grammar | Avg. Commits/Year (2023-2025) | Release Cadence |
|---|---|---|
| PHP | ~30-40 | Irregular, follows PHP releases |
| JavaScript | ~20-30 | Irregular, follows TC39 proposals |
| TypeScript | ~25-35 | Irregular, follows TS releases |

All three grammars are under the official `tree-sitter` GitHub organization, ensuring long-term maintenance and community support.

### 7.6 Using via tree-sitter-language-pack

The `tree-sitter-language-pack` (v0.13.0) bundles pre-compiled binaries for all three grammars:

```python
from tree_sitter_language_pack import get_parser

# These "just work" -- no compilation needed
php_parser = get_parser("php")          # PHP with <?php tags
js_parser = get_parser("javascript")    # JavaScript + JSX
ts_parser = get_parser("typescript")    # TypeScript
tsx_parser = get_parser("tsx")          # TypeScript + JSX
```

---

## 8. Implications for Knowledge Graph Builder

### 8.1 What Tree-sitter Gives Us

1. **Fast, reliable parsing** of PHP, JS, and TS with error recovery
2. **Structural extraction** of all declaration types (classes, functions, interfaces, types)
3. **Import/export graph** construction from syntactic import statements
4. **Call site identification** (syntactic -- who calls what)
5. **Inheritance/implementation relationships** from extends/implements clauses
6. **Type annotation extraction** (TypeScript explicit types, PHP type hints)
7. **Decorator/attribute extraction** for metadata
8. **Incremental capability** for efficient re-processing of changed files

### 8.2 What We Must Build On Top

1. **Cross-file import resolution**: Map import paths to actual files using project configuration (tsconfig.json, composer.json, package.json)
2. **Symbol table**: Aggregate all declarations across files into a unified namespace
3. **Call graph resolution**: Use the symbol table to resolve call sites to their targets
4. **Type propagation**: For TypeScript, propagate explicit types through assignments and returns
5. **Dynamic dispatch handling**: Mark ambiguous calls and use heuristics (class hierarchy, type annotations) to narrow targets
6. **Alias tracking**: Follow re-exports, namespace aliases, and trait use declarations
7. **Scope analysis**: Determine variable scoping for accurate reference resolution

### 8.3 Recommended Architecture

```
Phase 1: Parse & Extract (Tree-sitter)
|-- Parse all files with appropriate language grammar
|-- Run extraction queries for each entity type
|-- Produce per-file entity lists (classes, functions, imports, exports, calls)
|-- Store raw extraction results

Phase 2: Resolve & Link (Custom Logic)
|-- Build import graph (resolve paths to files)
|-- Build symbol table (aggregate all declarations)
|-- Resolve call sites to declaration targets
|-- Build inheritance graph (extends/implements chains)
|-- Track re-exports and aliases
|-- Produce knowledge graph edges

Phase 3: Enrich & Query (Graph Database)
|-- Store entities as nodes with properties
|-- Store relationships as typed edges
|-- Add metadata (file, line, visibility, type annotations)
|-- Enable graph queries ("who calls this?", "what implements this interface?")
|-- Support incremental updates (re-process only changed files)
```

### 8.4 Performance Budget Estimate

For a medium-sized codebase (~5,000 files, ~500K LOC):

| Phase | Estimated Time | Notes |
|---|---|---|
| File discovery & hashing | 1-3 seconds | OS-level file walk |
| Parsing all files | 15-45 seconds | ~3-9ms per file average |
| Query extraction | 10-30 seconds | Multiple queries per file |
| Import resolution | 2-5 seconds | Path resolution logic |
| Symbol table construction | 1-3 seconds | In-memory aggregation |
| Call graph resolution | 5-15 seconds | Depends on call density |
| **Total initial build** | **~35-100 seconds** | First run |
| **Incremental update (10 files)** | **<2 seconds** | Skip unchanged files |

---

## Appendix A: Node Types JSON Files

The raw `node-types.json` files for each grammar are stored at:
- `/a0/usr/projects/codebase_knowledgebuilder/research-data/php-node-types.json`
- `/a0/usr/projects/codebase_knowledgebuilder/research-data/js-node-types.json`
- `/a0/usr/projects/codebase_knowledgebuilder/research-data/ts-node-types.json`
- `/a0/usr/projects/codebase_knowledgebuilder/research-data/tsx-node-types.json`

These contain the complete grammar specification including all node types, fields, children, and subtypes.

## Appendix B: Quick Reference -- Entity Extraction Queries

| Entity | PHP Query Root | JS Query Root | TS Query Root |
|---|---|---|---|
| Class | `class_declaration` | `class_declaration` | `class_declaration`, `abstract_class_declaration` |
| Interface | `interface_declaration` | N/A | `interface_declaration` |
| Trait | `trait_declaration` | N/A | N/A |
| Enum | `enum_declaration` | N/A | `enum_declaration` |
| Function | `function_definition` | `function_declaration` | `function_declaration` |
| Method | `method_declaration` | `method_definition` | `method_definition` |
| Import | `namespace_use_declaration` | `import_statement` | `import_statement` |
| Export | N/A | `export_statement` | `export_statement` |
| Type Alias | N/A | N/A | `type_alias_declaration` |
| Namespace | `namespace_definition` | N/A | `module` / `internal_module` |
| Decorator | `attribute_list` | `decorator` | `decorator` |
| Call Site | `function_call_expression`, `member_call_expression`, `scoped_call_expression` | `call_expression`, `new_expression` | `call_expression`, `new_expression` |
| Property | `property_declaration` | `field_definition` | `public_field_definition` |

## Appendix C: Sources & References

1. Tree-sitter Official Documentation: https://tree-sitter.github.io/tree-sitter/
2. py-tree-sitter (v0.25.2): https://pypi.org/project/tree-sitter/
3. tree-sitter-language-pack (v0.13.0): https://pypi.org/project/tree-sitter-language-pack/
4. tree-sitter-php: https://github.com/tree-sitter/tree-sitter-php
5. tree-sitter-javascript: https://github.com/tree-sitter/tree-sitter-javascript
6. tree-sitter-typescript: https://github.com/tree-sitter/tree-sitter-typescript
7. "Why Tree-Sitter Is Inadequate for Program Analysis" - Cubix Framework: https://www.cubix-framework.com/tree-sitter-limitations.html
8. GitHub Semantic - Why Tree-sitter: https://github.com/github/semantic/blob/master/docs/why-tree-sitter.md
9. Tree-sitter Query Syntax Documentation: https://tree-sitter.github.io/tree-sitter/using-parsers/queries
10. Incremental Parsing with Tree-sitter: https://dasroot.net/posts/2026/02/incremental-parsing-tree-sitter-code-analysis/
