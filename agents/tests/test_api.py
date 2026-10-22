"""Tests for the voice agent service."""

from __future__ import annotations

import json

from django.test import Client, SimpleTestCase
from minidb import Database
from minidb.django.database import reset_database, set_database

from agents import storage


class ServiceTestCase(SimpleTestCase):
    """A base class with a clean database and a JSON client.

    The tests run against a throwaway in-memory database. Django's test
    runner knows nothing about minidb, so without this the database handle
    is redirected by hand — otherwise the tests wipe the *development*
    database, and seeding it and then running the tests loses the agents.
    """

    def setUp(self) -> None:
        super().setUp()
        set_database(Database(":memory:"))
        database = storage.get_database()
        for name in ("models", "agent"):
            if name in database.list_collection_names():
                database[name].delete_many({})
        self.client = Client()

    def tearDown(self) -> None:
        reset_database()
        super().tearDown()

    def post(self, path: str, payload: dict):
        return self.client.post(path, json.dumps(payload), content_type="application/json")

    def patch(self, path: str, payload: dict):
        return self.client.patch(path, json.dumps(payload), content_type="application/json")

    def body(self, response) -> dict:
        return json.loads(response.content)


class PaginationTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        for index in range(5):
            self.post("/api/models", {"name": f"Model {index}", "kind": "llm"})

    def test_everything_is_returned_by_default(self):
        body = self.body(self.client.get("/api/models"))
        self.assertEqual(body["count"], 5)
        self.assertEqual(body["total"], 5)

    def test_a_limit_cuts_the_page(self):
        body = self.body(self.client.get("/api/models?limit=2"))
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["total"], 5)
        self.assertEqual(body["limit"], 2)

    def test_an_offset_skips_the_start(self):
        body = self.body(self.client.get("/api/models?limit=2&offset=2"))
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["offset"], 2)
        self.assertEqual(body["results"][0]["slug"], "model-2")

    def test_paging_through_everything_covers_it_all(self):
        seen = []
        for offset in (0, 2, 4):
            body = self.body(self.client.get(f"/api/models?limit=2&offset={offset}"))
            seen.extend(model["slug"] for model in body["results"])
        self.assertEqual(sorted(seen), [f"model-{index}" for index in range(5)])

    def test_a_bad_limit_is_rejected(self):
        response = self.client.get("/api/models?limit=lots")
        self.assertEqual(response.status_code, 400)

    def test_agents_are_paged_too(self):
        for index in range(3):
            self.post("/api/agents", {"name": f"Agent {index}"})
        body = self.body(self.client.get("/api/agents?limit=2"))
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["total"], 3)


class SchemaTests(ServiceTestCase):
    def test_the_openapi_document_is_served(self):
        response = self.client.get("/api/schema")
        self.assertEqual(response.status_code, 200)
        body = self.body(response)
        self.assertEqual(body["openapi"], "3.1.0")
        self.assertIn("/api/models", body["paths"])
        self.assertIn("/api/agents", body["paths"])
        self.assertIn("/api/models/{slug}", body["paths"])

    def test_the_schema_describes_both_collections(self):
        body = self.body(self.client.get("/api/schema"))
        components = body["components"]["schemas"]
        self.assertIn("Model", components)
        self.assertIn("Agent", components)
        for field in ("stt", "model", "tts", "prompt", "config", "handle"):
            self.assertIn(field, components["Agent"]["properties"])

    def test_the_schema_knows_the_model_kinds(self):
        body = self.body(self.client.get("/api/schema"))
        kinds = body["components"]["schemas"]["Model"]["properties"]["kind"]["enum"]
        self.assertEqual(sorted(kinds), ["llm", "stt", "tts"])


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


class HealthTests(ServiceTestCase):
    def test_health_reports_the_database(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = self.body(response)
        self.assertEqual(body["status"], "ok")
        self.assertIn("models", body)
        self.assertIn("agents", body)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


class ModelTests(ServiceTestCase):
    def test_creating_a_model(self):
        response = self.post(
            "/api/models", {"name": "GPT-4o", "kind": "llm", "handle": "openai"}
        )
        self.assertEqual(response.status_code, 201)
        body = self.body(response)
        self.assertEqual(body["slug"], "gpt-4o")
        self.assertEqual(body["kind"], "llm")
        self.assertTrue(body["active"])
        self.assertIn("$oid", body["_id"])

    def test_the_slug_is_made_from_the_name(self):
        response = self.post("/api/models", {"name": "Claude Sonnet", "kind": "llm"})
        self.assertEqual(self.body(response)["slug"], "claude-sonnet")

    def test_a_duplicate_slug_is_a_conflict(self):
        self.post("/api/models", {"name": "GPT-4o", "kind": "llm"})
        response = self.post("/api/models", {"name": "GPT-4o", "kind": "llm"})
        self.assertEqual(response.status_code, 409)

    def test_an_unknown_kind_is_rejected(self):
        response = self.post("/api/models", {"name": "X", "kind": "nonsense"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("kind", self.body(response)["error"])

    def test_a_missing_name_is_rejected(self):
        response = self.post("/api/models", {"kind": "llm"})
        self.assertEqual(response.status_code, 400)

    def test_an_unexpected_field_is_rejected(self):
        response = self.post("/api/models", {"name": "X", "kind": "llm", "nope": 1})
        self.assertEqual(response.status_code, 400)

    def test_listing_models(self):
        self.post("/api/models", {"name": "A", "kind": "llm"})
        self.post("/api/models", {"name": "B", "kind": "tts"})
        self.post("/api/models", {"name": "C", "kind": "stt"})

        body = self.body(self.client.get("/api/models"))
        self.assertEqual(body["count"], 3)

    def test_filtering_by_kind(self):
        self.post("/api/models", {"name": "A", "kind": "llm"})
        self.post("/api/models", {"name": "B", "kind": "tts"})

        body = self.body(self.client.get("/api/models?kind=tts"))
        self.assertEqual([m["slug"] for m in body["results"]], ["b"])

    def test_an_unknown_kind_in_the_query_is_rejected(self):
        response = self.client.get("/api/models?kind=nonsense")
        self.assertEqual(response.status_code, 400)

    def test_searching(self):
        self.post("/api/models", {"name": "Claude Sonnet", "kind": "llm"})
        self.post("/api/models", {"name": "GPT-4o", "kind": "llm"})

        body = self.body(self.client.get("/api/models?q=claude"))
        self.assertEqual([m["slug"] for m in body["results"]], ["claude-sonnet"])

    def test_fetching_one_model(self):
        self.post("/api/models", {"name": "GPT-4o", "kind": "llm"})
        body = self.body(self.client.get("/api/models/gpt-4o"))
        self.assertEqual(body["name"], "GPT-4o")

    def test_fetching_a_model_that_is_not_there(self):
        response = self.client.get("/api/models/nothing")
        self.assertEqual(response.status_code, 404)

    def test_updating_a_model(self):
        self.post("/api/models", {"name": "GPT-4o", "kind": "llm"})
        response = self.patch("/api/models/gpt-4o", {"description": "Multimodal"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.body(response)["description"], "Multimodal")

    def test_updating_a_model_merges_the_config(self):
        self.post("/api/models", {"name": "GPT-4o", "kind": "llm", "config": {"a": 1, "b": 2}})
        body = self.body(self.patch("/api/models/gpt-4o", {"config": {"b": 3}}))
        self.assertEqual(body["config"], {"a": 1, "b": 3})

    def test_deleting_a_model(self):
        self.post("/api/models", {"name": "GPT-4o", "kind": "llm"})
        response = self.client.delete("/api/models/gpt-4o")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/models/gpt-4o").status_code, 404)


# ---------------------------------------------------------------------------
# agents
# ---------------------------------------------------------------------------


class AgentTests(ServiceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.post("/api/models", {"name": "GPT-4o", "kind": "llm"})
        self.post("/api/models", {"name": "Whisper", "kind": "stt"})
        self.post("/api/models", {"name": "Nova", "kind": "tts"})

    def test_creating_an_agent(self):
        response = self.post(
            "/api/agents",
            {
                "name": "Customer Support",
                "prompt": "Be helpful.",
                "stt": "whisper",
                "model": "gpt-4o",
                "tts": "nova",
                "config": {"language": "en"},
            },
        )
        self.assertEqual(response.status_code, 201)
        body = self.body(response)
        self.assertEqual(body["slug"], "customer-support")
        self.assertEqual(body["stt"], "whisper")
        self.assertEqual(body["model"], "gpt-4o")
        self.assertEqual(body["tts"], "nova")
        self.assertEqual(body["handle"], "customer-support")

    def test_an_agent_may_name_no_models(self):
        response = self.post("/api/agents", {"name": "Bare"})
        self.assertEqual(response.status_code, 201)

    def test_an_agent_may_not_name_a_model_that_does_not_exist(self):
        response = self.post("/api/agents", {"name": "Broken", "model": "nope"})
        self.assertEqual(response.status_code, 400)

    def test_an_agent_may_not_use_the_wrong_kind_of_model(self):
        response = self.post("/api/agents", {"name": "Wrong", "stt": "gpt-4o"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("stt", str(self.body(response)))

    def test_listing_agents(self):
        self.post("/api/agents", {"name": "One"})
        self.post("/api/agents", {"name": "Two"})
        body = self.body(self.client.get("/api/agents"))
        self.assertEqual(body["count"], 2)

    def test_fetching_an_agent(self):
        self.post("/api/agents", {"name": "Support"})
        body = self.body(self.client.get("/api/agents/support"))
        self.assertEqual(body["name"], "Support")

    def test_updating_an_agent_merges_the_config(self):
        self.post("/api/agents", {"name": "Support", "config": {"a": 1, "b": 2}})
        body = self.body(self.patch("/api/agents/support", {"config": {"b": 3}}))
        self.assertEqual(body["config"], {"a": 1, "b": 3})

    def test_deleting_an_agent(self):
        self.post("/api/agents", {"name": "Support"})
        self.assertEqual(self.client.delete("/api/agents/support").status_code, 200)
        self.assertEqual(self.client.get("/api/agents/support").status_code, 404)

    def test_a_model_in_use_may_not_be_deleted(self):
        self.post("/api/agents", {"name": "Support", "model": "gpt-4o"})
        response = self.client.delete("/api/models/gpt-4o")
        self.assertEqual(response.status_code, 409)
        self.assertIn("support", self.body(response)["error"])

    def test_a_model_can_be_deleted_once_it_is_unused(self):
        self.post("/api/agents", {"name": "Support", "model": "gpt-4o"})
        self.client.delete("/api/agents/support")
        self.assertEqual(self.client.delete("/api/models/gpt-4o").status_code, 200)


# ---------------------------------------------------------------------------
# tasks — dispatching an agent to the runtime
# ---------------------------------------------------------------------------


class TaskTests(ServiceTestCase):
    """The task endpoint hands work to the nitpick-core service.

    The runtime is stubbed out, so these tests do not need it running.
    """

    def setUp(self) -> None:
        super().setUp()
        self.post("/api/agents", {"name": "Customer Support", "handle": "acme-support"})
        self.calls: list[tuple[str, str, dict]] = []

        from agents import api

        self._original_core_request = api._core_request

        def fake_request(method, path, payload=None):
            self.calls.append((method, path, payload or {}))
            if path == "/tasks":
                return {
                    "id": "ses-123",
                    "handle": "acme-support",
                    "room_id": (payload or {}).get("room_id"),
                    "status": "queued",
                    "flow_run_id": "flow-1",
                }
            if path.startswith("/sessions/"):
                return {"id": path.rsplit("/", 1)[-1], "status": "running"}
            return {"count": 1, "results": [{"id": "ses-123", "status": "running"}]}

        api._core_request = fake_request

    def tearDown(self) -> None:
        from agents import api

        api._core_request = self._original_core_request
        super().tearDown()

    def test_dispatching_an_agent(self):
        response = self.post("/api/tasks", {"agent": "acme-support", "room_id": "demo"})
        self.assertEqual(response.status_code, 202)
        body = self.body(response)
        self.assertEqual(body["id"], "ses-123")
        self.assertEqual(body["flow_run_id"], "flow-1")

        method, path, payload = self.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/tasks")
        self.assertEqual(payload["handle"], "acme-support")
        self.assertEqual(payload["room_id"], "demo")

    def test_an_agent_may_be_named_by_its_handle(self):
        response = self.post("/api/tasks", {"agent": "acme-support"})
        self.assertEqual(response.status_code, 202)

    def test_an_unknown_agent_is_a_404(self):
        """The agent is checked here, so the runtime is never asked."""
        response = self.post("/api/tasks", {"agent": "nobody"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.calls, [])

    def test_a_task_without_an_agent_is_rejected(self):
        response = self.post("/api/tasks", {})
        self.assertEqual(response.status_code, 400)

    def test_fetching_a_task(self):
        response = self.client.get("/api/tasks/ses-123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.body(response)["status"], "running")

    def test_listing_tasks(self):
        response = self.client.get("/api/tasks")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.body(response)["count"], 1)


# ---------------------------------------------------------------------------
# the collections themselves
# ---------------------------------------------------------------------------


class CollectionTests(ServiceTestCase):
    def test_the_collections_are_named_models_and_agent(self):
        database = storage.get_database()
        self.assertIn("models", database.list_collection_names())
        self.assertIn("agent", database.list_collection_names())

    def test_the_slug_is_unique(self):
        database = storage.get_database()
        indexes = {i["name"]: i for i in database["models"].list_indexes()}
        self.assertTrue(indexes["slug_1"]["unique"])

    def test_a_document_that_breaks_the_schema_is_refused(self):
        database = storage.get_database()
        from minidb.errors import ValidationError

        with self.assertRaises(ValidationError):
            database["models"].insert_one({"name": "No kind"})

    def test_an_agent_is_stored_with_the_fields_the_api_exposes(self):
        storage.create_model({"name": "GPT-4o", "kind": "llm"})
        storage.create_model({"name": "Whisper", "kind": "stt"})
        storage.create_model({"name": "Nova", "kind": "tts"})
        storage.create_agent(
            {
                "name": "Support",
                "stt": "whisper",
                "model": "gpt-4o",
                "tts": "nova",
                "prompt": "Be helpful.",
                "config": {"language": "en"},
            }
        )
        document = storage.get_database()["agent"].find_one({"slug": "support"})
        for field in ("stt", "model", "tts", "name", "slug", "handle", "prompt", "config"):
            self.assertIn(field, document)
