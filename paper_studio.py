#!/usr/bin/env python3
"""FolioMind: a local-first PDF folder summarizer and study workspace for Linux."""
from __future__ import annotations

import base64
import datetime
import faulthandler
import hashlib
import html
import json
import os
import random
import re
import secrets
import sys
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import fitz  # PyMuPDF
import keyring
import markdown as markdown_renderer
import requests
from weasyprint import HTML
from PySide6.QtCore import QObject, QPointF, Qt, QThread, Signal, QSettings, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont, QIcon, QPixmap, QTextCursor
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QCheckBox, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTextBrowser, QToolBar, QVBoxLayout, QWidget,
)

APP_NAME = "FolioMind"
APP_VERSION = "0.0.21"
KEYRING_SERVICE = "foliomind"
HF_CHAT_URL = "https://router.huggingface.co/v1/chat/completions"
HF_AUTH_URL = "https://huggingface.co/oauth/authorize"
HF_TOKEN_URL = "https://huggingface.co/oauth/token"
MAX_CHUNK_CHARS = 18_000
DEFAULT_SUMMARY_PROMPT = "Write a concise, well-structured summary in the original language. Use bullet points for key findings."

PROVIDERS = {
    "openrouter": {"label": "OpenRouter (free models)", "model": "openrouter/free"},
}

DEBUG_LOG_PATH: Path | None = None
DEBUG_LOG_LOCK = threading.Lock()
FAULT_LOG_FILE = None


def write_debug(message: str):
    """Record operational events locally without logging secrets or document contents."""
    if not DEBUG_LOG_PATH:
        return
    try:
        with DEBUG_LOG_LOCK:
            stamp = datetime.datetime.now().isoformat(timespec="seconds")
            with DEBUG_LOG_PATH.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{stamp}  {message}\n")
    except OSError:
        pass


def unhandled_exception(exception_type, exception, trace):
    write_debug("UNHANDLED PYTHON EXCEPTION\n" + "".join(traceback.format_exception(exception_type, exception, trace)))
    sys.__excepthook__(exception_type, exception, trace)

TEXT = {
    "English": {},
    "Italiano": {"Open Folder": "Apri cartella", "PDF EXPLORER": "ESPLORA PDF", "PDF VIEWER": "VISUALIZZATORE PDF", "SOURCE TEXT PREVIEW": "ANTEPRIMA TESTO", "Source text": "Testo sorgente", "Export PDF": "Esporta PDF", "AI ASSISTANT": "ASSISTENTE AI", "Connect to AI Assistant": "Connetti assistente AI", "AI Assistant Settings": "Impostazioni assistente AI", "Generate Summary": "Genera riassunto", "Find categories": "Trova categorie", "Create 4-choice test": "Crea test a 4 risposte", "Settings": "Impostazioni", "Appearance": "Aspetto", "Theme": "Tema", "Language": "Lingua", "Light": "Chiaro", "Dark": "Scuro", "Save": "Salva", "Cancel": "Annulla", "NO FOLDER OPEN": "NESSUNA CARTELLA APERTA", "PDF": "PDF", "SUMMARY.MD — EDITABLE": "SUMMARY.MD — MODIFICABILE", "Your generated Markdown summary will appear here.": "Il riassunto Markdown generato apparirà qui.", "Provider": "Provider", "Model": "Modello", "Load available models": "Carica modelli disponibili", "Choose a model": "Scegli un modello", "What should the summary do?": "Come deve essere il riassunto?", "STUDY QUIZ": "QUIZ DI STUDIO", "All categories": "Tutte le categorie", "Choose ‘Find categories’ after generating a summary.": "Scegli ‘Trova categorie’ dopo aver generato un riassunto.", "OUTPUT": "OUTPUT", "Ready — open a folder of PDFs.": "Pronto — apri una cartella di PDF.", "Search PDFs": "Cerca PDF", "Search a PDF name or text inside extracted PDFs…": "Cerca un nome PDF o testo nei PDF estratti…", "AI ASSISTANT CONNECTION": "CONNESSIONE ASSISTENTE AI", "HUGGING FACE OAUTH CLIENT ID": "ID CLIENT OAUTH HUGGING FACE", "Sign in with Hugging Face": "Accedi con Hugging Face", "API KEY": "CHIAVE API", "Save API key securely": "Salva la chiave API in modo sicuro", "HUGGING FACE ACCESS TOKEN (ALTERNATIVE TO OAUTH)": "TOKEN HUGGING FACE (ALTERNATIVA A OAUTH)", "Save Hugging Face token securely": "Salva il token Hugging Face in modo sicuro", "OPENAI-COMPATIBLE BASE URL": "URL BASE COMPATIBILE OPENAI", "Paste your public OAuth app client ID": "Incolla l'ID client della tua app OAuth pubblica", "Paste access token or API key, then save it securely": "Incolla token o chiave API, poi salvala in modo sicuro", "Load models or enter a model ID": "Carica modelli o inserisci un ID modello", "Provider API keys and OAuth tokens are stored in the Linux keyring. Account passwords are never collected.": "Le chiavi API e i token OAuth sono salvati nel portachiavi Linux. Le password non vengono mai richieste.", "Settings saved. Restart FolioMind to apply all language changes.": "Impostazioni salvate. Riavvia FolioMind per applicare tutte le modifiche della lingua.", "Connected: ": "Connesso: ", "Not connected: ": "Non connesso: ", " — text match": " — testo trovato", "Reading PDFs…": "Lettura dei PDF…", "Creating summary…": "Creazione del riassunto…", "Loading models…": "Caricamento modelli…", "Preparing quiz…": "Preparazione quiz…", "Write a concise, well-structured summary in the original language. Use bullet points for key findings.": "Scrivi un riassunto conciso e ben strutturato nella lingua originale. Usa un elenco puntato per i risultati principali."},
    "Deutsch": {"Open Folder": "Ordner öffnen", "PDF EXPLORER": "PDF-ÜBERSICHT", "PDF VIEWER": "PDF-ANSICHT", "SOURCE TEXT PREVIEW": "TEXTVORSCHAU", "Source text": "Quelltext", "Export PDF": "PDF exportieren", "AI ASSISTANT": "KI-ASSISTENT", "Connect to AI Assistant": "KI-Assistent verbinden", "AI Assistant Settings": "KI-Assistent-Einstellungen", "Generate Summary": "Zusammenfassung erstellen", "Find categories": "Kategorien finden", "Create 4-choice test": "Test mit 4 Antworten erstellen", "Settings": "Einstellungen", "Appearance": "Darstellung", "Theme": "Design", "Language": "Sprache", "Light": "Hell", "Dark": "Dunkel", "Save": "Speichern", "Cancel": "Abbrechen", "NO FOLDER OPEN": "KEIN ORDNER GEÖFFNET", "PDF": "PDF", "SUMMARY.MD — EDITABLE": "SUMMARY.MD — BEARBEITBAR", "Your generated Markdown summary will appear here.": "Ihre generierte Markdown-Zusammenfassung erscheint hier.", "Provider": "Anbieter", "Model": "Modell", "Load available models": "Verfügbare Modelle laden", "Choose a model": "Modell auswählen", "What should the summary do?": "Wie soll die Zusammenfassung aussehen?", "STUDY QUIZ": "LERNQUIZ", "All categories": "Alle Kategorien", "Choose ‘Find categories’ after generating a summary.": "Wählen Sie nach einer Zusammenfassung „Kategorien finden“.", "OUTPUT": "AUSGABE", "Ready — open a folder of PDFs.": "Bereit — öffnen Sie einen PDF-Ordner.", "Search PDFs": "PDFs suchen", "Search a PDF name or text inside extracted PDFs…": "PDF-Name oder Text in extrahierten PDFs suchen…", "AI ASSISTANT CONNECTION": "KI-ASSISTENT-VERBINDUNG", "HUGGING FACE OAUTH CLIENT ID": "HUGGING FACE OAUTH-CLIENT-ID", "Sign in with Hugging Face": "Mit Hugging Face anmelden", "API KEY": "API-SCHLÜSSEL", "Save API key securely": "API-Schlüssel sicher speichern", "HUGGING FACE ACCESS TOKEN (ALTERNATIVE TO OAUTH)": "HUGGING-FACE-ZUGRIFFSTOKEN (ALTERNATIVE ZU OAUTH)", "Save Hugging Face token securely": "Hugging-Face-Token sicher speichern", "OPENAI-COMPATIBLE BASE URL": "OPENAI-KOMPATIBLE BASIS-URL", "Paste your public OAuth app client ID": "Client-ID Ihrer öffentlichen OAuth-App einfügen", "Paste access token or API key, then save it securely": "Zugriffstoken oder API-Schlüssel einfügen und sicher speichern", "Load models or enter a model ID": "Modelle laden oder Modell-ID eingeben", "Provider API keys and OAuth tokens are stored in the Linux keyring. Account passwords are never collected.": "API-Schlüssel und OAuth-Token werden im Linux-Schlüsselbund gespeichert. Kontopasswörter werden niemals abgefragt.", "Settings saved. Restart FolioMind to apply all language changes.": "Einstellungen gespeichert. Starten Sie FolioMind neu, um alle Sprachänderungen anzuwenden.", "Connected: ": "Verbunden: ", "Not connected: ": "Nicht verbunden: ", " — text match": " — Texttreffer", "Reading PDFs…": "PDFs werden gelesen…", "Creating summary…": "Zusammenfassung wird erstellt…", "Loading models…": "Modelle werden geladen…", "Preparing quiz…": "Quiz wird vorbereitet…", "Write a concise, well-structured summary in the original language. Use bullet points for key findings.": "Schreibe eine kurze, gut strukturierte Zusammenfassung in der Originalsprache. Verwende Aufzählungspunkte für die wichtigsten Erkenntnisse."},
}


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


def valid_summary(markdown: str) -> bool:
    """Reject provider error messages and tiny non-summary responses."""
    meaningful_lines = [line for line in markdown.splitlines() if line.strip()]
    return len(markdown.strip()) >= 500 and len(meaningful_lines) >= 8


def call_llm(provider: str, credential: str, model: str, messages: list[dict], endpoint: str = "") -> str:
    """Send one chat request through a provider's documented API."""
    if provider in ("openrouter", "huggingface", "openai", "compatible"):
        urls = {
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
            "huggingface": HF_CHAT_URL,
            "openai": "https://api.openai.com/v1/chat/completions",
            "compatible": endpoint.rstrip("/") + "/chat/completions" if not endpoint.rstrip("/").endswith("/chat/completions") else endpoint.rstrip("/"),
        }
        if not urls[provider] or (provider == "compatible" and not endpoint.strip()):
            raise RuntimeError("Enter the provider's OpenAI-compatible base URL in Settings.")
        response = requests.post(urls[provider], headers={"Authorization": f"Bearer {credential}"},
            json={"model": model, "messages": messages, "temperature": 0.2}, timeout=180)
        try: response.raise_for_status()
        except requests.HTTPError as exc: raise RuntimeError(f"{provider} returned HTTP {response.status_code}: {response.text[:700]}") from exc
        try:
            content = response.json()["choices"][0]["message"].get("content")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"{provider} returned an invalid chat response.") from exc
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"{provider} returned an empty response. The selected free model may be temporarily unavailable; retry or choose another free model.")
        return content
    if provider == "gemini":
        system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
        contents = [{"role": "user", "parts": [{"text": message["content"]}]} for message in messages if message["role"] != "system"]
        clean_model = model.removeprefix("models/")
        response = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent",
            headers={"x-goog-api-key": credential, "Content-Type": "application/json"},
            json={"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                  "generationConfig": {"temperature": 0.2}}, timeout=180)
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    if provider == "anthropic":
        system = "\n\n".join(message["content"] for message in messages if message["role"] == "system")
        chat = [{"role": message["role"], "content": message["content"]} for message in messages if message["role"] != "system"]
        response = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": credential, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": 4096, "temperature": 0.2, "system": system, "messages": chat}, timeout=180)
        response.raise_for_status()
        return "".join(block.get("text", "") for block in response.json()["content"] if block.get("type") == "text")
    raise RuntimeError("Unknown AI provider.")


def fetch_models(provider: str, credential: str, endpoint: str = "") -> list[str]:
    """Return models the connected account can use, when its API supports listing."""
    if provider == "openrouter":
        response = requests.get("https://openrouter.ai/api/v1/models", headers={"Authorization": f"Bearer {credential}"}, timeout=30)
        response.raise_for_status()
        free = [item["id"] for item in response.json().get("data", []) if str(item.get("pricing", {}).get("prompt")) == "0" and str(item.get("pricing", {}).get("completion")) == "0"]
        return sorted(set(["openrouter/free", *free]))
    if provider == "gemini":
        response = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": credential}, timeout=30)
        response.raise_for_status()
        models = response.json().get("models", [])
        return sorted(model["name"].removeprefix("models/") for model in models
                      if "generateContent" in model.get("supportedGenerationMethods", model.get("supportedActions", [])))
    if provider == "anthropic":
        response = requests.get("https://api.anthropic.com/v1/models",
            headers={"x-api-key": credential, "anthropic-version": "2023-06-01"}, timeout=30)
    else:
        urls = {
            "huggingface": "https://router.huggingface.co/v1/models",
            "openai": "https://api.openai.com/v1/models",
            "compatible": endpoint.rstrip("/") + "/models" if not endpoint.rstrip("/").endswith("/models") else endpoint.rstrip("/"),
        }
        if provider == "compatible" and not endpoint.strip():
            raise RuntimeError("Enter the provider's OpenAI-compatible base URL first.")
        response = requests.get(urls[provider], headers={"Authorization": f"Bearer {credential}"}, timeout=30)
    response.raise_for_status()
    return sorted({item["id"] for item in response.json().get("data", []) if item.get("id")})


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

    def __init__(self, documents: dict[str, str], prompt: str, provider: str, credential: str, model: str, endpoint: str, cache_path: Path):
        super().__init__()
        self.documents, self.prompt, self.provider, self.credential, self.model, self.endpoint, self.cache_path = documents, prompt, provider, credential, model, endpoint, cache_path

    def _call(self, messages: list[dict]) -> str:
        return call_llm(self.provider, self.credential, self.model, messages, self.endpoint)

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
            result = ""
            for attempt in range(1, 4):
                self.progress.emit(f"Writing final Markdown summary (attempt {attempt}/3)")
                try:
                    result = self._call([
                        {"role": "system", "content": "You are a precise multilingual document summarizer. Return only a detailed Markdown summary; never return moderation labels, safety classifications, or a one-line reply."},
                        {"role": "user", "content": final_prompt},
                    ])
                except RuntimeError as exc:
                    self.progress.emit(f"Final-summary attempt {attempt} failed: {exc}")
                    continue
                self.progress.emit(f"Final summary response received ({len(result)} characters)")
                if valid_summary(result):
                    self.finished.emit(markdown_toc(result) + result)
                    return
            raise RuntimeError("The selected AI model returned an incomplete final summary three times. Choose another free model and retry; the extracted notes are safely cached.")
        except Exception as exc:
            self.failed.emit(str(exc))


class QuizWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, text: str, provider: str, credential: str, model: str, endpoint: str, category: str, mode: str, question_count: int = 8, difficulty: str = "Medium"):
        super().__init__(); self.text, self.provider, self.credential, self.model, self.endpoint, self.category, self.mode, self.question_count, self.difficulty = text, provider, credential, model, endpoint, category, mode, question_count, difficulty

    def run(self):
        try:
            if self.mode == "categories":
                instruction = "Return JSON only: {\"categories\":[{\"name\":string,\"subcategories\":[string]}]}. Find 3-10 important categories and their subcategories from this summary."
            else:
                scope = "all categories" if self.category == "All categories" else self.category
                instruction = f"Return JSON only: {{\"questions\":[{{\"question\":string,\"answers\":[string,string,string,string],\"correct_index\":0-3,\"explanation\":string}}]}}. Create exactly {self.question_count} factual {self.difficulty.lower()}-difficulty multiple-choice questions about {scope}. Exactly four answers each; exactly one correct. Match the summary language."
            raw = call_llm(self.provider, self.credential, self.model, [{"role":"system","content":"You create accurate educational materials."}, {"role":"user","content": instruction + "\n\n" + self.text[:90_000]}], self.endpoint)
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
            self.finished.emit(json.loads(raw))
        except Exception as exc: self.failed.emit(str(exc))


class ModelListWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, provider: str, credential: str, endpoint: str):
        super().__init__(); self.provider, self.credential, self.endpoint = provider, credential, endpoint

    def run(self):
        try: self.finished.emit(fetch_models(self.provider, self.credential, self.endpoint))
        except Exception as exc: self.failed.emit(str(exc))


class VisualAnalysisWorker(QObject):
    """Render one selected PDF page and ask a vision-capable OpenRouter model about it."""

    finished = Signal(str, int, str)
    failed = Signal(str)

    def __init__(self, pdf_path: str, page_number: int, provider: str, credential: str, model: str, endpoint: str):
        super().__init__()
        self.pdf_path, self.page_number = pdf_path, page_number
        self.provider, self.credential, self.model, self.endpoint = provider, credential, model, endpoint

    def run(self):
        try:
            with fitz.open(self.pdf_path) as document:
                if self.page_number not in range(len(document)):
                    raise RuntimeError("The selected PDF page is unavailable.")
                page = document[self.page_number]
                image_bytes = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).tobytes("png")
                page_text = page.get_text("text").strip()
            image_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
            instruction = f"""Interpret the important visual material on page {self.page_number + 1} of this study PDF.
Describe diagrams, charts, illustrations, arrows, relationships, and their learning meaning in the document's language. Do not merely transcribe text already visible on the page. Write a concise factual note that can be included in a study summary.

Selectable page text for context:
{page_text}"""
            result = call_llm(self.provider, self.credential, self.model, [
                {"role": "system", "content": "You accurately interpret educational diagrams and document visuals."},
                {"role": "user", "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]},
            ], self.endpoint).strip()
            if len(result) < 40:
                raise RuntimeError("The model did not return a usable visual interpretation. Keep openrouter/free selected, or choose a vision-capable free model.")
            self.finished.emit(Path(self.pdf_path).name, self.page_number + 1, result)
        except Exception as exc:
            self.failed.emit(str(exc))


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


class BusyTextEdit(QPlainTextEdit):
    """A text editor with a small, non-blocking activity indicator inside it."""

    FRAMES = ("◐", "◓", "◑", "◒")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._frame = 0
        self._message = ""
        self._busy = QLabel(self.viewport())
        self._busy.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._busy.setStyleSheet(
            "background: rgba(14, 99, 156, 225); color: white; border-radius: 12px; "
            "padding: 5px 10px; font-weight: 600;"
        )
        self._busy.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(130)
        self._timer.timeout.connect(self._advance)

    def set_busy(self, active: bool, message: str = ""):
        self._message = message
        if active:
            self._frame = 0
            self._advance()
            self._busy.show()
            self._timer.start()
        else:
            self._timer.stop()
            self._busy.hide()

    def _advance(self):
        self._busy.setText(f"{self.FRAMES[self._frame]}  {self._message}")
        self._busy.adjustSize()
        self._frame = (self._frame + 1) % len(self.FRAMES)
        self._place_indicator()

    def _place_indicator(self):
        viewport = self.viewport()
        self._busy.move(
            max(8, (viewport.width() - self._busy.width()) // 2),
            max(8, (viewport.height() - self._busy.height()) // 2),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_indicator()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("FolioMind", "FolioMind")
        self.language = str(self.settings.value("language", "English"))
        self.folder: Path | None = None
        self.files: list[Path] = []
        self.documents: dict[str, str] = {}
        self.extracting = False
        self.extract_worker = None
        self.summary_worker = None
        self.summary_thread = None
        self.visual_worker = None
        self.visual_thread = None
        self.busy_operations: dict[str, str] = {}
        self.summary_save_timer = QTimer(self)
        self.summary_save_timer.setSingleShot(True)
        self.summary_save_timer.setInterval(700)
        self.summary_save_timer.timeout.connect(self.save_summary_draft)
        try: self.pdf_positions = json.loads(str(self.settings.value("pdf_positions", "{}")))
        except json.JSONDecodeError: self.pdf_positions = {}
        self.current_pdf_path, self.pending_pdf_path, self.loading_pdf = None, None, False
        self.categories, self.questions, self.question_index = [], [], 0
        self.quiz_answers: list[dict] = []
        self.thread = None
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(asset_path("foliomind-icon.png")))
        self.resize(1600, 940)
        self._build_ui()
        self._apply_theme()

    def t(self, text: str) -> str:
        return TEXT.get(self.language, {}).get(text, text)

    def _build_ui(self):
        toolbar = QToolBar("Activity")
        toolbar.setOrientation(Qt.Vertical); toolbar.setMovable(False); toolbar.setIconSize(toolbar.iconSize())
        for label, tip, action in [("☰", "Explorer", self.choose_folder), ("⌕", "Search PDFs", self.search_documents), ("◷", "Summary history", self.show_history), ("⚙", "Settings", self.open_settings)]:
            button = QAction(label, self); button.setToolTip(tip); button.triggered.connect(action); toolbar.addAction(button)
        self.addToolBar(Qt.LeftToolBarArea, toolbar)

        self.file_list = QListWidget(); self.file_list.itemSelectionChanged.connect(self.preview_pdf_text)
        explorer = QWidget(); e = QVBoxLayout(explorer); e.setContentsMargins(12, 12, 8, 8)
        brand = QLabel(); brand.setPixmap(QPixmap(asset_path("foliomind-logo.png")).scaledToWidth(210, Qt.SmoothTransformation)); brand.setAlignment(Qt.AlignCenter); e.addWidget(brand)
        self.folder_label = QLabel(self.t("NO FOLDER OPEN"))
        open_button = QPushButton(self.t("Open Folder")); open_button.clicked.connect(self.choose_folder)
        self.extract_button = QPushButton("Read PDFs"); self.extract_button.setEnabled(False); self.extract_button.clicked.connect(self.extract_all)
        e.addWidget(self.folder_label); e.addWidget(open_button); e.addWidget(self.extract_button); e.addWidget(QLabel(self.t("PDF EXPLORER"))); e.addWidget(self.file_list)

        self.tabs = QStackedWidget()
        self.pdf_document = QPdfDocument(self)
        self.pdf_view = QPdfView(); self.pdf_view.setDocument(self.pdf_document)
        self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage); self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.pdf_document.statusChanged.connect(self.pdf_loaded)
        self.pdf_view.pageNavigator().currentPageChanged.connect(self.remember_pdf_page)
        pdf_page = QWidget(); p = QVBoxLayout(pdf_page); p.setContentsMargins(16, 12, 16, 12); p.addWidget(QLabel(self.t("PDF VIEWER"))); p.addWidget(self.pdf_view)
        self.source_view = QTextBrowser(); self.source_view.setOpenExternalLinks(True)
        source_page = QWidget(); s = QVBoxLayout(source_page); s.setContentsMargins(16, 12, 16, 12); s.addWidget(QLabel(self.t("SOURCE TEXT PREVIEW"))); s.addWidget(self.source_view)
        self.markdown = QPlainTextEdit(); self.markdown.setPlaceholderText(self.t("Your generated Markdown summary will appear here.")); self.markdown.textChanged.connect(self.queue_summary_save)
        markdown_page = QWidget(); m = QVBoxLayout(markdown_page); m.setContentsMargins(16, 12, 16, 12); m.addWidget(QLabel(self.t("SUMMARY.MD — EDITABLE"))); m.addWidget(self.markdown)
        self.tabs.addWidget(pdf_page); self.tabs.addWidget(source_page); self.tabs.addWidget(markdown_page)
        center = QWidget(); c = QVBoxLayout(center); c.setContentsMargins(0, 0, 0, 0)
        tabbar = QHBoxLayout(); pdf = QPushButton("PDF"); pdf.clicked.connect(lambda: self.tabs.setCurrentIndex(0)); source = QPushButton(self.t("Source text")); source.clicked.connect(lambda: self.tabs.setCurrentIndex(1)); md = QPushButton("Summary.md"); md.clicked.connect(lambda: self.tabs.setCurrentIndex(2)); self.analyze_visual = QPushButton("Analyze visual page"); self.analyze_visual.clicked.connect(self.analyze_current_page); export = QPushButton(self.t("Export PDF")); export.clicked.connect(self.export_pdf)
        tabbar.addWidget(pdf); tabbar.addWidget(source); tabbar.addWidget(md); tabbar.addStretch(); tabbar.addWidget(self.analyze_visual); tabbar.addWidget(export); c.addLayout(tabbar); c.addWidget(self.tabs)

        ai = QWidget(); a = QVBoxLayout(ai); a.setContentsMargins(12, 12, 12, 8); self.ai_widget, self.ai_layout = ai, a
        a.addWidget(QLabel(self.t("AI ASSISTANT")))
        self.connect_ai = QPushButton(self.t("Connect to AI Assistant")); self.connect_ai.clicked.connect(self.open_settings); a.addWidget(self.connect_ai)
        self.ai_status = QLabel(); self.ai_status.setWordWrap(True); a.addWidget(self.ai_status)
        self.connection_panel = QWidget(); connection = QVBoxLayout(self.connection_panel); connection.setContentsMargins(0, 0, 0, 0)
        connection.addWidget(QLabel(self.t("Provider"))); self.provider = QComboBox()
        for provider_id, details in PROVIDERS.items(): self.provider.addItem(details["label"], provider_id)
        saved_provider = str(self.settings.value("provider", "openrouter")); self.provider.setCurrentIndex(max(0, self.provider.findData(saved_provider))); self.provider.currentIndexChanged.connect(self.provider_changed); connection.addWidget(self.provider)
        self.provider_help = QLabel(); self.provider_help.setWordWrap(True); connection.addWidget(self.provider_help)
        self.oauth_label = QLabel(self.t("HUGGING FACE OAUTH CLIENT ID")); connection.addWidget(self.oauth_label)
        self.oauth_client_id = QLineEdit(str(self.settings.value("hf_oauth_client_id", os.environ.get("HF_OAUTH_CLIENT_ID", "")))); self.oauth_client_id.setPlaceholderText(self.t("Paste your public OAuth app client ID")); self.oauth_client_id.editingFinished.connect(self.save_oauth_client_id); connection.addWidget(self.oauth_client_id)
        self.sign_in = QPushButton(self.t("Sign in with Hugging Face")); self.sign_in.clicked.connect(self.hf_oauth); connection.addWidget(self.sign_in)
        self.api_key_label = QLabel(self.t("API KEY")); connection.addWidget(self.api_key_label)
        self.api_key = QLineEdit(); self.api_key.setEchoMode(QLineEdit.EchoMode.Password); self.api_key.setPlaceholderText(self.t("Paste access token or API key, then save it securely")); connection.addWidget(self.api_key)
        self.save_api_key = QPushButton(self.t("Save API key securely")); self.save_api_key.clicked.connect(self.save_api_key_securely); connection.addWidget(self.save_api_key)
        self.endpoint_label = QLabel(self.t("OPENAI-COMPATIBLE BASE URL")); connection.addWidget(self.endpoint_label)
        self.endpoint = QLineEdit(str(self.settings.value("compatible_endpoint", ""))); self.endpoint.setPlaceholderText("https://api.example.com/v1"); self.endpoint.editingFinished.connect(self.save_provider_settings); connection.addWidget(self.endpoint)
        connection.addWidget(QLabel(self.t("Model"))); self.model = QLineEdit(); self.model.setPlaceholderText(self.t("Load models or enter a model ID")); self.model.editingFinished.connect(self.save_provider_settings); connection.addWidget(self.model)
        model_row = QHBoxLayout(); self.load_models = QPushButton(self.t("Load available models")); self.load_models.clicked.connect(self.load_available_models); self.model_picker = QComboBox(); self.model_picker.setPlaceholderText(self.t("Choose a model")); self.model_picker.textActivated.connect(self.select_model); model_row.addWidget(self.load_models); model_row.addWidget(self.model_picker, 1); connection.addLayout(model_row)
        self.provider_changed()
        self.connection_panel.hide(); a.addWidget(self.connection_panel)
        a.addWidget(QLabel(self.t("What should the summary do?"))); self.prompt = BusyTextEdit(self.t(DEFAULT_SUMMARY_PROMPT)); self.prompt.setMaximumHeight(170); a.addWidget(self.prompt)
        self.generate = QPushButton(self.t("Generate Summary")); self.generate.setEnabled(False); self.generate.clicked.connect(self.generate_summary); a.addWidget(self.generate)
        a.addWidget(QLabel(self.t("STUDY QUIZ"))); self.discover_categories = QPushButton(self.t("Find categories")); self.discover_categories.clicked.connect(lambda: self.run_quiz_worker("categories")); a.addWidget(self.discover_categories)
        self.category_picker = QComboBox(); self.category_picker.addItem(self.t("All categories")); a.addWidget(self.category_picker)
        quiz_options = QFormLayout(); self.quiz_count = QSpinBox(); self.quiz_count.setRange(3, 50); self.quiz_count.setValue(8); self.quiz_difficulty = QComboBox(); self.quiz_difficulty.addItems(["Easy", "Medium", "Hard"]); self.quiz_shuffle = QCheckBox("Shuffle questions and answers"); self.quiz_shuffle.setChecked(True)
        quiz_options.addRow("Questions", self.quiz_count); quiz_options.addRow("Difficulty", self.quiz_difficulty); a.addLayout(quiz_options); a.addWidget(self.quiz_shuffle)
        self.create_quiz = QPushButton(self.t("Create 4-choice test")); self.create_quiz.clicked.connect(lambda: self.run_quiz_worker("questions")); a.addWidget(self.create_quiz)
        self.quiz_question = QLabel(self.t("Choose ‘Find categories’ after generating a summary.")); self.quiz_question.setWordWrap(True); a.addWidget(self.quiz_question)
        self.answer_buttons = []
        for index in range(4):
            answer = QPushButton(""); answer.setVisible(False); answer.clicked.connect(lambda checked=False, i=index: self.answer_question(i)); a.addWidget(answer); self.answer_buttons.append(answer)
        self.next_question = QPushButton("Next question"); self.next_question.setVisible(False); self.next_question.clicked.connect(self.advance_question); a.addWidget(self.next_question)
        self.retry_missed = QPushButton("Retry missed questions"); self.retry_missed.setVisible(False); self.retry_missed.clicked.connect(self.retry_missed_questions); a.addWidget(self.retry_missed)
        self.restart_quiz = QPushButton("Restart quiz"); self.restart_quiz.setVisible(False); self.restart_quiz.clicked.connect(self.restart_current_quiz); a.addWidget(self.restart_quiz)
        self.export_quiz = QPushButton("Export quiz results"); self.export_quiz.setVisible(False); self.export_quiz.clicked.connect(self.export_quiz_results); a.addWidget(self.export_quiz)
        a.addWidget(QLabel(self.t("OUTPUT"))); self.status = QPlainTextEdit(); self.status.setReadOnly(True); self.status.setMaximumBlockCount(300); a.addWidget(self.status)

        ai_scroll = QScrollArea(); ai_scroll.setWidgetResizable(True); ai_scroll.setFrameShape(QFrame.Shape.NoFrame); ai_scroll.setWidget(ai)
        splitter = QSplitter(); splitter.addWidget(explorer); splitter.addWidget(center); splitter.addWidget(ai_scroll); splitter.setSizes([270, 900, 330]); self.setCentralWidget(splitter)
        self.statusBar().showMessage(self.t("Ready — open a folder of PDFs."))
        version_label = QLabel(f"v{APP_VERSION}")
        version_label.setStyleSheet("color:#858585; padding: 0 8px;")
        self.statusBar().addPermanentWidget(version_label)
        self.refresh_ai_connection_state()
        QTimer.singleShot(0, self.restore_last_folder)

    def _apply_theme(self):
        dark = str(self.settings.value("theme", "Dark")) == "Dark"
        colors = ("#1e1e1e", "#d4d4d4", "#181818", "#2d2d2d", "#454545", "#3a3d41", "#252526", "#3c3c3c", "#bbbbbb", "#333") if dark else ("#f6f6f6", "#202020", "#e7e7e7", "#ffffff", "#c9c9c9", "#eeeeee", "#ffffff", "#c9c9c9", "#404040", "#d4d4d4")
        bg, fg, toolbar, button, border, hover, field, field_border, label, handle = colors
        self.setStyleSheet(f"""
          QMainWindow, QWidget {{ background:{bg}; color:{fg}; font: 13px 'Noto Sans'; }}
          QToolBar {{ background:{toolbar}; border:0; spacing:8px; padding:6px; }} QToolButton {{ font-size:20px; padding:8px; }}
          QPushButton {{ background:{button}; border:1px solid {border}; padding:7px 10px; border-radius:3px; }} QPushButton:hover {{ background:{hover}; }} QPushButton:default {{ background:#0e639c; color:white; }}
          QPlainTextEdit, QTextBrowser, QListWidget, QLineEdit, QComboBox {{ background:{field}; border:1px solid {field_border}; border-radius:3px; padding:7px; selection-background-color:#264f78; }}
          QLabel {{ color:{label}; font-weight:600; font-size:11px; }} QSplitter::handle {{ background:{handle}; width:1px; }}
        """)

    def log(self, text: str):
        self.status.appendPlainText(text); self.statusBar().showMessage(text); write_debug(text)

    def summary_draft_path(self) -> Path | None:
        return self.folder / ".foliomind-cache" / "latest-summary.md" if self.folder else None

    def queue_summary_save(self):
        if self.folder:
            self.summary_save_timer.start()

    def save_summary_draft(self):
        path = self.summary_draft_path()
        if not path:
            return
        try:
            path.parent.mkdir(exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(self.markdown.toPlainText(), encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            self.log(f"Could not save summary draft: {exc}")

    def show_busy(self, operation: str, message: str):
        """Keep an animated indicator visible while any background task is active."""
        self.busy_operations[operation] = self.t(message)
        visible_message = list(self.busy_operations.values())[-1]
        self.prompt.set_busy(True, visible_message)

    def hide_busy(self, operation: str):
        self.busy_operations.pop(operation, None)
        if self.busy_operations:
            visible_message = list(self.busy_operations.values())[-1]
            self.prompt.set_busy(True, visible_message)
        else:
            self.prompt.set_busy(False)

    def choose_folder(self):
        chosen = QFileDialog.getExistingDirectory(self, "Choose PDF folder", str(self.folder or Path.home()))
        if not chosen: return
        self.open_folder(Path(chosen))

    def restore_last_folder(self):
        saved = str(self.settings.value("last_folder", "")).strip()
        if saved and Path(saved).is_dir():
            self.open_folder(Path(saved), restored=True)

    def open_folder(self, folder: Path, restored: bool = False):
        global DEBUG_LOG_PATH, FAULT_LOG_FILE
        self.folder = folder
        self.settings.setValue("last_folder", str(folder))
        debug_dir = self.folder / ".debug"
        try:
            debug_dir.mkdir(exist_ok=True)
            DEBUG_LOG_PATH = debug_dir / "foliomind.log"
            if FAULT_LOG_FILE:
                FAULT_LOG_FILE.close()
            FAULT_LOG_FILE = (debug_dir / "native-crash.log").open("a", encoding="utf-8")
            faulthandler.enable(FAULT_LOG_FILE, all_threads=True)
            write_debug(f"=== FolioMind v{APP_VERSION} session started; folder: {self.folder} ===")
        except OSError:
            DEBUG_LOG_PATH = None
        self.files = sorted((path for path in self.folder.iterdir() if path.is_file() and path.suffix.casefold() == ".pdf"), key=lambda p: natural_key(p.name))
        self.documents = {}; self.generate.setEnabled(False); self.extract_button.setEnabled(bool(self.files))
        self.file_list.clear(); self.file_list.addItems([file.name for file in self.files]); self.folder_label.setText(self.folder.name.upper())
        draft = self.summary_draft_path()
        try:
            self.markdown.setPlainText(draft.read_text(encoding="utf-8") if draft and draft.exists() else "")
        except OSError as exc:
            self.log(f"Could not restore saved summary: {exc}")
        self.log(f"Found {len(self.files)} PDF(s), ordered alphanumerically.")
        if not self.files:
            QMessageBox.information(self, APP_NAME, "This folder contains no PDF files. Choose the folder that directly contains your PDFs.")
            return
        if restored:
            self.log("Restored your last folder and saved Markdown draft. Press ‘Read PDFs’ only when you want to refresh the extracted text.")
        else:
            self.log("Folder ready. Press ‘Read PDFs’ when you want FolioMind to extract the text.")

    def extract_all(self):
        if not self.files or self.extracting: return
        self.extracting = True; self.extract_button.setEnabled(False); self.show_busy("extraction", "Reading PDFs…"); self.log("Starting local PDF extraction. Summary generation unlocks when this finishes.")
        self.thread = QThread(self); self.extract_worker = ExtractWorker(self.files, self.folder / ".foliomind-cache"); self.extract_worker.moveToThread(self.thread)
        self.thread.started.connect(self.extract_worker.run); self.extract_worker.progress.connect(self.log); self.extract_worker.finished.connect(self.extraction_finished)
        self.extract_worker.finished.connect(self.thread.quit); self.extract_worker.finished.connect(self.extract_worker.deleteLater); self.thread.finished.connect(self.thread.deleteLater); self.thread.start()

    def extraction_finished(self, docs, warnings):
        self.extracting = False; self.extract_worker = None; self.documents = docs; self.extract_button.setEnabled(True); self.hide_busy("extraction")
        for warning in warnings: self.log("Warning: " + warning)
        readable = sum(bool(text.strip()) for text in self.documents.values())
        self.generate.setEnabled(bool(readable))
        self.log(f"Local extraction complete: {readable}/{len(self.files)} PDF(s) have readable text.")
        if not readable:
            QMessageBox.warning(self, APP_NAME, "No readable text was extracted. For scanned PDFs, run OCRmyPDF first, then open the folder again.")
        if self.files: self.file_list.setCurrentRow(0)

    def preview_pdf_text(self):
        selected = self.file_list.currentItem()
        if selected:
            content = html.escape(self.documents.get(selected.text(), "Extracting…"))
            self.source_view.setHtml(f"<pre>{content}</pre>")
            source_file = next((path for path in self.files if path.name == selected.text()), None)
            if source_file:
                path_key = str(source_file)
                if path_key != self.current_pdf_path:
                    self.current_pdf_path, self.pending_pdf_path, self.loading_pdf = path_key, path_key, True
                    self.pdf_document.load(path_key)
                self.tabs.setCurrentIndex(0)

    def pdf_loaded(self, status):
        if status != QPdfDocument.Status.Ready or not self.pending_pdf_path: return
        path_key, page = self.pending_pdf_path, int(self.pdf_positions.get(self.pending_pdf_path, 0))
        self.pending_pdf_path = None
        def restore_position():
            if path_key == self.current_pdf_path:
                self.pdf_view.pageNavigator().jump(page, QPointF(0, 0), 0)
            self.loading_pdf = False
        QTimer.singleShot(0, restore_position)

    def remember_pdf_page(self, page: int):
        if self.current_pdf_path and not self.loading_pdf:
            self.pdf_positions[self.current_pdf_path] = page
            self.settings.setValue("pdf_positions", json.dumps(self.pdf_positions))

    def visual_notes_path(self) -> Path | None:
        return self.folder / ".foliomind-cache" / "visual-notes.json" if self.folder else None

    def load_visual_notes(self) -> dict[str, list[dict]]:
        path = self.visual_notes_path()
        if not path:
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def analyze_current_page(self):
        provider, credential = self.provider_id(), self.active_credential()
        if self.summary_thread and self.summary_thread.isRunning():
            QMessageBox.information(self, APP_NAME, "A summary is being created. Analyze visual pages after it finishes.")
            return
        if not self.current_pdf_path:
            QMessageBox.information(self, APP_NAME, "Open a PDF and navigate to the page containing the diagram or picture first.")
            return
        if not credential:
            QMessageBox.warning(self, APP_NAME, "Connect OpenRouter in Settings before analyzing a visual page.")
            return
        if not self.model.text().strip():
            QMessageBox.warning(self, APP_NAME, "Choose openrouter/free or another vision-capable model in Settings first.")
            return
        if self.visual_thread and self.visual_thread.isRunning():
            return
        page_number = self.pdf_view.pageNavigator().currentPage()
        self.analyze_visual.setEnabled(False); self.show_busy("vision", "Analyzing visual page…")
        self.log(f"Analyzing visual material on {Path(self.current_pdf_path).name}, page {page_number + 1}…")
        self.visual_thread = QThread(self)
        self.visual_worker = VisualAnalysisWorker(self.current_pdf_path, page_number, provider, credential, self.model.text().strip(), self.endpoint.text().strip())
        self.visual_worker.moveToThread(self.visual_thread)
        self.visual_thread.started.connect(self.visual_worker.run)
        self.visual_worker.finished.connect(self.visual_analysis_ready)
        self.visual_worker.failed.connect(self.visual_analysis_failed)
        for signal in (self.visual_worker.finished, self.visual_worker.failed):
            signal.connect(self.visual_thread.quit)
            signal.connect(self.visual_worker.deleteLater)
        self.visual_thread.finished.connect(self.visual_thread_finished)
        self.visual_thread.finished.connect(self.visual_thread.deleteLater)
        self.visual_thread.start()

    def visual_thread_finished(self):
        self.visual_thread = None
        self.analyze_visual.setEnabled(True)

    def visual_analysis_ready(self, filename: str, page_number: int, description: str):
        notes = self.load_visual_notes()
        entries = [entry for entry in notes.get(filename, []) if entry.get("page") != page_number]
        entries.append({"page": page_number, "description": description})
        notes[filename] = sorted(entries, key=lambda entry: entry["page"])
        path = self.visual_notes_path()
        try:
            if path:
                path.parent.mkdir(exist_ok=True)
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(path)
        except OSError as exc:
            self.log(f"Could not save visual interpretation: {exc}")
        self.hide_busy("vision"); self.visual_worker = None
        self.log(f"Saved visual interpretation for {filename}, page {page_number}. It will be included in the next summary.")
        QMessageBox.information(self, "Visual interpretation", f"Page {page_number} — {filename}\n\n{description}")

    def visual_analysis_failed(self, error: str):
        self.hide_busy("vision"); self.visual_worker = None
        self.log("Visual analysis failed: " + error)
        QMessageBox.warning(self, "Visual analysis failed", error)

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

    def provider_id(self) -> str:
        return str(self.provider.currentData())

    def provider_changed(self):
        provider = self.provider_id()
        is_hf, is_custom = provider == "huggingface", provider == "compatible"
        self.oauth_label.setVisible(is_hf); self.oauth_client_id.setVisible(is_hf); self.sign_in.setVisible(is_hf)
        self.api_key_label.setVisible(True); self.api_key.setVisible(True); self.save_api_key.setVisible(True)
        self.api_key_label.setText(self.t("HUGGING FACE ACCESS TOKEN (ALTERNATIVE TO OAUTH)" if is_hf else "API KEY"))
        self.save_api_key.setText(self.t("Save Hugging Face token securely" if is_hf else "Save API key securely"))
        self.load_models.setText("Load free models" if provider == "openrouter" else self.t("Load available models"))
        self.endpoint_label.setVisible(is_custom); self.endpoint.setVisible(is_custom)
        self.provider_help.setText("Create a free OpenRouter API key, paste it below, then choose a free model. Your account password is never requested or stored.")
        saved_model = str(self.settings.value(f"model_{provider}", PROVIDERS[provider]["model"]))
        if provider == "huggingface" and saved_model == "Qwen/Qwen2.5-7B-Instruct-1M:fastest": saved_model = PROVIDERS[provider]["model"]
        self.model.setText(saved_model)
        self.model_picker.clear()
        self.settings.setValue("provider", provider)

    def save_provider_settings(self):
        provider = self.provider_id()
        self.settings.setValue(f"model_{provider}", self.model.text().strip())
        if provider == "compatible": self.settings.setValue("compatible_endpoint", self.endpoint.text().strip())

    def save_api_key_securely(self):
        provider, secret = self.provider_id(), self.api_key.text().strip()
        if not secret:
            QMessageBox.warning(self, APP_NAME, "Paste an access token or API key first.")
            return
        try:
            keyring.set_password(KEYRING_SERVICE, "huggingface" if provider == "huggingface" else f"provider:{provider}", secret)
            self.api_key.clear(); self.save_provider_settings(); self.refresh_ai_connection_state(); self.log(f"{PROVIDERS[provider]['label']} credential saved securely and will be reused next time. Choose Load available models.")
        except Exception as exc:
            QMessageBox.critical(self, "Could not save API key", str(exc))

    def active_credential(self) -> str | None:
        provider = self.provider_id()
        try:
            return keyring.get_password(KEYRING_SERVICE, "huggingface" if provider == "huggingface" else f"provider:{provider}")
        except Exception:
            return None

    def load_available_models(self):
        provider, credential = self.provider_id(), self.active_credential()
        if not credential:
            QMessageBox.warning(self, APP_NAME, "Connect the selected provider first, then load its models.")
            return
        self.save_provider_settings(); self.load_models.setEnabled(False); self.show_busy("models", "Loading models…"); self.model_picker.clear(); self.model_picker.addItem("Loading models…")
        self.model_thread = QThread(self)
        worker = ModelListWorker(provider, credential, self.endpoint.text().strip()); worker.moveToThread(self.model_thread)
        self.model_thread.started.connect(worker.run); worker.finished.connect(self.models_loaded); worker.failed.connect(self.models_failed)
        for signal in (worker.finished, worker.failed): signal.connect(self.model_thread.quit); signal.connect(worker.deleteLater)
        self.model_thread.finished.connect(lambda: self.load_models.setEnabled(True)); self.model_thread.finished.connect(self.model_thread.deleteLater); self.model_thread.start()

    def models_loaded(self, models: list[str]):
        self.hide_busy("models")
        current = self.model.text().strip(); self.model_picker.clear()
        if not models:
            self.model_picker.addItem("No usable chat models returned")
            self.log("This provider returned no chat models. Enter its model ID manually.")
            return
        self.model_picker.addItems(models)
        if current in models: self.model_picker.setCurrentText(current)
        self.log(f"Loaded {len(models)} available model(s). Choose one from the list.")

    def models_failed(self, error: str):
        self.hide_busy("models")
        self.model_picker.clear(); self.model_picker.addItem("Could not load models")
        self.log(f"Could not load available models: {error}")

    def select_model(self, model: str):
        if model and not model.startswith(("Loading", "No usable", "Could not")):
            self.model.setText(model); self.save_provider_settings(); self.log(f"Selected model: {model}")

    def generate_summary(self):
        provider, credential = self.provider_id(), self.active_credential()
        if self.summary_thread and self.summary_thread.isRunning():
            QMessageBox.information(self, APP_NAME, "A summary is already being created. Wait for it to finish.")
            return
        if self.visual_thread and self.visual_thread.isRunning():
            QMessageBox.information(self, APP_NAME, "Visual analysis is still running. Wait for it to finish before creating a summary.")
            return
        if self.extracting: QMessageBox.information(self, APP_NAME, "PDF extraction is still running. Wait for the ‘Local extraction complete’ message."); return
        if not self.folder or not self.files: QMessageBox.warning(self, APP_NAME, "Choose a folder that directly contains PDF files first."); return
        if not any(text.strip() for text in self.documents.values()): QMessageBox.warning(self, APP_NAME, "No readable PDF text is available. Wait for extraction or use OCR for scanned PDFs."); return
        if not credential: QMessageBox.warning(self, APP_NAME, "Connect the selected provider first: sign in to Hugging Face or save that provider's API key."); return
        if not self.model.text().strip(): QMessageBox.warning(self, APP_NAME, "Enter a model ID for the selected provider."); return
        documents_for_summary = dict(self.documents)
        for filename, entries in self.load_visual_notes().items():
            if filename in documents_for_summary and entries:
                visual_context = "\n\n".join(f"[Visual interpretation — page {entry['page']}]\n{entry['description']}" for entry in entries)
                documents_for_summary[filename] += "\n\n" + visual_context
        self.save_provider_settings(); self.generate.setEnabled(False); self.analyze_visual.setEnabled(False); self.show_busy("summary", "Creating summary…")
        self.summary_thread = QThread(self)
        self.summary_worker = SummaryWorker(documents_for_summary, self.prompt.toPlainText(), provider, credential, self.model.text().strip(), self.endpoint.text().strip(), self.folder / ".foliomind-cache" / "knowledge-notes.json")
        self.summary_worker.moveToThread(self.summary_thread)
        self.summary_thread.started.connect(self.summary_worker.run)
        self.summary_worker.progress.connect(self.log)
        self.summary_worker.failed.connect(self.summary_failed)
        self.summary_worker.finished.connect(self.summary_ready)
        for signal in (self.summary_worker.finished, self.summary_worker.failed):
            signal.connect(self.summary_thread.quit)
            signal.connect(self.summary_worker.deleteLater)
        self.summary_thread.finished.connect(self.summary_thread_finished)
        self.summary_thread.finished.connect(self.summary_thread.deleteLater)
        self.summary_thread.start()

    def summary_ready(self, markdown):
        self.hide_busy("summary")
        if not valid_summary(markdown):
            self.summary_failed("The provider returned an incomplete summary. Try another free model; your extracted notes remain cached.")
            return
        self.log(f"Processing final Markdown summary ({len(markdown)} characters).")
        self.markdown.setPlainText(markdown); self.save_summary_draft(); self.tabs.setCurrentIndex(2); self.log("Summary ready and saved. Review Markdown, then export PDF.")

    def summary_failed(self, message: str):
        self.hide_busy("summary"); self.log("Summary failed: " + message)
        QMessageBox.critical(self, "Summary failed", message)

    def summary_thread_finished(self):
        self.log("Summary worker stopped.")
        self.summary_worker = None
        self.summary_thread = None
        self.generate.setEnabled(bool(any(text.strip() for text in self.documents.values())))
        self.analyze_visual.setEnabled(True)

    def run_quiz_worker(self, mode: str):
        provider, credential = self.provider_id(), self.active_credential()
        text = self.markdown.toPlainText() or "\n\n".join(self.documents.values())
        if not text or not credential: QMessageBox.warning(self, APP_NAME, "Generate a summary and connect the selected provider first."); return
        if not self.model.text().strip(): QMessageBox.warning(self, APP_NAME, "Enter a model ID for the selected provider."); return
        self.show_busy("quiz", "Preparing quiz…"); self.log("Finding categories…" if mode == "categories" else "Writing test questions…")
        self.save_provider_settings(); self.thread = QThread(self); worker = QuizWorker(text, provider, credential, self.model.text().strip(), self.endpoint.text().strip(), self.category_picker.currentText(), mode, self.quiz_count.value(), self.quiz_difficulty.currentText()); worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run); worker.finished.connect(lambda result: self.quiz_ready(mode, result)); worker.failed.connect(self.quiz_failed)
        for signal in (worker.finished, worker.failed): signal.connect(self.thread.quit); signal.connect(worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater); self.thread.start()

    def quiz_ready(self, mode: str, result: dict):
        self.hide_busy("quiz")
        if mode == "categories":
            self.categories = result.get("categories", []); self.category_picker.clear(); self.category_picker.addItem("All categories")
            for category in self.categories: self.category_picker.addItem(category.get("name", "Untitled category"))
            self.log(f"Found {len(self.categories)} categories. Choose one or keep All categories.")
        else:
            self.questions = result.get("questions", [])
            self.prepare_quiz(self.questions)

    def quiz_failed(self, error: str):
        self.hide_busy("quiz")
        QMessageBox.critical(self, "Quiz failed", error)

    def prepare_quiz(self, questions: list[dict]):
        validated = []
        for question in questions:
            answers = question.get("answers", [])
            correct = question.get("correct_index")
            if len(answers) != 4 or not isinstance(correct, int) or correct not in range(4):
                continue
            item = {**question, "answers": list(answers), "correct_index": correct}
            if self.quiz_shuffle.isChecked():
                indexed_answers = list(enumerate(item["answers"]))
                random.shuffle(indexed_answers)
                item["answers"] = [answer for _, answer in indexed_answers]
                item["correct_index"] = next(index for index, (old_index, _) in enumerate(indexed_answers) if old_index == correct)
            validated.append(item)
        if self.quiz_shuffle.isChecked():
            random.shuffle(validated)
        self.questions, self.question_index, self.quiz_answers = validated, 0, []
        self.retry_missed.setVisible(False); self.restart_quiz.setVisible(False); self.export_quiz.setVisible(False)
        if not self.questions:
            self.quiz_question.setText("The AI did not return usable four-choice questions. Try again.")
            return
        self.log(f"Quiz ready: {len(self.questions)} question(s), {self.quiz_difficulty.currentText().lower()} difficulty.")
        self.show_question()

    def show_question(self):
        if not self.questions: self.quiz_question.setText("No questions were returned."); return
        question = self.questions[self.question_index]; self.quiz_question.setText(f"{self.question_index + 1}/{len(self.questions)}  {question['question']}")
        self.next_question.setVisible(False)
        for index, button in enumerate(self.answer_buttons):
            button.setText(question["answers"][index]); button.setVisible(True); button.setEnabled(True); button.setStyleSheet("")

    def answer_question(self, index: int):
        question = self.questions[self.question_index]; correct = question.get("correct_index")
        for button_index, button in enumerate(self.answer_buttons):
            button.setEnabled(False)
            if button_index == correct: button.setStyleSheet("background:#2e7d32; color:white;")
            elif button_index == index: button.setStyleSheet("background:#a1260d; color:white;")
        is_correct = index == correct
        self.quiz_answers.append({"question": question["question"], "selected": index, "correct": correct, "is_correct": is_correct, "explanation": question.get("explanation", ""), "answers": question["answers"]})
        self.log(("Correct. " if is_correct else "Incorrect. ") + question.get("explanation", ""))
        self.next_question.setText("Finish quiz" if self.question_index == len(self.questions) - 1 else "Next question")
        self.next_question.setVisible(True)

    def advance_question(self):
        self.question_index += 1
        if self.question_index >= len(self.questions):
            self.show_quiz_results()
        else:
            self.show_question()

    def show_quiz_results(self):
        correct = sum(1 for answer in self.quiz_answers if answer["is_correct"])
        total = len(self.quiz_answers)
        wrong = total - correct
        percentage = round((correct / total) * 100) if total else 0
        self.quiz_question.setText(f"Quiz complete — {correct}/{total} correct ({percentage}%). Wrong: {wrong}.")
        for button in self.answer_buttons: button.setVisible(False)
        self.next_question.setVisible(False); self.retry_missed.setVisible(bool(wrong)); self.restart_quiz.setVisible(True); self.export_quiz.setVisible(True)
        self.save_quiz_result(correct, total, percentage)
        self.log(f"Quiz complete: {correct}/{total} correct, {wrong} wrong.")

    def retry_missed_questions(self):
        missed_questions = [self.questions[index] for index, answer in enumerate(self.quiz_answers) if not answer["is_correct"]]
        self.prepare_quiz(missed_questions)

    def restart_current_quiz(self):
        self.prepare_quiz(self.questions)

    def quiz_results_path(self) -> Path | None:
        return self.folder / ".foliomind-cache" / "quiz-results.json" if self.folder else None

    def save_quiz_result(self, correct: int, total: int, percentage: int):
        path = self.quiz_results_path()
        if not path:
            return
        record = {"completed_at": datetime.datetime.now().isoformat(timespec="seconds"), "category": self.category_picker.currentText(), "difficulty": self.quiz_difficulty.currentText(), "correct": correct, "wrong": total - correct, "total": total, "percentage": percentage, "answers": self.quiz_answers}
        try:
            path.parent.mkdir(exist_ok=True)
            try: history = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError): history = []
            history.append(record)
            path.write_text(json.dumps(history[-100:], ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self.log(f"Could not save quiz result: {exc}")

    def export_quiz_results(self):
        if not self.quiz_answers:
            return
        correct = sum(1 for answer in self.quiz_answers if answer["is_correct"])
        lines = ["# FolioMind quiz results", "", f"**Score:** {correct}/{len(self.quiz_answers)} correct", ""]
        for number, answer in enumerate(self.quiz_answers, 1):
            state = "Correct" if answer["is_correct"] else "Incorrect"
            lines.extend([f"## {number}. {answer['question']}", f"- Your answer: {answer['answers'][answer['selected']]}", f"- Correct answer: {answer['answers'][answer['correct']]}", f"- Result: {state}", f"- Explanation: {answer['explanation']}", ""])
        default = str((self.folder or Path.home()) / "quiz-results.md")
        output, selected_filter = QFileDialog.getSaveFileName(self, "Export quiz results", default, "Markdown files (*.md);;PDF files (*.pdf)")
        if output:
            try:
                content = "\n".join(lines)
                if output.casefold().endswith(".pdf") or selected_filter.startswith("PDF"):
                    rendered = markdown_renderer.markdown(content, extensions=["extra", "sane_lists"])
                    HTML(string=f"<!doctype html><html><head><meta charset='utf-8'></head><body>{rendered}</body></html>").write_pdf(output)
                else:
                    Path(output).write_text(content, encoding="utf-8")
                self.log(f"Exported quiz results to {output}")
            except OSError as exc:
                QMessageBox.critical(self, "Quiz export failed", str(exc))

    def export_pdf(self):
        body = self.markdown.toPlainText().strip()
        if not body: QMessageBox.warning(self, APP_NAME, "Generate or write a Markdown summary first."); return
        default = str((self.folder or Path.home()) / "folder-summary.pdf")
        output, _ = QFileDialog.getSaveFileName(self, "Export PDF", default, "PDF files (*.pdf)")
        if not output: return
        try:
            md_file = Path(output).with_suffix(".md"); md_file.write_text(body, encoding="utf-8")
            rendered = markdown_renderer.markdown(body, extensions=["extra", "toc", "sane_lists"])
            css = """@page { size: A4; margin: 20mm; } body { font-family: sans-serif; line-height: 1.45; color: #202020; } h1,h2,h3 { color:#173f5f; } pre { white-space: pre-wrap; } a { color:#0e639c; text-decoration:none; }"""
            HTML(string=f"<!doctype html><html><head><meta charset='utf-8'><style>{css}</style></head><body>{rendered}</body></html>").write_pdf(output)
            self.log(f"Exported {output}")
        except Exception as exc:
            QMessageBox.critical(self, "PDF export failed", str(exc))

    def search_documents(self):
        dialog = QDialog(self); dialog.setWindowTitle(self.t("Search PDFs")); layout = QVBoxLayout(dialog)
        query = QLineEdit(); query.setPlaceholderText(self.t("Search a PDF name or text inside extracted PDFs…"))
        results = QListWidget()
        def update_results(text=""):
            results.clear(); needle = text.casefold().strip()
            for index, path in enumerate(self.files):
                body = self.documents.get(path.name, "").casefold()
                name_hit, text_hit = needle in path.name.casefold(), needle in body
                if not needle or name_hit or text_hit:
                    suffix = self.t(" — text match") if needle and text_hit and not name_hit else ""
                    item = QListWidgetItem(path.name + suffix); item.setData(Qt.UserRole, index); results.addItem(item)
        query.textChanged.connect(update_results); results.itemDoubleClicked.connect(lambda item: (self.file_list.setCurrentRow(item.data(Qt.UserRole)), dialog.accept()))
        layout.addWidget(query); layout.addWidget(results); update_results(); query.setFocus(); dialog.resize(480, 360); dialog.exec()

    def open_settings(self):
        dialog = QDialog(self); dialog.setWindowTitle("FolioMind " + self.t("Settings")); layout = QVBoxLayout(dialog); form = QFormLayout()
        theme = QComboBox(); theme.addItem(self.t("Dark"), "Dark"); theme.addItem(self.t("Light"), "Light"); theme.setCurrentIndex(max(0, theme.findData(str(self.settings.value("theme", "Dark")))))
        language = QComboBox(); language.addItems(["English", "Italiano", "Deutsch"]); language.setCurrentText(self.language)
        form.addRow(self.t("Theme"), theme); form.addRow(self.t("Language"), language); layout.addWidget(QLabel(self.t("Appearance"))); layout.addLayout(form)
        layout.addWidget(QLabel(self.t("AI ASSISTANT CONNECTION"))); self.connection_panel.setParent(dialog); self.connection_panel.show(); layout.addWidget(self.connection_panel)
        layout.addWidget(QLabel(self.t("Provider API keys and OAuth tokens are stored in the Linux keyring. Account passwords are never collected.")))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        buttons.button(QDialogButtonBox.Save).setText(self.t("Save")); buttons.button(QDialogButtonBox.Cancel).setText(self.t("Cancel"))
        accepted = dialog.exec() == QDialog.Accepted
        self.connection_panel.setParent(self.ai_widget); self.ai_layout.addWidget(self.connection_panel); self.connection_panel.hide()
        if accepted:
            existing_prompt = self.prompt.toPlainText().strip()
            default_prompts = {DEFAULT_SUMMARY_PROMPT} | {translations.get(DEFAULT_SUMMARY_PROMPT, DEFAULT_SUMMARY_PROMPT) for translations in TEXT.values()}
            self.settings.setValue("theme", theme.currentData()); self.settings.setValue("language", language.currentText()); self.language = language.currentText()
            if existing_prompt in default_prompts: self.prompt.setPlainText(self.t(DEFAULT_SUMMARY_PROMPT))
            self.save_oauth_client_id(); self.save_provider_settings(); self._apply_theme(); self.refresh_ai_connection_state(); self.log(self.t("Settings saved. Restart FolioMind to apply all language changes."))

    def refresh_ai_connection_state(self):
        provider = self.provider_id(); connected = bool(self.active_credential())
        self.ai_status.setText(self.t("Connected: " if connected else "Not connected: ") + PROVIDERS[provider]["label"])
        self.connect_ai.setText(self.t("AI Assistant Settings") if connected else self.t("Connect to AI Assistant"))

    def closeEvent(self, event):
        if self.summary_thread and self.summary_thread.isRunning():
            QMessageBox.information(self, APP_NAME, "A summary is still running. Wait for it to finish before closing FolioMind.")
            event.ignore()
            return
        self.save_summary_draft()
        write_debug("FolioMind window closed normally.")
        event.accept()

    def focus_files(self): self.file_list.setFocus()
    def focus_ai(self): self.prompt.setFocus()
    def show_history(self): self.log("History will be added after the first MVP export workflow.")


if __name__ == "__main__":
    sys.excepthook = unhandled_exception
    app = QApplication(sys.argv); app.setApplicationName(APP_NAME)
    window = MainWindow(); window.show(); sys.exit(app.exec())
