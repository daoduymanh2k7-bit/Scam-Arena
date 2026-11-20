from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.rasa_review_routes import router
from app.auth import get_current_user
from rasa.evaluation.dataset_workflow import read_json, write_json


def test_only_admin_can_access_and_change_rasa_review(tmp_path, monkeypatch):
    endpoint = "/api/arena/admin/rasa-review"
    monkeypatch.setenv("RASA_REVIEW_DIR", str(tmp_path))
    write_json(tmp_path / "review.json", {
        "speakers": {"demo": None},
        "rows": [{"sample": "one", "speaker": "demo", "intent": None,
                  "style": "message", "text": "Tôi không làm theo."}],
    })
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get(endpoint).status_code == 401

    app.dependency_overrides[get_current_user] = lambda: {"role": "user"}
    assert client.get(endpoint).status_code == 403
    assert client.post(f"{endpoint}/collect").status_code == 403
    assert client.patch(f"{endpoint}/speakers/demo", json={"split": "train", "expected_split": None}).status_code == 403
    payload = {"intent": "refuse", "expected_intent": None}
    assert client.patch(f"{endpoint}/samples/one", json=payload).status_code == 403

    app.dependency_overrides[get_current_user] = lambda: {"role": "admin"}
    queue = client.get(endpoint)
    assert queue.headers["Cache-Control"] == "no-store"
    assert queue.json()["pending"] == 1
    assert client.patch(f"{endpoint}/samples/one", json=payload).status_code == 422
    assert client.patch(f"{endpoint}/speakers/demo", json={"split": "train", "expected_split": None}).status_code == 200
    assert client.patch(f"{endpoint}/samples/one", json=payload).status_code == 200
    assert client.patch(f"{endpoint}/samples/one", json=payload).status_code == 409
    assert read_json(tmp_path / "review.json", None)["rows"][0]["intent"] == "refuse"
    assert client.get(f"{endpoint}?status=reviewed").json()["total"] == 1

    write_json(tmp_path / "split_lock.json", {"demo": "train"})
    response = client.patch(f"{endpoint}/speakers/demo", json={"split": "holdout", "expected_split": "train"})
    assert response.status_code == 409
