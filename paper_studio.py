#!/usr/bin/env python3
"""FolioMind: a local-first PDF folder summarizer and study workspace for Linux."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import fitz  # PyMuPDF
import keyring
import requests
from PySide6.QtCore import QObject, Qt, QThread, Signal, QSettings, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont, QIcon, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QStackedWidget, QTextBrowser, QToolBar, QVBoxLayout, QWidget,
)

APP_NAME = "FolioMind"
KEYRING_SERVICE = "foliomind"
HF_CHAT_URL = "https://router.huggingface.co/v1/chat/completions"
HF_AUTH_URL = "https://huggingface.co/oauth/authorize"
HF_TOKEN_URL = "https://huggingface.co/oauth/token"
MAX_CHUNK_CHARS = 18_000


def asset_path(name: str) -> str:
    """Locate bundled artwork both in source and the one-file executable."""
    return str(Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / name)


def natural_key(value: str):
    return [int(piece) if piece.isdigit() else piece.casefold() for piece in re.split(r"(\d+)", value)]


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "summary"


def markdown_toc(markdown: str) -> str:
    """Produce a Markdown TOC whose anchors work in common HTML/PDF renderers."""
    links = []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,3})\s+(.+?)\s*$", line)
        if not match:
            continue
        level, title = len(match.group(1)), re.sub(r"[*_`]", "", match.group(2))
        anchor = safe_slug(title)
        links.append("  " * (level - 1) + f"- [{title}](#{anchor})")
    return "## Contents\n\n" + "\n".join(links) + "\n\n" if links else ""


class ExtractWorker(QObject):
    progress = Signal(str)
    finished = Signal(dict, list)

    def __init__(self, files: list[Path], cache_dir: Path):
        super().__init__()
        self.files = files
        self.cache_path = cache_dir / "extraction-cache.json"

    @staticmethod
    def _skip_page(text: str, page_number: int) -> bool:
        """Avoid sending navigational/reference pages to the model."""
        first = text[:700].casefold()
        markers = ("table of contents", "contents", "indice", "indice generale", "index", "indice analitico", "bibliography", "references", "riferimenti bibliografici")
        return page_number > 0 and any(marker in first for marker in markers) and len(text) < 4_000

    def _load_cache(self):
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"files": {}}

    def _save_cache(self, cache):
        self.cache_path.parent.mkdir(exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.cache_path)

    def run(self):
        documents, warnings, cache = {}, [], self._load_cache()
        for pdf in self.files:
            fingerprint = f"{pdf.stat().st_mtime_ns}:{pdf.stat().st_size}"
            saved = cache["files"].get(str(pdf))
            if saved and saved.get("fingerprint") == fingerprint and saved.get("complete"):
                documents[pdf.name] = "\n\n".join(saved.get("pages", [])); self.progress.emit(f"Resumed cached extraction: {pdf.name}"); continue
            self.progress.emit(f"Extracting pages: {pdf.name}")
            try:
                with fitz.open(pdf) as document:
                    pages = saved.get("pages", []) if saved and saved.get("fingerprint") == fingerprint else []
                    for number in range(len(pages), len(document)):
                        text = re.sub(r"\n{3,}", "\n\n", document[number].get_text("text")).strip()
                        if text and not self._skip_page(text, number): pages.append(f"[Page {number + 1}]\n{text}")
                        else: pages.append("")
                        cache["files"][str(pdf)] = {"fingerprint": fingerprint, "pages": pages, "complete": False}
                        self._save_cache(cache)
                        self.progress.emit(f"{pdf.name}: page {number + 1}/{len(document)}")
                text = "\n\n".join(page for page in pages if page).strip()
                if len(text) < 100:
                    warnings.append(f"{pdf.name}: little selectable text (run OCRmyPDF, then retry).")
                documents[pdf.name] = text
                cache["files"][str(pdf)] = {"fingerprint": fingerprint, "pages": pages, "complete": True}
                self._save_cache(cache)
            except Exception as exc:
                warnings.append(f"{pdf.name}: {exc}")
        self.finished.emit(documents, warnings)


class SummaryWorker(QObject):
    progress = Signal(str)
    chunk = Signal(str)
    failed = Signal(str)
    finished = Signal(str)

    def __init__(self, documents: dict[str, str], prompt: str, token: str, model: str, cache_path: Path):
        super().__init__()
        self.documents, self.prompt, self.token, self.model, self.cache_path = documents, prompt, token, model, cache_path

    def _call(self, messages: list[dict]) -> str:
        response = requests.post(HF_CHAT_URL, headers={"Authorization": f"Bearer {self.token}"},
            json={"model": self.model, "messages": messages, "temperature": 0.2}, timeout=180)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def run(self):
        try:
            try: notes = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): notes = {}
            partials = []
            for filename, body in self.documents.items():
                if not body:
                    continue
                for number, start in enumerate(range(0, len(body), MAX_CHUNK_CHARS), 1):
                    self.progress.emit(f"Reading {filename}, section {number}")
                    excerpt = body[start:start + MAX_CHUNK_CHARS]
                    key = hashlib.sha256(f"{filename}:{excerpt}".encode()).hexdigest()
                    if key not in notes:
                        notes[key] = self._call([
                            {"role": "system", "content": "Extract faithful facts and structure from the supplied PDF excerpt. Preserve the document name."},
                            {"role": "user", "content": f"Document: {filename}\n\n{excerpt}"},
                        ])
                        self.cache_path.parent.mkdir(exist_ok=True)
                        temporary = self.cache_path.with_suffix(".tmp"); temporary.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8"); temporary.replace(self.cache_path)
                    partials.append(notes[key])
            if not partials:
                raise RuntimeError("No extractable PDF text was found.")
            self.progress.emit("Writing final Markdown summary")
            final_prompt = f"""Create one coherent Markdown document from the source notes below.
User request: {self.prompt}

Use a # title and meaningful ## / ### headings. Do not use a Contents heading: the app inserts a clickable table of contents. Clearly distinguish individual PDFs when relevant. Reply with Markdown only.

Source notes:
{chr(10).join(partials)}"""
            result = self._call([{"role": "system", "content": "You are a precise multilingual document summarizer."}, {"role": "user", "content": final_prompt}])
            self.finished.emit(markdown_toc(result) + result)
        except Exception as exc:
            self.failed.emit(str(exc))


class QuizWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, text: str, token: str, model: str, category: str, mode: str):
        super().__init__(); self.text, self.token, self.model, self.category, self.mode = text, token, model, category, mode

    def run(self):
        try:
            if self.mode == "categories":
                instruction = "Return JSON only: {\"categories\":[{\"name\":string,\"subcategories\":[string]}]}. Find 3-10 important categories and their subcategories from this summary."
            else:
                scope = "all categories" if self.category == "All categories" else self.category
                instruction = f"Return JSON only: {{\"questions\":[{{\"question\":string,\"answers\":[string,string,string,string],\"correct_index\":0-3,\"explanation\":string}}]}}. Create 8 factual multiple-choice questions about {scope}. Exactly four answers each; exactly one correct. Match the summary language."
            response = requests.post(HF_CHAT_URL, headers={"Authorization": f"Bearer {self.token}"}, json={"model": self.model, "messages": [{"role":"system","content":"You create accurate educational materials."}, {"role":"user","content": instruction + "\n\n" + self.text[:90_000]}]}, timeout=180)
            response.raise_for_status(); raw = response.json()["choices"][0]["message"]["content"]
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            self.finished.emit(json.loads(raw))
        except Exception as exc: self.failed.emit(str(exc))


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    code = None
    state = None
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        type(self).code, type(self).state = query.get("code", [None])[0], query.get("state", [None])[0]
        self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
        self.wfile.write(b"<h2>FolioMind is connected.</h2><p>You may close this browser tab.</p>")
    def log_message(self, format, *args):
        pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("FolioMind", "FolioMind")
        self.folder: Path | None = None
        self.files: list[Path] = []
        self.documents: dict[str, str] = {}
        self.categories, self.questions, self.question_index = [], [], 0
        self.thread = None
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(asset_path("foliomind-icon.png")))
        self.resize(1600, 940)
        self._build_ui()
        self._apply_theme()

    def _build_ui(self):
        toolbar = QToolBar("Activity")
        toolbar.setOrientation(Qt.Vertical); toolbar.setMovable(False); toolbar.setIconSize(toolbar.iconSize())
        for label, tip, action in [("☰", "Explorer", self.choose_folder), ("⌕", "Search PDFs", self.focus_files), ("◷", "Summary history", self.show_history), ("⚙", "Settings", self.focus_ai)]:
            button = QAction(label, self); button.setToolTip(tip); button.triggered.connect(action); toolbar.addAction(button)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)

        self.file_list = QListWidget(); self.file_list.itemSelectionChanged.connect(self.preview_pdf_text)
        explorer = QWidget(); e = QVBoxLayout(explorer); e.setContentsMargins(12, 12, 8, 8)
        brand = QLabel(); brand.setPixmap(QPixmap(asset_path("foliomind-logo.png")).scaledToWidth(210, Qt.SmoothTransformation)); brand.setAlignment(Qt.AlignCenter); e.addWidget(brand)
        self.folder_label = QLabel("NO FOLDER OPEN")
        open_button = QPushButton("Open Folder"); open_button.clicked.connect(self.choose_folder)
        e.addWidget(self.folder_label); e.addWidget(open_button); e.addWidget(QLabel("PDF EXPLORER")); e.addWidget(self.file_list)

        self.tabs = QStackedWidget()
        self.source_view = QTextBrowser(); self.source_view.setOpenExternalLinks(True)
        source_page = QWidget(); s = QVBoxLayout(source_page); s.setContentsMargins(16, 12, 16, 12); s.addWidget(QLabel("SOURCE TEXT PREVIEW")); s.addWidget(self.source_view)
        self.markdown = QPlainTextEdit(); self.markdown.setPlaceholderText("Your generated Markdown summary will appear here.")
        markdown_page = QWidget(); m = QVBoxLayout(markdown_page); m.setContentsMargins(16, 12, 16, 12); m.addWidget(QLabel("SUMMARY.MD — EDITABLE")); m.addWidget(self.markdown)
        self.tabs.addWidget(source_page); self.tabs.addWidget(markdown_page)
        center = QWidget(); c = QVBoxLayout(center); c.setContentsMargins(0, 0, 0, 0)
        tabbar = QHBoxLayout(); source = QPushButton("Source"); source.clicked.connect(lambda: self.tabs.setCurrentIndex(0)); md = QPushButton("Summary.md"); md.clicked.connect(lambda: self.tabs.setCurrentIndex(1)); export = QPushButton("Export PDF"); export.clicked.connect(self.export_pdf)
        tabbar.addWidget(source); tabbar.addWidget(md); tabbar.addStretch(); tabbar.addWidget(export); c.addLayout(tabbar); c.addWidget(self.tabs)

        ai = QWidget(); a = QVBoxLayout(ai); a.setContentsMargins(12, 12, 12, 8)
        a.addWidget(QLabel("AI ASSISTANT")); a.addWidget(QLabel("Provider")); self.provider = QLineEdit("Hugging Face Inference Providers"); self.provider.setReadOnly(True); a.addWidget(self.provider)
        a.addWidget(QLabel("HUGGING FACE OAUTH CLIENT ID")); self.oauth_client_id = QLineEdit(self.settings.value("hf_oauth_client_id", os.environ.get("HF_OAUTH_CLIENT_ID", ""))); self.oauth_client_id.setPlaceholderText("Paste your public OAuth app client ID"); self.oauth_client_id.editingFinished.connect(self.save_oauth_client_id); a.addWidget(self.oauth_client_id)
        self.sign_in = QPushButton("Sign in with Hugging Face"); self.sign_in.clicked.connect(self.hf_oauth); a.addWidget(self.sign_in)
        a.addWidget(QLabel("Model")); self.model = QLineEdit("Qwen/Qwen2.5-7B-Instruct-1M:fastest"); a.addWidget(self.model)
        a.addWidget(QLabel("What should the summary do?")); self.prompt = QPlainTextEdit("Write a concise, well-structured summary in the original language. Use bullet points for key findings."); self.prompt.setMaximumHeight(170); a.addWidget(self.prompt)
        self.generate = QPushButton("Generate Summary"); self.generate.clicked.connect(self.generate_summary); a.addWidget(self.generate)
        a.addWidget(QLabel("STUDY QUIZ")); self.discover_categories = QPushButton("Find categories"); self.discover_categories.clicked.connect(lambda: self.run_quiz_worker("categories")); a.addWidget(self.discover_categories)
        self.category_picker = QComboBox(); self.category_picker.addItem("All categories"); a.addWidget(self.category_picker)
        self.create_quiz = QPushButton("Create 4-choice test"); self.create_quiz.clicked.connect(lambda: self.run_quiz_worker("questions")); a.addWidget(self.create_quiz)
        self.quiz_question = QLabel("Choose ‘Find categories’ after generating a summary."); self.quiz_question.setWordWrap(True); a.addWidget(self.quiz_question)
        self.answer_buttons = []
        for index in range(4):
            answer = QPushButton(""); answer.setVisible(False); answer.clicked.connect(lambda checked=False, i=index: self.answer_question(i)); a.addWidget(answer); self.answer_buttons.append(answer)
        a.addWidget(QLabel("OUTPUT")); self.status = QPlainTextEdit(); self.status.setReadOnly(True); self.status.setMaximumBlockCount(300); a.addWidget(self.status)

        splitter = QSplitter(); splitter.addWidget(explorer); splitter.addWidget(center); splitter.addWidget(ai); splitter.setSizes([270, 900, 330]); self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready — open a folder of PDFs.")

    def _apply_theme(self):
        self.setStyleSheet("""
          QMainWindow, QWidget { background:#1e1e1e; color:#d4d4d4; font: 13px 'Noto Sans'; }
          QToolBar { background:#181818; border:0; spacing:8px; padding:6px; } QToolButton { font-size:20px; padding:8px; }
          QPushButton { background:#2d2d2d; border:1px solid #454545; padding:7px 10px; border-radius:3px; } QPushButton:hover { background:#3a3d41; } QPushButton:default { background:#0e639c; }
          QPlainTextEdit, QTextBrowser, QListWidget, QLineEdit { background:#252526; border:1px solid #3c3c3c; border-radius:3px; padding:7px; selection-background-color:#264f78; }
          QLabel { color:#bbbbbb; font-weight:600; font-size:11px; } QSplitter::handle { background:#333; width:1px; }
        """)

    def log(self, text: str):
        self.status.appendPlainText(text); self.statusBar().showMessage(text)

    def choose_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose PDF folder", str(self.folder or Path.home()))
        if not chosen: return
        self.folder = Path(chosen); self.files = sorted(self.folder.glob("*.pdf"), key=lambda p: natural_key(p.name))
        self.file_list.clear(); self.file_list.addItems([file.name for file in self.files]); self.folder_label.setText(self.folder.name.upper())
        self.log(f"Found {len(self.files)} PDF(s), ordered alphanumerically.")
        self.extract_all()

    def extract_all(self):
        if not self.files: return
        self.thread = QThread(self); worker = ExtractWorker(self.files, self.folder / ".foliomind-cache"); worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run); worker.progress.connect(self.log); worker.finished.connect(self.extraction_finished)
        worker.finished.connect(self.thread.quit); worker.finished.connect(worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater); self.thread.start()

    def extraction_finished(self, docs, warnings):
        self.documents = docs
        for warning in warnings: self.log("Warning: " + warning)
        self.log("Local extraction complete.")
        if self.files: self.file_list.setCurrentRow(0)

    def preview_pdf_text(self):
        selected = self.file_list.currentItem()
        if selected:
            content = html.escape(self.documents.get(selected.text(), "Extracting…"))
            self.source_view.setHtml(f"<pre>{content}</pre>"); self.tabs.setCurrentIndex(0)

    def hf_oauth(self):
        client_id = self.oauth_client_id.text().strip()
        if not client_id:
            QMessageBox.information(self, "Hugging Face OAuth setup", "Create a public OAuth app in Hugging Face settings, paste its client ID here, then click Sign in. Use http://127.0.0.1:8765/callback as its redirect URI.")
            return
        verifier = secrets.token_urlsafe(64); challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode(); state = secrets.token_urlsafe(24)
        OAuthCallbackHandler.code = OAuthCallbackHandler.state = None
        parameters = {"client_id": client_id, "redirect_uri": "http://127.0.0.1:8765/callback", "response_type": "code", "scope": "openid profile inference-api", "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
        QDesktopServices.openUrl(QUrl(HF_AUTH_URL + "?" + urllib.parse.urlencode(parameters)))
        self.log("Browser opened: authorize Hugging Face to use inference.")
        def receive():
            server = HTTPServer(("127.0.0.1", 8765), OAuthCallbackHandler); server.timeout = 180
            while not OAuthCallbackHandler.code: server.handle_request()
            server.server_close()
            if OAuthCallbackHandler.state != state: self.log("OAuth state check failed."); return
            try:
                result = requests.post(HF_TOKEN_URL, data={"grant_type":"authorization_code", "code":OAuthCallbackHandler.code, "redirect_uri":"http://127.0.0.1:8765/callback", "client_id":client_id, "code_verifier":verifier}, timeout=30); result.raise_for_status()
                keyring.set_password(KEYRING_SERVICE, "huggingface", result.json()["access_token"]); self.log("Hugging Face connected securely.")
            except Exception as exc: self.log(f"OAuth failed: {exc}")
        threading.Thread(target=receive, daemon=True).start()

    def save_oauth_client_id(self):
        self.settings.setValue("hf_oauth_client_id", self.oauth_client_id.text().strip())

    def generate_summary(self):
        token = keyring.get_password(KEYRING_SERVICE, "huggingface")
        if not self.documents: QMessageBox.warning(self, APP_NAME, "Choose a folder and wait for extraction first."); return
        if not token: QMessageBox.warning(self, APP_NAME, "Sign in with Hugging Face first."); return
        self.generate.setEnabled(False); self.thread = QThread(self); worker = SummaryWorker(self.documents, self.prompt.toPlainText(), token, self.model.text(), self.folder / ".foliomind-cache" / "knowledge-notes.json"); worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run); worker.progress.connect(self.log); worker.failed.connect(lambda message: QMessageBox.critical(self, "Summary failed", message)); worker.finished.connect(self.summary_ready)
        for signal in (worker.finished, worker.failed): signal.connect(self.thread.quit); signal.connect(worker.deleteLater)
        self.thread.finished.connect(lambda: self.generate.setEnabled(True)); self.thread.finished.connect(self.thread.deleteLater); self.thread.start()

    def summary_ready(self, markdown):
        self.markdown.setPlainText(markdown); self.tabs.setCurrentIndex(1); self.log("Summary ready. Review Markdown, then export PDF.")

    def run_quiz_worker(self, mode: str):
        token = keyring.get_password(KEYRING_SERVICE, "huggingface")
        text = self.markdown.toPlainText() or "\n\n".join(self.documents.values())
        if not text or not token: QMessageBox.warning(self, APP_NAME, "Generate a summary and sign in first."); return
        self.log("Finding categories…" if mode == "categories" else "Writing test questions…")
        self.thread = QThread(self); worker = QuizWorker(text, token, self.model.text(), self.category_picker.currentText(), mode); worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run); worker.finished.connect(lambda result: self.quiz_ready(mode, result)); worker.failed.connect(lambda error: QMessageBox.critical(self, "Quiz failed", error))
        for signal in (worker.finished, worker.failed): signal.connect(self.thread.quit); signal.connect(worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater); self.thread.start()

    def quiz_ready(self, mode: str, result: dict):
        if mode == "categories":
            self.categories = result.get("categories", []); self.category_picker.clear(); self.category_picker.addItem("All categories")
            for category in self.categories: self.category_picker.addItem(category.get("name", "Untitled category"))
            self.log(f"Found {len(self.categories)} categories. Choose one or keep All categories.")
        else:
            self.questions, self.question_index = result.get("questions", []), 0; self.show_question()

    def show_question(self):
        if not self.questions: self.quiz_question.setText("No questions were returned."); return
        question = self.questions[self.question_index]; self.quiz_question.setText(f"{self.question_index + 1}/{len(self.questions)}  {question['question']}")
        for index, button in enumerate(self.answer_buttons): button.setText(question["answers"][index]); button.setVisible(True); button.setEnabled(True)

    def answer_question(self, index: int):
        question = self.questions[self.question_index]; correct = question.get("correct_index")
        for button in self.answer_buttons: button.setEnabled(False)
        self.log(("Correct. " if index == correct else "Incorrect. ") + question.get("explanation", ""))
        self.question_index = (self.question_index + 1) % len(self.questions)
        QTimer.singleShot(1800, self.show_question)

    def export_pdf(self):
        body = self.markdown.toPlainText().strip()
        if not body: QMessageBox.warning(self, APP_NAME, "Generate or write a Markdown summary first."); return
        command = shutil.which("markdown-pdf")
        if not command:
            local_converter = Path(__file__).parent / "node_modules" / ".bin" / "markdown-pdf"
            if local_converter.exists(): command = str(local_converter)
        if not command: QMessageBox.warning(self, APP_NAME, "markdown-pdf is not installed or on PATH. Run: npm install --global markdown-pdf"); return
        default = str((self.folder or Path.home()) / "folder-summary.pdf")
        output, _ = QFileDialog.getSaveFileName(self, "Export PDF", default, "PDF files (*.pdf)")
        if not output: return
        md_file = Path(output).with_suffix(".md"); md_file.write_text(body, encoding="utf-8")
        try:
            subprocess.run([command, str(md_file), "-o", output], check=True, capture_output=True, text=True)
            self.log(f"Exported {output}")
        except subprocess.CalledProcessError as exc:
            QMessageBox.critical(self, "PDF export failed", exc.stderr or str(exc))

    def focus_files(self): self.file_list.setFocus()
    def focus_ai(self): self.prompt.setFocus()
    def show_history(self): self.log("History will be added after the first MVP export workflow.")


if __name__ == "__main__":
    app = QApplication(sys.argv); app.setApplicationName(APP_NAME)
    window = MainWindow(); window.show(); sys.exit(app.exec())
