"""The JSON API.

    GET    /api/health
    GET    /api/models?kind=llm&q=search
    POST   /api/models
    GET    /api/models/<slug>
    PATCH  /api/models/<slug>
    DELETE /api/models/<slug>
    GET    /api/agents?q=search
    POST   /api/agents
    GET    /api/agents/<slug>
    PATCH  /api/agents/<slug>
    DELETE /api/agents/<slug>
    POST   /api/tasks
    GET    /api/tasks/<session_id>
"""

from __future__ import annotations

import json
from typing import Any, Callable

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from minidb.bson import to_jsonable
from minidb.errors import ValidationError

from . import storage
from .storage import Conflict, Invalid, NotFound

__all__ = [
    "health",
    "schema",
    "model_collection",
    "model_detail",
    "agent_collection",
    "agent_detail",
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _body(request: HttpRequest) -> dict:
    """The JSON body of a request."""
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Invalid(f"the request body is not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise Invalid("the request body must be a JSON object")
    return payload


def _ok(payload: Any, status: int = 200) -> JsonResponse:
    """A JSON response, with the extended types written MongoDB's way."""
    return JsonResponse(
        to_jsonable(payload), status=status, json_dumps_params={"indent": 2}
    )


def _error(message: str, status: int = 400, details: list[str] | None = None) -> JsonResponse:
    body: dict[str, Any] = {"error": message}
    if details:
        body["details"] = details
    return JsonResponse(body, status=status, json_dumps_params={"indent": 2})


def _paging(request: HttpRequest) -> tuple[int, int]:
    """The ``limit`` and ``offset`` from the query string."""
    try:
        limit = max(0, int(request.GET.get("limit", 0) or 0))
        offset = max(0, int(request.GET.get("offset", 0) or 0))
    except ValueError as error:
        raise Invalid("limit and offset must be whole numbers") from error
    return limit, offset


def _page(results: list[dict], total: int, limit: int, offset: int) -> dict:
    """A page of results."""
    return {
        "count": len(results),
        "total": total,
        "limit": limit,
        "offset": offset,
        "results": results,
    }


def _guard(function: Callable) -> Callable:
    """Turn the storage errors into HTTP responses."""

    def wrapper(request: HttpRequest, *args, **kwargs) -> JsonResponse:
        try:
            return function(request, *args, **kwargs)
        except NotFound as error:
            return _error(str(error), 404)
        except Conflict as error:
            return _error(str(error), 409)
        except Invalid as error:
            return _error(str(error), 400, error.details)
        except ValidationError as error:
            # The collection layer validates too; this is the safety net.
            return _error(str(error), 400, error.details)

    wrapper.__name__ = function.__name__
    wrapper.__doc__ = function.__doc__
    return wrapper


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


@_guard
def health(request: HttpRequest) -> JsonResponse:
    """Is the service up, and what is in the database?"""
    from minidb import __version__

    return _ok(
        {
            "status": "ok",
            "minidb": __version__,
            "database": storage.get_database().path,
            **storage.stats(),
        }
    )


@_guard
def schema(request: HttpRequest) -> JsonResponse:
    """The OpenAPI description of this service."""
    from .openapi import openapi_schema

    return _ok(openapi_schema())


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


@_guard
def model_list(request: HttpRequest) -> JsonResponse:
    """List the models in the registry."""
    return model_collection(request)


@csrf_exempt
@_guard
def model_detail(request: HttpRequest, slug: str) -> JsonResponse:
    """One model, or a change to it."""
    if request.method == "GET":
        return _ok(storage.get_model(slug))

    if request.method == "POST" or request.method == "PUT":
        document = storage.create_model({**_body(request), "slug": slug})
        return _ok(document, 201)

    if request.method == "PATCH":
        return _ok(storage.update_model(slug, _body(request)))

    if request.method == "DELETE":
        storage.delete_model(slug)
        return _ok({"deleted": slug})

    return _error(f"{request.method} is not allowed here", 405)


@csrf_exempt
@_guard
def model_collection(request: HttpRequest) -> JsonResponse:
    """List the models, or create one."""
    if request.method == "GET":
        kind = request.GET.get("kind") or None
        if kind and kind not in ("llm", "tts", "stt"):
            return _error("kind must be one of llm, tts, stt", 400)
        limit, offset = _paging(request)
        models, total = storage.list_models(
            kind=kind,
            search=request.GET.get("q") or None,
            active_only=request.GET.get("active") == "true",
            limit=limit,
            offset=offset,
        )
        return _ok(_page(models, total, limit, offset))

    if request.method == "POST":
        document = storage.create_model(_body(request))
        return _ok(document, 201)

    return _error(f"{request.method} is not allowed here", 405)


# ---------------------------------------------------------------------------
# agents
# ---------------------------------------------------------------------------


@csrf_exempt
@_guard
def agent_detail(request: HttpRequest, slug: str) -> JsonResponse:
    """One agent, or a change to it."""
    if request.method == "GET":
        return _ok(storage.get_agent(slug))

    if request.method == "POST" or request.method == "PUT":
        document = storage.create_agent({**_body(request), "slug": slug})
        return _ok(document, 201)

    if request.method == "PATCH":
        return _ok(storage.update_agent(slug, _body(request)))

    if request.method == "DELETE":
        storage.delete_agent(slug)
        return _ok({"deleted": slug})

    return _error(f"{request.method} is not allowed here", 405)


@csrf_exempt
@_guard
def agent_collection(request: HttpRequest) -> JsonResponse:
    """List the agents, or create one."""
    if request.method == "GET":
        limit, offset = _paging(request)
        agents, total = storage.list_agents(
            search=request.GET.get("q") or None, limit=limit, offset=offset
        )
        return _ok(_page(agents, total, limit, offset))

    if request.method == "POST":
        document = storage.create_agent(_body(request))
        return _ok(document, 201)

    return _error(f"{request.method} is not allowed here", 405)


# ---------------------------------------------------------------------------
# tasks — dispatching an agent to run
# ---------------------------------------------------------------------------


def _core_url() -> str:
    """Where the nitpick-core service is."""
    from django.conf import settings

    return getattr(settings, "NITPICK_CORE_URL", "http://127.0.0.1:8100")


def _core_request(method: str, path: str, payload: dict | None = None) -> Any:
    """Call the nitpick-core service."""
    import httpx

    url = f"{_core_url().rstrip('/')}{path}"
    try:
        response = httpx.request(
            method,
            url,
            json=payload,
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
    except httpx.HTTPError as error:
        raise Invalid(
            f"could not reach the agent runtime at {url}: {error}",
            ["the nitpick-core service is not running"],
        ) from error

    if response.status_code >= 400:
        detail = response.text
        try:
            body = response.json()
            detail = body.get("detail") or body.get("error") or detail
        except Exception:  # noqa: BLE001 - the body may not be JSON
            pass
        raise Invalid(f"the agent runtime refused the task: {detail}", [str(detail)])

    if not response.content:
        return {}
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return {}


@csrf_exempt
@_guard
def task_collection(request: HttpRequest) -> JsonResponse:
    """Dispatch an agent to run.

    The agent is looked up in the registry first, so an unknown handle is
    rejected here rather than at the runtime. The task is then handed to
    nitpick-core, which dispatches it through Prefect.
    """
    if request.method == "GET":
        # The runtime owns the sessions, so this is a proxy of its list.
        limit, offset = _paging(request)
        body = _core_request("GET", "/sessions")
        results = body.get("results") if isinstance(body, dict) else body
        results = list(results or [])
        total = len(results) if isinstance(body, dict) and "count" not in body else (
            body.get("count", len(results)) if isinstance(body, dict) else len(results)
        )
        page = results[offset : offset + limit] if limit else results[offset:]
        return _ok(_page(page, total, limit, offset))

    if request.method != "POST":
        return _error(f"{request.method} is not allowed here", 405)

    body = _body(request)
    handle = body.get("agent") or body.get("handle")
    if not isinstance(handle, str) or not handle.strip():
        raise Invalid("an agent handle is required", ["agent"])

    # The agent has to exist. The runtime resolves it too, but failing here
    # gives the caller a 404 instead of a runtime error.
    agent = storage.get_agent_by_handle(handle.strip())

    room_id = body.get("room_id")
    if room_id is not None and not isinstance(room_id, str):
        raise Invalid("room_id must be a string", ["room_id"])

    metadata = body.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise Invalid("metadata must be an object", ["metadata"])

    result = _core_request(
        "POST",
        "/tasks",
        {
            "handle": agent.get("handle") or agent.get("slug"),
            "room_id": room_id,
            "metadata": metadata or {},
        },
    )
    return _ok(result, 202)


@csrf_exempt
@_guard
def task_detail(request: HttpRequest, session_id: str) -> JsonResponse:
    """One dispatched task."""
    if request.method != "GET":
        return _error(f"{request.method} is not allowed here", 405)
    return _ok(_core_request("GET", f"/sessions/{session_id}"))
