"""
extractors/regex.py — Tier 4: Regex fallback extractor.

Fast, free, ~70% accurate. Works on any language without parsing.
No dependencies.

Supported languages (auto-detected by file extension):
  - Python   (.py)   — @app.get("/path"), @router.post("/path")
  - JS/TS    (.js, .ts, .mjs) — app.get("/path"), router.post("/path")
  - Ruby     (.rb)   — get "/path", post "/path"
  - Java     (.java) — @GetMapping("/path"), @RequestMapping("/path")
  - Go       (.go)   — r.GET("/path"), router.HandleFunc("/path", ...)
  - PHP      (.php)  — Route::get("/path", ...)

Limitations:
  - No parameter type extraction (all params marked as type="any")
  - Misses dynamic route registrations, runtime-generated routes
  - Multi-line route definitions may be missed
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from agora_kiro.models import Param, Route, RouteCatalog

HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"}


# --------------------------------------------------------------------------- #
#  Per-language regex patterns                                                 #
# Each yields (method, path) tuples                                            #
# --------------------------------------------------------------------------- #

_PATTERNS: dict[str, list[tuple[re.Pattern, int, int]]] = {
    # Python: @app.get("/path") or @router.post("/path", ...)
    ".py": [
        (re.compile(
            r'@\w+\.(get|post|put|delete|patch|head|options)\s*\(\s*["\']([^"\']+)["\']',
            re.IGNORECASE,
        ), 1, 2),
        # @app.route("/path", methods=["GET"])
        (re.compile(
            r'@\w+\.route\s*\(\s*["\']([^"\']+)["\'].*?methods\s*=\s*\[([^\]]+)\]',
            re.IGNORECASE | re.DOTALL,
        ), None, 1),  # special case — handled separately
    ],
    # JavaScript / TypeScript: app.get('/path', ...) or router.post('/path', ...)
    ".js": [
        (re.compile(
            r'\b\w+\.(get|post|put|delete|patch)\s*\(\s*["\`\']([^"\'`]+)["\`\']',
            re.IGNORECASE,
        ), 1, 2),
    ],
    ".ts": [
        (re.compile(
            r'@(Get|Post|Put|Delete|Patch)\s*\(\s*["\']([^"\']*)["\']',
        ), 1, 2),
        # Express-style in TS
        (re.compile(
            r'\b\w+\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
            re.IGNORECASE,
        ), 1, 2),
    ],
    # Ruby on Rails
    ".rb": [
        (re.compile(
            r'\b(get|post|put|delete|patch)\s+["\']([^"\']+)["\']',
            re.IGNORECASE,
        ), 1, 2),
        # resources :products → generates standard CRUD routes
        (re.compile(
            r'\bresources\s*:(\w+)',
        ), None, 1),  # special case
    ],
    # Java Spring Boot
    ".java": [
        (re.compile(
            r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping)\s*\(\s*["\']([^"\']+)["\']',
        ), 1, 2),
        (re.compile(
            r'@RequestMapping\s*\(.*?value\s*=\s*["\']([^"\']+)["\'].*?method\s*=\s*RequestMethod\.(\w+)',
            re.DOTALL,
        ), 2, 1),
    ],
    # Go (gorilla/mux, chi, gin)
    ".go": [
        (re.compile(
            r'\.(GET|POST|PUT|DELETE|PATCH|HandleFunc)\s*\(\s*["\']([^"\']+)["\']',
        ), 1, 2),
    ],
    # PHP Laravel
    ".php": [
        (re.compile(
            r"Route::(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]",
            re.IGNORECASE,
        ), 1, 2),
    ],
}
# Aliases
_PATTERNS[".mjs"] = _PATTERNS[".js"]
_PATTERNS[".jsx"] = _PATTERNS[".js"]
_PATTERNS[".tsx"] = _PATTERNS[".ts"]

# Spring annotation → HTTP method name
_SPRING_MAP = {
    "GetMapping": "GET", "PostMapping": "POST",
    "PutMapping": "PUT", "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}

# Rails resources → standard CRUD routes
_RAILS_RESOURCES = [
    ("GET", "/{resource}"),
    ("POST", "/{resource}"),
    ("GET", "/{resource}/{id}"),
    ("PUT", "/{resource}/{id}"),
    ("PATCH", "/{resource}/{id}"),
    ("DELETE", "/{resource}/{id}"),
]


def can_handle(target: str) -> bool:
    """Always returns True — regex is the universal fallback."""
    return True


async def extract(target: str) -> RouteCatalog:
    """Scan files with regex patterns, return discovered routes."""
    path = Path(target)
    if path.is_file():
        files = [path]
    else:
        files = [
            f for f in path.rglob("*")
            if f.is_file() and f.suffix in _PATTERNS
            and not _is_excluded(f)
        ]

    routes: List[Route] = []
    for f in files:
        try:
            source = f.read_text(encoding="utf-8", errors="ignore")
            routes.extend(_scan_file(source, f.suffix))
        except Exception:
            continue

    return RouteCatalog(source=str(target), extractor="regex", routes=routes)


def _scan_file(source: str, ext: str) -> List[Route]:
    patterns = _PATTERNS.get(ext, [])
    routes: List[Route] = []

    for pattern, method_group, path_group in patterns:
        for m in pattern.finditer(source):
            try:
                # Special case: Rails resources
                if method_group is None and ext == ".rb":
                    resource = m.group(1)
                    for method, path_template in _RAILS_RESOURCES:
                        routes.append(Route(
                            method=method,
                            path=path_template.format(resource=resource),
                            description=f"Rails resource: {resource}",
                        ))
                    continue

                # Special case: Python @app.route with methods= list
                if method_group is None and ext == ".py":
                    path = m.group(path_group)
                    methods_raw = m.group(2)
                    for meth in re.findall(r'["\'](\w+)["\']', methods_raw):
                        if meth.upper() in HTTP_METHODS:
                            routes.append(Route(method=meth.upper(), path=path))
                    continue

                method_raw = m.group(method_group)
                path = m.group(path_group)

                # Normalise Spring annotations
                method = _SPRING_MAP.get(method_raw, method_raw.upper())
                if method not in HTTP_METHODS:
                    continue

                routes.append(Route(method=method, path=path))
            except (IndexError, AttributeError):
                continue

    return routes


def _is_excluded(path: Path) -> bool:
    excluded = {
        "node_modules", ".git", "__pycache__", ".venv", "venv",
        "dist", "build", ".next", "vendor", "target",
    }
    return any(part in excluded for part in path.parts)
