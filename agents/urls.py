"""URLs for the voice agent service."""

from __future__ import annotations

from django.urls import path

from . import api

urlpatterns = [
    path("api/health", api.health, name="health"),
    path("api/schema", api.schema, name="schema"),
    path("api/models", api.model_collection, name="model-list"),
    path("api/models/<slug:slug>", api.model_detail, name="model-detail"),
    path("api/agents", api.agent_collection, name="agent-list"),
    path("api/agents/<slug:slug>", api.agent_detail, name="agent-detail"),
    path("api/tasks", api.task_collection, name="task-list"),
    path("api/tasks/<str:session_id>", api.task_detail, name="task-detail"),
]
