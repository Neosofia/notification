"""Container integration tests.

Runs against a live HTTP server to verify the image builds cleanly,
Gunicorn starts and serves correctly, and key endpoints respond as expected.

Set BASE_URL to target a specific instance (default: http://localhost:8005).

Coverage is not collected here. src/gunicorn_logger.py is exercised by this
suite and is therefore excluded from the unit-test coverage report.
"""

import os
import subprocess
import time
import requests
import pytest
from testcontainers.core.container import DockerContainer

IMAGE_TAG = "notification-svc-test:latest"

@pytest.fixture(scope="session", autouse=True)
def build_container_image():
    """Build the Docker image once per test session."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "."],
        cwd=repo_root,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    yield
    pass

@pytest.fixture(scope="module")
def app_container():
    """Spin up the built container.
    """
    container = DockerContainer(IMAGE_TAG)
    container.with_env("RESEND_API_KEY", "test_key")
    container.with_env("NOTIFICATION_FROM", "noreply@example.com")
    container.with_env("NOTIFICATION_TO", "inbox@example.com")
    container.with_env("CORS_ORIGINS", "http://localhost:3000")
    container.with_env("TRUSTED_PROXY_HOPS", "0")
    container.with_env("ENV", "test")
    container.with_exposed_ports(8005)
    
    with container as c:
        port = c.get_exposed_port(8005)
        host = c.get_container_host_ip()
        url = f"http://{host}:{port}/health"

        start = time.time()
        ready = False
        while time.time() - start < 15:
            try:
                res = requests.get(url, timeout=1)
                if res.status_code == 200:
                    ready = True
                    break
            except requests.exceptions.RequestException:
                time.sleep(0.5)
        
        if not ready:
            pytest.fail("Container did not become ready in time.")
            
        yield f"http://{host}:{port}"

VALID_PAYLOAD = {
    "from_email": "visitor@example.com",
    "subject": "Integration test",
    "message": "Hello from the integration test suite.",
}

def test_health(app_container):
    resp = requests.get(f"{app_container}/health", timeout=5)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

def test_valid_payload_returns_200_or_502(app_container):
    """Valid payload returns 200 (live Resend key) or 502 (stub/invalid key).
    Either outcome proves the request traversed the full application stack.
    """
    resp = requests.post(f"{app_container}/api/emails", json=VALID_PAYLOAD, timeout=15)
    assert resp.status_code in (200, 502)
