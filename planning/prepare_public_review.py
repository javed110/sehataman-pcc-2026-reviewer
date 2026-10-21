"""Prepare a contact-redacted reviewer copy without publishing or changing sources.

Owner-workspace helper: it requires the supplied private application contact.
Run once into an empty .local/public-reviewer-stage/SehatAman_PCC2026 directory.
The staged copy has no private Git history, credentials, keys or persisted store.
"""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit
from zipfile import ZipFile

from lxml import etree as E

try:
    from .release_project import files, ROOT
except ImportError:
    from release_project import files, ROOT


PUBLIC_URL = "https://github.com/javed110/sehataman-pcc-2026-reviewer"
PRIVATE_URL = "https://github.com/javed110/sehataman-pcc-2026"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS = {"w": W[1:-1]}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![A-Za-z0-9])(?:\+92|0092|0)[ -]*3\d{2}[ -]*\d{7}(?![A-Za-z0-9])")
URL = re.compile(r"https?://[^\s<>\"'()]+")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def forbidden_path(path):
    return (any(p.startswith(".local") or p == ".git" or p in
                ("protected", "issuer-secrets", "__pycache__") for p in path.parts)
            or path.name.startswith("~$")
            or path.name in ("keys.json", "demo-accounts.json", "audit-head.json")
            or path.suffix.lower() in (".key", ".sqlite", ".sqlite3", ".db", ".pyc"))


def private_journal_material(path):
    """Keep private journal preparation out even if the release allowlist broadens."""
    parts = path.parts
    return bool(parts and (parts[0].casefold() == "jcpsp_submission"
                or (len(parts) > 1 and parts[0].casefold() == "planning"
                    and parts[1].casefold().startswith("build_jcpsp"))))


def cell_text(cell):
    return "".join(cell.itertext())


def contact_cell(root, name):
    matches = []
    for row in root.findall(".//w:tr", NS):
        cells = row.findall("w:tc", NS)
        if len(cells) == 4 and cell_text(cells[1]).strip() == name:
            matches.append(cells[3])
    assert len(matches) == 1, "Expected exactly one named team contact cell"
    return matches[0]


def redact_word(raw, supplied):
    with ZipFile(BytesIO(raw)) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
        entries = archive.infolist()
    root = E.fromstring(parts["word/document.xml"])
    before = deepcopy(root)
    cell = contact_cell(root, "Humaira Zubair")
    for value in supplied:
        assert value in cell_text(cell), "Private contact must be retained in source Word"
    paragraphs = cell.findall("w:p", NS)
    assert paragraphs
    paragraph = paragraphs[0]
    exemplar = paragraph.find("w:r/w:rPr", NS)
    for child in list(paragraph):
        if child.tag != W + "pPr":
            paragraph.remove(child)
    for extra in paragraphs[1:]:
        cell.remove(extra)
    run = E.SubElement(paragraph, W + "r")
    if exemplar is not None:
        run.append(deepcopy(exemplar))
    for index, line in enumerate(("Email: Withheld in public copy", "Phone: Withheld in public copy")):
        if index:
            E.SubElement(run, W + "br")
        E.SubElement(run, W + "t").text = line
    # Prove that no other document subtree was edited.
    old_cell = contact_cell(before, "Humaira Zubair")
    old_cell.getparent().replace(old_cell, deepcopy(cell))
    assert E.tostring(before) == E.tostring(root)
    parts["word/document.xml"] = E.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for entry in entries:
            archive.writestr(entry, parts[entry.filename])
    with ZipFile(BytesIO(output.getvalue())) as archive:
        assert archive.testzip() is None
        with ZipFile(BytesIO(raw)) as original:
            assert archive.namelist() == original.namelist()
            assert all(archive.read(n) == original.read(n) for n in archive.namelist()
                       if n != "word/document.xml")
    return output.getvalue()


def main():
    stage_parent = (ROOT / '.local' / (sys.argv[1] if len(sys.argv)>1 else 'public-reviewer-stage')).resolve()
    assert stage_parent.is_relative_to((ROOT / '.local').resolve())
    stage = (stage_parent / "SehatAman_PCC2026").resolve()
    assert stage.is_relative_to(ROOT.resolve()) and stage.parent == stage_parent
    assert not stage.exists(), "Refusing to overwrite an existing review stage"
    team_path = ROOT / "planning/application_team_details.json"
    word_path = ROOT / "docs/SehatAman_PCC26_Concept_Note.docx"
    private_team_bytes, private_word_bytes = team_path.read_bytes(), word_path.read_bytes()
    team = json.loads(private_team_bytes)
    supplied = []
    supplied_members = []
    for member in team["members"]:
        actual = [member[key] for key in ("email", "phone") if member.get(key)]
        if actual:
            supplied_members.append(member["name"])
            supplied.extend(actual)
            for key in ("email", "phone"):
                if member.get(key):
                    member[key] = "Withheld from public copy"
            member["public_contact_note"] = "Supplied privately; withheld from public copy"
    assert supplied_members == ["Humaira Zubair"], "Review redaction scope if more contacts are supplied"
    assert supplied, "This helper requires the owner-held private application copy"
    source_files = [source for source in files()
                    if not private_journal_material(source.relative_to(ROOT))]
    for source in source_files:
        relative = source.relative_to(ROOT)
        assert not forbidden_path(relative) and not private_journal_material(relative), str(relative)
        assert source.resolve().is_relative_to(ROOT.resolve()) and not source.is_symlink()
    stage.mkdir(parents=True)
    for source in source_files:
        target = stage / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    (stage / "planning/application_team_details.json").write_text(
        json.dumps(team, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (stage / "docs/SehatAman_PCC26_Concept_Note.docx").write_bytes(redact_word(private_word_bytes, supplied))
    readme_path = stage / "README.md"
    readme = readme_path.read_text(encoding="utf-8")
    readme = readme.replace("# SehatAman PCC 2026", "# SehatAman PCC 2026 public reviewer copy", 1)
    private_link = "The existing [application repository](" + PRIVATE_URL + ") remains private."
    assert readme.count(private_link) == 1, "Review the private repository link before staging"
    readme = readme.replace(private_link, "The owner retains a separate private application copy; it is not required to review this contact-redacted package.")
    readme += ("\nThis package is the public, contact-redacted reviewer copy. See "
               "[public-copy details](docs/PUBLIC_REVIEW_COPY.txt) and "
               "`planning/reviewer_publication.json` for publication and verification status. "
               "Public material delivery does not deploy the app.\n")
    readme_path.write_text(readme, encoding="utf-8")
    readme_txt_path = stage / "README.txt"
    readme_txt = readme_txt_path.read_text(encoding="utf-8")
    readme_txt = readme_txt.replace(
        "Deployment remains deferred. A private source/materials repository was separately\nauthorized at " + PRIVATE_URL + "; this does not host the app.",
        "Deployment remains deferred. The owner retains a separate private application\ncopy; it is not required to review this public, contact-redacted package.")
    assert PRIVATE_URL not in readme_txt.replace(PUBLIC_URL, ""), "Private repository URL remains in public README.txt"
    readme_txt += "\nPUBLIC REVIEW COPY\nPersonal contacts are redacted in this copy. See docs/PUBLIC_REVIEW_COPY.txt.\n"
    readme_txt_path.write_text(readme_txt, encoding="utf-8")
    public_note = (
        "SEHATAMAN PUBLIC REVIEW COPY\n\n"
        "Intended reviewer destination: " + PUBLIC_URL + "\n"
        "Consult planning/reviewer_publication.json for publication and verification status.\n"
        "This package provides code, documents, evidence and recordings, not a running\n"
        "public app. Localhost instructions require a local server on the same computer.\n\n"
        "Personal contact values supplied by the team are withheld from this public copy.\n"
        "Humaira's email and phone were supplied privately and remain in the owner's\n"
        "private application note; they are redacted in this Word note and team JSON.\n"
        "Genuinely missing contacts and Tehreem's exact MS title remain pending. Confirmed\n"
        "names, roles and academic details remain user supplied. The retained original\n"
        "template is blank. No applicant signature or application submission is added.\n\n"
        "No open-source licence, IP ownership conclusion, patent or institutional\n"
        "endorsement is asserted. Public visibility alone is not a licence grant.\n"
        "All application entities and verification outcomes are synthetic. The local\n"
        "OS and protected keys are trusted; there is no live PMDC/NADRA integration,\n"
        "production TLS service, clinical validation or security certification.\n"
        "Stakeholder/domain and commercial market-gap validation remain pending.\n"
        "Recordings capture actual earlier interface copy; core access rules remain.\n"
        "No deployment, submission, reviewer invitation or email is authorized here.\n"
    )
    (stage / "docs/PUBLIC_REVIEW_COPY.txt").write_text(public_note, encoding="utf-8")
    findings, urls, scanned_text, scanned_xml = [], set(), 0, 0
    for path in sorted(stage.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(stage)
        assert not forbidden_path(relative) and not private_journal_material(relative), str(relative)
        raw = path.read_bytes()
        for value in supplied:
            if any(value.encode(encoding) in raw for encoding in ("utf-8", "utf-16le")):
                findings.append({"path":relative.as_posix(), "kind":"known_contact_binary"})
        parts = []
        if path.suffix.lower() == ".docx":
            with ZipFile(BytesIO(raw)) as archive:
                parts = [(name, archive.read(name).decode("utf-8")) for name in archive.namelist()
                         if name.endswith((".xml", ".rels"))]
                scanned_xml += len(parts)
                for name, content in parts:
                    if name.endswith(".rels"):
                        relationships = E.fromstring(content.encode("utf-8"))
                        for relationship in relationships:
                            if relationship.get("Type", "").endswith("/hyperlink"):
                                target = relationship.get("Target", "")
                                urls.add(target)
                                assert urlsplit(target).hostname in ("github.com", "pmdc.pk", "www.pmdc.pk"), "Unexpected concept-note hyperlink host"
                    if name == "word/document.xml":
                        document = E.fromstring(content.encode("utf-8"))
                        instructions = " ".join(document.xpath("//w:instrText/text()", namespaces=NS))
                        for target in URL.findall(instructions):
                            urls.add(target)
                            assert urlsplit(target).hostname in ("github.com", "pmdc.pk", "www.pmdc.pk"), "Unexpected concept-note field-link host"
        elif path.suffix.lower() not in (".jpg", ".png", ".mp4"):
            try:
                parts = [("", raw.decode("utf-8-sig"))]
                scanned_text += 1
            except UnicodeDecodeError:
                findings.append({"path":relative.as_posix(), "kind":"unexpected_non_text_file"})
        for part, content in parts:
            for kind, pattern in (("email", EMAIL), ("phone", PHONE)):
                if pattern.search(content):
                    findings.append({"path":relative.as_posix(), "part":part, "kind":kind})
            if any(value in content for value in supplied):
                findings.append({"path":relative.as_posix(), "part":part, "kind":"known_contact_text"})
            if relative.parts[0] == "docs" or relative.name.startswith("README"):
                # XML schema/namespace URLs are not reviewer-facing hyperlinks.
                if path.suffix.lower() != ".docx":
                    urls.update(URL.findall(content))
    assert not findings, json.dumps(findings)
    assert not any("openai" in value.lower() or "chatgpt" in value.lower() for value in urls), "Disallowed reviewer-facing URL"
    assert team_path.read_bytes() == private_team_bytes and word_path.read_bytes() == private_word_bytes
    with ZipFile(BytesIO(word_path.read_bytes())) as archive:
        private_text = "".join(E.fromstring(archive.read("word/document.xml")).itertext())
        assert all(value in private_text for value in supplied)
    rows = []
    differences = []
    for path in sorted(stage.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(stage)
        raw = path.read_bytes()
        rows.append({"path":relative.as_posix(), "bytes":len(raw), "sha256":sha(raw)})
        source = ROOT / relative
        if not source.exists() or source.read_bytes() != raw:
            differences.append(relative.as_posix())
    manifest = {"application":"SehatAman", "version":"0.5.0", "copy":"public contact-redacted reviewer copy",
                "reviewer_destination":PUBLIC_URL, "publication_status":"See planning/reviewer_publication.json",
                "all_app_fixtures_synthetic":True, "personal_contacts_redacted":True,
                "excluded":["private Git history", "local homes", "credentials", "keys", "sessions", "databases", "Office lock files", "JCPSP_Submission/", "planning/build_jcpsp*"],
                "files":rows}
    manifest_text = json.dumps(manifest, indent=2) + "\n"
    (stage / "PROJECT_MANIFEST.json").write_text(manifest_text, encoding="utf-8")
    assert not EMAIL.search(manifest_text) and not PHONE.search(manifest_text)
    assert not any(value in manifest_text for value in supplied)
    assert not any("openai" in value.lower() or "chatgpt" in value.lower()
                   for value in URL.findall(manifest_text))
    scanned_text += 1
    report = {"stage":str(stage), "copied_allowlisted_files":len(source_files), "content_files":len(rows),
              "total_files_including_manifest":len(rows)+1, "private_contacts_retained":True,
              "private_source_files_unchanged":True, "redacted_member_count":len(supplied_members),
              "contact_scan":"passed", "scan_text_files":scanned_text, "scan_docx_xml_parts":scanned_xml,
              "prohibited_path_scan":"passed", "reviewer_url_scan":"passed", "reviewer_urls":sorted(urls),
              "files_different_from_root":differences+["PROJECT_MANIFEST.json"],
              "published":False, "deployed":False, "submitted":False}
    (stage_parent / "PUBLIC_STAGE_SCAN.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
