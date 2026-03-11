# AST Parsing & Code Knowledge Graph Construction
# Comprehensive Technical Research for PHP, JavaScript & TypeScript

> **Date**: 2026-03-10  
> **Purpose**: Inform architecture decisions for a custom repository parsing solution that builds knowledge graphs from codebases  
> **Languages**: PHP (custom + Laravel), JavaScript (ES Modules + CommonJS), TypeScript  
> **Research Corpus**: 5 detailed research documents totaling ~606KB of technical analysis  

---

## Table of Contents

1. [Executive Summary & Architecture Decisions](#1-executive-summary--architecture-decisions)
2. [Tree-sitter Capabilities](#2-tree-sitter-capabilities)
3. [PHP-Specific Parsing](#3-php-specific-parsing)
4. [JavaScript/TypeScript Parsing](#4-javascripttypescript-parsing)
5. [Graph Schema Design](#5-graph-schema-design)
6. [Cross-Language Patterns](#6-cross-language-patterns)
7. [Unified Schema Specification](#7-unified-schema-specification)
8. [Implementation Roadmap](#8-implementation-roadmap)
9. [Appendices](#9-appendices)

---

## 1. Executive Summary & Architecture Decisions

### 1.1 Core Findings

This research synthesizes deep technical analysis across five domains to establish the foundation for a code knowledge graph builder. The key findings are:

1. **Tree-sitter is the optimal primary parser** for all three languages. It provides fast (~5-50ms/file), incremental, error-tolerant parsing with consistent CST output across PHP, JavaScript, and TypeScript. The Python bindings (py-tree-sitter) are mature and the grammars are actively maintained.

2. **A multi-parser strategy is required for PHP**. Tree-sitter handles structural extraction, but nikic/PHP-Parser is needed for name resolution (namespace/use statement resolution), and PHPStan/Larastan provides type enrichment that AST alone cannot deliver.

3. **JavaScript/TypeScript module resolution is the hardest problem**. The combination of ES Modules, CommonJS, TypeScript path mappings, bundler aliases, package.json exports, and monorepo workspaces creates a complex resolution matrix. A dedicated Python ModuleResolver is required.

4. **SQLite + NetworkX hybrid is the optimal storage backend**. SQLite with WAL mode + FTS5 provides portable, zero-infrastructure storage with sub-millisecond queries via recursive CTEs. NetworkX supplements with graph algorithms (PageRank, betweenness centrality) for context relevance ranking.

5. **Cross-language connections are detectable with high confidence**. PHP API routes can be matched to JavaScript fetch/axios calls through a multi-strategy matching pipeline (exact → parameterized → prefix → fuzzy), achieving 85-95% coverage for well-structured codebases.

### 1.2 Architecture Decision Record

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Primary parser | Tree-sitter (py-tree-sitter) | Fast, incremental, error-tolerant, multi-language, Python bindings |
| PHP name resolution | nikic/PHP-Parser (subprocess) | De facto standard, built-in NameResolver visitor |
| PHP type enrichment | PHPStan/Larastan (subprocess) | Resolves facades, container bindings, Eloquent types |
| JS/TS module resolution | Custom Python ModuleResolver | Must handle ESM, CJS, TS paths, aliases, exports field |
| Graph storage | SQLite (WAL + FTS5) | Portable, zero-infra, sub-ms queries, single file |
| Graph algorithms | NetworkX (in-memory) | PageRank, centrality, shortest path for context ranking |
| Query language | SQL (recursive CTEs) + Python | No external query engine dependency |
| Output format | Structured Markdown with token budgeting | Optimized for LLM context windows |
| Schema | 22 node types, 24+ edge types | Unified across PHP/JS/TS with language-specific extensions |
| Incremental updates | Content-hash based file tracking | Skip unchanged files, re-parse only modified |

### 1.3 Performance Budget (5,000-file codebase)

| Phase | Estimated Time | Notes |
|-------|---------------|-------|
| File discovery | <1s | Filesystem scan + gitignore filtering |
| Tree-sitter parsing (all files) | 25-50s | ~5-10ms/file average |
| PHP name resolution | 10-30s | nikic/PHP-Parser subprocess batch |
| Module resolution (JS/TS) | 5-15s | Path resolution + node_modules traversal |
| Framework pattern detection | 5-10s | Route/model/event extraction |
| Cross-language matching | 2-5s | URL pattern matching |
| Graph construction | 2-5s | SQLite inserts + index building |
| **Total initial build** | **50-120s** | |
| **Incremental update** | **<2s** | Content-hash skip for unchanged files |

### 1.4 Research Document Index

| Document | Size | Focus |
|----------|------|-------|
| `research-treesitter-deep-dive.md` | 61KB / 1,703 lines | Tree-sitter architecture, node types, queries, Python bindings, limitations |
| `research-php-parsing.md` | 75KB / 2,038 lines | PHP parsers comparison, constructs, dynamic dispatch, static analysis, Laravel |
| `research-js-ts-parsing.md` | 142KB / 4,506 lines | JS/TS modules, JSX/TSX, TypeScript constructs, module resolution, frameworks |
| `research-graph-schema.md` | 64KB / 1,459 lines | Graph node/edge types, storage options, LLM queries, existing tool analysis |
| `research-cross-language.md` | 276KB / 7,648 lines | PHP→JS connections, mixed projects, metadata extraction, detection algorithms |

---

## 2. Tree-sitter Capabilities

> Detailed reference: `research-treesitter-deep-dive.md`

### 2.1 Architecture Overview

Tree-sitter is an incremental parsing system that produces Concrete Syntax Trees (CSTs). Key properties:

- **Incremental**: Re-parses only changed portions of a file using an edit API
- **Error-tolerant**: Produces valid trees even for syntactically broken code (critical for in-progress editing)
- **Fast**: Written in C, typically parses files in 5-50ms
- **Consistent**: All languages produce trees with the same API, enabling unified extraction logic
- **Query system**: S-expression pattern matching for declarative entity extraction

### 2.2 Node Type Statistics

| Language | Grammar | Total Node Types | Named Node Types | Supertypes |
|----------|---------|-----------------|------------------|------------|
| PHP | tree-sitter-php | 305 | 162 | 7 (statement, expression, type, literal, primary_expression, declaration, _scope_resolution) |
| JavaScript | tree-sitter-javascript | 226 | 119 | 4 (expression, declaration, statement, pattern) |
| TypeScript | tree-sitter-typescript | 324 | 183 | 5 (expression, declaration, statement, pattern, type) |
| TSX | tree-sitter-tsx | 330+ | 185+ | 5 (same as TS + JSX nodes) |

### 2.3 Key Entity Node Types by Language

#### PHP
| Entity | Node Type | Key Fields |
|--------|-----------|------------|
| Class | `class_declaration` | `name`, `body`, `modifier` (abstract) |
| Interface | `interface_declaration` | `name`, `body` |
| Trait | `trait_declaration` | `name`, `body` |
| Enum | `enum_declaration` | `name`, `body` |
| Method | `method_declaration` | `name`, `parameters`, `return_type`, `visibility_modifier` |
| Function | `function_definition` | `name`, `parameters`, `return_type` |
| Property | `property_declaration` | `name`, `type`, `visibility_modifier` |
| Namespace | `namespace_definition` | `name`, `body` |
| Use statement | `namespace_use_declaration` | `(namespace_use_clause)` children |
| Inheritance | `base_clause` | parent class reference |
| Implements | `class_interface_clause` | interface references |
| Trait use | `use_declaration` | trait references |
| Call | `member_call_expression`, `scoped_call_expression`, `function_call_expression` | `name`, `object`/`scope`, `arguments` |
| Attribute | `attribute_list` → `attribute` | `name`, `parameters` |

#### JavaScript
| Entity | Node Type | Key Fields |
|--------|-----------|------------|
| Class | `class_declaration` | `name`, `body` |
| Function | `function_declaration` | `name`, `parameters`, `body` |
| Arrow function | `arrow_function` | `parameters`, `body` |
| Method | `method_definition` | `name`, `parameters`, `body` |
| Variable | `variable_declaration` → `variable_declarator` | `name`, `value` |
| Import | `import_statement` | `source`, specifiers |
| Export | `export_statement` | `declaration`, `source` |
| Require | `call_expression` with `require` | `arguments` |
| Call | `call_expression` | `function`, `arguments` |
| Class heritage | `class_heritage` | extends reference |
| JSX element | `jsx_element`, `jsx_self_closing_element` | `name`, `attribute` children |

#### TypeScript
Inherits all JavaScript node types plus:

| Entity | Node Type | Key Fields |
|--------|-----------|------------|
| Interface | `interface_declaration` | `name`, `body`, `type_parameters` |
| Type alias | `type_alias_declaration` | `name`, `value`, `type_parameters` |
| Enum | `enum_declaration` | `name`, `body` |
| Generic params | `type_parameters` → `type_parameter` | `name`, `constraint` |
| Type annotation | `type_annotation` | `type` |
| Decorator | `decorator` | `value` (call_expression or identifier) |
| Abstract class | `abstract_class_declaration` | `name`, `body` |
| Ambient declaration | `ambient_declaration` | `declaration` |
| Namespace | `internal_module` | `name`, `body` |

### 2.4 Tree-sitter Query System

Tree-sitter queries use S-expression syntax with captures (`@name`), predicates (`#match?`, `#eq?`), and field names.

#### Essential Extraction Queries

**PHP - Classes with inheritance:**
~~~scm
(class_declaration
  name: (name) @class.name
  (base_clause (name) @class.parent)?
  (class_interface_clause (name) @class.interface)*
  body: (declaration_list) @class.body
) @class.def
~~~

**PHP - Methods with visibility:**
~~~scm
(method_declaration
  (visibility_modifier) @method.visibility
  (static_modifier)? @method.static
  name: (name) @method.name
  parameters: (formal_parameters) @method.params
  return_type: (_)? @method.return_type
) @method.def
~~~

**PHP - Namespace and use statements:**
~~~scm
(namespace_definition
  name: (namespace_name) @namespace.name
) @namespace.def

(namespace_use_declaration
  (namespace_use_clause
    (qualified_name) @use.name
    (namespace_aliasing_clause (name) @use.alias)?
  )
) @use.def
~~~

**PHP - Function/method calls:**
~~~scm
;; Static method calls: ClassName::method()
(scoped_call_expression
  scope: (_) @call.scope
  name: (name) @call.method
  arguments: (arguments) @call.args
) @call.static

;; Instance method calls: $obj->method()
(member_call_expression
  object: (_) @call.object
  name: (name) @call.method
  arguments: (arguments) @call.args
) @call.instance

;; Function calls: func()
(function_call_expression
  function: (_) @call.function
  arguments: (arguments) @call.args
) @call.func
~~~

**JavaScript/TypeScript - Imports (ESM + CJS):**
~~~scm
;; ES Module imports
(import_statement
  source: (string) @import.source
  (import_clause
    [(identifier) @import.default
     (named_imports
       (import_specifier
         name: (identifier) @import.name
         alias: (identifier)? @import.alias))
     (namespace_import (identifier) @import.namespace)]
  )?
) @import.esm

;; CommonJS require
(call_expression
  function: (identifier) @_func
  arguments: (arguments (string) @require.source)
  (#eq? @_func "require")
) @import.cjs

;; Dynamic import()
(call_expression
  function: (import)
  arguments: (arguments (_) @import.source)
) @import.dynamic
~~~

**TypeScript - Interfaces and type aliases:**
~~~scm
(interface_declaration
  name: (type_identifier) @interface.name
  type_parameters: (type_parameters)? @interface.generics
  (extends_type_clause
    (type_identifier) @interface.extends)*
  body: (interface_body) @interface.body
) @interface.def

(type_alias_declaration
  name: (type_identifier) @type.name
  type_parameters: (type_parameters)? @type.generics
  value: (_) @type.value
) @type.def
~~~

**TypeScript - Decorators:**
~~~scm
(decorator
  (call_expression
    function: (identifier) @decorator.name
    arguments: (arguments) @decorator.args)
) @decorator.call

(decorator
  (identifier) @decorator.name
) @decorator.bare
~~~

### 2.5 py-tree-sitter Python API

#### Installation
~~~bash
pip install tree-sitter tree-sitter-language-pack
~~~

#### Basic Usage
~~~python
import tree_sitter_language_pack as tslp

# Get language and parser
parser = tslp.get_parser("php")
tree = parser.parse(bytes(source_code, "utf-8"))

# Run a query
language = tslp.get_language("php")
query = language.query("""
(class_declaration
  name: (name) @class.name
  (base_clause (name) @class.parent)?
) @class.def
""")

matches = query.matches(tree.root_node)
for match_id, captures in matches:
    for capture_name, nodes in captures.items():
        for node in nodes:
            print(f"{capture_name}: {node.text.decode()}"
                  f" at line {node.start_point[0]+1}")
~~~

#### Incremental Parsing
~~~python
# Initial parse
tree = parser.parse(source_bytes)

# After editing the source (e.g., inserting text at line 10, col 5)
tree.edit(
    start_byte=old_start_byte,
    old_end_byte=old_end_byte,
    new_end_byte=new_end_byte,
    start_point=(10, 5),
    old_end_point=(10, 5),
    new_end_point=(10, 20)
)

# Re-parse with the old tree for incremental parsing
new_tree = parser.parse(new_source_bytes, tree)

# Get changed ranges
for range in tree.changed_ranges(new_tree):
    print(f"Changed: {range.start_point} -> {range.end_point}")
~~~

### 2.6 Tree-sitter Limitations

| Limitation | Impact | Mitigation |
|-----------|--------|------------|
| **Syntax-only** (no semantic analysis) | Cannot resolve types, infer values, or understand runtime behavior | Supplement with PHPStan, TypeScript compiler API |
| **No cross-file awareness** | Each file parsed independently; no import resolution | Build custom module resolver on top |
| **CST not AST** | Trees include all tokens (punctuation, whitespace nodes) | Filter to named nodes only in extraction |
| **No type inference** | Cannot determine types of untyped variables | Use PHPStan/Psalm for PHP; TS compiler for TypeScript |
| **Dynamic features invisible** | `$obj->$method()`, `eval()`, `call_user_func()` not resolvable | Log as unresolved; use static analysis tools for partial resolution |
| **PHP string interpolation** | Complex interpolated strings may have simplified tree structure | Accept limitation; extract what is available |
| **Template literals** | Dynamic template parts not resolvable | Extract static prefix when possible |
| **Decorator metadata** | Decorator arguments parsed syntactically, not semantically | Pattern-match known decorator signatures |

---


## 3. PHP-Specific Parsing

> Detailed reference: `research-php-parsing.md`

### 3.1 Parser Comparison

| Feature | tree-sitter-php | nikic/PHP-Parser | glayzzle/php-parser |
|---------|----------------|-----------------|--------------------|
| Language | C (with Python/Rust/Node bindings) | PHP | JavaScript |
| Output | CST (Concrete Syntax Tree) | AST (Abstract Syntax Tree) | AST |
| Speed | ~5-50ms/file | ~50-200ms/file | ~100-500ms/file |
| PHP version support | PHP 8.4 (full) | PHP 7.0-8.4 | PHP 7.x (incomplete 8.x) |
| Error recovery | Yes (built-in) | Partial (error nodes) | Limited |
| Incremental parsing | Yes | No | No |
| Name resolution | No | Yes (NameResolver visitor) | No |
| Type inference | No | No | No |
| Python integration | Native (py-tree-sitter) | Subprocess | Subprocess (Node.js) |
| Maintenance status | Active (tree-sitter org) | Active (nikic) | Effectively unmaintained |
| **Recommendation** | **Primary parser** | **Name resolution only** | **Do not use** |

### 3.2 Multi-Parser Strategy

No single parser handles all PHP knowledge graph requirements. The recommended strategy:

1. **tree-sitter-php** (Primary): Structural extraction of all entities — classes, methods, functions, properties, traits, enums, namespaces, use statements, call sites, attributes
2. **nikic/PHP-Parser** (Supplementary): Name resolution — resolving short class names to fully-qualified names using namespace context and use statements
3. **PHPStan/Larastan** (Enrichment): Type inference — resolving untyped variables, facade bindings, container injections, Eloquent model types

#### Integration Architecture
~~~python
# Phase 1: Tree-sitter extracts structure
tree = parser.parse(source_bytes)
entities = extract_entities(tree)  # classes, methods, calls, etc.

# Phase 2: nikic/PHP-Parser resolves names (batch subprocess)
result = subprocess.run(
    ["php", "resolve_names.php", "--batch", file_list_path],
    capture_output=True
)
name_map = json.loads(result.stdout)  # {short_name: fqcn}

# Phase 3: PHPStan enriches types (optional, for deep analysis)
result = subprocess.run(
    ["vendor/bin/phpstan", "analyse", "--level=6",
     "--error-format=json", "src/"],
    capture_output=True
)
type_info = json.loads(result.stdout)  # type errors reveal type info
~~~

### 3.3 PHP-Specific Constructs

#### Namespaces and Use Statements
PHP namespaces are critical for resolving class references to file paths (via PSR-4 autoloading).

**Tree-sitter extraction:**
~~~scm
;; Namespace declaration
(namespace_definition
  name: (namespace_name) @ns.name
) @ns.def

;; Use statements (all forms)
(namespace_use_declaration
  ["function" "const"]? @use.type
  (namespace_use_clause
    (qualified_name) @use.name
    (namespace_aliasing_clause (name) @use.alias)?
  )
) @use.def

;; Group use: use App\Models\{User, Post, Comment};
(namespace_use_declaration
  (namespace_use_group
    (namespace_name) @use.prefix
    (namespace_use_clause
      (namespace_name) @use.suffix
      (namespace_aliasing_clause (name) @use.alias)?
    )+
  )
) @use.group
~~~

**PSR-4 Resolution Algorithm (Python):**
~~~python
def resolve_fqcn_to_file(fqcn: str, psr4_map: dict) -> str | None:
    """Resolve a fully-qualified class name to a file path.
    psr4_map from composer.json: {"App\\\\": "src/"}
    """
    for prefix, base_dir in sorted(psr4_map.items(),
                                     key=lambda x: -len(x[0])):
        if fqcn.startswith(prefix):
            relative = fqcn[len(prefix):].replace("\\\\", "/") + ".php"
            return os.path.join(base_dir, relative)
    return None
~~~

#### Traits
Traits are PHP's mechanism for horizontal code reuse. They inject methods into classes and can create complex resolution chains.

~~~scm
;; Trait declaration
(trait_declaration
  name: (name) @trait.name
  body: (declaration_list) @trait.body
) @trait.def

;; Trait use in class
(use_declaration
  (name) @trait.used
  (use_list
    (use_instead_of_clause)? @trait.insteadof
    (use_as_clause)? @trait.as
  )?
) @trait.use
~~~

**Graph edges for traits:**
- `uses_trait`: Class → Trait
- `trait_overrides`: Trait method → Trait method (insteadof resolution)
- `trait_aliases`: Trait method → alias name (as clause)

#### Magic Methods
Magic methods create implicit call paths that are invisible to static AST analysis:

| Magic Method | Trigger | Graph Implication |
|-------------|---------|------------------|
| `__construct` | `new ClassName()` | Explicit — captured by `instantiates` edge |
| `__call` | `$obj->undefinedMethod()` | Any unresolved method call might route here |
| `__callStatic` | `ClassName::undefinedMethod()` | Any unresolved static call might route here |
| `__get` | `$obj->undefinedProperty` | Property access on objects with `__get` is dynamic |
| `__set` | `$obj->undefinedProperty = x` | Property writes may be intercepted |
| `__invoke` | `$obj()` | Object used as function — creates callable edge |
| `__toString` | `(string)$obj` or string context | Implicit conversion — rarely graph-relevant |

**Detection strategy:** When a class defines `__call` or `__callStatic`, flag all unresolved method calls on instances of that class as "potentially dynamic" with reduced confidence.

#### Laravel Facades
Facades map static method calls to service container bindings:

~~~php
// What code looks like:
Cache::get('key');  // Static call to Cache facade

// What actually happens:
app('cache')->get('key');  // Resolves to Illuminate\Cache\CacheManager
~~~

**Resolution strategy:**
1. Find facade classes (extend `Illuminate\Support\Facades\Facade`)
2. Extract `getFacadeAccessor()` return value
3. Map accessor to service container binding
4. Create edge: `FacadeClass --resolves_to--> ActualClass`

**Common Laravel facade mappings:**

| Facade | Accessor | Actual Class |
|--------|----------|--------------|
| `Cache` | `'cache'` | `Illuminate\Cache\CacheManager` |
| `DB` | `'db'` | `Illuminate\Database\DatabaseManager` |
| `Auth` | `'auth'` | `Illuminate\Auth\AuthManager` |
| `Route` | `'router'` | `Illuminate\Routing\Router` |
| `Queue` | `'queue'` | `Illuminate\Queue\QueueManager` |
| `Event` | `'events'` | `Illuminate\Events\Dispatcher` |
| `Log` | `'log'` | `Illuminate\Log\LogManager` |
| `Mail` | `'mailer'` | `Illuminate\Mail\Mailer` |

#### Eloquent Model Relationships
Eloquent relationships define the data model graph:

~~~scm
;; Detect relationship methods
(method_declaration
  name: (name) @method.name
  body: (compound_statement
    (return_statement
      (member_call_expression
        object: (variable_name (name) @_this)
        name: (name) @rel.type
        arguments: (arguments
          (class_constant_access_expression
            (name) @rel.target)?
        )
        (#match? @_this "this")
        (#match? @rel.type
          "^(hasOne|hasMany|belongsTo|belongsToMany|hasManyThrough|hasOneThrough|morphTo|morphMany|morphOne|morphToMany|morphedByMany)$")
      )
    )
  )
) @rel.def
~~~

**Graph edges for Eloquent:**

| Relationship | Edge Type | Direction |
|-------------|-----------|----------|
| `hasOne` | `has_one` | Parent → Child |
| `hasMany` | `has_many` | Parent → Children |
| `belongsTo` | `belongs_to` | Child → Parent |
| `belongsToMany` | `many_to_many` | Model ↔ Model (via pivot) |
| `morphTo` | `morph_to` | Polymorphic child → parent |
| `morphMany` | `morph_many` | Parent → polymorphic children |

### 3.4 Dynamic Dispatch Handling

| Pattern | Statically Resolvable? | Strategy |
|---------|----------------------|----------|
| `$obj->method()` | Yes (if type known) | Use PHPStan type info |
| `$obj->$method()` | No | Log as unresolved, flag class |
| `call_user_func([$obj, 'method'])` | Partially (string literal) | Extract string, resolve if literal |
| `call_user_func($callback)` | No (variable) | Log as unresolved |
| `new $className()` | No (variable) | Check if assigned from config/constant |
| `ClassName::$staticMethod()` | No (variable) | Log as unresolved |
| `static::method()` | Yes (late static binding) | Resolve to calling class hierarchy |
| `self::method()` | Yes | Resolve to defining class |
| `parent::method()` | Yes | Resolve to parent class |

### 3.5 Static Analysis Enrichment

**PHPStan integration for type enrichment:**
~~~bash
# Run PHPStan and capture JSON output
vendor/bin/phpstan analyse --level=6 --error-format=json src/ 2>/dev/null
~~~

**Larastan additions** (Laravel-specific PHPStan extension):
- Resolves facade method calls to actual class methods
- Understands Eloquent model properties from database schema
- Resolves service container bindings
- Validates route parameters and middleware

**Integration approach:**
1. Run PHPStan/Larastan as subprocess
2. Parse JSON output for type information
3. Enrich graph nodes with resolved types
4. Add confidence scores based on PHPStan level

---

## 4. JavaScript/TypeScript Parsing

> Detailed reference: `research-js-ts-parsing.md`

### 4.1 Module System Detection

JavaScript has two module systems that must both be handled:

| Feature | ES Modules (ESM) | CommonJS (CJS) |
|---------|------------------|----------------|
| Syntax | `import`/`export` | `require()`/`module.exports` |
| Loading | Static (hoisted) | Dynamic (runtime) |
| Tree-shakeable | Yes | No |
| File extensions | `.mjs`, `.js` (with `"type": "module"`) | `.cjs`, `.js` (default) |
| Node.js support | Native (14+) | Native (always) |

**Multi-layered detection strategy:**

1. **File extension**: `.mjs` → ESM, `.cjs` → CJS, `.ts`/`.tsx` → ESM (always)
2. **package.json `type` field**: `"module"` → ESM, `"commonjs"` or absent → CJS
3. **AST analysis**: Presence of `import`/`export` statements → ESM; `require()`/`module.exports` → CJS

**Tree-sitter queries for both systems:**
~~~scm
;; ESM: import declarations
(import_statement
  source: (string) @import.source
) @import.esm

;; ESM: export declarations
(export_statement
  source: (string)? @export.source
) @export.esm

;; CJS: require() calls
(call_expression
  function: (identifier) @_fn
  arguments: (arguments (string) @require.source)
  (#eq? @_fn "require")
) @import.cjs

;; CJS: module.exports
(assignment_expression
  left: (member_expression
    object: (identifier) @_mod
    property: (property_identifier) @_exp
    (#eq? @_mod "module")
    (#eq? @_exp "exports")
  )
) @export.cjs
~~~

### 4.2 JSX/TSX Component Extraction

JSX elements represent component usage — critical edges in a React knowledge graph.

**Distinguishing custom components from HTML elements:**
- Uppercase first letter → custom component (e.g., `<UserProfile />`) → creates `renders` edge
- Lowercase first letter → HTML element (e.g., `<div>`) → skip

~~~scm
;; JSX custom component usage
(jsx_element
  open_tag: (jsx_opening_element
    name: [(identifier) (member_expression)] @component.name
    (#match? @component.name "^[A-Z]")
    (jsx_attribute
      (property_identifier) @prop.name
      (_)? @prop.value
    )*
  )
) @component.usage

;; Self-closing JSX components
(jsx_self_closing_element
  name: [(identifier) (member_expression)] @component.name
  (#match? @component.name "^[A-Z]")
  (jsx_attribute
    (property_identifier) @prop.name
    (_)? @prop.value
  )*
) @component.usage_self
~~~

**Graph edges from JSX:**
- `renders`: ParentComponent → ChildComponent
- `passes_prop`: ParentComponent → ChildComponent (with prop name as edge property)

### 4.3 TypeScript-Specific Constructs

#### Interfaces
~~~scm
(interface_declaration
  name: (type_identifier) @interface.name
  type_parameters: (type_parameters
    (type_parameter
      name: (type_identifier) @interface.generic_param
      constraint: (constraint (_) @interface.constraint)?
    )
  )?
  (extends_type_clause
    (type_identifier) @interface.extends
  )*
  body: (interface_body) @interface.body
) @interface.def
~~~

**Graph nodes/edges:**
- Node: `Interface` with properties: name, file, line, generic_params
- Edge: `extends` → parent interface
- Edge: `implements` ← implementing class

#### Generics
Generics create type-level relationships that are important for understanding API contracts:

~~~scm
(type_parameters
  (type_parameter
    name: (type_identifier) @generic.name
    constraint: (constraint
      (extends_type_clause (_) @generic.constraint))?
    value: (default_type (_) @generic.default)?
  )
) @generic.params
~~~

#### Decorators (TC39 Stage 3 + Legacy/Experimental)
~~~scm
;; Decorator with arguments: @Component({...})
(decorator
  (call_expression
    function: (identifier) @decorator.name
    arguments: (arguments) @decorator.args
  )
) @decorator.call

;; Bare decorator: @Injectable
(decorator
  (identifier) @decorator.name
) @decorator.bare

;; Decorator on class
(class_declaration
  (decorator) @class.decorator
  name: (type_identifier) @class.name
) @class.decorated
~~~

**Graph edges:** `decorated_by`: Class/Method → Decorator

#### Enums
~~~scm
(enum_declaration
  name: (identifier) @enum.name
  body: (enum_body
    (enum_assignment
      name: (property_identifier) @enum.member
      value: (_) @enum.value
    )*
  )
) @enum.def
~~~

#### Type Aliases, Union Types, Intersection Types
~~~scm
(type_alias_declaration
  name: (type_identifier) @type.name
  type_parameters: (type_parameters)? @type.generics
  value: (_) @type.value
) @type.def

;; Union type members
(union_type
  (_) @union.member
) @union.def

;; Intersection type members
(intersection_type
  (_) @intersection.member
) @intersection.def
~~~

### 4.4 Module Path Resolution

Module resolution is the most complex part of JS/TS parsing. The resolution order:

1. **Core modules**: `fs`, `path`, `http`, etc. → mark as external
2. **Relative paths** (`./`, `../`): Try exact → add extensions (.ts, .tsx, .js, .jsx, .json) → try as directory (index.ts, index.js)
3. **TypeScript paths**: Match against `tsconfig.json` `paths` with `baseUrl`
4. **Bundler aliases**: Match against webpack `resolve.alias` or vite `resolve.alias`
5. **Package imports** (`#` prefix): Resolve via `package.json` `imports` field
6. **node_modules**: Walk up directory tree, check `package.json` `exports` field (conditional exports: types > import > require > default), then `main`/`module`/`types` fields

**Key implementation details:**

~~~python
class ModuleResolver:
    def __init__(self, project_root: str):
        self.root = project_root
        self.tsconfig = self._load_tsconfig()
        self.aliases = self._load_bundler_aliases()
        self.workspaces = self._discover_workspaces()

    EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".json",
                  "/index.ts", "/index.tsx", "/index.js", "/index.jsx"]

    def resolve(self, specifier: str, from_file: str) -> Resolution:
        # 1. Core module check
        if specifier in CORE_MODULES or specifier.startswith("node:"):
            return Resolution(specifier, "core", confidence=1.0)

        # 2. Relative path
        if specifier.startswith("."):
            return self._resolve_relative(specifier, from_file)

        # 3. TypeScript paths
        if self.tsconfig and "paths" in self.tsconfig:
            result = self._resolve_ts_paths(specifier)
            if result: return result

        # 4. Bundler aliases
        for alias, target in self.aliases.items():
            if specifier == alias or specifier.startswith(alias + "/"):
                return self._resolve_alias(specifier, alias, target)

        # 5. Package imports (#prefix)
        if specifier.startswith("#"):
            return self._resolve_package_imports(specifier, from_file)

        # 6. node_modules
        return self._resolve_node_modules(specifier, from_file)
~~~

**Barrel file detection:**
Barrel files (`index.ts` that re-export everything) are common in JS/TS projects. They create indirect dependency chains that should be flattened in the graph:

~~~python
def is_barrel_file(file_path: str, tree) -> bool:
    """Detect if a file is primarily re-exports."""
    export_count = 0
    other_count = 0
    for child in tree.root_node.children:
        if child.type == "export_statement" and child.child_by_field_name("source"):
            export_count += 1  # re-export
        elif child.type not in ("comment", "empty_statement"):
            other_count += 1
    return export_count > 0 and other_count <= 1
~~~

### 4.5 Dynamic Import Resolvability

| Pattern | Resolvability | Confidence |
|---------|--------------|------------|
| `import('./module')` | Static string → 100% | 1.0 |
| `` import(`./pages/${name}`) `` | Template with known prefix → ~60% | 0.6 |
| `import.meta.glob('./pages/*.vue')` | Glob pattern → ~95% | 0.95 |
| `require.context('./modules', true, /\.js$/)` | Directory + regex → ~95% | 0.95 |
| `import(variable)` | Unresolvable → 0% | 0.0 |

**85-95% of imports in well-structured codebases are statically resolvable.**

### 4.6 Framework-Specific Patterns

#### React
- **Hooks**: `useState`, `useEffect`, `useMemo`, `useCallback`, `useRef`, `useContext`, `useReducer`
- **Custom hooks**: Functions starting with `use[A-Z]` → creates `defines_hook` edge
- **Context**: `createContext()` → `provides_context` / `consumes_context` edges
- **Component patterns**: `React.memo()`, `React.forwardRef()`, `React.lazy()` → wrapper edges

#### Next.js
- **App Router**: `app/` directory with `page.tsx`, `layout.tsx`, `loading.tsx`, `error.tsx`, `route.ts`
- **Pages Router**: `pages/` directory with file-based routing
- **Server/Client**: `"use client"` / `"use server"` directives
- **API Routes**: `app/api/*/route.ts` with `GET`, `POST`, `PUT`, `DELETE` exports

#### Vue
- **SFC parsing**: Extract `<template>`, `<script>`, `<style>` blocks
- **Composition API**: `defineProps()`, `defineEmits()`, `defineExpose()`
- **Composables**: Functions in `composables/` directory starting with `use`

#### Angular
- **Decorators**: `@Component`, `@NgModule`, `@Injectable`, `@Directive`, `@Pipe`
- **Dependency injection**: Constructor parameter types
- **Module system**: `@NgModule({ imports, declarations, providers, exports })`

#### NestJS
- **Decorators**: `@Controller`, `@Module`, `@Injectable`
- **HTTP methods**: `@Get()`, `@Post()`, `@Put()`, `@Delete()`, `@Patch()`
- **Guards/Interceptors**: `@UseGuards()`, `@UseInterceptors()`, `@UsePipes()`

---


## 5. Graph Schema Design

> Detailed reference: `research-graph-schema.md`

### 5.1 Existing Tool Analysis

Six existing tools were analyzed to inform schema design:

| Tool | Nodes | Edges | Storage | Key Insight |
|------|-------|-------|---------|-------------|
| code-graph-rag | 15 types | 14 types | Memgraph | Separate Module_Interface and Module_Implementation nodes |
| codebase-memory-mcp | 12 types | 18 types | SQLite (WAL) | Sub-ms queries via content-hash indexing; 64 language support |
| rag-code-mcp | 7 CodeChunk types | Vector similarity | Qdrant | Deep PHP/Laravel support via VKCOM/php-parser |
| Sourcetrail | ~10 types | 10 types | SQLite | Proven schema for IDE-grade code navigation |
| LSIF | LSP-based | LSP-based | JSON dump | Microsoft's Language Server Index Format — standardized |
| Aider | File-level | imports/defines | NetworkX | PageRank for context relevance; tree-sitter tags for extraction |

**Key takeaways:**
- 20-25 node types is the sweet spot (enough for language-specific constructs without over-fragmentation)
- 15-25 edge types covering structural, inheritance, call graph, type system, and framework relationships
- SQLite is the most common storage for portable tools
- PageRank on dependency graphs is proven for LLM context selection

### 5.2 Storage Backend Comparison

| Backend | Query Speed | Memory (5K files) | Incremental Updates | Python Integration | Portability |
|---------|------------|-------------------|--------------------|--------------------|-------------|
| **SQLite + FTS5** | <1ms (indexed) | ~50-100MB on disk | Excellent (UPSERT) | Built-in (sqlite3) | Single file |
| NetworkX | <1ms (in-memory) | ~200-500MB RAM | Good (add/remove) | Native | In-memory only |
| Neo4j | 1-10ms | 500MB+ (server) | Good (MERGE) | neo4j-driver | Requires server |
| DuckDB | <1ms (analytical) | ~100-200MB | Good | duckdb package | Single file |
| RDF/SPARQL | 10-100ms | 500MB+ | Poor | rdflib (slow) | Complex |

**Recommendation: SQLite (WAL mode + FTS5) as primary, NetworkX as supplementary for graph algorithms.**

Rationale:
- SQLite: Zero infrastructure, single-file portability, sub-ms queries via recursive CTEs, built-in FTS5 for text search, excellent Python support
- NetworkX: PageRank, betweenness centrality, shortest path, cycle detection — algorithms that are complex to implement in SQL
- Hybrid approach: SQLite stores the persistent graph; NetworkX loads a projection for algorithm execution

### 5.3 SQLite Schema Design

~~~sql
-- Core tables
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,           -- unique identifier (file:line:name)
    kind TEXT NOT NULL,            -- node type (class, function, method, etc.)
    name TEXT NOT NULL,            -- entity name
    qualified_name TEXT,           -- fully-qualified name (namespace\Class::method)
    file_path TEXT NOT NULL,       -- relative file path
    start_line INTEGER,
    end_line INTEGER,
    language TEXT NOT NULL,        -- php, javascript, typescript
    visibility TEXT,               -- public, protected, private, null
    is_static BOOLEAN DEFAULT 0,
    is_abstract BOOLEAN DEFAULT 0,
    is_async BOOLEAN DEFAULT 0,
    signature TEXT,                -- function/method signature
    docblock TEXT,                 -- extracted documentation
    metadata JSON,                 -- language-specific properties
    content_hash TEXT,             -- for incremental updates
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES nodes(id),
    target_id TEXT NOT NULL REFERENCES nodes(id),
    kind TEXT NOT NULL,            -- edge type (calls, imports, extends, etc.)
    confidence REAL DEFAULT 1.0,   -- 0.0-1.0 confidence score
    line_number INTEGER,           -- where the relationship occurs
    metadata JSON,                 -- edge-specific properties
    UNIQUE(source_id, target_id, kind, line_number)
);

CREATE TABLE files (
    path TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    content_hash TEXT NOT NULL,    -- SHA-256 for change detection
    size_bytes INTEGER,
    line_count INTEGER,
    module_system TEXT,            -- esm, cjs, php
    last_parsed TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX idx_nodes_kind ON nodes(kind);
CREATE INDEX idx_nodes_file ON nodes(file_path);
CREATE INDEX idx_nodes_name ON nodes(name);
CREATE INDEX idx_nodes_qualified ON nodes(qualified_name);
CREATE INDEX idx_edges_source ON edges(source_id);
CREATE INDEX idx_edges_target ON edges(target_id);
CREATE INDEX idx_edges_kind ON edges(kind);

-- Full-text search on node names and docblocks
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    name, qualified_name, docblock, signature,
    content=nodes, content_rowid=rowid
);
~~~

### 5.4 Graph Queries for LLM Context Retrieval

#### "Give me everything related to this function"
~~~sql
-- Get function and all its relationships (1 hop)
WITH target AS (
    SELECT id FROM nodes WHERE qualified_name = :target_name
)
SELECT
    n.kind, n.name, n.qualified_name, n.file_path,
    n.start_line, n.end_line, n.signature,
    e.kind AS relationship, e.confidence,
    CASE WHEN e.source_id IN (SELECT id FROM target)
         THEN 'outgoing' ELSE 'incoming' END AS direction
FROM edges e
JOIN nodes n ON n.id = CASE
    WHEN e.source_id IN (SELECT id FROM target) THEN e.target_id
    ELSE e.source_id END
WHERE e.source_id IN (SELECT id FROM target)
   OR e.target_id IN (SELECT id FROM target)
ORDER BY e.confidence DESC;
~~~

#### "What is the blast radius of changing this class?"
~~~sql
-- Recursive transitive dependents
WITH RECURSIVE dependents(id, depth) AS (
    SELECT :class_id, 0
    UNION
    SELECT e.source_id, d.depth + 1
    FROM edges e
    JOIN dependents d ON e.target_id = d.id
    WHERE d.depth < 5  -- max depth
    AND e.kind IN ('imports', 'extends', 'implements', 'calls', 'uses_type')
)
SELECT DISTINCT n.kind, n.name, n.qualified_name, n.file_path, d.depth
FROM dependents d
JOIN nodes n ON n.id = d.id
WHERE d.id != :class_id
ORDER BY d.depth, n.file_path;
~~~

#### "Find circular dependencies"
~~~python
import networkx as nx

def find_circular_dependencies(db_path: str) -> list[list[str]]:
    G = nx.DiGraph()
    conn = sqlite3.connect(db_path)
    for row in conn.execute(
        "SELECT source_id, target_id FROM edges WHERE kind = 'imports'"
    ):
        G.add_edge(row[0], row[1])
    return list(nx.simple_cycles(G))
~~~

#### "What are the most important files?" (PageRank)
~~~python
def rank_files_by_importance(db_path: str) -> list[tuple[str, float]]:
    G = nx.DiGraph()
    conn = sqlite3.connect(db_path)
    for row in conn.execute("""
        SELECT DISTINCT
            s.file_path AS source_file,
            t.file_path AS target_file
        FROM edges e
        JOIN nodes s ON s.id = e.source_id
        JOIN nodes t ON t.id = e.target_id
        WHERE e.kind IN ('imports', 'calls', 'extends', 'implements')
        AND s.file_path != t.file_path
    """):
        G.add_edge(row[0], row[1])
    ranks = nx.pagerank(G)
    return sorted(ranks.items(), key=lambda x: -x[1])
~~~

### 5.5 LLM-Optimized Output Format

Graph query results should be formatted for LLM consumption with token budget management:

~~~python
def format_context_for_llm(nodes: list, edges: list,
                            max_tokens: int = 4000) -> str:
    """Format graph query results for LLM context window."""
    sections = []

    # 1. Summary header (always included)
    sections.append(f"## Code Context: {len(nodes)} entities, "
                    f"{len(edges)} relationships\n")

    # 2. Entity signatures (compact, high-value)
    sections.append("### Key Entities")
    for node in sorted(nodes, key=lambda n: -n['importance']):
        sections.append(
            f"- **{node['kind']}** `{node['qualified_name']}` "
            f"({node['file_path']}:{node['start_line']})")
        if node.get('signature'):
            sections.append(f"  Signature: `{node['signature']}`")

    # 3. Relationship summary (grouped by type)
    sections.append("\n### Relationships")
    by_kind = defaultdict(list)
    for edge in edges:
        by_kind[edge['kind']].append(edge)
    for kind, group in sorted(by_kind.items()):
        sections.append(f"\n#### {kind} ({len(group)})")
        for edge in group[:10]:  # limit per type
            sections.append(
                f"- `{edge['source']}` → `{edge['target']}`"
                f" (confidence: {edge['confidence']:.0%})")

    # 4. Token budget enforcement
    result = "\n".join(sections)
    estimated_tokens = len(result) // 4
    if estimated_tokens > max_tokens:
        # Truncate least important entities
        result = truncate_to_budget(result, max_tokens)

    return result
~~~

---

## 6. Cross-Language Patterns

> Detailed reference: `research-cross-language.md`

### 6.1 PHP Backend → JS Frontend Connections

The primary connection between PHP backends and JS/TS frontends is through HTTP API endpoints. Detection requires matching both sides:

#### Server Side: Laravel Route Extraction
~~~scm
;; Laravel Route::method() calls
(scoped_call_expression
  scope: (name) @_route
  name: (name) @http.method
  arguments: (arguments
    (string) @route.path
    [(array_creation_expression
       (array_element_initializer
         (class_constant_access_expression (name) @route.controller)
         (string) @route.action))
     (string) @route.action_string]
  )
  (#eq? @_route "Route")
  (#match? @http.method "^(get|post|put|patch|delete|any|match|options)$")
) @route.def
~~~

#### Client Side: API Call Detection
~~~scm
;; fetch() calls
(call_expression
  function: (identifier) @_fn
  arguments: (arguments
    [(string) (template_string)] @fetch.url
  )
  (#eq? @_fn "fetch")
) @fetch.call

;; axios.method() calls
(call_expression
  function: (member_expression
    object: (identifier) @_axios
    property: (property_identifier) @axios.method
  )
  arguments: (arguments
    [(string) (template_string)] @axios.url
  )
  (#eq? @_axios "axios")
  (#match? @axios.method "^(get|post|put|patch|delete|head|options|request)$")
) @axios.call
~~~

#### Cross-Language Matching Algorithm

The matching pipeline uses 5 strategies in order of confidence:

| Strategy | Confidence | Example |
|----------|-----------|----------|
| 1. Ziggy named routes | 0.98 | `route('users.index')` → `Route::get('/users', ...)` |
| 2. Exact URL match | 0.95 | `fetch('/api/users')` → `Route::get('/api/users', ...)` |
| 3. Parameterized match | 0.85 | `fetch(\`/api/users/${id}\`)` → `Route::get('/api/users/{user}', ...)` |
| 4. Prefix match | 0.60 | `axios.get('/api/users' + query)` → `Route::get('/api/users', ...)` |
| 5. Fuzzy match | 0.40 | Levenshtein distance < threshold |

**URL parameter normalization** across languages:
~~~python
def normalize_url_pattern(url: str) -> str:
    """Normalize URL parameters across PHP/JS conventions."""
    import re
    # PHP: {param}, {param?}
    # JS: :param, ${param}, ${variable}
    # All → {PARAM}
    url = re.sub(r'\{(\w+)\??\}', '{PARAM}', url)   # PHP
    url = re.sub(r':(\w+)', '{PARAM}', url)           # Express
    url = re.sub(r'\$\{[^}]+\}', '{PARAM}', url)     # JS template
    url = re.sub(r'\[([^\]]+)\]', '{PARAM}', url)    # Next.js
    return url.rstrip('/')
~~~

### 6.2 Server-Side Rendering Bridges

#### Inertia.js (PHP → Vue/React)
Inertia.js creates direct PHP controller → frontend component mappings:

~~~php
// PHP Controller
return Inertia::render('Users/Index', [
    'users' => User::all(),
    'filters' => $request->only('search', 'role'),
]);
~~~

**Detection:** Extract `Inertia::render()` first argument as component path, second argument keys as prop names.

**Graph edges:**
- `inertia_renders`: Controller method → Vue/React component
- `inertia_passes_prop`: Controller method → Component (with prop name)

#### Blade Templates with JavaScript
~~~php
{{-- Blade passing data to JS --}}
<script>
    window.__data__ = @json($data);
</script>
~~~

**Detection:** Scan Blade templates for `@json()`, `window.__` assignments, `data-*` attributes with PHP expressions.

#### Livewire (PHP ↔ JS bidirectional)
Livewire components have both PHP class and Blade template with JS interop:
- PHP class properties → automatically available in Blade
- `wire:click`, `wire:model` → JS event bindings to PHP methods
- `$dispatch()`, `$emit()` → cross-component communication

### 6.3 Shared Data Contracts

Detecting when PHP API responses match TypeScript interfaces:

~~~python
def detect_type_contract(php_resource: dict, ts_interface: dict) -> float:
    """Score similarity between PHP API Resource and TS interface."""
    php_fields = set(normalize_field(f) for f in php_resource['fields'])
    ts_fields = set(normalize_field(f) for f in ts_interface['fields'])

    # Jaccard similarity with snake_case ↔ camelCase normalization
    intersection = php_fields & ts_fields
    union = php_fields | ts_fields

    if not union:
        return 0.0

    field_overlap = len(intersection) / len(union)

    # Name similarity bonus
    name_sim = name_similarity(php_resource['name'], ts_interface['name'])

    return 0.6 * field_overlap + 0.4 * name_sim

def normalize_field(name: str) -> str:
    """Normalize snake_case and camelCase to common form."""
    import re
    # camelCase → snake_case
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
~~~

### 6.4 Metadata Extraction Beyond AST

#### Documentation Extraction

**PHPDoc:**
~~~scm
(comment) @doc.phpdoc
(#match? @doc.phpdoc "^/\\*\\*")
~~~

Extract: `@param type $name`, `@return type`, `@throws type`, `@var type`, `@property type $name`, `@method type name()`, `@deprecated`, `@see reference`

**JSDoc/TSDoc:**
~~~scm
(comment) @doc.jsdoc
(#match? @doc.jsdoc "^/\\*\\*")
~~~

Extract: `@param {type} name`, `@returns {type}`, `@typedef`, `@callback`, `@template`, `@implements`, `@extends`

#### Git Metadata Enrichment

~~~python
def get_file_change_frequency(repo_path: str, days: int = 90) -> dict:
    """Get change frequency per file from git log."""
    import subprocess
    result = subprocess.run(
        ["git", "log", f"--since={days} days ago",
         "--name-only", "--pretty=format:"],
        capture_output=True, text=True, cwd=repo_path
    )
    freq = Counter(f for f in result.stdout.strip().split('\n') if f)
    return dict(freq)

def get_co_change_pairs(repo_path: str, min_commits: int = 3) -> list:
    """Find files that frequently change together."""
    import subprocess
    result = subprocess.run(
        ["git", "log", "--name-only", "--pretty=format:COMMIT"],
        capture_output=True, text=True, cwd=repo_path
    )
    commits = []
    current = []
    for line in result.stdout.split('\n'):
        if line == 'COMMIT':
            if current:
                commits.append(set(current))
            current = []
        elif line.strip():
            current.append(line.strip())

    # Count co-occurrences
    pair_counts = Counter()
    file_counts = Counter()
    for commit_files in commits:
        for f in commit_files:
            file_counts[f] += 1
        for pair in combinations(sorted(commit_files), 2):
            pair_counts[pair] += 1

    # Jaccard similarity for co-change strength
    co_changes = []
    for (f1, f2), count in pair_counts.items():
        if count >= min_commits:
            jaccard = count / (file_counts[f1] + file_counts[f2] - count)
            co_changes.append((f1, f2, jaccard, count))

    return sorted(co_changes, key=lambda x: -x[2])
~~~

#### Complexity Metrics

~~~python
def cyclomatic_complexity(tree, language: str) -> int:
    """Estimate cyclomatic complexity from AST."""
    decision_nodes = {
        'php': ['if_statement', 'elseif_clause', 'while_statement',
                'for_statement', 'foreach_statement', 'case_statement',
                'catch_clause', 'conditional_expression',
                'binary_expression'],  # && and ||
        'javascript': ['if_statement', 'while_statement',
                       'for_statement', 'for_in_statement',
                       'switch_case', 'catch_clause',
                       'ternary_expression', 'binary_expression'],
        'typescript': ['if_statement', 'while_statement',
                       'for_statement', 'for_in_statement',
                       'switch_case', 'catch_clause',
                       'ternary_expression', 'binary_expression'],
    }
    count = 1  # base complexity
    for node in walk_tree(tree.root_node):
        if node.type in decision_nodes.get(language, []):
            if node.type == 'binary_expression':
                op = node.child_by_field_name('operator')
                if op and op.text.decode() in ('&&', '||', 'and', 'or'):
                    count += 1
            else:
                count += 1
    return count
~~~

### 6.5 Cross-Language Edge Type Registry

| Category | Edge Type | Source → Target | Confidence Range |
|----------|-----------|----------------|------------------|
| **API Layer** | `api_endpoint_serves` | PHP Route → Controller Method | 0.95-1.0 |
| | `api_calls` | JS fetch/axios → URL pattern | 0.70-0.95 |
| | `api_matches` | URL pattern → PHP Route | 0.40-0.98 |
| **Template** | `renders_template` | PHP Controller → Blade template | 0.95-1.0 |
| | `template_includes_script` | Blade template → JS entry point | 0.80-0.95 |
| **Inertia.js** | `inertia_renders` | PHP Controller → Vue/React component | 0.95-1.0 |
| | `inertia_passes_prop` | Controller → Component (prop) | 0.90-1.0 |
| **Type Contracts** | `shares_type_contract` | PHP Resource ↔ TS Interface | 0.50-0.90 |
| **Config** | `shares_config` | PHP .env usage ↔ JS .env usage | 0.80-0.95 |
| | `shares_translation` | PHP i18n key ↔ JS i18n key | 0.85-0.95 |
| **Build** | `build_entry_point` | Build config → JS entry file | 0.90-1.0 |
| | `asset_reference` | Blade template → Built asset | 0.80-0.95 |
| **Git-Derived** | `co_changes_with` | File ↔ File | 0.30-0.80 |

---


## 7. Unified Schema Specification

This section defines the complete, unified schema for the code knowledge graph, synthesizing node and edge types from all five research documents.

### 7.1 Node Type Registry (25 types)

#### File-Level Nodes

| Node Type | Description | Key Properties | Languages |
|-----------|-------------|----------------|-----------|
| `File` | Source code file | path, language, content_hash, line_count, module_system | All |
| `Directory` | Directory in project | path, is_package | All |
| `Package` | npm package or composer package | name, version, type | All |

#### Declaration-Level Nodes

| Node Type | Description | Key Properties | Languages |
|-----------|-------------|----------------|-----------|
| `Class` | Class declaration | name, qualified_name, visibility, is_abstract, is_final | All |
| `Interface` | Interface declaration | name, qualified_name, generic_params | PHP, TS |
| `Trait` | Trait declaration | name, qualified_name | PHP |
| `Enum` | Enum declaration | name, qualified_name, backing_type | PHP 8.1+, TS |
| `Function` | Standalone function | name, qualified_name, is_async, is_generator | All |
| `Method` | Class/interface method | name, visibility, is_static, is_abstract, is_async | All |
| `Property` | Class property | name, visibility, is_static, is_readonly, type | All |
| `Variable` | Module-level variable/constant | name, is_const, is_exported | JS, TS |
| `Constant` | Class or global constant | name, qualified_name, value | PHP |
| `TypeAlias` | Type alias declaration | name, generic_params, value_kind | TS |
| `Namespace` | Namespace declaration | name, qualified_name | PHP, TS |

#### Structural Nodes

| Node Type | Description | Key Properties | Languages |
|-----------|-------------|----------------|-----------|
| `Parameter` | Function/method parameter | name, type, default_value, is_variadic, is_optional | All |
| `Decorator` | Decorator/Attribute | name, arguments | PHP 8+, TS |
| `GenericParam` | Generic type parameter | name, constraint, default | TS |

#### Import/Export Nodes

| Node Type | Description | Key Properties | Languages |
|-----------|-------------|----------------|-----------|
| `Import` | Import/require/use statement | source, specifiers, is_type_only, module_system | All |
| `Export` | Export statement | specifiers, is_default, is_type_only, source (re-export) | JS, TS |

#### Framework-Specific Nodes

| Node Type | Description | Key Properties | Languages |
|-----------|-------------|----------------|-----------|
| `Route` | HTTP route definition | path, http_method, middleware | PHP (Laravel), JS (Express/Next) |
| `Component` | UI component (React/Vue/Angular) | name, framework, is_server, is_client | JS, TS |
| `Hook` | React hook or Vue composable | name, dependencies | JS, TS |
| `Model` | ORM model (Eloquent) | name, table, relationships | PHP |
| `Event` | Event class or listener | name, channel | PHP, JS |
| `Middleware` | HTTP middleware | name, priority | PHP, JS |

### 7.2 Edge Type Registry (30 types)

#### Structural Edges

| Edge Type | Source → Target | Description | Confidence |
|-----------|----------------|-------------|------------|
| `contains` | File/Class/Namespace → any | Parent contains child entity | 1.0 |
| `defined_in` | any → File | Entity is defined in file | 1.0 |
| `member_of` | Method/Property → Class | Entity is member of class | 1.0 |

#### Inheritance & Type System Edges

| Edge Type | Source → Target | Description | Confidence |
|-----------|----------------|-------------|------------|
| `extends` | Class → Class, Interface → Interface | Inheritance | 1.0 |
| `implements` | Class → Interface | Interface implementation | 1.0 |
| `uses_trait` | Class → Trait | Trait usage | 1.0 |
| `has_type` | Property/Parameter/Variable → Type | Type annotation | 1.0 |
| `returns_type` | Function/Method → Type | Return type | 1.0 |
| `generic_of` | TypeAlias/Class/Interface → GenericParam | Generic parameter | 1.0 |
| `union_of` | TypeAlias → Type[] | Union type members | 1.0 |
| `intersection_of` | TypeAlias → Type[] | Intersection type members | 1.0 |

#### Dependency Edges

| Edge Type | Source → Target | Description | Confidence |
|-----------|----------------|-------------|------------|
| `imports` | File → File/Package | Module import | 0.85-1.0 |
| `imports_type` | File → File | Type-only import | 0.85-1.0 |
| `exports` | File → Entity | Module export | 1.0 |
| `re_exports` | File → File | Re-export (barrel) | 0.90-1.0 |
| `dynamic_imports` | File → File | Dynamic import() | 0.40-0.95 |
| `depends_on` | Package → Package | Package dependency | 1.0 |

#### Call Graph Edges

| Edge Type | Source → Target | Description | Confidence |
|-----------|----------------|-------------|------------|
| `calls` | Function/Method → Function/Method | Function/method call | 0.70-1.0 |
| `instantiates` | Function/Method → Class | new ClassName() | 0.85-1.0 |
| `dispatches_event` | Function/Method → Event | Event dispatch | 0.80-1.0 |
| `listens_to` | Function/Method → Event | Event listener | 0.90-1.0 |

#### Framework Edges

| Edge Type | Source → Target | Description | Confidence |
|-----------|----------------|-------------|------------|
| `routes_to` | Route → Method | Route handler | 0.95-1.0 |
| `renders` | Component → Component | Component renders child | 0.90-1.0 |
| `passes_prop` | Component → Component | Prop passing (with prop name) | 0.85-1.0 |
| `injects` | Class → Class | Dependency injection | 0.80-1.0 |
| `decorated_by` | Class/Method → Decorator | Decorator application | 1.0 |
| `uses_hook` | Component → Hook | Hook usage | 1.0 |

#### Cross-Language Edges

| Edge Type | Source → Target | Description | Confidence |
|-----------|----------------|-------------|------------|
| `api_matches` | JS API call → PHP Route | Cross-language API connection | 0.40-0.98 |
| `shares_type_contract` | PHP Resource ↔ TS Interface | Shared data shape | 0.50-0.90 |
| `inertia_renders` | PHP Controller → JS Component | Inertia.js bridge | 0.95-1.0 |

### 7.3 Node Properties Schema

All nodes share a common base schema with language-specific extensions:

~~~python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class BaseNode:
    id: str                          # Unique: "file_path:start_line:name"
    kind: str                        # Node type from registry
    name: str                        # Entity name
    qualified_name: Optional[str]    # Fully-qualified name
    file_path: str                   # Relative to project root
    start_line: int
    end_line: int
    language: str                    # php, javascript, typescript
    docblock: Optional[str] = None
    content_hash: Optional[str] = None
    metadata: dict = field(default_factory=dict)

@dataclass
class ClassNode(BaseNode):
    kind: str = "class"
    visibility: Optional[str] = None  # public, protected, private
    is_abstract: bool = False
    is_final: bool = False
    is_readonly: bool = False         # PHP 8.2
    parent_class: Optional[str] = None
    interfaces: list[str] = field(default_factory=list)
    traits: list[str] = field(default_factory=list)
    generic_params: list[str] = field(default_factory=list)

@dataclass
class FunctionNode(BaseNode):
    kind: str = "function"
    signature: Optional[str] = None
    parameters: list[dict] = field(default_factory=list)
    return_type: Optional[str] = None
    is_async: bool = False
    is_generator: bool = False
    is_exported: bool = False
    visibility: Optional[str] = None
    is_static: bool = False
    is_abstract: bool = False
    decorators: list[str] = field(default_factory=list)

@dataclass
class ImportNode(BaseNode):
    kind: str = "import"
    source: str = ""                  # Module specifier
    specifiers: list[dict] = field(default_factory=list)
    is_type_only: bool = False
    module_system: str = "esm"        # esm, cjs, php
    resolved_path: Optional[str] = None
    resolution_confidence: float = 1.0

@dataclass
class RouteNode(BaseNode):
    kind: str = "route"
    path: str = ""                    # URL pattern
    http_method: str = "GET"
    controller: Optional[str] = None
    action: Optional[str] = None
    middleware: list[str] = field(default_factory=list)
    prefix: Optional[str] = None

@dataclass
class ComponentNode(BaseNode):
    kind: str = "component"
    framework: str = "react"          # react, vue, angular
    is_server_component: bool = False
    is_client_component: bool = False
    props_interface: Optional[str] = None
    hooks_used: list[str] = field(default_factory=list)
~~~

### 7.4 Edge Properties Schema

~~~python
@dataclass
class Edge:
    source_id: str
    target_id: str
    kind: str                         # Edge type from registry
    confidence: float = 1.0           # 0.0-1.0
    line_number: Optional[int] = None # Where the relationship occurs
    metadata: dict = field(default_factory=dict)
    # metadata examples:
    # calls: {"is_dynamic": false, "is_conditional": false}
    # imports: {"specifiers": ["default", "named"], "is_type_only": false}
    # api_matches: {"strategy": "parameterized", "url_pattern": "/api/users/{id}"}
    # passes_prop: {"prop_name": "userId", "prop_type": "string"}
~~~

---

## 8. Implementation Roadmap

### 8.1 Unified Processing Pipeline (8 Phases)

~~~
Phase 1: Project Discovery
    ├── Detect project type (PHP, JS, TS, mixed)
    ├── Parse composer.json (PSR-4 map, dependencies)
    ├── Parse package.json (type, dependencies, workspaces)
    ├── Parse tsconfig.json (paths, baseUrl, strict)
    ├── Parse bundler configs (aliases, entry points)
    └── Build ModuleResolver with all config sources

Phase 2: File Discovery & Hashing
    ├── Scan project directories (respect .gitignore)
    ├── Classify files by language (PHP, JS, TS, JSX, TSX, Vue, Blade)
    ├── Compute content hashes (SHA-256)
    ├── Compare with stored hashes → skip unchanged files
    └── Build file processing queue (changed files only)

Phase 3: Structural Extraction (Tree-sitter)
    ├── Parse each file with appropriate grammar
    │   ├── PHP: tree-sitter-php (or php_only for libraries)
    │   ├── JS/JSX: tree-sitter-javascript
    │   ├── TS: tree-sitter-typescript
    │   ├── TSX: tree-sitter-tsx
    │   └── Vue: Split SFC → parse each block
    ├── Run extraction queries for each language
    │   ├── Classes, interfaces, traits, enums
    │   ├── Functions, methods, properties
    │   ├── Imports, exports, require calls
    │   ├── Call sites (function calls, method calls)
    │   ├── Type annotations, decorators/attributes
    │   └── Documentation blocks (PHPDoc, JSDoc, TSDoc)
    └── Create preliminary graph nodes

Phase 4: Name & Module Resolution
    ├── PHP: Resolve short names → FQCN
    │   ├── Parse namespace + use statements
    │   ├── Apply PSR-4 autoload mapping
    │   └── Optional: nikic/PHP-Parser subprocess for complex cases
    ├── JS/TS: Resolve import specifiers → file paths
    │   ├── Apply ModuleResolver (relative, TS paths, aliases, node_modules)
    │   ├── Detect barrel files and flatten re-exports
    │   └── Handle dynamic imports with confidence scoring
    └── Create import/export edges with resolved targets

Phase 5: Framework Pattern Detection
    ├── PHP/Laravel:
    │   ├── Route definitions → Route nodes + routes_to edges
    │   ├── Eloquent models → Model nodes + relationship edges
    │   ├── Facade resolution → resolves_to edges
    │   ├── Service container bindings → injects edges
    │   ├── Event/Listener registration → dispatches/listens edges
    │   └── Middleware pipeline → middleware edges
    ├── React/Next.js:
    │   ├── Component hierarchy → renders/passes_prop edges
    │   ├── Hook usage → uses_hook edges
    │   ├── Context providers/consumers → provides/consumes edges
    │   ├── File-based routing → Route nodes
    │   └── Server/client component classification
    ├── Vue:
    │   ├── SFC component extraction
    │   ├── Composition API (defineProps, defineEmits)
    │   └── Composable usage
    ├── Angular/NestJS:
    │   ├── Decorator-based module/component/service detection
    │   ├── Dependency injection graph
    │   └── Route/controller mapping
    └── Express/Fastify:
        ├── Route handler detection
        └── Middleware chain extraction

Phase 6: Cross-Language Matching
    ├── Build PHP Route Registry (URL → Controller::method)
    ├── Extract JS API calls (fetch, axios, etc.)
    ├── Match API calls to routes (5-strategy pipeline)
    ├── Detect Inertia.js bridges (PHP → Vue/React)
    ├── Detect Blade → JS asset references
    ├── Match PHP Resources ↔ TS Interfaces (type contracts)
    ├── Detect shared config (.env variables)
    └── Create cross-language edges with confidence scores

Phase 7: Enrichment (Optional)
    ├── PHPStan/Larastan type enrichment (subprocess)
    ├── Git metadata (change frequency, co-change analysis)
    ├── Complexity metrics (cyclomatic complexity, LOC)
    ├── PageRank / centrality computation (NetworkX)
    └── Update graph nodes with enrichment data

Phase 8: Graph Persistence & Indexing
    ├── Upsert nodes into SQLite
    ├── Upsert edges into SQLite
    ├── Update file hashes for incremental tracking
    ├── Rebuild FTS5 index
    ├── Build NetworkX projection for graph algorithms
    └── Generate summary statistics
~~~

### 8.2 Implementation Priority Order

| Priority | Component | Effort | Value | Dependencies |
|----------|-----------|--------|-------|--------------|
| P0 | File discovery + hashing | 1 day | Foundation | None |
| P0 | Tree-sitter parsing (PHP, JS, TS) | 3 days | Core extraction | py-tree-sitter |
| P0 | SQLite schema + persistence | 1 day | Storage | None |
| P1 | PHP name resolution | 2 days | Accurate PHP graph | Tree-sitter |
| P1 | JS/TS module resolution | 3 days | Accurate JS/TS graph | Tree-sitter |
| P1 | Basic graph queries | 1 day | LLM context retrieval | SQLite |
| P2 | Laravel pattern detection | 2 days | Framework understanding | PHP resolution |
| P2 | React/Next.js pattern detection | 2 days | Framework understanding | JS/TS resolution |
| P2 | Cross-language matching | 2 days | Full-stack understanding | Both resolutions |
| P3 | PHPStan enrichment | 1 day | Type accuracy | PHP resolution |
| P3 | Git metadata enrichment | 1 day | Change intelligence | None |
| P3 | PageRank / centrality | 0.5 day | Context ranking | NetworkX |
| P3 | Vue/Angular/NestJS patterns | 2 days | Additional frameworks | JS/TS resolution |
| P3 | LLM output formatting | 1 day | Optimized context | Graph queries |

**Total estimated effort: ~22 days for full implementation**
- P0 (MVP): ~5 days — Parse files, extract entities, store in SQLite
- P1 (Usable): ~11 days — Accurate cross-file resolution, basic queries
- P2 (Powerful): ~17 days — Framework awareness, cross-language connections
- P3 (Complete): ~22 days — Enrichment, ranking, optimized output

### 8.3 Technology Stack

~~~
Core:
  Python 3.11+
  py-tree-sitter + tree-sitter-language-pack
  sqlite3 (built-in)
  networkx

PHP Enrichment (optional):
  nikic/PHP-Parser (PHP subprocess)
  PHPStan/Larastan (PHP subprocess)

Utilities:
  hashlib (content hashing)
  pathlib (path manipulation)
  json (config parsing)
  re (pattern matching)
  subprocess (external tool integration)
  dataclasses (schema definitions)
  collections (Counter, defaultdict)
  itertools (combinations for co-change)
~~~

### 8.4 Key Design Decisions

#### Decision 1: Content-Hash Based Incremental Updates
Store SHA-256 hash of each file's content. On re-parse, skip files whose hash hasn't changed. This is simpler and more reliable than Tree-sitter's character-level incremental parsing for batch processing.

~~~python
import hashlib

def file_content_hash(path: str) -> str:
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()

def get_changed_files(db, project_files: list[str]) -> list[str]:
    changed = []
    for path in project_files:
        current_hash = file_content_hash(path)
        stored = db.execute(
            "SELECT content_hash FROM files WHERE path = ?", (path,)
        ).fetchone()
        if not stored or stored[0] != current_hash:
            changed.append(path)
    return changed
~~~

#### Decision 2: Language Detection by Extension + Content
~~~python
LANGUAGE_MAP = {
    '.php': 'php',
    '.js': 'javascript',
    '.jsx': 'javascript',  # JSX handled by same grammar
    '.mjs': 'javascript',
    '.cjs': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'tsx',
    '.vue': 'vue',         # Special: split into blocks
    '.blade.php': 'blade', # Special: template + PHP
}

def detect_language(path: str) -> str:
    if path.endswith('.blade.php'):
        return 'blade'
    ext = os.path.splitext(path)[1]
    return LANGUAGE_MAP.get(ext, 'unknown')
~~~

#### Decision 3: Confidence Scoring System
All edges carry a confidence score (0.0-1.0) indicating how certain we are about the relationship:

| Confidence Tier | Range | Meaning | Example |
|----------------|-------|---------|----------|
| Certain | 1.0 | Syntactically explicit | `extends`, `implements`, `import` |
| High | 0.85-0.99 | Resolved with high certainty | Static method call with known type |
| Medium | 0.50-0.84 | Resolved with assumptions | Parameterized URL matching |
| Low | 0.10-0.49 | Heuristic/fuzzy match | Fuzzy URL matching, name similarity |
| Unresolved | 0.0 | Cannot determine | Dynamic dispatch, eval() |

#### Decision 4: Unified ID Format
Node IDs follow a consistent format for cross-referencing:

~~~
{relative_file_path}:{start_line}:{entity_kind}:{entity_name}

Examples:
src/Models/User.php:15:class:App\Models\User
src/Models/User.php:42:method:App\Models\User::posts
src/components/UserList.tsx:8:component:UserList
src/api/users.ts:3:import:@/services/userService
routes/api.php:12:route:GET:/api/users
~~~

---

## 9. Appendices

### Appendix A: Tree-sitter Query Quick Reference

| Entity | PHP Query Pattern | JS/TS Query Pattern |
|--------|------------------|--------------------|
| Class | `(class_declaration name: (name) @n)` | `(class_declaration name: (identifier) @n)` |
| Interface | `(interface_declaration name: (name) @n)` | `(interface_declaration name: (type_identifier) @n)` |
| Function | `(function_definition name: (name) @n)` | `(function_declaration name: (identifier) @n)` |
| Method | `(method_declaration name: (name) @n)` | `(method_definition name: (property_identifier) @n)` |
| Property | `(property_declaration)` | `(public_field_definition name: (property_identifier) @n)` |
| Import | `(namespace_use_declaration)` | `(import_statement source: (string) @s)` |
| Export | N/A | `(export_statement)` |
| Call | `(function_call_expression function: (_) @f)` | `(call_expression function: (_) @f)` |
| Extends | `(base_clause (name) @parent)` | `(class_heritage (identifier) @parent)` |
| Implements | `(class_interface_clause (name) @i)` | TS: `(class_declaration (implements_clause (type_identifier) @i))` |
| Decorator | `(attribute name: (name) @d)` | `(decorator (identifier) @d)` |
| Namespace | `(namespace_definition name: (namespace_name) @n)` | TS: `(internal_module name: (identifier) @n)` |
| Enum | `(enum_declaration name: (name) @n)` | TS: `(enum_declaration name: (identifier) @n)` |
| Type alias | N/A | `(type_alias_declaration name: (type_identifier) @n)` |
| Trait | `(trait_declaration name: (name) @n)` | N/A |

### Appendix B: Detailed Research Document Map

| Document | Sections | Key Content |
|----------|----------|-------------|
| `research-treesitter-deep-dive.md` | 8 + 3 appendices | Node type statistics, complete query examples, py-tree-sitter API, incremental parsing, performance budgets |
| `research-php-parsing.md` | 8 sections, 40+ subsections | Parser comparison matrix, namespace/trait/magic method handling, facade resolution, Eloquent relationships, PHPStan integration, 6-phase extraction pipeline |
| `research-js-ts-parsing.md` | 7 sections, 60 subsections | Module system detection, JSX component extraction, all TS constructs with queries, ModuleResolver implementation, 6 framework pattern detectors, build config parsing |
| `research-graph-schema.md` | 9 sections | 6 existing tool analyses, 5 storage backend comparisons, SQL/Python query implementations, LLM output formatting, token budget management |
| `research-cross-language.md` | 7 sections, 40+ subsections | 8 detection algorithms with Python implementations, 18 cross-language edge types, URL matching pipeline, Inertia/Livewire/Blade bridge detection, git metadata enrichment |

### Appendix C: Supporting Data Files

| File | Location | Content |
|------|----------|---------|
| `php-node-types.json` | `research-data/` | Raw Tree-sitter PHP grammar node types |
| `js-node-types.json` | `research-data/` | Raw Tree-sitter JavaScript grammar node types |
| `ts-node-types.json` | `research-data/` | Raw Tree-sitter TypeScript grammar node types |
| `tsx-node-types.json` | `research-data/` | Raw Tree-sitter TSX grammar node types |

### Appendix D: External References

| Resource | URL | Relevance |
|----------|-----|-----------|
| Tree-sitter | https://tree-sitter.github.io/ | Primary parsing engine |
| tree-sitter-php | https://github.com/tree-sitter/tree-sitter-php | PHP grammar |
| tree-sitter-javascript | https://github.com/tree-sitter/tree-sitter-javascript | JS grammar (includes JSX) |
| tree-sitter-typescript | https://github.com/tree-sitter/tree-sitter-typescript | TS/TSX grammars |
| py-tree-sitter | https://github.com/tree-sitter/py-tree-sitter | Python bindings |
| tree-sitter-language-pack | https://pypi.org/project/tree-sitter-language-pack/ | Pre-built grammars for Python |
| nikic/PHP-Parser | https://github.com/nikic/PHP-Parser | PHP AST parser with name resolution |
| PHPStan | https://phpstan.org/ | PHP static analysis |
| Larastan | https://github.com/larastan/larastan | Laravel-specific PHPStan extension |
| code-graph-rag | https://github.com/vitali87/code-graph-rag | Reference implementation (AST + Graph + MCP) |
| codebase-memory-mcp | https://github.com/DeusData/codebase-memory-mcp | Reference implementation (SQLite graph) |
| Aider | https://github.com/paul-gauthier/aider | PageRank-based context selection |
| NetworkX | https://networkx.org/ | Graph algorithms library |

---

> **Document generated**: 2026-03-10  
> **Total research corpus**: ~606KB across 5 detailed research documents  
> **This synthesis**: Architecture decisions, unified schema, implementation roadmap  
> **Next step**: Begin P0 implementation — file discovery, Tree-sitter parsing, SQLite persistence

