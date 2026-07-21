from pathlib import Path

from app import main


def test_image_signatures_and_safe_names():
    assert main._image_format(b"\xff\xd8\xffrest") == "image/jpeg"
    assert main._image_format(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert main._image_format(b"RIFFxxxxWEBP") == "image/webp"
    assert main._image_format(b"not-an-image") is None
    assert main._safe_upload_name(r"C:\temp\photo.jpg", "image/jpeg") == "photo.jpg"
    assert main._safe_upload_name("../report.html", "image/png") == "report.png"
    assert main._safe_upload_name("<script>.gif", "image/gif") == "script.gif"
    assert main._safe_upload_name("..", "image/webp") == ""


def test_upload_route_is_registered():
    assert any(
        route.path == "/api/upload-photo" and "POST" in route.methods
        for route in main.app.routes
    )


def test_delete_rejects_traversal_and_unknown_without_mutation(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    metadata = upload_dir / "photos.json"
    stored = upload_dir / "photo.jpg"
    stored.write_bytes(b"data")
    metadata.write_text('[{"filename": "photo.jpg"}]', encoding="utf-8")
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(main, "PHOTOS_JSON", metadata)

    import asyncio
    for name in ("../photo.jpg", r"..\photo.jpg", "/absolute.jpg", "unknown.jpg"):
        response = asyncio.run(main.delete_photo(name))
        assert response.status_code in (400, 404)
    response = asyncio.run(main.delete_photo("photo.jpg"))
    assert response["success"] is True
    assert not stored.exists()
    assert metadata.read_text(encoding="utf-8") == "[]"
