import io
import zipfile

from scholarship_agent.cv import interpret_cv, read_cv


def _docx(text: str) -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_a_phd_cv_searches_phd_computer_science():
    reading = read_cv(
        "amina.docx",
        _docx("Amina Hassan. PhD candidate in computer science. MSc in software engineering. Teaching assistant."),
    )
    assert reading.degree == "phd"
    assert "computer science" in reading.field
    assert "software engineering" in reading.field


def test_an_objective_overrides_an_earlier_degree():
    reading = interpret_cv(
        "Bachelor of Science in chemistry. Objective: seeking a master's scholarship in chemistry."
    )
    assert reading.degree == "masters"
    assert "chemistry" in reading.field


def test_a_finished_masters_searches_for_phd():
    reading = interpret_cv(
        "Master of Science in Computer Science, graduated 2024. Bachelor of Science in Software Engineering."
    )
    assert reading.degree == "phd"
    assert reading.reason == "completed-master"
    assert "computer science" in reading.field


def test_a_current_masters_student_still_searches_masters():
    reading = interpret_cv(
        "Currently pursuing a master's in chemistry and looking for a scholarship to finish the degree program."
    )
    assert reading.degree == "masters"


def test_any_file_with_text_is_accepted():
    reading = read_cv(
        "notes.bin",
        b"Bachelor of Science in chemistry. Graduated and looking for the next degree program.",
    )
    assert reading.degree == "masters"
    assert "chemistry" in reading.field


def test_an_rtf_cv_is_accepted():
    reading = read_cv(
        "cv.rtf",
        br"{\rtf1\ansi Bachelor of Civil Engineering with a final project in structural design.}",
    )
    assert reading.degree == "masters"
    assert "civil engineering" in reading.field


def test_a_photo_of_a_cv_is_read():
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 64)
    image = Image.new("RGB", (1800, 400), "white")
    ImageDraw.Draw(image).text(
        (40, 140),
        "Master of Science in Computer Science, graduated 2024.",
        fill="black",
        font=font,
    )
    payload = io.BytesIO()
    image.save(payload, format="JPEG", quality=90)
    reading = read_cv("scan.jpg", payload.getvalue())
    assert reading.degree == "phd"
    assert reading.reason == "completed-master"
    assert "computer science" in reading.field


def test_civil_engineering_stays_one_department():
    reading = interpret_cv(
        "Bachelor of Civil Engineering with a final project in structural design and construction management."
    )
    assert reading.degree == "masters"
    assert reading.reason == "completed-bachelor"
    assert reading.field.startswith("civil engineering")
    assert reading.field != "engineering"
