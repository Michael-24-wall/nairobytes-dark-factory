def test_create_table_201(client):
    r = client.post("/tables", json={"table_id": "t1", "capacity": 4})
    assert r.status_code == 201
    assert r.json() == {"table_id": "t1", "capacity": 4}


def test_create_table_zero_capacity_400(client):
    r = client.post("/tables", json={"table_id": "t1", "capacity": 0})
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_CAPACITY"


def test_create_table_negative_capacity_400(client):
    r = client.post("/tables", json={"table_id": "t1", "capacity": -2})
    assert r.status_code == 400


def test_create_table_duplicate_409(client):
    assert client.post("/tables", json={"table_id": "t1", "capacity": 4}).status_code == 201
    r = client.post("/tables", json={"table_id": "t1", "capacity": 2})
    assert r.status_code == 409
    assert r.json()["error"] == "TABLE_EXISTS"


def test_create_table_missing_fields_422(client):
    r = client.post("/tables", json={"table_id": "t1"})
    assert r.status_code == 422
