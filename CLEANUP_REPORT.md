# BrandIQ — Cleanup Report
Generated: 2026-05-14

## Workspace Structure Analysis

### Original workspace root: `BrandIQ_copy/`
```
BrandIQ_copy/
├── .venv/              ← ROOT VENV (empty, only pip installed) — EXCLUDED
├── .vscode/            ← IDE settings — EXCLUDED
└── brandiq/
    ├── .vscode/        ← IDE settings — EXCLUDED
    ├── brandiq/        ← ✅ ACTUAL PROJECT (Git repo, deployed to Railway)
    │   ├── .git/       ← Git history — EXCLUDED from clean copy
    │   ├── .venv/      ← Project venv — EXCLUDED
    │   ├── src/        ← ✅ Source code
    │   ├── migrations/ ← ✅ DB migrations
    │   ├── main.py     ← ✅ FastAPI entry point
    │   └── ...
    ├── src/            ← DUPLICATE/OLD copy of source — NOT the deployed version
    ├── migrations/     ← DUPLICATE/OLD migrations
    ├── main.py         ← DUPLICATE/OLD main.py
    └── python-3.12.6-amd64.exe  ← Python installer binary — EXCLUDED
```

## Files Excluded from Clean Copy

| Category | Items |
|---|---|
| Virtual environments | `.venv/` (root), `brandiq/.venv/`, `brandiq/brandiq/.venv/` |
| IDE metadata | `.vscode/` (3 instances) |
| Git history | `brandiq/brandiq/.git/` |
| Python cache | All `__pycache__/` directories (100+ folders) |
| Compiled Python | All `*.pyc`, `*.pyo` files |
| Binary installer | `brandiq/python-3.12.6-amd64.exe` (44MB) |
| Generated image | `brandiq/brandiq/topper_ias_icon.png` |
| Test script | `test_nurture_flow.py` (kept — useful for testing) |

## Clean Copy Location
`c:\Users\acer\Documents\BrandIQ_CLEAN\`

## File Count
- Original (with artifacts): ~2000+ files
- Clean copy: 72 files (source code only)

## Suspicious / Risky Files (reviewed, kept)
- `fix_enums.py` — one-time DB fix script, safe to keep
- `canva_import_test.py` — test script, safe to keep
- `.env` — contains real secrets, NOT copied to clean folder (use `.env.example`)
