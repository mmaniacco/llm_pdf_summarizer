# FolioMind

FolioMind is a local-first Linux desktop workspace for studying a folder of PDFs. It keeps the familiar three-pane layout: a PDF explorer, an integrated PDF/Markdown workspace, and an AI-assisted study panel.

![FolioMind](assets/foliomind-logo.png)

## What it does

- Lists PDF files alphabetically and opens them in the built-in, scrollable PDF viewer.
- Extracts selectable text locally, retaining a per-page extraction cache.
- Searches file names and extracted text.
- Creates a single prompt-guided Markdown summary across all extracted PDFs.
- Exports Markdown to a PDF with a clickable table of contents.
- Finds categories and creates four-answer study questions.
- Offers quiz difficulty and question-count choices, shuffled answers, final scoring, retry-missed, saved result history, and Markdown/PDF results export.
- Lets you interpret a selected diagram or image page with a vision-capable OpenRouter model, then includes that visual note in the next summary.
- Remembers the last page viewed in every PDF.
- Saves the last opened workspace folder and automatically preserves the latest Markdown draft, so work can continue after reopening the app.
- Supports English, Italian, and German interface settings, plus light and dark themes.

## How summaries work

Choose a folder, then click **Read PDFs** when you are ready. FolioMind does not begin extraction merely because a folder was opened.

It sends only extracted text to the configured AI provider—not the original PDF files. The summary process first creates factual notes for each text section, then asks the model to create the final Markdown document. This produces stronger summaries but can take time for large folders, especially with free models. Intermediate notes are cached locally in the PDF folder, which makes repeated summaries of unchanged documents faster.

Scanned or image-only PDFs need OCR before they can be summarized. Install `ocrmypdf` and `tesseract` through your Linux package manager. For a meaningful diagram, photograph, or other visual-only page, open that PDF page in the viewer and select **Analyze visual page**. FolioMind sends a rendered image of that one selected page to OpenRouter, saves the resulting interpretation locally, and includes it in the next summary. This is manual by design: many PDFs contain decorative/template images on every page, and analyzing all of them would be slow and waste free-model requests.

## OpenRouter free models

FolioMind uses OpenRouter’s free models router by default.

1. Create an OpenRouter API key.
2. Open **Settings** in FolioMind.
3. Paste the key and choose **Save API key securely**.
4. Keep `openrouter/free` for automatic free-model routing, or choose **Load free models** and select a specific free model.

The key is stored in the Linux desktop keyring, never in this project directory. FolioMind never asks for an account password.

Free models can be queued, rate-limited, or temporarily unavailable. For the most reliable behavior, use the automatic `openrouter/free` router.

## Saved workspace data

The selected PDF folder contains a hidden `.foliomind-cache` directory. It holds extraction cache data, intermediate notes, and `latest-summary.md`, the recovery copy of the current Markdown editor. This cache is local and should not be committed to Git.

For troubleshooting, FolioMind also creates a `.debug` directory in the selected PDF folder. Its `foliomind.log` records timestamped app events and handled errors; unhandled Python exceptions are recorded there too. It does not log API keys or PDF text.

## Run from source

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python paper_studio.py
```

## Build the Linux executable

Build on the Linux distribution family you intend to use:

```bash
chmod +x build.sh
./build.sh
```

The single executable is written to `dist/foliomind`.

## Create a click-to-install Debian package

For Ubuntu, Linux Mint, Debian, and related distributions:

```bash
chmod +x package-deb.sh
./package-deb.sh
```

The package is written to `dist/foliomind_<version>_amd64.deb`. Its version is automatically read from `APP_VERSION` in `paper_studio.py`; the current release is `0.0.21`.

## Uploading to GitHub

Upload the source files in this directory: `paper_studio.py`, `requirements.txt`, `assets/`, `packaging/`, `build.sh`, `package-deb.sh`, `.gitignore`, and this README.

Do **not** upload `dist/`, `.venv/`, `build/`, `.package-root/`, generated PDFs, `.foliomind-cache/`, or `.debug/`. They are intentionally ignored because the installer is large and the two hidden directories are local workspace data. To share an installer, create a GitHub Release and attach the generated `.deb` as a release asset instead of committing it to the repository.

## License

Choose and add a license before publishing the project publicly.
