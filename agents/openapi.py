"""An OpenAPI description of the service.

    GET /api/schema

Other services can generate a client from this, and it doubles as
documentation that cannot drift from the code, because the paths and the
field names are taken from the same place the views and the schemas use.
"""

from __future__ import annotations

from typing import Any

from .models import AGENT_SCHEMA, MODEL_KINDS, MODEL_SCHEMA

__all__ = ["openapi_schema", "SCHEMA_URL"]

SCHEMA_URL = "/api/schema"

_ERROR = {
    "type": "object",
    "properties": {
        "error": {"type": "string"},
        "details": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["error"],
}


def _model_properties(schema: dict) -> dict:
    """The JSON schema of a collection, as OpenAPI properties."""
    properties: dict[str, Any] = {}
    for name, rules in (schema.get("properties") or {}).items():
        entry: dict[str, Any] = {}
        if "enum" in rules:
            entry["enum"] = rules["enum"]
        elif rules.get("type") == "integer":
            entry["type"] = "integer"
        elif rules.get("type") == "number":
            entry["type"] = "number"
        elif rules.get("type") == "boolean":
            entry["type"] = "boolean"
        elif rules.get("type") == "array":
            entry["type"] = "array"
            entry["items"] = {"type": "object"}
        elif rules.get("type") == "object":
            entry["type"] = "object"
        else:
            entry["type"] = "string"
        if "default" in rules:
            entry["default"] = rules["default"]
        if "description" in rules:
            entry["description"] = rules["description"]
        properties[name] = entry
    return properties


def _model_schema(schema: dict, title: str) -> dict:
    return {
        "type": "object",
        "title": title,
        "properties": {
            **_model_properties(schema),
            "_id": {
                "type": "object",
                "description": "The document id, written MongoDB's Extended JSON way.",
                "properties": {"$oid": {"type": "string"}},
            },
        },
        "required": schema.get("required", []),
    }


def _query(name: str, description: str, schema: dict) -> dict:
    return {
        "name": name,
        "in": "query",
        "description": description,
        "required": False,
        "schema": schema,
    }


def openapi_schema() -> dict:
    """The OpenAPI document for this service."""
    model_schema = _model_schema(MODEL_SCHEMA, "Model")
    agent_schema = _model_schema(AGENT_SCHEMA, "Agent")

    paging = [
        _query("limit", "How many to return. 0 means all of them.", {"type": "integer"}),
        _query("offset", "How many to skip.", {"type": "integer"}),
    ]

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Voice agent service",
            "version": "0.1.0",
            "description": (
                "A registry of LLM, TTS and STT models, and the voice agents "
                "built from them. Everything is stored in minidb."
            ),
        },
        "paths": {
            "/api/health": {
                "get": {
                    "summary": "Is the service up?",
                    "responses": {
                        "200": {
                            "description": "The service is up.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string"},
                                            "minidb": {"type": "string"},
                                            "database": {"type": "string"},
                                            "models": {"type": "integer"},
                                            "agents": {"type": "integer"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/api/models": {
                "get": {
                    "summary": "List the models.",
                    "parameters": [
                        _query(
                            "kind",
                            "Only models of this kind.",
                            {"type": "string", "enum": list(MODEL_KINDS)},
                        ),
                        _query("q", "Search the name, slug or handle.", {"type": "string"}),
                        _query("active", "Only the active ones.", {"type": "boolean"}),
                        *paging,
                    ],
                    "responses": {
                        "200": {
                            "description": "A page of models.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "count": {"type": "integer"},
                                            "total": {"type": "integer"},
                                            "limit": {"type": "integer"},
                                            "offset": {"type": "integer"},
                                            "results": {
                                                "type": "array",
                                                "items": model_schema,
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "400": {"description": "Bad query.", "content": {"application/json": {"schema": _ERROR}}},
                    },
                },
                "post": {
                    "summary": "Create a model.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {"schema": model_schema}
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "The model that was created.",
                            "content": {"application/json": {"schema": model_schema}},
                        },
                        "400": {"description": "It does not fit the schema.", "content": {"application/json": {"schema": _ERROR}}},
                        "409": {"description": "The slug is taken.", "content": {"application/json": {"schema": _ERROR}}},
                    },
                },
            },
            "/api/models/{slug}": {
                "parameters": [
                    {
                        "name": "slug",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "get": {
                    "summary": "One model.",
                    "responses": {
                        "200": {"description": "The model.", "content": {"application/json": {"schema": model_schema}}},
                        "404": {"description": "No such model.", "content": {"application/json": {"schema": _ERROR}}},
                    },
                },
                "patch": {
                    "summary": "Change a model.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": model_schema}},
                    },
                    "responses": {
                        "200": {"description": "The model, changed.", "content": {"application/json": {"schema": model_schema}}},
                        "400": {"description": "It does not fit the schema.", "content": {"application/json": {"schema": _ERROR}}},
                        "404": {"description": "No such model.", "content": {"application/json": {"schema": _ERROR}}},
                        "409": {"description": "The slug is taken.", "content": {"application/json": {"schema": _ERROR}}},
                    },
                },
                "delete": {
                    "summary": "Remove a model.",
                    "responses": {
                        "200": {"description": "It is gone.", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "404": {"description": "No such model.", "content": {"application/json": {"schema": _ERROR}}},
                        "409": {"description": "An agent still uses it.", "content": {"application/json": {"schema": _ERROR}}},
                    },
                },
            },
            "/api/agents": {
                "get": {
                    "summary": "List the agents.",
                    "parameters": [
                        _query("q", "Search the name, slug or handle.", {"type": "string"}),
                        *paging,
                    ],
                    "responses": {
                        "200": {
                            "description": "A page of agents.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "count": {"type": "integer"},
                                            "total": {"type": "integer"},
                                            "limit": {"type": "integer"},
                                            "offset": {"type": "integer"},
                                            "results": {
                                                "type": "array",
                                                "items": agent_schema,
                                            },
                                        },
                                    }
                                }
                            },
                        }
                    },
                },
                "post": {
                    "summary": "Create an agent.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": agent_schema}},
                    },
                    "responses": {
                        "201": {
                            "description": "The agent that was created.",
                            "content": {"application/json": {"schema": agent_schema}},
                        },
                        "400": {
                            "description": "It does not fit the schema, or names a model that does not exist.",
                            "content": {"application/json": {"schema": _ERROR}},
                        },
                        "409": {"description": "The slug is taken.", "content": {"application/json": {"schema": _ERROR}}},
                    },
                },
            },
            "/api/agents/{slug}": {
                "parameters": [
                    {
                        "name": "slug",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "get": {
                    "summary": "One agent.",
                    "responses": {
                        "200": {"description": "The agent.", "content": {"application/json": {"schema": agent_schema}}},
                        "404": {"description": "No such agent.", "content": {"application/json": {"schema": _ERROR}}},
                    },
                },
                "patch": {
                    "summary": "Change an agent.",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": agent_schema}},
                    },
                    "responses": {
                        "200": {"description": "The agent, changed.", "content": {"application/json": {"schema": agent_schema}}},
                        "400": {
                            "description": "It does not fit the schema, or names a model that does not exist.",
                            "content": {"application/json": {"schema": _ERROR}},
                        },
                        "404": {"description": "No such agent.", "content": {"application/json": {"schema": _ERROR}}},
                        "409": {"description": "The slug is taken.", "content": {"application/json": {"schema": _ERROR}}},
                    },
                },
                "delete": {
                    "summary": "Remove an agent.",
                    "responses": {
                        "200": {"description": "It is gone.", "content": {"application/json": {"schema": {"type": "object"}}}},
                        "404": {"description": "No such agent.", "content": {"application/json": {"schema": _ERROR}}},
                    },
                },
            },
        },
        "components": {
            "schemas": {
                "Model": model_schema,
                "Agent": agent_schema,
                "Error": _ERROR,
            }
        },
    }
