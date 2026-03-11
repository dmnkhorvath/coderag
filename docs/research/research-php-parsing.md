# PHP Parsing Approaches for Code Knowledge Graph Construction

> Comprehensive Technical Research Document  
> Generated: 2026-03-10  
> Purpose: Inform the design of a custom code knowledge graph builder for PHP/Laravel codebases

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Parser Comparison](#2-parser-comparison)
   - 2.1 [tree-sitter-php](#21-tree-sitter-php)
   - 2.2 [nikic/PHP-Parser](#22-nikicphp-parser)
   - 2.3 [glayzzle/php-parser](#23-glayzzlephp-parser)
   - 2.4 [Comparison Matrix](#24-comparison-matrix)
3. [PHP-Specific Constructs Requiring Special Handling](#3-php-specific-constructs-requiring-special-handling)
4. [Dynamic Dispatch in PHP](#4-dynamic-dispatch-in-php)
5. [Static Analysis Tools as Complement](#5-static-analysis-tools-as-complement)
6. [Laravel/Framework-Specific Patterns](#6-laravelframework-specific-patterns)
7. [Recommendations for Knowledge Graph Construction](#7-recommendations-for-knowledge-graph-construction)

---

## 1. Executive Summary

This document evaluates three PHP parsing approaches for building a code knowledge graph: **tree-sitter-php** (C-based incremental parser with Python bindings), **nikic/PHP-Parser** (PHP-native AST library), and **glayzzle/php-parser** (JavaScript-based PHP parser). The analysis covers architecture, PHP version support, construct handling, and suitability for knowledge graph extraction.

**Key Findings:**

- **tree-sitter-php** is the recommended primary parser for a Python-based knowledge graph builder. It produces a Concrete Syntax Tree (CST) with excellent PHP 8.x support (enums, attributes, readonly, match, named arguments, intersection/union/DNF types), has native Python bindings via `py-tree-sitter`, supports incremental parsing for IDE-like performance, and uses a powerful S-expression query language for pattern matching. Its CST preserves all syntactic detail needed for precise source mapping.

- **nikic/PHP-Parser** is the gold standard for PHP-native AST manipulation. It offers the most complete PHP version support (7.0-8.4), built-in name resolution (fully qualifying namespaced names), format-preserving pretty printing, and a rich visitor-based traversal API. However, it runs only in PHP, requiring a subprocess bridge for Python integration. It is the foundation for PHPStan, Psalm, Rector, and most PHP static analysis tools.

- **glayzzle/php-parser** is a JavaScript/Node.js PHP parser with partial PHP 8.x support. It has known issues with `readonly` keyword handling and enum support. Its ecosystem is smaller and less actively maintained than the other two options. Not recommended as a primary parser for knowledge graph construction.

- **Complementary tools** (PHPStan, Psalm, Larastan) provide type inference, taint analysis, and framework-aware resolution that pure AST parsing cannot achieve. Their JSON output can enrich the knowledge graph with resolved types, especially for untyped legacy code.

**Recommended Architecture:** Use tree-sitter-php as the primary parser (Python-native, fast, incremental), with nikic/PHP-Parser as a secondary tool for name resolution and PHP-specific semantic analysis (via PHP subprocess), and PHPStan/Larastan for type inference and Laravel-specific resolution.

---

## 2. Parser Comparison

### 2.1 tree-sitter-php

#### Architecture

tree-sitter-php is a grammar implementation for the [tree-sitter](https://tree-sitter.github.io/) incremental parsing system. It follows a multi-layered architecture:

1. **Grammar Definition**: Written in JavaScript (`grammar.js`), defines PHP syntax rules
2. **Custom Scanner**: C implementation handling complex syntax (heredoc/nowdoc, string interpolation, escape sequences)
3. **Generated Parser**: tree-sitter CLI generates C code from the grammar
4. **Language Bindings**: Native bindings for Python, Rust, Node.js, Go, Swift, C

The parser produces a **Concrete Syntax Tree (CST)**, not an abstract syntax tree. This means all tokens from the source code are preserved, including punctuation, delimiters, and structural tokens. While the tree-sitter documentation sometimes uses "AST" loosely, the output retains concrete syntactic details.

**Two Grammar Variants:**
- **`php`**: Handles standard PHP files with HTML embedding (`<?php` tags)
- **`php_only`**: Parses pure PHP code without HTML integration (more efficient for libraries)

Both share a common scanner and helper functions defined in `common/define-grammar.js`.

#### Node Types

tree-sitter-php produces 305 total node types (162 named). Key node types for knowledge graph construction:

**Declarations:**
- `class_declaration` — with modifiers, base_clause, interface_clause, body
- `interface_declaration` — with base_clause for extending interfaces
- `trait_declaration` — with name and declaration_list body
- `enum_declaration` — PHP 8.1 enums with backing type, interface clause, enum_case
- `function_definition` — standalone functions
- `method_declaration` — class/trait/enum methods
- `property_declaration` — class properties with modifiers
- `const_declaration` — class and global constants
- `namespace_definition` — bracketed and semicolon-terminated forms

**Imports & References:**
- `namespace_use_declaration` — `use` statements
- `namespace_use_clause` — individual use clauses
- `namespace_aliasing_clause` — `as` aliases
- `use_declaration` — trait use within classes
- `use_instead_of_clause` — trait conflict resolution (`insteadof`)
- `use_as_clause` — trait method aliasing (`as`)

**PHP 8.x Features:**
- `attribute_list` / `attribute_group` / `attribute` — PHP 8.0 attributes (`#[...]`)
- `enum_declaration` / `enum_case` — PHP 8.1 enums
- `match_expression` / `match_block` / `match_conditional_expression` — PHP 8.0 match
- `readonly_modifier` — PHP 8.1 readonly properties, PHP 8.2 readonly classes
- `named_type` / `union_type` / `intersection_type` / `disjunctive_normal_form_type` — full type system
- Named arguments via `argument` rule with optional `_argument_name` prefix

**Expressions & Calls:**
- `function_call_expression` — function calls
- `member_call_expression` — method calls (`$obj->method()`)
- `scoped_call_expression` — static calls (`Class::method()`)
- `member_access_expression` — property access
- `scoped_property_access_expression` — static property access
- `object_creation_expression` — `new` expressions
- `class_constant_access_expression` — `Class::CONST`

#### Query Capabilities

tree-sitter uses an S-expression pattern matching language for querying syntax trees:

~~~scheme
;; Find all class declarations with their names
(class_declaration
  name: (name) @class.name
  body: (declaration_list) @class.body
) @class.def

;; Find trait usage within classes
(use_declaration
  (name) @trait.name
) @uses_trait.rel

;; Find namespace declarations
(namespace_definition
  name: (namespace_name) @namespace.name
  body: (compound_statement)? @namespace.body
) @namespace.def

;; Find method calls
(member_call_expression
  object: (_) @call.object
  name: (name) @call.method
  arguments: (arguments) @call.args
) @method_call

;; Find static method calls (important for facades)
(scoped_call_expression
  scope: (_) @call.class
  name: (name) @call.method
  arguments: (arguments) @call.args
) @static_call

;; Find PHP 8 attributes
(attribute_list
  (attribute_group
    (attribute
      name: (_) @attr.name
      parameters: (arguments)? @attr.params
    )
  )
) @attribute
~~~

#### Language Version Support

| Feature | Supported | Node Type |
|---------|-----------|----------|
| Namespaces | Yes | `namespace_definition`, `namespace_use_declaration` |
| Traits | Yes | `trait_declaration`, `use_declaration`, `use_instead_of_clause` |
| Interfaces | Yes | `interface_declaration` |
| Enums (8.1) | Yes | `enum_declaration`, `enum_case` |
| Attributes (8.0) | Yes | `attribute_list`, `attribute_group`, `attribute` |
| Match (8.0) | Yes | `match_expression`, `match_block` |
| Readonly (8.1/8.2) | Yes | `readonly_modifier` |
| Named Arguments (8.0) | Yes | `argument` with `_argument_name` |
| Union Types (8.0) | Yes | `union_type` |
| Intersection Types (8.1) | Yes | `intersection_type` |
| DNF Types (8.2) | Yes | `disjunctive_normal_form_type` |
| Fibers (8.1) | N/A | No special syntax needed (standard class API) |
| Constructor Promotion (8.0) | Yes | `property_promotion_parameter` |
| Nullsafe Operator (8.0) | Yes | `nullsafe_member_access_expression` |

#### Performance

- **Incremental parsing**: Only re-parses changed portions of the file, making it extremely fast for IDE-like use cases
- **C-based parser**: Generated C code runs at native speed
- **Memory efficient**: Tree structure uses compact representation
- **Typical performance**: Parses thousands of lines per millisecond for initial parse; sub-millisecond for incremental updates
- **Python binding overhead**: `py-tree-sitter` adds minimal overhead; parsing a typical PHP file (500-1000 lines) takes 1-5ms

#### Ecosystem & Maturity

- **Maintained by**: tree-sitter organization (GitHub)
- **Used by**: VS Code, Neovim, Atom, GitHub code navigation, Zed editor, Helix
- **npm downloads**: ~17 dependent packages
- **Maturity**: Production-grade, battle-tested in major editors
- **Active development**: Regular updates tracking PHP language evolution

#### Python Integration

~~~python
import tree_sitter_php
import tree_sitter

# Initialize parser
parser = tree_sitter.Parser(tree_sitter.Language(tree_sitter_php.language()))

# Parse PHP code
code = b"""<?php
namespace App\\Models;

use Illuminate\\Database\\Eloquent\\Model;
use Illuminate\\Database\\Eloquent\\Relations\\HasMany;

#[Attribute]
class User extends Model
{
    use HasFactory;

    public function posts(): HasMany
    {
        return $this->hasMany(Post::class);
    }
}
"""

tree = parser.parse(code)
root = tree.root_node

# Query for class declarations
query = tree_sitter.Language(tree_sitter_php.language()).query("""
(class_declaration
  name: (name) @class.name
  body: (declaration_list) @class.body
) @class.def
""")

matches = query.matches(root)
for match in matches:
    for capture_name, nodes in match[1].items():
        for node in nodes:
            print(f"{capture_name}: {node.text.decode()}")
~~~

#### Strengths for Knowledge Graph Construction

- Native Python integration (no subprocess needed)
- Powerful query language for pattern extraction
- Incremental parsing for watch-mode / live updates
- CST preserves exact source positions for all tokens
- Comprehensive PHP 8.x support
- Battle-tested in production editors
- Two grammar variants (with/without HTML) for different file types

#### Weaknesses for Knowledge Graph Construction

- CST (not AST) means more nodes to process; need to skip punctuation/delimiters
- No built-in name resolution (must implement namespace/use tracking manually)
- No semantic analysis (types, inheritance resolution)
- Cannot resolve dynamic constructs
- Query language has learning curve
- No built-in pretty printing or code generation

---

### 2.2 nikic/PHP-Parser

#### Architecture

nikic/PHP-Parser is a PHP parser written in PHP. It follows a pipeline architecture:

1. **Lexer**: Tokenizes PHP source code (handles token emulation for cross-version support)
2. **Parser**: LALR(1) parser generated from a grammar, produces AST
3. **AST**: Nested tree of typed node objects (`PhpParser\Node`)
4. **Traverser**: Visitor-pattern based tree traversal system
5. **Pretty Printer**: Converts AST back to PHP code (with format-preserving mode)

The parser produces a true **Abstract Syntax Tree (AST)** — syntactic sugar and punctuation are abstracted away. Each node type has its own PHP class with typed properties for child nodes.

#### Node Types

Nodes are organized into three main categories:

**Statements (`PhpParser\Node\Stmt`):**
- `Stmt\Namespace_` — namespace declarations
- `Stmt\Use_` — use statements (with `UseUse` for individual clauses)
- `Stmt\GroupUse` — group use declarations (`use App\{Foo, Bar}`)
- `Stmt\Class_` — class declarations (with flags for abstract, final, readonly)
- `Stmt\Interface_` — interface declarations
- `Stmt\Trait_` — trait declarations
- `Stmt\TraitUse` — trait use within classes (with `TraitUseAdaptation` for conflict resolution)
- `Stmt\Enum_` — PHP 8.1 enum declarations
- `Stmt\EnumCase` — enum case declarations
- `Stmt\Function_` — function declarations
- `Stmt\ClassMethod` — method declarations
- `Stmt\Property` — property declarations
- `Stmt\ClassConst` — class constant declarations
- `Stmt\Expression` — expression statements
- `Stmt\Return_`, `Stmt\If_`, `Stmt\While_`, `Stmt\For_`, `Stmt\Foreach_`, etc.

**Expressions (`PhpParser\Node\Expr`):**
- `Expr\FuncCall` — function calls
- `Expr\MethodCall` — instance method calls
- `Expr\StaticCall` — static method calls
- `Expr\PropertyFetch` — property access
- `Expr\StaticPropertyFetch` — static property access
- `Expr\New_` — object creation
- `Expr\ClassConstFetch` — class constant access
- `Expr\Variable` — variables
- `Expr\Closure` — anonymous functions
- `Expr\ArrowFunction` — arrow functions
- `Expr\Match_` — match expressions
- `Expr\NullsafeMethodCall` — nullsafe method calls
- `Expr\NullsafePropertyFetch` — nullsafe property access

**Other Nodes:**
- `Node\Name` — simple names
- `Node\Name\FullyQualified` — fully qualified names
- `Node\Name\Relative` — relative names (`namespace\...`)
- `Node\Arg` — function/method arguments (with `name` for named arguments)
- `Node\Param` — function/method parameters
- `Node\Attribute` — PHP 8.0 attributes
- `Node\AttributeGroup` — attribute groups
- `Node\Identifier` — simple identifiers
- `Node\IntersectionType`, `Node\UnionType`, `Node\NullableType` — type nodes

#### Query Capabilities (Traversal API)

nikic/PHP-Parser uses a visitor pattern for AST traversal:

~~~php
<?php
use PhpParser\NodeTraverser;
use PhpParser\NodeVisitorAbstract;
use PhpParser\Node;

class ClassFinder extends NodeVisitorAbstract
{
    public array $classes = [];

    public function enterNode(Node $node)
    {
        if ($node instanceof Node\Stmt\Class_) {
            $this->classes[] = [
                'name' => $node->namespacedName?->toString() ?? $node->name->toString(),
                'extends' => $node->extends?->toString(),
                'implements' => array_map(fn($i) => $i->toString(), $node->implements),
                'traits' => $this->extractTraits($node),
                'methods' => $this->extractMethods($node),
                'properties' => $this->extractProperties($node),
                'isAbstract' => $node->isAbstract(),
                'isFinal' => $node->isFinal(),
                'isReadonly' => $node->isReadonly(), // PHP 8.2
                'attributes' => $this->extractAttributes($node),
            ];
        }
    }
}

// Usage
$parser = (new PhpParser\ParserFactory)->createForNewestSupportedVersion();
$traverser = new NodeTraverser();
$traverser->addVisitor(new PhpParser\NodeVisitor\NameResolver()); // Auto-resolve names
$traverser->addVisitor($finder = new ClassFinder());

$code = file_get_contents('User.php');
$ast = $parser->parse($code);
$traverser->traverse($ast);

print_r($finder->classes);
~~~

**Visitor Methods:**
- `beforeTraverse(array $nodes)` — called once before traversal
- `enterNode(Node $node)` — called when entering each node (before children)
- `leaveNode(Node $node)` — called when leaving each node (after children)
- `afterTraverse(array $nodes)` — called once after traversal

**Return Values:**
- `null` — keep node unchanged
- Modified node — replace current node
- `NodeVisitor::DONT_TRAVERSE_CHILDREN` — skip children
- `NodeVisitor::STOP_TRAVERSAL` — halt traversal
- `NodeVisitor::REMOVE_NODE` — remove node from parent array
- Array of nodes — replace node with multiple nodes (in `leaveNode` only)

**Built-in Name Resolution:**

The `NameResolver` visitor is critical for knowledge graph construction:

~~~php
<?php
// Before NameResolver:
// use App\Models\User as UserModel;
// new UserModel()  ->  Name: "UserModel"

// After NameResolver:
// new UserModel()  ->  Name\FullyQualified: "App\Models\User"

$traverser = new NodeTraverser();
$traverser->addVisitor(new PhpParser\NodeVisitor\NameResolver());
$resolvedAst = $traverser->traverse($ast);

// Now all class/function/constant names are fully qualified
// Class/function/constant declarations get a `namespacedName` subnode
~~~

This is a major advantage over tree-sitter-php, which has no built-in name resolution.

#### Language Version Support

| Version | Runtime Requirement | Parsing Support |
|---------|--------------------|-----------------|
| PHP-Parser 5.x (current) | PHP >= 7.4 | PHP 7.0 - 8.4 (limited PHP 5.x) |
| PHP-Parser 4.x (supported) | PHP >= 7.0 | PHP 5.2 - 8.3 |

Version targeting:
~~~php
<?php
use PhpParser\ParserFactory;
use PhpParser\PhpVersion;

// Parse as newest supported version (widest acceptance)
$parser = (new ParserFactory)->createForNewestSupportedVersion();

// Parse targeting specific version
$parser = (new ParserFactory)->createForVersion(PhpVersion::fromString('8.1'));
~~~

**Error Recovery**: Can parse syntactically incorrect code into a partial AST, useful for analyzing incomplete or broken files.

#### Performance

- **Pure PHP**: Slower than C-based parsers (tree-sitter)
- **Typical performance**: Parsing a 1000-line file takes ~10-50ms (varies with complexity)
- **Memory**: Higher memory usage than tree-sitter due to object-per-node architecture
- **Optimization tips** (from docs): Disable Xdebug, enable object reuse, manage garbage collection
- **No incremental parsing**: Must re-parse entire file on changes
- **Batch processing**: Can process thousands of files in seconds with proper setup

#### Ecosystem & Maturity

- **Author**: Nikita Popov (PHP core contributor, LLVM developer)
- **Packagist downloads**: 500M+ total downloads
- **Used by**: PHPStan, Psalm, Rector, PHP-CS-Fixer, Laravel Shift, and virtually every PHP static analysis tool
- **Maturity**: The de facto standard PHP parser; production-grade since 2012
- **Active development**: Tracks PHP language evolution closely (maintained by PHP internals contributors)

#### Integration with Python

nikic/PHP-Parser runs only in PHP. Integration options for a Python-based knowledge graph builder:

**Option 1: PHP Subprocess with JSON Output**
~~~php
<?php
// extract_ast.php - Run via subprocess from Python
require 'vendor/autoload.php';

use PhpParser\ParserFactory;
use PhpParser\NodeTraverser;
use PhpParser\NodeVisitor\NameResolver;
use PhpParser\JsonDecoder;

$parser = (new ParserFactory)->createForNewestSupportedVersion();
$traverser = new NodeTraverser();
$traverser->addVisitor(new NameResolver());

$code = file_get_contents($argv[1]);
$ast = $parser->parse($code);
$resolvedAst = $traverser->traverse($ast);

// Output as JSON
$jsonEncoder = new PhpParser\JsonEncoder();
echo $jsonEncoder->encode($resolvedAst);
~~~

~~~python
# Python side
import subprocess
import json

def parse_php_file(filepath: str) -> dict:
    result = subprocess.run(
        ['php', 'extract_ast.php', filepath],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)
~~~

**Option 2: PHP Server with HTTP API**
~~~php
<?php
// Persistent PHP process serving AST requests over HTTP
// Avoids subprocess startup overhead for batch processing
~~~

**Option 3: Use tree-sitter-php as primary, nikic/PHP-Parser for name resolution only**
This hybrid approach gets the best of both worlds.

#### Strengths for Knowledge Graph Construction

- Built-in name resolution (fully qualifies all names)
- True AST (cleaner than CST for semantic analysis)
- Most complete PHP version support (7.0-8.4)
- Rich typed node hierarchy with semantic meaning
- Format-preserving pretty printing for code modification
- JSON encoding/decoding of ASTs
- Error recovery for broken files
- Massive ecosystem and community
- De facto standard used by all PHP tools

#### Weaknesses for Knowledge Graph Construction

- PHP-only runtime (requires subprocess bridge for Python)
- No incremental parsing
- Higher memory usage per file
- Slower than tree-sitter for raw parsing
- No query language (must write visitor classes)
- Subprocess overhead for Python integration

---

### 2.3 glayzzle/php-parser

#### Architecture

glayzzle/php-parser is a JavaScript library that parses PHP code and converts it to an AST. Architecture:

1. **Lexer**: Tokenizes PHP source (similar to PHP\'s `token_get_all`)
2. **Parser**: Processes tokens according to PHP grammar rules
3. **AST Module**: Constructs a tree of JavaScript objects

The parser produces an AST as plain JavaScript objects with `kind` properties identifying node types.

#### API

~~~javascript
const PhpParser = require('php-parser');

const parser = new PhpParser({
  parser: {
    extractDoc: true,   // Extract PHPDoc comments
    php7: true,         // Enable PHP 7 syntax
  },
  ast: {
    withPositions: true // Include position info
  }
});

// Parse with PHP tags
const ast = parser.parseCode('<?php echo "Hello";');

// Parse without PHP tags (eval mode)
const ast2 = parser.parseEval('echo "Hello";');

// Tokenize only
const tokens = parser.tokenGetAll('<?php echo "Hello";');
~~~

#### Node Types

The AST uses `kind` properties to identify nodes:
- `program` — root node
- `class`, `interface`, `trait` — type declarations
- `method`, `function` — callable declarations
- `property`, `classconstant` — member declarations
- `namespace`, `usegroup`, `useitem` — namespace constructs
- `call`, `staticlookup`, `propertylookup` — access expressions
- `new`, `variable`, `string`, `number` — basic expressions
- `echo`, `return`, `if`, `while`, `for` — statements

#### Language Version Support

| Feature | Status | Notes |
|---------|--------|-------|
| PHP 7.x | Supported | Core target version |
| PHP 8.0 (match, named args, attributes) | Partial | Some features added in recent releases |
| PHP 8.1 (enums, readonly, fibers) | Partial | Enum support has known issues (#896) |
| PHP 8.2 (readonly classes, DNF types) | Partial | readonly keyword issues (#1170, still open) |
| PHP 8.3 (typed class constants) | Supported | Added in recent release (#1136) |
| PHP 8.4 | Unknown | No documented support |

**Known Issues:**
- `readonly` keyword not accepted when it comes first in class property definition (#1170 - open)
- `enum` treated as reserved word even before PHP 8.1 (#896)
- Various edge cases with newer PHP syntax

#### Performance

- **JavaScript-based**: Slower than C-based tree-sitter, comparable to or slower than PHP-Parser
- **No incremental parsing**: Must re-parse entire file
- **Memory**: JavaScript object overhead for each node

#### Ecosystem & Maturity

- **npm downloads**: ~89 dependent packages
- **Latest version**: 3.2.5 (published ~2 months ago as of research date)
- **Maintenance**: Active but smaller community than nikic/PHP-Parser
- **Used by**: Prettier PHP plugin, some linting tools, webpack loaders
- **Maturity**: Usable but less battle-tested than alternatives

#### Integration

- **Node.js native**: Direct JavaScript/TypeScript integration
- **Python integration**: Would require Node.js subprocess or WASM compilation
- **No Python bindings**: Unlike tree-sitter, no native Python support

#### Strengths for Knowledge Graph Construction

- JavaScript/Node.js native (good for web-based tools)
- Simple API, easy to get started
- Position tracking in AST
- PHPDoc extraction built-in

#### Weaknesses for Knowledge Graph Construction

- Incomplete PHP 8.x support (known issues with readonly, enums)
- No Python bindings (requires Node.js subprocess)
- Smaller ecosystem and community
- No built-in name resolution
- No query language
- No incremental parsing
- Less actively maintained than alternatives
- Not recommended for production knowledge graph construction

---

### 2.4 Comparison Matrix

| Feature | tree-sitter-php | nikic/PHP-Parser | glayzzle/php-parser |
|---------|----------------|-----------------|--------------------|
| **Language** | C (generated) | PHP | JavaScript |
| **Output** | CST (Concrete Syntax Tree) | AST (Abstract Syntax Tree) | AST |
| **Python Integration** | Native (`py-tree-sitter`) | Subprocess (PHP) | Subprocess (Node.js) |
| **PHP Version Support** | 7.x - 8.2+ | 7.0 - 8.4 | 7.x, partial 8.x |
| **Incremental Parsing** | Yes | No | No |
| **Name Resolution** | No (manual) | Yes (built-in `NameResolver`) | No |
| **Query Language** | S-expression patterns | Visitor pattern (PHP) | Manual traversal (JS) |
| **Error Recovery** | Yes | Yes | Limited |
| **Format-Preserving Print** | No | Yes | Via php-unparser |
| **JSON AST Export** | No (custom needed) | Yes (built-in) | Yes (native JS objects) |
| **Parsing Speed** | Fastest (C-native) | Medium (PHP) | Slower (JS) |
| **Memory Usage** | Lowest | Higher (object-per-node) | Medium |
| **Ecosystem Size** | Large (editors) | Largest (PHP tools) | Small |
| **Maturity** | Production | Production | Usable |
| **PHP 8.0 Attributes** | Full | Full | Partial |
| **PHP 8.1 Enums** | Full | Full | Issues |
| **PHP 8.1 Readonly Props** | Full | Full | Issues |
| **PHP 8.2 Readonly Classes** | Full | Full | Issues |
| **PHP 8.2 DNF Types** | Full | Full | Unknown |
| **Named Arguments** | Full | Full | Partial |
| **Match Expressions** | Full | Full | Partial |
| **Intersection Types** | Full | Full | Unknown |
| **Union Types** | Full | Full | Partial |
| **Constructor Promotion** | Full | Full | Partial |
| **Nullsafe Operator** | Full | Full | Partial |



---

## 3. PHP-Specific Constructs Requiring Special Handling

This section documents how each parser handles PHP constructs that require special attention for knowledge graph construction.

### 3.1 Namespaces

#### Namespace Declarations

PHP supports two namespace declaration forms:

~~~php
<?php
// Semicolon-terminated (file-level)
namespace App\Models;

// Bracketed (multiple namespaces per file)
namespace App\Models {
    class User {}
}
namespace App\Services {
    class UserService {}
}
~~~

**tree-sitter-php** query to extract namespaces:
~~~scheme
(namespace_definition
  name: (namespace_name) @ns.name
  body: (compound_statement)? @ns.body
) @ns.def
~~~

**nikic/PHP-Parser** produces `Stmt\Namespace_` nodes with `name` (a `Name` node) and `stmts` (array of statements). After `NameResolver` traversal, all class/function/constant declarations within the namespace get a `namespacedName` subnode with the fully qualified name.

**glayzzle/php-parser** produces `namespace` nodes with `name` and `children` properties.

#### Use Statements

PHP has several forms of use statements:

~~~php
<?php
use App\Models\User;                          // Simple use
use App\Models\User as UserModel;             // Aliased use
use App\Models\{User, Post, Comment};         // Group use
use function App\Helpers\formatDate;          // Function use
use const App\Config\MAX_RETRIES;             // Constant use
~~~

**tree-sitter-php** query:
~~~scheme
;; Simple and aliased use
(namespace_use_declaration
  (namespace_use_clause
    (qualified_name (namespace_name)) @import.name
    (namespace_aliasing_clause (name) @import.alias)?
  )
) @import.def
~~~

**nikic/PHP-Parser** produces:
- `Stmt\Use_` for simple use statements (with `UseUse` items)
- `Stmt\GroupUse` for group use declarations (with prefix and `UseUse` items)
- Each `UseUse` has `name`, `alias`, and `type` (class/function/constant)

**Knowledge Graph Implication:** Use statements create alias mappings that must be tracked to resolve short names to fully qualified names. nikic/PHP-Parser's `NameResolver` handles this automatically. For tree-sitter-php, you must build an alias resolution table manually.

### 3.2 Traits

#### Trait Declarations and Usage

~~~php
<?php
trait Timestampable {
    public function getCreatedAt(): DateTime { /* ... */ }
    public function touch(): void { /* ... */ }
}

trait SoftDeletes {
    public function touch(): void { /* ... */ }  // Conflicts with Timestampable
    public function restore(): void { /* ... */ }
}

class Post {
    use Timestampable, SoftDeletes {
        Timestampable::touch insteadof SoftDeletes;  // Conflict resolution
        SoftDeletes::touch as softTouch;              // Aliasing
    }
}
~~~

**tree-sitter-php** produces `use_declaration` nodes within `declaration_list`, containing `use_instead_of_clause` and `use_as_clause` for conflict resolution.

**nikic/PHP-Parser** produces:
- `Stmt\TraitUse` with `traits` (array of `Name` nodes) and `adaptations`
- `TraitUseAdaptation\Precedence` for `insteadof` clauses
- `TraitUseAdaptation\Alias` for `as` clauses

**Knowledge Graph Implication:** Traits create "mixin" relationships. The knowledge graph must:
1. Record which traits a class uses
2. Track conflict resolution rules (insteadof/as)
3. Merge trait methods into the class effective method set
4. Handle trait-in-trait usage (traits using other traits)

### 3.3 Magic Methods

PHP magic methods have special semantics that affect how code behaves:

| Magic Method | Triggered When | Knowledge Graph Impact |
|-------------|---------------|----------------------|
| `__construct` | Object creation (`new`) | Constructor dependency injection |
| `__call` | Undefined instance method called | Dynamic method dispatch (opaque) |
| `__callStatic` | Undefined static method called | Dynamic static dispatch (facades!) |
| `__get` | Undefined property read | Dynamic property access |
| `__set` | Undefined property write | Dynamic property mutation |
| `__isset` | `isset()` on undefined property | Property existence check |
| `__unset` | `unset()` on undefined property | Property removal |
| `__toString` | Object-to-string conversion | Implicit type conversion |
| `__invoke` | Object used as function | Callable objects |
| `__clone` | Object cloned | Deep copy semantics |

All three parsers detect magic method declarations as regular method declarations. The key challenge is semantic implications:

- `__call` and `__callStatic` make the class method set effectively unbounded
- `__get` and `__set` make the property set effectively unbounded
- For facades (which use `__callStatic`), the actual method set comes from the underlying service
- Static analysis tools (PHPStan/Psalm) use PHPDoc `@method` annotations to declare virtual methods
- The knowledge graph should flag classes with `__call`/`__callStatic` as having dynamic dispatch

### 3.4 Facades (Laravel)

Laravel facades provide a static-like interface to classes in the service container:

~~~php
<?php
// What developers write:
use Illuminate\Support\Facades\Cache;
Cache::get('key');  // Looks like a static call

// What actually happens:
// 1. Cache facade extends Illuminate\Support\Facades\Facade
// 2. Facade::__callStatic('get', ['key']) is triggered
// 3. __callStatic resolves the underlying class from the service container
// 4. The actual call is: app('cache')->get('key')

// The facade class:
class Cache extends Facade {
    protected static function getFacadeAccessor(): string {
        return 'cache';  // Service container binding key
    }
}
~~~

**Resolution Strategy for Knowledge Graph:**

1. **Detect facade classes**: Find classes extending `Illuminate\Support\Facades\Facade`
2. **Extract accessor**: Parse `getFacadeAccessor()` return value (usually a string literal)
3. **Map to service provider**: Find where the accessor is bound in service providers
4. **Resolve actual class**: The facade `Cache::get()` actually calls `CacheManager::get()`
5. **Use IDE helper**: Laravel IDE Helper generates `_ide_helper.php` with `@method` annotations

**Common Laravel Facades and Their Underlying Classes:**

| Facade | Accessor | Underlying Class |
|--------|----------|------------------|
| `Cache` | `cache` | `Illuminate\Cache\CacheManager` |
| `DB` | `db` | `Illuminate\Database\DatabaseManager` |
| `Route` | `router` | `Illuminate\Routing\Router` |
| `Auth` | `auth` | `Illuminate\Auth\AuthManager` |
| `Event` | `events` | `Illuminate\Events\Dispatcher` |
| `Log` | `log` | `Illuminate\Log\LogManager` |
| `Mail` | `mailer` | `Illuminate\Mail\Mailer` |
| `Queue` | `queue` | `Illuminate\Queue\QueueManager` |
| `Storage` | `filesystem` | `Illuminate\Filesystem\FilesystemManager` |
| `View` | `view` | `Illuminate\View\Factory` |

All three parsers see facade calls as regular static method calls. The knowledge graph must implement facade resolution logic on top of the AST. Larastan (PHPStan extension for Laravel) already handles this resolution by booting the Laravel container.

### 3.5 Service Container and Dependency Injection

Laravel service container is the foundation of dependency injection:

~~~php
<?php
class AppServiceProvider extends ServiceProvider {
    public function register(): void {
        // Interface-to-implementation binding
        $this->app->bind(PaymentGateway::class, StripeGateway::class);

        // Singleton binding
        $this->app->singleton(CacheStore::class, function ($app) {
            return new RedisCacheStore($app['config']['cache.redis']);
        });

        // Contextual binding
        $this->app->when(PhotoController::class)
            ->needs(Filesystem::class)
            ->give(function () {
                return Storage::disk('local');
            });
    }
}
~~~

**Resolution Strategy for Knowledge Graph:**

1. Parse service providers (classes extending `ServiceProvider`)
2. Extract bindings from `register()` and `boot()` methods:
   - `$this->app->bind(Interface::class, Implementation::class)`
   - `$this->app->singleton(Abstract::class, Concrete::class)`
   - `$this->app->instance(Abstract::class, $instance)`
   - Contextual bindings (`when()->needs()->give()`)
3. Resolve constructor injection: For each constructor parameter with a type hint, check for explicit bindings; if none, the container auto-resolves concrete classes
4. Track method injection in controller actions

### 3.6 Autoloading (PSR-4)

PHP uses Composer PSR-4 autoloading to map class names to file paths:

~~~json
{
    "autoload": {
        "psr-4": {
            "App\\\\": "app/",
            "Database\\\\Factories\\\\": "database/factories/",
            "Database\\\\Seeders\\\\": "database/seeders/"
        },
        "classmap": ["database/migrations"],
        "files": ["app/helpers.php"]
    }
}
~~~

**Resolution Algorithm (Python):**

~~~python
def resolve_class_to_file(fqcn: str, autoload_map: dict) -> str | None:
    """Resolve a fully qualified class name to a file path using PSR-4 rules."""
    # Sort prefixes by length (longest first) for most specific match
    sorted_prefixes = sorted(autoload_map.keys(), key=len, reverse=True)
    for prefix in sorted_prefixes:
        if fqcn.startswith(prefix):
            relative_class = fqcn[len(prefix):]
            relative_path = relative_class.replace('\\', '/') + '.php'
            base_dir = autoload_map[prefix]
            return f"{base_dir}/{relative_path}"
    return None
~~~

**Knowledge Graph Implication:**
- Parse `composer.json` to build the autoload map
- Use the map to resolve class references to file paths
- This enables cross-file relationship tracking
- Also parse `vendor/composer/autoload_classmap.php` for classmap entries
- Handle `files` autoload for global function/constant definitions

### 3.7 PHP 8.x Features

#### Attributes (PHP 8.0)

~~~php
<?php
#[Route('/api/users', methods: ['GET'])]
#[Middleware('auth')]
class UserController {
    #[Deprecated('Use findById instead')]
    public function find(int $id): User { /* ... */ }
}
~~~

**tree-sitter-php** query:
~~~scheme
(attribute_list
  (attribute_group
    (attribute
      name: (_) @attr.name
      parameters: (arguments)? @attr.params
    )
  )
) @attribute
~~~

**nikic/PHP-Parser** produces `Node\AttributeGroup` containing `Node\Attribute` nodes with `name` and `args`.

Attributes are metadata that can define routes, validation rules, ORM mappings, API documentation. The knowledge graph should extract attribute metadata and associate it with the decorated entity.

#### Enums (PHP 8.1)

~~~php
<?php
enum Status: string {
    case Active = 'active';
    case Inactive = 'inactive';
    case Pending = 'pending';

    public function label(): string {
        return match($this) {
            self::Active => 'Active',
            self::Inactive => 'Inactive',
            self::Pending => 'Pending',
        };
    }
}
~~~

**tree-sitter-php** query:
~~~scheme
(enum_declaration
  name: (name) @enum.name
  body: (enum_declaration_list
    (enum_case
      name: (name) @case.name
      value: (_)? @case.value
    )
  )
) @enum.def
~~~

**nikic/PHP-Parser** produces `Stmt\Enum_` with `name`, `scalarType`, `implements`, and `stmts` (containing `Stmt\EnumCase` nodes).

#### Readonly Properties and Classes (PHP 8.1/8.2)

~~~php
<?php
// Readonly property (PHP 8.1)
class User {
    public function __construct(
        public readonly string $name,
        public readonly string $email,
    ) {}
}

// Readonly class (PHP 8.2)
readonly class Point {
    public function __construct(
        public float $x,
        public float $y,
    ) {}
}
~~~

Both tree-sitter-php and nikic/PHP-Parser fully support readonly modifiers. glayzzle/php-parser has known issues (#1170).

#### Intersection Types and DNF Types (PHP 8.1/8.2)

~~~php
<?php
function process(Countable&Iterator $collection): void {}
function handle((Countable&Iterator)|null $collection): void {}
~~~

tree-sitter-php produces `intersection_type`, `union_type`, and `disjunctive_normal_form_type` nodes.
nikic/PHP-Parser produces `Node\IntersectionType`, `Node\UnionType`, and `Node\NullableType` nodes.

### 3.8 Anonymous Classes and Closures

~~~php
<?php
// Anonymous class
$validator = new class implements ValidatorInterface {
    public function validate(mixed $value): bool {
        return $value !== null;
    }
};

// Closure with use clause
$greeting = 'Hello';
$closure = function (string $name) use ($greeting): string {
    return "$greeting, $name!";
};

// Arrow function (PHP 7.4+)
$doubled = array_map(fn($n) => $n * 2, $numbers);
~~~

**tree-sitter-php** produces:
- `object_creation_expression` with `anonymous_class` for anonymous classes
- `anonymous_function_creation_expression` for closures
- `arrow_function` for arrow functions

**nikic/PHP-Parser** produces:
- `Expr\New_` with `Stmt\Class_` (anonymous) for anonymous classes
- `Expr\Closure` for closures (with `uses` for captured variables)
- `Expr\ArrowFunction` for arrow functions

**Knowledge Graph Implication:**
- Anonymous classes should be treated as unnamed implementations of their interfaces
- Closures capture variables from their enclosing scope (`use` clause)
- `Closure::bind()` creates dynamic scope binding (opaque to static analysis)
- Arrow functions implicitly capture by value

---

## 4. Dynamic Dispatch in PHP

PHP is a highly dynamic language. Many constructs cannot be fully resolved by static analysis alone. This section catalogs dynamic patterns and their analyzability.

### 4.1 Variable Functions and Methods

~~~php
<?php
// Variable function call
$func = 'strtolower';
$result = $func('HELLO');  // Calls strtolower('HELLO')

// Variable method call
$method = 'save';
$user->$method();  // Calls $user->save()

// Variable static method call
$class = 'App\\Models\\User';
$class::find(1);  // Calls User::find(1)

// Dynamic class instantiation
$className = 'App\\Models\\User';
$instance = new $className();
~~~

**Static Analysis Capability:**
- If the variable is assigned a string literal in the same scope, some tools can resolve it
- If the variable comes from config, database, or user input, resolution is impossible statically
- PHPStan at higher levels will flag these as errors (calling method on mixed type)

**Parser Handling:**
- tree-sitter-php: `function_call_expression` with `variable_name` as the function, `member_call_expression` with `variable_name` as the method
- nikic/PHP-Parser: `Expr\FuncCall` with `Expr\Variable` as name, `Expr\MethodCall` with `Expr\Variable` as name

**Knowledge Graph Strategy:** Flag these as "dynamic dispatch" edges with unknown targets. If simple constant propagation can resolve the variable, record the resolved target.

### 4.2 call_user_func and call_user_func_array

~~~php
<?php
// Function reference
call_user_func('strtolower', 'HELLO');

// Static method reference
call_user_func(['App\\Models\\User', 'find'], 1);
call_user_func('App\\Models\\User::find', 1);

// Instance method reference
call_user_func([$user, 'save']);

// With array of arguments
call_user_func_array([$controller, $action], $params);
~~~

**Static Analysis Capability:**
- When the first argument is a string literal or array of literals, the target can be resolved
- PHPStan and Psalm can resolve `call_user_func` with literal arguments
- When arguments are variables, resolution requires data flow analysis

**Knowledge Graph Strategy:** Parse `call_user_func` calls specially. If the callable argument is a literal string or array, resolve the target. Otherwise, flag as dynamic.

### 4.3 Reflection API

~~~php
<?php
// Reflection-based instantiation
$reflector = new ReflectionClass($className);
$instance = $reflector->newInstanceArgs($args);

// Reflection-based method call
$method = new ReflectionMethod($className, $methodName);
$method->invoke($instance, ...$args);

// Getting class info
$reflection = new ReflectionClass(User::class);
$properties = $reflection->getProperties();
$methods = $reflection->getMethods();
~~~

**Static Analysis Capability:** Reflection usage is almost entirely opaque to static analysis. When `ReflectionClass` is constructed with a `::class` constant, the target class is known. Otherwise, it is dynamic.

**Knowledge Graph Strategy:** Flag reflection usage as dynamic. If the class argument is a `::class` constant, record the relationship.

### 4.4 String-Based Class References in Config

~~~php
<?php
// Laravel config/app.php
return [
    'providers' => [
        App\\Providers\\AppServiceProvider::class,
        App\\Providers\\AuthServiceProvider::class,
        App\\Providers\\EventServiceProvider::class,
    ],
    'aliases' => [
        'App' => Illuminate\\Support\\Facades\\App::class,
        'Cache' => Illuminate\\Support\\Facades\\Cache::class,
    ],
];

// Event listener mapping
protected $listen = [
    UserRegistered::class => [
        SendWelcomeEmail::class,
        CreateDefaultWorkspace::class,
    ],
];
~~~

**Static Analysis Capability:**
- `::class` constants are fully resolvable (they produce the FQCN as a string)
- String literals containing class names can be resolved with heuristics
- Both PHPStan and Psalm understand `::class` constants

**Knowledge Graph Strategy:** Parse config files and extract `::class` references. These are reliable. String-based class names require heuristic matching against known classes.

### 4.5 Late Static Binding

~~~php
<?php
class ParentClass {
    public static function create(): static {
        return new static();  // Creates instance of the called class
    }

    public function clone(): static {
        return new static();  // NOT new self()
    }
}

class ChildClass extends ParentClass {}

// ParentClass::create() returns ParentClass
// ChildClass::create() returns ChildClass (late static binding)
~~~

**Static Analysis Capability:**
- `static` return type is understood by PHPStan and Psalm
- `new static()` vs `new self()` distinction is tracked
- The actual type depends on the calling context (which subclass calls the method)

**Knowledge Graph Strategy:** Record `static` return types and `new static()` usage. The knowledge graph should note that the actual type depends on the inheritance chain.

### 4.6 Summary: Static vs Dynamic Analyzability

| Pattern | Statically Resolvable? | Strategy |
|---------|----------------------|----------|
| `$obj->method()` (literal method name) | Yes | Direct edge |
| `$obj->$method()` (variable method) | Sometimes | Constant propagation |
| `$func()` (variable function) | Sometimes | Constant propagation |
| `new $className()` | Sometimes | Constant propagation |
| `call_user_func('func')` | Yes (literal) | Parse argument |
| `call_user_func($var)` | Sometimes | Data flow analysis |
| `Class::class` constant | Always | Direct resolution |
| `'Class'` string literal | Heuristic | Match against known classes |
| Reflection API | Rarely | Flag as dynamic |
| `__call` / `__callStatic` | No | Requires PHPDoc `@method` |
| `__get` / `__set` | No | Requires PHPDoc `@property` |
| `static::method()` | Context-dependent | Track inheritance chain |
| Config array class refs | Usually | Parse config files |
| Facade static calls | Yes (with resolution) | Map facade to underlying class |

---

## 5. Static Analysis Tools as Complement

Pure AST parsing cannot resolve types, infer return values, or understand framework conventions. Static analysis tools like PHPStan and Psalm fill this gap.

### 5.1 PHPStan

#### Architecture and Level System

PHPStan performs static analysis at configurable strictness levels (0-9):

| Level | What It Checks |
|-------|---------------|
| 0 | Basic checks: unknown classes, functions, methods called on `$this` |
| 1 | Possibly undefined variables, unknown magic methods |
| 2 | Unknown methods on all expressions (not just `$this`), validate PHPDocs |
| 3 | Return types, types assigned to properties |
| 4 | Basic dead code checking, always-true/false conditions |
| 5 | Argument types for function/method calls |
| 6 | Report missing typehints |
| 7 | Report partially wrong union types |
| 8 | Report nullable types |
| 9 | Strict mixed type checking |

#### Type Inference

PHPStan resolves types that AST alone cannot:

~~~php
<?php
// PHPStan infers return type from implementation
function getUser(int $id) {
    return User::find($id);  // PHPStan knows this returns User|null
}

// PHPStan tracks type narrowing through control flow
$user = getUser(1);
if ($user !== null) {
    $user->name;  // PHPStan knows $user is User here (not null)
}

// PHPStan resolves generic types
/** @var Collection<int, User> $users */
$users = User::all();
$first = $users->first();  // PHPStan knows this is User|null
~~~

#### JSON Output Format

PHPStan can output analysis results in JSON format:

~~~bash
phpstan analyse --error-format=json src/
~~~

Output structure:
~~~json
{
    "totals": {"errors": 0, "file_errors": 3},
    "files": {
        "/app/Models/User.php": {
            "errors": 1,
            "messages": [
                {
                    "message": "Method App\\Models\\User::posts() return type has no value type specified in iterable type Collection.",
                    "line": 25,
                    "ignorable": true,
                    "identifier": "missingType.iterableValue"
                }
            ]
        }
    },
    "errors": []
}
~~~

#### Baseline System

PHPStan's baseline feature allows incremental adoption:

~~~bash
# Generate baseline (ignore all current errors)
phpstan analyse --generate-baseline

# Run with baseline (only report new errors)
phpstan analyse  # Reads phpstan-baseline.neon automatically
~~~

The baseline file (`phpstan-baseline.neon`) contains a list of all currently known errors, allowing teams to hold new code to a higher standard while gradually fixing existing issues.

#### Programmatic Integration

For knowledge graph enrichment, PHPStan can be run programmatically:

~~~python
import subprocess
import json

def run_phpstan(project_path: str, level: int = 5) -> dict:
    """Run PHPStan and return JSON results."""
    result = subprocess.run(
        ['php', 'vendor/bin/phpstan', 'analyse',
         '--error-format=json', '--no-progress',
         f'--level={level}', 'src/'],
        capture_output=True, text=True,
        cwd=project_path
    )
    return json.loads(result.stdout)
~~~

#### PHPStan dumpType() for Type Resolution

PHPStan provides a `dumpType()` function for debugging type resolution:

~~~php
<?php
\PHPStan\dumpType(1 + 1);  // Reports: Dumped type: 2
\PHPStan\dumpType($user);  // Reports: Dumped type: App\Models\User
~~~

This can be used to verify what types PHPStan resolves for specific expressions, which is useful for validating knowledge graph type annotations.

### 5.2 Psalm

#### Architecture

Psalm is another PHP static analysis tool with complementary capabilities:

- Built on nikic/PHP-Parser for AST generation
- Performs type inference, dead code detection, and security analysis
- Supports custom plugins for framework-specific analysis

#### Taint Analysis

Psalm's unique feature is taint analysis for security:

~~~php
<?php
// Psalm tracks tainted data flow
$userInput = $_GET['name'];           // Source: tainted
$query = "SELECT * FROM users WHERE name = '$userInput'";  // Psalm flags: SQL injection
$db->query($query);                   // Sink: SQL query

// Psalm understands sanitization
$safe = htmlspecialchars($userInput);  // Sanitized
echo $safe;                            // OK: no XSS
~~~

#### Type Assertions

Psalm supports custom type assertions via annotations:

~~~php
<?php
/** @psalm-assert string $value */
function assertString(mixed $value): void {
    if (!is_string($value)) {
        throw new InvalidArgumentException();
    }
}

/** @psalm-assert-if-true User $value */
function isUser(mixed $value): bool {
    return $value instanceof User;
}
~~~

#### JSON Output

~~~bash
psalm --output-format=json src/
~~~

Output structure:
~~~json
[
    {
        "severity": "error",
        "line_from": 25,
        "line_to": 25,
        "type": "InvalidReturnType",
        "message": "The declared return type is incorrect",
        "file_name": "src/Models/User.php",
        "file_path": "/app/src/Models/User.php",
        "snippet": "public function posts(): Collection",
        "selected_text": "Collection",
        "from": 450,
        "to": 460
    }
]
~~~

### 5.3 Larastan (PHPStan for Laravel)

Larastan is a PHPStan extension that understands Laravel conventions:

#### What Larastan Resolves

| Pattern | How Larastan Resolves It |
|---------|--------------------------|
| Facade calls | Boots Laravel container, resolves `getFacadeAccessor()` to actual class |
| Eloquent models | Understands `$casts`, `$fillable`, magic properties from DB columns |
| Eloquent relationships | Resolves `hasMany()`, `belongsTo()` return types |
| Query builder | Tracks chained query builder methods and return types |
| Collection methods | Resolves generic types through collection pipeline |
| Config access | Validates config keys and return types |
| Route model binding | Understands implicit model binding in controllers |
| Service container | Resolves `app()` and `resolve()` calls |

#### How Larastan Works

Larastan boots the actual Laravel application container during analysis. This means:

1. It reads `config/app.php` to discover service providers
2. It registers all service providers to build the binding map
3. It resolves facades to their underlying classes
4. It reads database schema (if configured) to understand model properties

This is the most accurate way to resolve Laravel-specific patterns, but it requires a bootable Laravel application.

#### Integration with Knowledge Graph

~~~python
import subprocess
import json

def run_larastan(project_path: str) -> dict:
    """Run Larastan and return JSON results."""
    result = subprocess.run(
        ['php', 'vendor/bin/phpstan', 'analyse',
         '--error-format=json', '--no-progress'],
        capture_output=True, text=True,
        cwd=project_path
    )
    return json.loads(result.stdout)
~~~

### 5.4 Using Static Analysis to Enrich the Knowledge Graph

**Strategy: Multi-Pass Analysis**

1. **Pass 1 - AST Extraction (tree-sitter-php):** Extract all structural entities (classes, methods, properties, relationships) and build the initial graph
2. **Pass 2 - Name Resolution (nikic/PHP-Parser):** Resolve all names to fully qualified names, handling namespace aliases and use statements
3. **Pass 3 - Type Enrichment (PHPStan/Larastan):** Run static analysis to resolve types for untyped code, validate type annotations, and resolve framework-specific patterns
4. **Pass 4 - Security Analysis (Psalm):** Optionally run taint analysis to identify security-sensitive data flows

**What Static Analysis Adds:**
- Resolved types for variables, parameters, and return values without explicit type hints
- Generic type parameters (e.g., `Collection<int, User>`)
- Narrowed types after control flow (e.g., after `instanceof` checks)
- Framework-specific resolutions (facades, container bindings, model properties)
- Dead code identification
- Security-sensitive data flow paths

---

## 6. Laravel/Framework-Specific Patterns

Laravel introduces numerous conventions and patterns that require specialized handling beyond standard PHP parsing.

### 6.1 Route Definitions to Controller Mapping

~~~php
<?php
// routes/web.php or routes/api.php

// Closure route
Route::get('/welcome', function () {
    return view('welcome');
});

// Controller action (tuple syntax - Laravel 8+)
Route::get('/users', [UserController::class, 'index']);
Route::post('/users', [UserController::class, 'store']);

// Controller action (string syntax - legacy)
Route::get('/users', 'UserController@index');

// Resource routes (generates 7 routes)
Route::resource('posts', PostController::class);
// Equivalent to:
// GET    /posts          -> PostController::index
// GET    /posts/create   -> PostController::create
// POST   /posts          -> PostController::store
// GET    /posts/{post}   -> PostController::show
// GET    /posts/{post}/edit -> PostController::edit
// PUT    /posts/{post}   -> PostController::update
// DELETE /posts/{post}   -> PostController::destroy

// API resource (excludes create/edit)
Route::apiResource('comments', CommentController::class);

// Route groups with middleware and prefix
Route::middleware(['auth', 'verified'])->prefix('admin')->group(function () {
    Route::get('/dashboard', [AdminController::class, 'dashboard']);
});
~~~

**Knowledge Graph Extraction Strategy:**

1. Parse route files (`routes/*.php`)
2. Identify `Route::` static calls (these are facade calls to `Illuminate\Routing\Router`)
3. Extract HTTP method, URI pattern, and handler:
   - Tuple syntax: `[Controller::class, 'method']` - fully resolvable
   - String syntax: `'Controller@method'` - requires namespace resolution
   - Closure: inline function - extract as anonymous handler
4. Expand `Route::resource()` and `Route::apiResource()` into individual routes
5. Track route groups for middleware and prefix inheritance
6. Create edges: `Route --dispatches--> Controller::method`

### 6.2 Eloquent Model Relationships

~~~php
<?php
class User extends Model {
    // One-to-Many
    public function posts(): HasMany {
        return $this->hasMany(Post::class);
    }

    // Many-to-Many
    public function roles(): BelongsToMany {
        return $this->belongsToMany(Role::class);
    }

    // One-to-One
    public function profile(): HasOne {
        return $this->hasOne(Profile::class);
    }

    // Has-Many-Through
    public function deployments(): HasManyThrough {
        return $this->hasManyThrough(Deployment::class, Project::class);
    }

    // Polymorphic
    public function comments(): MorphMany {
        return $this->morphMany(Comment::class, 'commentable');
    }
}
~~~

**Relationship Types and Their Graph Edges:**

| Eloquent Method | Relationship | Graph Edge |
|----------------|-------------|------------|
| `hasOne()` | One-to-One | `User --hasOne--> Profile` |
| `hasMany()` | One-to-Many | `User --hasMany--> Post` |
| `belongsTo()` | Inverse One-to-Many | `Post --belongsTo--> User` |
| `belongsToMany()` | Many-to-Many | `User --belongsToMany--> Role` |
| `hasManyThrough()` | Has-Many-Through | `User --hasManyThrough--> Deployment (via Project)` |
| `hasOneThrough()` | Has-One-Through | Similar to above, singular |
| `morphOne()` | Polymorphic One-to-One | `User --morphOne--> Image` |
| `morphMany()` | Polymorphic One-to-Many | `User --morphMany--> Comment` |
| `morphToMany()` | Polymorphic Many-to-Many | `Post --morphToMany--> Tag` |
| `morphedByMany()` | Inverse Polymorphic M2M | `Tag --morphedByMany--> Post` |

**Extraction Strategy:**
1. Find classes extending `Illuminate\Database\Eloquent\Model`
2. Find methods that return relationship types (`HasMany`, `BelongsTo`, etc.)
3. Parse the relationship method call to extract the related model class
4. Extract optional parameters: foreign key, local key, pivot table
5. Create typed edges between models in the knowledge graph

### 6.3 Event/Listener Registration

~~~php
<?php
// app/Providers/EventServiceProvider.php
class EventServiceProvider extends ServiceProvider {
    protected $listen = [
        UserRegistered::class => [
            SendWelcomeEmail::class,
            CreateDefaultWorkspace::class,
            NotifyAdmins::class,
        ],
        OrderPlaced::class => [
            ProcessPayment::class,
            SendOrderConfirmation::class,
        ],
    ];

    protected $subscribe = [
        UserEventSubscriber::class,
    ];
}

// Dispatching events
event(new UserRegistered($user));
UserRegistered::dispatch($user);
Event::dispatch(new UserRegistered($user));
~~~

**Knowledge Graph Extraction:**
1. Parse `EventServiceProvider` to extract `$listen` and `$subscribe` arrays
2. Create edges: `Event --triggers--> Listener`
3. Find `event()` calls and `::dispatch()` calls to map where events are fired
4. Create edges: `Class::method --dispatches--> Event`

### 6.4 Middleware Pipeline

~~~php
<?php
// app/Http/Kernel.php
class Kernel extends HttpKernel {
    protected $middleware = [
        TrustProxies::class,
        PreventRequestsDuringMaintenance::class,
        ValidatePostSize::class,
    ];

    protected $middlewareGroups = [
        'web' => [
            EncryptCookies::class,
            AddQueuedCookiesToResponse::class,
            StartSession::class,
            ShareErrorsFromSession::class,
            VerifyCsrfToken::class,
        ],
        'api' => [
            ThrottleRequests::class.':api',
            SubstituteBindings::class,
        ],
    ];

    protected $middlewareAliases = [
        'auth' => Authenticate::class,
        'verified' => EnsureEmailIsVerified::class,
        'throttle' => ThrottleRequests::class,
    ];
}
~~~

**Knowledge Graph Extraction:**
1. Parse `Kernel.php` to extract middleware stacks
2. Map middleware aliases to their classes
3. Track which routes/groups use which middleware
4. Create pipeline edges: `Request --passes-through--> Middleware --then--> Controller`

### 6.5 Blade Templates and PHP Class References

~~~blade
{{-- resources/views/users/show.blade.php --}}

@extends('layouts.app')

@section('content')
    <h1>{{ $user->name }}</h1>

    {{-- Component reference --}}
    <x-user-card :user="$user" />

    {{-- Livewire component --}}
    @livewire('user-activity-feed', ['user' => $user])

    {{-- Include partial --}}
    @include('users.partials.sidebar')

    {{-- Conditional directive --}}
    @can('edit', $user)
        <a href="{{ route('users.edit', $user) }}">Edit</a>
    @endcan
@endsection
~~~

**Blade-to-PHP Mappings:**

| Blade Construct | PHP Resolution |
|----------------|---------------|
| `<x-user-card>` | `App\View\Components\UserCard` class |
| `<x-forms.input>` | `App\View\Components\Forms\Input` class |
| `@livewire('name')` | Livewire component class (by convention) |
| `@extends('layout')` | `resources/views/layout.blade.php` |
| `@include('partial')` | `resources/views/partial.blade.php` |
| `@component('name')` | Anonymous or class-based component |
| `route('name')` | Named route (from route definitions) |

**Extraction Strategy:**
1. Parse Blade files for directives and component references
2. Resolve `<x-component>` tags to their PHP component classes
3. Track `@extends`, `@include`, `@component` for template hierarchy
4. Extract `route()` calls to link templates to routes
5. Note: Blade is not PHP - it requires a separate parser or regex-based extraction

### 6.6 Config and Service Provider Bindings

~~~php
<?php
// config/services.php
return [
    'stripe' => [
        'key' => env('STRIPE_KEY'),
        'secret' => env('STRIPE_SECRET'),
        'webhook_secret' => env('STRIPE_WEBHOOK_SECRET'),
    ],
];

// Service provider binding
class PaymentServiceProvider extends ServiceProvider {
    public function register(): void {
        $this->app->bind(PaymentGateway::class, function ($app) {
            return new StripeGateway(
                config('services.stripe.key'),
                config('services.stripe.secret')
            );
        });
    }
}
~~~

**Knowledge Graph Extraction:**
1. Parse all service providers registered in `config/app.php`
2. Extract `bind()`, `singleton()`, `instance()` calls from `register()` methods
3. Map interface/abstract to concrete implementation
4. Track `config()` calls to link code to configuration keys
5. Parse config files to understand the configuration structure

### 6.7 Artisan Command Registration

~~~php
<?php
class SendWeeklyReport extends Command {
    protected $signature = 'report:weekly {--queue : Queue the report}';
    protected $description = 'Send the weekly analytics report';

    public function handle(ReportService $reportService): int {
        $reportService->generateWeekly();
        return Command::SUCCESS;
    }
}
~~~

**Knowledge Graph Extraction:**
1. Find classes extending `Illuminate\Console\Command`
2. Extract `$signature` for command name and arguments
3. Parse `handle()` method for dependencies (injected via service container)
4. Track command scheduling in `app/Console/Kernel.php`

### 6.8 Queue Job Dispatching

~~~php
<?php
// Job class
class ProcessPodcast implements ShouldQueue {
    use Dispatchable, InteractsWithQueue, Queueable, SerializesModels;

    public function __construct(
        public readonly Podcast $podcast,
    ) {}

    public function handle(AudioProcessor $processor): void {
        $processor->process($this->podcast);
    }
}

// Dispatching
ProcessPodcast::dispatch($podcast);
ProcessPodcast::dispatch($podcast)->onQueue('processing');
dispatch(new ProcessPodcast($podcast));
Bus::dispatch(new ProcessPodcast($podcast));
~~~

**Knowledge Graph Extraction:**
1. Find classes implementing `ShouldQueue` or using `Dispatchable` trait
2. Extract constructor parameters (job payload)
3. Parse `handle()` method for dependencies and side effects
4. Find `::dispatch()` and `dispatch()` calls to map where jobs are dispatched from
5. Create edges: `Controller::method --dispatches--> Job --processes--> Service`

### 6.9 Summary: Laravel Pattern Detection Checklist

| Pattern | Detection Method | Complexity |
|---------|-----------------|------------|
| Routes to Controllers | Parse route files, extract handler tuples | Medium |
| Eloquent Relationships | Find relationship method return types | Medium |
| Events/Listeners | Parse EventServiceProvider `$listen` array | Low |
| Middleware Pipeline | Parse Kernel.php arrays | Low |
| Blade Components | Parse `<x-*>` tags, resolve to classes | Medium |
| Service Bindings | Parse ServiceProvider `register()` methods | High |
| Facade Resolution | Map `getFacadeAccessor()` to bindings | High |
| Artisan Commands | Find Command subclasses, parse `$signature` | Low |
| Queue Jobs | Find ShouldQueue implementors, track dispatch | Medium |
| Config References | Track `config()` and `env()` calls | Low |
| Model Observers | Parse `$observers` or `observe()` calls | Medium |
| Form Requests | Find FormRequest subclasses, extract rules | Low |

---

## 7. Recommendations for Knowledge Graph Architecture

### 7.1 Recommended Parser Strategy

Based on this research, the recommended approach is a multi-parser, multi-pass architecture:

#### Primary Parser: tree-sitter-php (Python bindings)

**Rationale:**
- Native Python integration via `py-tree-sitter` - no subprocess overhead
- Incremental parsing for efficient re-analysis of changed files
- Full PHP 8.x support including enums, attributes, readonly, DNF types
- S-expression query language for precise node extraction
- Battle-tested in production (GitHub, Neovim, Zed, Helix)
- CST preserves all syntactic detail including comments and whitespace
- Fastest parser of the three (C-based, ~10-50ms for typical files)

**Use For:**
- All structural extraction (classes, methods, properties, functions)
- Relationship detection (inheritance, interface implementation, trait usage)
- PHP 8.x feature extraction (attributes, enums, readonly)
- Comment and PHPDoc extraction
- Incremental re-parsing on file changes

#### Secondary Parser: nikic/PHP-Parser (via subprocess)

**Rationale:**
- Built-in `NameResolver` visitor automatically resolves all names to FQCNs
- JSON serialization of AST for Python consumption
- Most accurate PHP parsing (written by PHP internals contributor)
- Handles edge cases that tree-sitter may miss

**Use For:**
- Name resolution pass: resolve short names to fully qualified class names
- Validation pass: cross-check tree-sitter extraction results
- Complex expression analysis where AST is more convenient than CST

**Integration Pattern:**

~~~python
import subprocess
import json

def resolve_names_with_php_parser(file_path: str) -> dict:
    """Run nikic/PHP-Parser with NameResolver and return JSON AST."""
    php_script = '''
    <?php
    require 'vendor/autoload.php';
    use PhpParser\\ParserFactory;
    use PhpParser\\NodeTraverser;
    use PhpParser\\NodeVisitor\\NameResolver;
    use PhpParser\\JsonDecoder;

    $parser = (new ParserFactory)->createForNewestSupportedVersion();
    $traverser = new NodeTraverser();
    $traverser->addVisitor(new NameResolver());

    $code = file_get_contents($argv[1]);
    $stmts = $parser->parse($code);
    $stmts = $traverser->traverse($stmts);

    $jsonEncoder = new PhpParser\\JsonDecoder();
    echo json_encode($stmts, JSON_PRETTY_PRINT);
    '''
    result = subprocess.run(
        ['php', '-r', php_script, file_path],
        capture_output=True, text=True
    )
    return json.loads(result.stdout)
~~~

#### Tertiary: PHPStan/Larastan (for type enrichment)

**Rationale:**
- Resolves types that neither parser can determine
- Understands Laravel conventions (facades, container, Eloquent)
- Provides error-level analysis for code quality assessment

**Use For:**
- Type enrichment pass: add resolved types to knowledge graph nodes
- Framework pattern resolution: facades, container bindings, model properties
- Code quality metrics: error counts by category and severity

### 7.2 Recommended Extraction Pipeline

~~~
Phase 1: File Discovery
  composer.json -> PSR-4 autoload map
  File system scan -> PHP file inventory
  .gitignore -> exclusion rules

Phase 2: Structural Extraction (tree-sitter-php)
  For each PHP file:
    Parse -> CST
    Extract: classes, interfaces, traits, enums, functions
    Extract: methods, properties, constants
    Extract: inheritance, implementation, trait usage
    Extract: use statements, namespace declarations
    Extract: attributes, PHPDoc comments
    Extract: method calls, property accesses, instantiations

Phase 3: Name Resolution (nikic/PHP-Parser)
  For each PHP file:
    Parse with NameResolver -> resolved AST
    Map short names to FQCNs
    Update knowledge graph edges with resolved names

Phase 4: Framework Pattern Detection
  Parse route files -> Route-to-Controller edges
  Parse service providers -> Interface-to-Implementation edges
  Parse EventServiceProvider -> Event-to-Listener edges
  Parse Kernel.php -> Middleware pipeline
  Parse Eloquent models -> Model relationship edges
  Resolve facades -> Facade-to-Service edges
  Parse Blade templates -> Template-to-Component edges

Phase 5: Type Enrichment (PHPStan/Larastan - optional)
  Run PHPStan analysis -> JSON output
  Extract resolved types for untyped code
  Add type annotations to knowledge graph nodes
  Flag dynamic dispatch points

Phase 6: Cross-Reference and Validation
  Resolve all class references to file paths (PSR-4)
  Validate all edges (do target classes/methods exist?)
  Flag unresolvable references (dynamic dispatch, missing code)
  Compute graph metrics (connectivity, centrality, coupling)
~~~

### 7.3 Knowledge Graph Node Types

Based on this research, the knowledge graph should support these node types:

| Node Type | Properties | Source |
|-----------|-----------|--------|
| `File` | path, namespace, size, last_modified | File system |
| `Namespace` | fqn, files | tree-sitter + PHP-Parser |
| `Class` | fqn, file, line, abstract, final, readonly | tree-sitter |
| `Interface` | fqn, file, line | tree-sitter |
| `Trait` | fqn, file, line | tree-sitter |
| `Enum` | fqn, file, line, scalar_type, cases | tree-sitter |
| `Method` | name, class, visibility, static, abstract, return_type | tree-sitter |
| `Property` | name, class, visibility, static, readonly, type | tree-sitter |
| `Function` | fqn, file, line, return_type | tree-sitter |
| `Constant` | name, class_or_namespace, value | tree-sitter |
| `Parameter` | name, method, type, default, variadic | tree-sitter |
| `Attribute` | name, target, arguments | tree-sitter |
| `Route` | method, uri, name, middleware | Route file parsing |
| `Event` | fqn, listeners | EventServiceProvider |
| `Job` | fqn, queue, connection | ShouldQueue detection |
| `Command` | signature, class | Command subclass detection |
| `Migration` | file, table, operations | Migration file parsing |
| `Config` | key, file, value_type | Config file parsing |

### 7.4 Knowledge Graph Edge Types

| Edge Type | From | To | Source |
|-----------|------|-----|--------|
| `extends` | Class | Class | tree-sitter |
| `implements` | Class | Interface | tree-sitter |
| `uses_trait` | Class | Trait | tree-sitter |
| `contains` | File/Class | Class/Method/Property | tree-sitter |
| `calls` | Method | Method/Function | tree-sitter + name resolution |
| `instantiates` | Method | Class | tree-sitter + name resolution |
| `type_of` | Property/Parameter | Class/Interface | tree-sitter + PHPStan |
| `returns` | Method | Class/Interface | tree-sitter + PHPStan |
| `throws` | Method | Class (Exception) | tree-sitter |
| `imports` | File | Class/Function/Constant | tree-sitter |
| `dispatches_to` | Route | Controller::method | Route parsing |
| `has_relationship` | Model | Model | Eloquent parsing |
| `listens_to` | Listener | Event | EventServiceProvider |
| `binds` | ServiceProvider | Interface->Implementation | Provider parsing |
| `middleware` | Route | Middleware | Route/Kernel parsing |
| `dispatches_job` | Method | Job | dispatch() detection |
| `fires_event` | Method | Event | event()/dispatch() detection |
| `facade_for` | Facade | Service class | Facade resolution |

### 7.5 Performance Considerations

| Operation | Expected Performance | Notes |
|-----------|---------------------|-------|
| tree-sitter parse (single file) | 5-50ms | Depends on file size |
| tree-sitter parse (1000 files) | 5-50 seconds | Parallelizable |
| nikic/PHP-Parser (single file) | 50-200ms | PHP subprocess overhead |
| nikic/PHP-Parser (1000 files) | 1-5 minutes | Batch mode recommended |
| PHPStan analysis (full project) | 30s-10min | Depends on project size and level |
| Knowledge graph construction | Seconds | After parsing is complete |
| Incremental update (1 file) | <100ms | tree-sitter incremental parsing |

**Optimization Strategies:**
1. Use tree-sitter for all initial extraction (fastest)
2. Run nikic/PHP-Parser in batch mode (single PHP process for all files)
3. Cache PHPStan results and only re-run on changed files
4. Use tree-sitter incremental parsing for file change events
5. Parallelize tree-sitter parsing across CPU cores
6. Store parsed ASTs in a cache (SQLite or pickle) for fast re-analysis

### 7.6 Limitations and Open Questions

1. **Dynamic dispatch remains partially opaque**: Variable method calls, reflection, and `__call` magic methods cannot be fully resolved statically. The knowledge graph should flag these as "dynamic" edges with unknown targets.

2. **Framework convention evolution**: Laravel conventions change between major versions. The knowledge graph builder should be configurable for different Laravel versions.

3. **Blade template parsing**: Blade is not PHP and requires a separate parser. Consider using regex-based extraction for common patterns or a dedicated Blade parser.

4. **Closure and anonymous class scope**: Closures capture variables from enclosing scope, and anonymous classes may reference outer variables. Tracking these scope relationships adds complexity.

5. **Composer package analysis**: Should the knowledge graph include vendor dependencies? This dramatically increases scope but provides complete type information.

6. **PHPStan/Psalm availability**: Not all projects have PHPStan or Psalm configured. The knowledge graph builder should work without them (degraded but functional).

7. **Database schema integration**: Eloquent model properties often come from database columns, not PHP code. Consider integrating migration analysis or database introspection.

---

## 8. Appendix: Parser Feature Comparison Matrix

| Feature | tree-sitter-php | nikic/PHP-Parser | glayzzle/php-parser |
|---------|----------------|-----------------|---------------------|
| **Language** | C (Python/JS/Rust bindings) | PHP | JavaScript |
| **Output** | CST (Concrete Syntax Tree) | AST (Abstract Syntax Tree) | AST |
| **PHP 8.0** | Full | Full | Partial |
| **PHP 8.1** | Full | Full | Partial |
| **PHP 8.2** | Full | Full | Unknown |
| **PHP 8.3** | Full | Full | Unknown |
| **PHP 8.4** | Partial | Full | Unknown |
| **Incremental Parsing** | Yes | No | No |
| **Error Recovery** | Yes (best) | Yes (good) | Yes (basic) |
| **Name Resolution** | No (manual) | Yes (NameResolver) | No |
| **Type Inference** | No | No | No |
| **Query Language** | S-expressions | Visitor pattern | Visitor pattern |
| **Python Integration** | Native (py-tree-sitter) | Subprocess (JSON) | Subprocess (JSON) |
| **Parse Speed** | ~5-50ms/file | ~50-200ms/file | ~100-500ms/file |
| **Memory Usage** | Low | Medium | Medium |
| **Maturity** | High (GitHub, editors) | Very High (de facto standard) | Low (unmaintained) |
| **Last Updated** | Active (2024) | Active (2024) | Stale (2022) |
| **License** | MIT | BSD-3-Clause | BSD-3-Clause |
| **GitHub Stars** | ~500 (grammar) | ~17,000 | ~1,200 |
| **Comment Preservation** | Yes (CST) | Yes (with option) | Yes |
| **PHPDoc Parsing** | Raw text only | Via phpdoc-parser | Basic |
| **Suitable for KG** | Primary parser | Name resolution | Not recommended |

---

*Document generated: 2026-03-10*
*Research conducted for: Codebase Knowledge Graph Builder Project*
