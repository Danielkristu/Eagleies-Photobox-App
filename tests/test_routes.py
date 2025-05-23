from unittest.mock import patch, MagicMock




def test_login_invalid(client):
    response = client.post("/login", data={"username": "salah", "password": "salah"}, follow_redirects=True)
    assert b"Username atau Password salah" in response.data



def test_activate_page_loads(client):
    response = client.get("/activate")
    assert b"Kode Aktivasi" in response.data or response.status_code == 200

def test_login_page_loads(client):
    response = client.get("/login")
    assert b"Username" in response.data
    assert b"Password" in response.data
