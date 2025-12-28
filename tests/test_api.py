"""Tests for API endpoints."""

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, client: TestClient):
        """Test health endpoint returns healthy status."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root_returns_info(self, client: TestClient):
        """Test root endpoint returns app info."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "status" in data
        assert data["status"] == "running"


# Placeholder tests for future API endpoints

class TestSessionsAPI:
    """Tests for sessions API endpoints."""

    @pytest.mark.skip(reason="API not implemented yet")
    def test_list_sessions(self, client: TestClient):
        """Test listing all sessions."""
        response = client.get("/api/sessions")
        assert response.status_code == 200

    @pytest.mark.skip(reason="API not implemented yet")
    def test_create_session(self, client: TestClient, sample_session_data):
        """Test creating a new session."""
        response = client.post("/api/sessions", json=sample_session_data)
        assert response.status_code == 201

    @pytest.mark.skip(reason="API not implemented yet")
    def test_get_session(self, client: TestClient):
        """Test getting session details."""
        response = client.get("/api/sessions/claude-test")
        assert response.status_code == 200


class TestTasksAPI:
    """Tests for tasks API endpoints."""

    @pytest.mark.skip(reason="API not implemented yet")
    def test_list_tasks(self, client: TestClient):
        """Test listing all tasks."""
        response = client.get("/api/tasks")
        assert response.status_code == 200

    @pytest.mark.skip(reason="API not implemented yet")
    def test_create_task(self, client: TestClient, sample_task_data):
        """Test creating a new task."""
        response = client.post("/api/tasks", json=sample_task_data)
        assert response.status_code == 201

    @pytest.mark.skip(reason="API not implemented yet")
    def test_assign_task(self, client: TestClient):
        """Test assigning task to session."""
        response = client.post(
            "/api/tasks/1/assign",
            json={"session_id": "claude-test"}
        )
        assert response.status_code == 200


class TestDocumentsAPI:
    """Tests for documents API endpoints."""

    @pytest.mark.skip(reason="API not implemented yet")
    def test_list_documents(self, client: TestClient):
        """Test listing all documents."""
        response = client.get("/api/documents")
        assert response.status_code == 200

    @pytest.mark.skip(reason="API not implemented yet")
    def test_get_document(self, client: TestClient):
        """Test getting document with content."""
        response = client.get("/api/documents/1")
        assert response.status_code == 200

    @pytest.mark.skip(reason="API not implemented yet")
    def test_get_document_lines(self, client: TestClient):
        """Test getting specific lines from document."""
        response = client.get("/api/documents/1/lines?start=1&end=10")
        assert response.status_code == 200
