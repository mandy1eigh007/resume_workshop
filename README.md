# Seattle Construction — Resume & Pathways (Replit edition)

This repo is set up to run on **Replit** using **Nix** and **Streamlit**.  
No local Python install required.

## Quick start (Replit)

1. Create a new Repl → **Import from GitHub** (or create empty and paste these files).
2. Ensure these files exist at repo root:
   - `.replit`
   - `replit.nix`
   - `requirements.txt`
   - `app.py` (this starts as a smoke test)
   - **DOCX masters**:
     - `resume_app_template.docx`
     - `Job_History_Master.docx`
     - `Stand_Out_Playbook_Master.docx`
     - `Transferable_Skills_to_Construction.docx`
3. Click **Run**. First boot installs Python deps; then Streamlit starts.

If you see a **non-fast-forward** Git warning in Replit:
- Open the **Version Control** panel → **Pull** → then **Commit** and **Push** again.

## What’s included
- **.replit**: tells Replit to install requirements and run `streamlit run app.py`.
- **replit.nix**: pins Nix packages (Python 3.11 + pip).
- **requirements.txt**: versions that build fast (no C toolchain needed).
- **app.py (smoke test)**: confirms dependencies and file presence.

## Swap in the full app
- Once the smoke test runs, replace `app.py` with your full Streamlit app code.
- Keep the requirements pinned unless we explicitly change them.

## Troubleshooting

**Stuck on “Preparing metadata (pyproject.toml)”**  
We pin versions to avoid slow source builds. If you edit `requirements.txt`, stick to:
- `pandas` 2.2.3 (or 2.1.4 if you must go older)
- `streamlit` 1.36.0 (known-good here)

**Red Git banner (“Expected branch to point to…”)**  
Use Version Control → **Pull** → then **Commit** and **Push** again. Or in shell:
```bash
git stash push -u -m tmp && git pull --rebase && git stash pop