# FolioMind

FolioMind is a Linux desktop study workspace that reads every PDF in a selected directory, produces prompt-guided Markdown summaries, discovers categories, and generates quizzes. PDFs are ordered alphanumerically, extracted locally, sent only to the selected LLM provider, then exported with a clickable table of contents.

![FolioMind](assets/foliomind-logo.png)

## Run from source

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install
.venv/bin/python paper_studio.py
```

`markdown-pdf` must be available on `PATH` for export. For image-only PDFs, install `ocrmypdf` and `tesseract` with your Linux package manager; FolioMind will otherwise mark the document as needing OCR.

## Hugging Face sign-in

Create a **public** OAuth application in Hugging Face settings and add `http://127.0.0.1:8765/callback` as its redirect URI. In FolioMind, paste the OAuth client ID into the AI panel and select **Sign in with Hugging Face**.

The app uses OAuth PKCE and asks for the `inference-api` scope. The access token is held in the desktop keyring, not in the project directory.

## Build a Linux executable or installer

```bash
chmod +x build.sh
./build.sh
```

The executable is written to `dist/foliomind`. Build it on the target Linux family for best compatibility.

To create a click-to-install Linux Mint/Ubuntu package instead:

```bash
chmod +x package-deb.sh
./package-deb.sh
```

The installer is written to `dist/foliomind_0.0.1_amd64.deb`.

## Provider status

The complete first provider is Hugging Face Inference Providers. The UI deliberately reserves a provider selector for additional OAuth-capable services; do not collect an account password in the app. Adding another provider means implementing that provider's documented OAuth flow and API adapter.
