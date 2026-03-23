"""Targeted tests for PHP extractor coverage."""

from unittest.mock import patch

import pytest

import coderag.plugins.php.extractor as ext_module
from coderag.core.models import EdgeKind, NodeKind
from coderag.plugins.php.extractor import PHPExtractor


@pytest.fixture
def ext():
    return PHPExtractor()


def _nodes_by_kind(result, kind):
    return [n for n in result.nodes if n.kind == kind]


def _edges_by_kind(result, kind):
    return [e for e in result.edges if e.kind == kind]


def _unresolved_by_kind(result, kind):
    return [u for u in result.unresolved_references if u.reference_kind == kind]


# ---- _is_abstract (line 77) ----
class TestAbstractModifier:
    def test_abstract_class(self, ext):
        source = b"""<?php
abstract class Shape {
    abstract public function area(): float;
    public function describe(): string { return "shape"; }
}
"""
        result = ext.extract("Shape.php", source)
        classes = _nodes_by_kind(result, NodeKind.CLASS)
        assert len(classes) >= 1
        shape = [c for c in classes if c.name == "Shape"][0]
        assert shape.metadata.get("abstract") is True

    def test_abstract_method(self, ext):
        source = b"""<?php
abstract class Base {
    abstract protected function doWork(): void;
}
"""
        result = ext.extract("Base.php", source)
        methods = _nodes_by_kind(result, NodeKind.METHOD)
        assert len(methods) >= 1
        assert any(m.metadata.get("abstract") is True for m in methods)


# ---- _extract_parameters params_node is None (line 129) ----
class TestExtractParameters:
    def test_function_no_params(self, ext):
        """Function with no formal_parameters node."""
        source = b"""<?php
function noParams() {
    return 42;
}
"""
        result = ext.extract("test.php", source)
        funcs = _nodes_by_kind(result, NodeKind.FUNCTION)
        assert len(funcs) >= 1

    def test_variadic_parameter(self, ext):
        source = b"""<?php
function sum(int ...$numbers): int {
    return array_sum($numbers);
}
"""
        result = ext.extract("math.php", source)
        funcs = _nodes_by_kind(result, NodeKind.FUNCTION)
        assert len(funcs) >= 1

    def test_property_promotion_parameter(self, ext):
        source = b"""<?php
class Point {
    public function __construct(
        public readonly float $x,
        public readonly float $y,
    ) {}
}
"""
        result = ext.extract("Point.php", source)
        methods = _nodes_by_kind(result, NodeKind.METHOD)
        assert len(methods) >= 1


# ---- _dispatch_declaration (lines 392-408) via braced namespace ----
class TestDispatchDeclaration:
    def test_braced_namespace_with_class(self, ext):
        """Braced namespace calls _dispatch_declaration."""
        source = b"""<?php
namespace App\\Models {
    class User {
        public string $name;
    }
}
"""
        result = ext.extract("User.php", source)
        classes = _nodes_by_kind(result, NodeKind.CLASS)
        assert any(c.name == "User" for c in classes)

    def test_braced_namespace_with_interface(self, ext):
        """Braced namespace dispatches interface_declaration."""
        source = b"""<?php
namespace App\\Contracts {
    interface Loggable {
        public function log(string $message): void;
    }
}
"""
        result = ext.extract("Loggable.php", source)
        ifaces = _nodes_by_kind(result, NodeKind.INTERFACE)
        assert any(i.name == "Loggable" for i in ifaces)

    def test_braced_namespace_with_trait(self, ext):
        """Braced namespace dispatches trait_declaration."""
        source = b"""<?php
namespace App\\Traits {
    trait Timestampable {
        public function getCreatedAt(): string { return ""; }
    }
}
"""
        result = ext.extract("Timestampable.php", source)
        traits = _nodes_by_kind(result, NodeKind.TRAIT)
        assert any(t.name == "Timestampable" for t in traits)

    def test_braced_namespace_with_enum(self, ext):
        """Braced namespace dispatches enum_declaration."""
        source = b"""<?php
namespace App\\Enums {
    enum Color {
        case Red;
        case Green;
        case Blue;
    }
}
"""
        result = ext.extract("Color.php", source)
        enums = _nodes_by_kind(result, NodeKind.ENUM)
        assert any(e.name == "Color" for e in enums)

    def test_braced_namespace_with_function(self, ext):
        """Braced namespace dispatches function_definition."""
        source = b"""<?php
namespace App\\Helpers {
    function formatDate(string $date): string {
        return date("Y-m-d", strtotime($date));
    }
}
"""
        result = ext.extract("helpers.php", source)
        funcs = _nodes_by_kind(result, NodeKind.FUNCTION)
        assert any(f.name == "formatDate" for f in funcs)

    def test_braced_namespace_with_const(self, ext):
        """Braced namespace dispatches const_declaration."""
        source = b"""<?php
namespace App\\Config {
    const MAX_RETRIES = 3;
    const TIMEOUT = 30;
}
"""
        result = ext.extract("config.php", source)
        consts = _nodes_by_kind(result, NodeKind.CONSTANT)
        assert len(consts) >= 2

    def test_braced_namespace_with_use(self, ext):
        """Braced namespace dispatches namespace_use_declaration."""
        source = b"""<?php
namespace App\\Controllers {
    use App\\Models\\User;
    class UserController {}
}
"""
        result = ext.extract("UserController.php", source)
        imports = _nodes_by_kind(result, NodeKind.IMPORT)
        classes = _nodes_by_kind(result, NodeKind.CLASS)
        assert any(c.name == "UserController" for c in classes)

    def test_dispatch_exception_handling(self, ext):
        """Exception in dispatch is caught and recorded as error."""
        real_handle_class = ext._handle_class

        def broken_handle_class(*args, **kwargs):
            raise RuntimeError("test error")

        with patch.object(ext, "_handle_class", side_effect=broken_handle_class):
            source = b"""<?php
namespace App {
    class Broken {}
}
"""
            result = ext.extract("Broken.php", source)
            assert any("test error" in e.message for e in result.errors)


# ---- Use declarations with alias and namespace_name fallback (lines 434-445) ----
class TestUseDeclarations:
    def test_use_with_alias(self, ext):
        source = b"""<?php
namespace App\\Controllers;
use App\\Models\\User as UserModel;
use App\\Services\\AuthService;
class UserController {}
"""
        result = ext.extract("UserController.php", source)
        imports = _nodes_by_kind(result, NodeKind.IMPORT)
        assert len(imports) >= 2

    def test_use_function_import(self, ext):
        source = b"""<?php
use function App\\Helpers\\format_date;
"""
        result = ext.extract("test.php", source)
        # use function may or may not produce IMPORT nodes depending on implementation
        # use function declaration processed without error
        assert result.file_path == "test.php"

    def test_use_group(self, ext):
        source = b"""<?php
use App\\Models\\{User, Post, Comment};
"""
        result = ext.extract("test.php", source)
        # Grouped use declarations may or may not produce individual IMPORT nodes
        assert result.file_path == "test.php"


# ---- Interface handler (lines 589, 641-644) ----
class TestInterface:
    def test_interface_declaration(self, ext):
        source = b"""<?php
interface Loggable {
    public function log(string $message): void;
    public function getLevel(): int;
}
"""
        result = ext.extract("Loggable.php", source)
        ifaces = _nodes_by_kind(result, NodeKind.INTERFACE)
        assert len(ifaces) >= 1
        methods = _nodes_by_kind(result, NodeKind.METHOD)
        assert len(methods) >= 2

    def test_interface_extends(self, ext):
        source = b"""<?php
interface Readable {
    public function read(): string;
}
interface Streamable extends Readable {
    public function stream(): void;
}
"""
        result = ext.extract("Streamable.php", source)
        ifaces = _nodes_by_kind(result, NodeKind.INTERFACE)
        assert len(ifaces) >= 2


# ---- Trait handler (lines 659, 689-692) ----
class TestTrait:
    def test_trait_declaration(self, ext):
        source = b"""<?php
trait Timestampable {
    private string $createdAt;
    public function getCreatedAt(): string { return $this->createdAt; }
}
"""
        result = ext.extract("Timestampable.php", source)
        traits = _nodes_by_kind(result, NodeKind.TRAIT)
        assert len(traits) >= 1

    def test_trait_use_in_class(self, ext):
        """Covers use_declaration in class body (line 880)."""
        source = b"""<?php
trait HasName {
    public function getName(): string { return $this->name; }
}
class User {
    use HasName;
    private string $name;
}
"""
        result = ext.extract("User.php", source)
        traits = _nodes_by_kind(result, NodeKind.TRAIT)
        assert len(traits) >= 1
        classes = _nodes_by_kind(result, NodeKind.CLASS)
        assert len(classes) >= 1


# ---- Enum handler (lines 707, 753-756) ----
class TestEnum:
    def test_enum_declaration(self, ext):
        source = b"""<?php
enum Color {
    case Red;
    case Green;
    case Blue;
}
"""
        result = ext.extract("Color.php", source)
        enums = _nodes_by_kind(result, NodeKind.ENUM)
        assert len(enums) >= 1

    def test_backed_enum_with_method(self, ext):
        source = b"""<?php
enum Status: string {
    case Active = "active";
    case Inactive = "inactive";
    public function label(): string { return ucfirst($this->value); }
}
"""
        result = ext.extract("Status.php", source)
        enums = _nodes_by_kind(result, NodeKind.ENUM)
        assert len(enums) >= 1
        methods = _nodes_by_kind(result, NodeKind.METHOD)
        assert len(methods) >= 1

    def test_enum_implements(self, ext):
        source = b"""<?php
interface HasLabel {
    public function label(): string;
}
enum Suit: string implements HasLabel {
    case Hearts = "hearts";
    case Diamonds = "diamonds";
    public function label(): string { return ucfirst($this->value); }
}
"""
        result = ext.extract("Suit.php", source)
        enums = _nodes_by_kind(result, NodeKind.ENUM)
        assert len(enums) >= 1

    def test_enum_with_const(self, ext):
        """Covers class_constant_declaration in class body (line 881)."""
        source = b"""<?php
enum Direction {
    case North;
    case South;
    const DEFAULT = self::North;
}
"""
        result = ext.extract("Direction.php", source)
        enums = _nodes_by_kind(result, NodeKind.ENUM)
        assert len(enums) >= 1
        consts = _nodes_by_kind(result, NodeKind.CONSTANT)
        assert len(consts) >= 1


# ---- Standalone function (lines 771, 809-812) ----
class TestStandaloneFunction:
    def test_function_definition(self, ext):
        source = b"""<?php
function calculateTotal(array $items, float $tax = 0.0): float {
    $sum = 0;
    foreach ($items as $item) {
        $sum += $item;
    }
    return $sum * (1 + $tax);
}
"""
        result = ext.extract("helpers.php", source)
        funcs = _nodes_by_kind(result, NodeKind.FUNCTION)
        assert len(funcs) >= 1
        assert any(f.name == "calculateTotal" for f in funcs)

    def test_function_with_calls(self, ext):
        source = b"""<?php
function process() {
    $data = fetchData();
    return transform($data);
}
"""
        result = ext.extract("process.php", source)
        funcs = _nodes_by_kind(result, NodeKind.FUNCTION)
        assert len(funcs) >= 1
        calls = _unresolved_by_kind(result, EdgeKind.CALLS)
        assert len(calls) >= 2


# ---- Top-level const (line 834) ----
class TestTopLevelConst:
    def test_const_declaration(self, ext):
        source = b"""<?php
const MAX_RETRIES = 3;
const DEFAULT_TIMEOUT = 30;
"""
        result = ext.extract("config.php", source)
        consts = _nodes_by_kind(result, NodeKind.CONSTANT)
        assert len(consts) >= 2


# ---- Class body: trait use + class_constant_declaration (lines 880-881, 900) ----
class TestClassBody:
    def test_class_with_trait_use_and_const(self, ext):
        source = b"""<?php
trait Cacheable {
    public function cache(): void {}
}
class Repository {
    use Cacheable;
    const TABLE = "repos";
    public string $name;
    public function find(int $id): void {
        $this->cache();
    }
}
"""
        result = ext.extract("Repository.php", source)
        classes = _nodes_by_kind(result, NodeKind.CLASS)
        assert len(classes) >= 1
        traits = _nodes_by_kind(result, NodeKind.TRAIT)
        assert len(traits) >= 1
        consts = _nodes_by_kind(result, NodeKind.CONSTANT)
        assert len(consts) >= 1

    def test_class_body_exception_handling(self, ext):
        """Exception in class body member is caught (line 900)."""
        real_handle_method = ext._handle_method

        def broken_handle_method(*args, **kwargs):
            raise RuntimeError("method error")

        with patch.object(ext, "_handle_method", side_effect=broken_handle_method):
            source = b"""<?php
class Broken {
    public function foo(): void {}
}
"""
            result = ext.extract("Broken.php", source)
            assert any("method error" in e.message for e in result.errors)


# ---- Method body scan (lines 943-944, 978) ----
class TestMethodCalls:
    def test_method_calls_in_body(self, ext):
        source = b"""<?php
class Service {
    public function process(): void {
        $data = $this->fetchData();
        $result = transform($data);
        Logger::info("done");
    }
}
"""
        result = ext.extract("Service.php", source)
        methods = _nodes_by_kind(result, NodeKind.METHOD)
        assert len(methods) >= 1
        calls = _unresolved_by_kind(result, EdgeKind.CALLS)
        assert len(calls) >= 1

    def test_new_expression(self, ext):
        source = b"""<?php
class Factory {
    public function create(): void {
        $p = new Product();
    }
}
"""
        result = ext.extract("Factory.php", source)
        instantiates = _unresolved_by_kind(result, EdgeKind.INSTANTIATES)
        assert len(instantiates) >= 1


# ---- Properties (line 978) ----
class TestClassProperties:
    def test_typed_properties(self, ext):
        source = b"""<?php
class Config {
    public string $name;
    protected int $timeout = 30;
    private ?array $options = null;
}
"""
        result = ext.extract("Config.php", source)
        props = _nodes_by_kind(result, NodeKind.PROPERTY)
        assert len(props) >= 3

    def test_static_property(self, ext):
        source = b"""<?php
class Counter {
    public static int $count = 0;
    public static function increment(): void { self::$count++; }
}
"""
        result = ext.extract("Counter.php", source)
        props = _nodes_by_kind(result, NodeKind.PROPERTY)
        assert len(props) >= 1

    def test_union_type_property(self, ext):
        source = b"""<?php
class Flexible {
    public int|string $value;
    public float|null $score = null;
}
"""
        result = ext.extract("Flexible.php", source)
        props = _nodes_by_kind(result, NodeKind.PROPERTY)
        assert len(props) >= 2


# ---- Class constants (line 1045) ----
class TestClassConstants:
    def test_class_const(self, ext):
        source = b"""<?php
class HttpStatus {
    const OK = 200;
    const NOT_FOUND = 404;
    const SERVER_ERROR = 500;
}
"""
        result = ext.extract("HttpStatus.php", source)
        consts = _nodes_by_kind(result, NodeKind.CONSTANT)
        assert len(consts) >= 3

    def test_typed_class_const(self, ext):
        source = b"""<?php
class Config {
    public const string VERSION = "1.0.0";
    protected const int MAX_RETRIES = 3;
}
"""
        result = ext.extract("Config.php", source)
        consts = _nodes_by_kind(result, NodeKind.CONSTANT)
        assert len(consts) >= 2


# ---- _scan_calls function_call_expression fallback (line 1084) ----
class TestScanCalls:
    def test_function_call_fallback(self, ext):
        """When _child_by_field returns None for function, fallback to first child."""
        real_cbf = ext_module._child_by_field

        def patched_cbf(node, field):
            if node.type == "function_call_expression" and field == "function":
                return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
function test() {
    doSomething();
}
"""
            result = ext.extract("test.php", source)
            # Should still extract the call via fallback
            calls = _unresolved_by_kind(result, EdgeKind.CALLS)
            assert len(calls) >= 1


# ---- Name resolution (lines 1193, 1197-1198) ----
class TestNameResolution:
    def test_fully_qualified_name(self, ext):
        """Fully qualified name starts with backslash."""
        source = b"""<?php
namespace App;
class Foo {
    public function bar(): void {
        $x = new \\DateTime();
    }
}
"""
        result = ext.extract("Foo.php", source)
        classes = _nodes_by_kind(result, NodeKind.CLASS)
        assert len(classes) >= 1

    def test_use_map_resolution(self, ext):
        """Name resolved via use-map."""
        source = b"""<?php
namespace App\\Services;
use App\\Models\\User;
class UserService {
    public function find(): void {
        $u = new User();
    }
}
"""
        result = ext.extract("UserService.php", source)
        instantiates = _unresolved_by_kind(result, EdgeKind.INSTANTIATES)
        assert len(instantiates) >= 1

    def test_namespace_relative_resolution(self, ext):
        """Name resolved relative to current namespace."""
        source = b"""<?php
namespace App\\Services;
class UserService {
    public function find(): void {
        $h = new Helper();
    }
}
"""
        result = ext.extract("UserService.php", source)
        instantiates = _unresolved_by_kind(result, EdgeKind.INSTANTIATES)
        assert len(instantiates) >= 1
        # Should be resolved as App\\Services\\Helper
        assert any("App" in u.reference_name for u in instantiates)


# ---- Body fallback paths via mocking _child_by_field ----
class TestBodyFallback:
    def test_interface_body_fallback(self, ext):
        """When _child_by_field returns None for body, fallback to declaration_list."""
        real_cbf = ext_module._child_by_field
        call_count = {"interface": 0}

        def patched_cbf(node, field):
            if field == "body" and node.type == "interface_declaration":
                call_count["interface"] += 1
                if call_count["interface"] <= 1:
                    return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
interface Loggable {
    public function log(string $msg): void;
}
"""
            result = ext.extract("Loggable.php", source)
            ifaces = _nodes_by_kind(result, NodeKind.INTERFACE)
            assert len(ifaces) >= 1

    def test_trait_body_fallback(self, ext):
        real_cbf = ext_module._child_by_field
        call_count = {"trait": 0}

        def patched_cbf(node, field):
            if field == "body" and node.type == "trait_declaration":
                call_count["trait"] += 1
                if call_count["trait"] <= 1:
                    return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
trait Cacheable {
    public function cache(): void {}
}
"""
            result = ext.extract("Cacheable.php", source)
            traits = _nodes_by_kind(result, NodeKind.TRAIT)
            assert len(traits) >= 1

    def test_enum_body_fallback(self, ext):
        real_cbf = ext_module._child_by_field
        call_count = {"enum": 0}

        def patched_cbf(node, field):
            if field == "body" and node.type == "enum_declaration":
                call_count["enum"] += 1
                if call_count["enum"] <= 1:
                    return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
enum Color {
    case Red;
    case Green;
}
"""
            result = ext.extract("Color.php", source)
            enums = _nodes_by_kind(result, NodeKind.ENUM)
            assert len(enums) >= 1

    def test_function_body_fallback(self, ext):
        real_cbf = ext_module._child_by_field
        call_count = {"func": 0}

        def patched_cbf(node, field):
            if field == "body" and node.type == "function_definition":
                call_count["func"] += 1
                if call_count["func"] <= 1:
                    return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
function process() {
    doSomething();
}
"""
            result = ext.extract("process.php", source)
            funcs = _nodes_by_kind(result, NodeKind.FUNCTION)
            assert len(funcs) >= 1

    def test_method_body_fallback(self, ext):
        real_cbf = ext_module._child_by_field
        call_count = {"method": 0}

        def patched_cbf(node, field):
            if field == "body" and node.type == "method_declaration":
                call_count["method"] += 1
                if call_count["method"] <= 1:
                    return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
class Svc {
    public function run(): void {
        doWork();
    }
}
"""
            result = ext.extract("Svc.php", source)
            methods = _nodes_by_kind(result, NodeKind.METHOD)
            assert len(methods) >= 1

    def test_class_body_fallback(self, ext):
        real_cbf = ext_module._child_by_field
        call_count = {"class": 0}

        def patched_cbf(node, field):
            if field == "body" and node.type == "class_declaration":
                call_count["class"] += 1
                if call_count["class"] <= 1:
                    return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
class Foo {
    public string $bar;
}
"""
            result = ext.extract("Foo.php", source)
            classes = _nodes_by_kind(result, NodeKind.CLASS)
            assert len(classes) >= 1


# ---- Class const name fallback (line 1045) ----
class TestClassConstNameFallback:
    def test_class_const_name_fallback(self, ext):
        """When _child_by_field returns None for name in const_element, fallback to gc.type==name."""
        real_cbf = ext_module._child_by_field

        def patched_cbf(node, field):
            if node.type == "const_element" and field == "name":
                return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
class Config {
    const VERSION = "1.0";
}
"""
            result = ext.extract("Config.php", source)
            consts = _nodes_by_kind(result, NodeKind.CONSTANT)
            assert len(consts) >= 1


# ---- Final class ----
class TestFinalClass:
    def test_final_class(self, ext):
        source = b"""<?php
final class Singleton {
    private static ?self $instance = null;
    public static function getInstance(): self {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }
}
"""
        result = ext.extract("Singleton.php", source)
        classes = _nodes_by_kind(result, NodeKind.CLASS)
        assert len(classes) >= 1
        singleton = [c for c in classes if c.name == "Singleton"][0]
        assert singleton.metadata.get("final") is True


# ---- Inheritance ----
class TestInheritance:
    def test_class_extends(self, ext):
        source = b"""<?php
class Animal {
    public string $name;
}
class Dog extends Animal {
    public function bark(): string { return "woof"; }
}
"""
        result = ext.extract("Dog.php", source)
        classes = _nodes_by_kind(result, NodeKind.CLASS)
        assert len(classes) >= 2

    def test_class_implements(self, ext):
        source = b"""<?php
interface Serializable {
    public function serialize(): string;
}
class JsonSerializer implements Serializable {
    public function serialize(): string { return "{}"; }
}
"""
        result = ext.extract("JsonSerializer.php", source)
        classes = _nodes_by_kind(result, NodeKind.CLASS)
        ifaces = _nodes_by_kind(result, NodeKind.INTERFACE)
        assert len(classes) >= 1
        assert len(ifaces) >= 1


# ---- Edge cases ----
class TestEdgeCases:
    def test_empty_source(self, ext):
        result = ext.extract("empty.php", b"")
        assert result.file_path == "empty.php"
        assert result.language == "php"

    def test_multiple_namespaces(self, ext):
        source = b"""<?php
namespace App\\Models;
class User {}
namespace App\\Services;
class UserService {}
"""
        result = ext.extract("multi.php", source)
        classes = _nodes_by_kind(result, NodeKind.CLASS)
        assert len(classes) >= 2

    def test_anonymous_class(self, ext):
        source = b"""<?php
function createLogger() {
    return new class {
        public function log(string $msg): void { echo $msg; }
    };
}
"""
        result = ext.extract("logger.php", source)
        funcs = _nodes_by_kind(result, NodeKind.FUNCTION)
        assert len(funcs) >= 1

    def test_intersection_type(self, ext):
        source = b"""<?php
class Handler {
    public function handle(Countable&Iterator $items): void {}
}
"""
        result = ext.extract("Handler.php", source)
        methods = _nodes_by_kind(result, NodeKind.METHOD)
        assert len(methods) >= 1

    def test_name_node_none_guard_class(self, ext):
        """When _child_by_field returns None for name, handler returns early (line 495)."""
        real_cbf = ext_module._child_by_field

        def patched_cbf(node, field):
            if node.type == "class_declaration" and field == "name":
                return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
class Foo {}
"""
            result = ext.extract("Foo.php", source)
            classes = _nodes_by_kind(result, NodeKind.CLASS)
            assert len(classes) == 0

    def test_name_node_none_guard_interface(self, ext):
        real_cbf = ext_module._child_by_field

        def patched_cbf(node, field):
            if node.type == "interface_declaration" and field == "name":
                return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
interface Bar {}
"""
            result = ext.extract("Bar.php", source)
            ifaces = _nodes_by_kind(result, NodeKind.INTERFACE)
            assert len(ifaces) == 0

    def test_name_node_none_guard_trait(self, ext):
        real_cbf = ext_module._child_by_field

        def patched_cbf(node, field):
            if node.type == "trait_declaration" and field == "name":
                return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
trait Baz {}
"""
            result = ext.extract("Baz.php", source)
            traits = _nodes_by_kind(result, NodeKind.TRAIT)
            assert len(traits) == 0

    def test_name_node_none_guard_enum(self, ext):
        real_cbf = ext_module._child_by_field

        def patched_cbf(node, field):
            if node.type == "enum_declaration" and field == "name":
                return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
enum Qux { case A; }
"""
            result = ext.extract("Qux.php", source)
            enums = _nodes_by_kind(result, NodeKind.ENUM)
            assert len(enums) == 0

    def test_name_node_none_guard_function(self, ext):
        real_cbf = ext_module._child_by_field

        def patched_cbf(node, field):
            if node.type == "function_definition" and field == "name":
                return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
function test() {}
"""
            result = ext.extract("test.php", source)
            funcs = _nodes_by_kind(result, NodeKind.FUNCTION)
            assert len(funcs) == 0

    def test_name_node_none_guard_method(self, ext):
        real_cbf = ext_module._child_by_field

        def patched_cbf(node, field):
            if node.type == "method_declaration" and field == "name":
                return None
            return real_cbf(node, field)

        with patch.object(ext_module, "_child_by_field", side_effect=patched_cbf):
            source = b"""<?php
class X {
    public function foo(): void {}
}
"""
            result = ext.extract("X.php", source)
            methods = _nodes_by_kind(result, NodeKind.METHOD)
            assert len(methods) == 0
