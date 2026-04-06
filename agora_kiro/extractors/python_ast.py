"""
extractors/python_ast.py — Tier 2: Python AST extractor.

Accurate, free, instant. Zero dependencies (stdlib ast module only).

Supports:
  - FastAPI  (@router.get, @app.post, @router.put, etc.)
  - Flask    (@app.route, @bp.route)
  - Django   (urlpatterns in urls.py)

Extracts: method, path, params (from type hints), docstring.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import List, Optional, Tuple

from agora_kiro.models import Param, Route, RouteCatalog

# Python type annotation → our type string
_TYPE_MAP = {
    "str": "str", "int": "int", "float": "float",
    "bool": "bool", "list": "list", "dict": "dict",
    "List": "list", "Dict": "dict", "Optional": "any",
    "Any": "any",
}


def can_handle(target: str) -> bool:
    """Return True if target is a directory containing Python files."""
    path = Path(target)
    if path.is_file() and path.suffix == ".py":
        return True
    if path.is_dir():
        return any(path.rglob("*.py"))
    return False


async def extract(target: str) -> RouteCatalog:
    """Walk Python files, extract all API routes."""
    path = Path(target)
    py_files = [path] if path.is_file() else list(path.rglob("*.py"))

    routes: List[Route] = []
    for py_file in py_files:
        try:
            source = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source, filename=str(py_file))
            file_routes = _extract_from_tree(tree, source)
            routes.extend(file_routes)
        except SyntaxError:
            continue  # skip unparseable files

    return RouteCatalog(source=str(target), extractor="ast", routes=routes)


# --------------------------------------------------------------------------- #
#  Tree walker                                                                 #
# --------------------------------------------------------------------------- #

def _extract_from_tree(tree: ast.Module, source: str) -> List[Route]:
    routes: List[Route] = []

    for node in ast.walk(tree):
        # --- FastAPI / Flask decorated functions ---
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for route in _extract_fastapi_flask(node, source):
                routes.append(route)

        # --- Django urlpatterns ---
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "urlpatterns":
                    for route in _extract_django(node.value):
                        routes.append(route)

    return routes


# --------------------------------------------------------------------------- #
#  FastAPI / Flask                                                              #
# --------------------------------------------------------------------------- #

def _extract_fastapi_flask(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
    source: str,
) -> List[Route]:
    routes = []
    for decorator in func.decorator_list:
        method, path = _parse_http_decorator(decorator)
        if method and path:
            params = _extract_params(func)
            docstring = ast.get_docstring(func) or ""
            routes.append(Route(
                method=method,
                path=path,
                params=params,
                description=docstring.split("\n")[0] if docstring else "",
                raw_code=_get_source_segment(source, func),
            ))
    return routes


def _parse_http_decorator(decorator: ast.expr) -> Tuple[Optional[str], Optional[str]]:
    """
    Detect patterns like:
      @app.get("/path")
      @router.post("/path")
      @bp.route("/path", methods=["GET"])
    Returns (METHOD, path) or (None, None).
    """
    HTTP_METHODS = {"get", "post", "put", "delete", "patch", "head", "options"}

    # @something.method("/path")
    if isinstance(decorator, ast.Call):
        func = decorator.func
        args = decorator.args
        keywords = {kw.arg: kw.value for kw in decorator.keywords}

        # @router.get("/path") or @app.post("/path")
        if isinstance(func, ast.Attribute) and func.attr.lower() in HTTP_METHODS:
            method = func.attr.upper()
            path = _get_string_arg(args, 0)
            if path:
                return method, path

        # @app.route("/path", methods=["GET", "POST"])
        if isinstance(func, ast.Attribute) and func.attr == "route":
            path = _get_string_arg(args, 0)
            if path:
                methods_node = keywords.get("methods")
                if methods_node and isinstance(methods_node, ast.List):
                    result = []
                    for elt in methods_node.elts:
                        if isinstance(elt, ast.Constant):
                            result.append((elt.value.upper(), path))
                    if result:
                        # Return first method — caller loops over function decorators anyway
                        return result[0]
                return "GET", path  # default for @app.route

    return None, None


def _get_string_arg(args: list, index: int) -> Optional[str]:
    if index < len(args):
        arg = args[index]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


# --------------------------------------------------------------------------- #
#  Parameter extraction from function signature                                #
# --------------------------------------------------------------------------- #

def _extract_params(func: ast.FunctionDef | ast.AsyncFunctionDef) -> List[Param]:
    params = []
    args = func.args

    # Pair each arg with its annotation
    all_args = args.args
    annotations = [a.annotation for a in all_args]
    defaults_offset = len(all_args) - len(args.defaults)

    # Skip 'self', 'cls', 'request', 'req', 'db', 'session' — framework internals
    skip_names = {"self", "cls", "request", "req", "db", "session", "background_tasks"}

    for i, arg in enumerate(all_args):
        if arg.arg in skip_names:
            continue

        type_str = _annotation_to_type(annotations[i])
        has_default = i >= defaults_offset
        required = not has_default

        # Heuristic: path params are in the path string (handled upstream)
        # Body params usually have Pydantic model type → mark as body
        location = "body" if type_str == "dict" else "query"

        params.append(Param(
            name=arg.arg,
            type=type_str,
            required=required,
            location=location,
        ))
    return params


def _annotation_to_type(annotation: Optional[ast.expr]) -> str:
    if annotation is None:
        return "any"
    if isinstance(annotation, ast.Constant):
        return str(annotation.value)
    if isinstance(annotation, ast.Name):
        return _TYPE_MAP.get(annotation.id, "any")
    if isinstance(annotation, ast.Attribute):
        return _TYPE_MAP.get(annotation.attr, "any")
    # Optional[X] → look inside
    if isinstance(annotation, ast.Subscript):
        if isinstance(annotation.value, ast.Name):
            if annotation.value.id == "Optional":
                return _annotation_to_type(annotation.slice)
            return _TYPE_MAP.get(annotation.value.id, "any")
    return "any"


def _get_source_segment(source: str, node: ast.AST) -> str:
    """Extract source code for a node. Returns up to 500 chars."""
    try:
        lines = source.splitlines()
        start = node.lineno - 1  # type: ignore[attr-defined]
        end = node.end_lineno     # type: ignore[attr-defined]
        return "\n".join(lines[start:end])[:500]
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
#  Django urlpatterns                                                          #
# --------------------------------------------------------------------------- #

def _extract_django(node: ast.expr) -> List[Route]:
    """
    Parse:
      urlpatterns = [
          path("products/", views.ProductList.as_view()),
          path("products/<int:pk>/", views.ProductDetail.as_view()),
          re_path(r"^orders/", views.OrderView.as_view()),
      ]
    """
    routes = []
    if not isinstance(node, ast.List):
        return routes

    for elt in node.elts:
        if not isinstance(elt, ast.Call):
            continue

        func_name = ""
        if isinstance(elt.func, ast.Name):
            func_name = elt.func.id
        elif isinstance(elt.func, ast.Attribute):
            func_name = elt.func.attr

        if func_name not in ("path", "re_path", "url"):
            continue

        if not elt.args:
            continue

        path_str = _get_string_arg(elt.args, 0)
        if not path_str:
            continue

        # Convert Django path converters: <int:pk> → {pk}
        import re
        clean_path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", path_str)

        # Django class-based views handle GET+POST — emit GET as default
        routes.append(Route(
            method="GET",
            path=f"/{clean_path.lstrip('/')}",
            params=[],
            description=f"Django view for {clean_path}",
        ))

    return routes
