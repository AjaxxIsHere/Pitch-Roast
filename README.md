# 🔥 PitchRoast

> **AI-powered cold PR pitch auditor.** Roast, score, redline, and rewrite your outreach before a real editor deletes it.

Cold PR pitches have a **70–80% deletion rate** before they're even read. PitchRoast simulates cynical tech and business editors to stress-test your pitches, score them across six dimensions, flag buzzword fluff, and generate a rewrite — all for free via OpenRouter's free-tier models.

---

## Features

- **5 Editor Personas** — TechCrunch, Forbes, The Verge, Gulf News, and RoastBot
- **6-Dimension Scoring** — Clarity, Specificity, Buzzword Density, Length, Relevance, Readability (0–10 each, weighted overall)
- **Fluff Detection** — Identifies buzzwords and suggests replacements inline
- **AI Rewrite** — Generates a concise, high-conversion version of your pitch
- **Copy to Clipboard** — One-click copy on roast, redlines, and rewrite
- **Dark Mode** — Default dark theme with split-screen dashboard
- **Zero Cost** — 100% free-tier operation via OpenRouter
- **Mock Mode** — `MOCK_LLM=true` for guaranteed demo-day operation with no API calls

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 16 (App Router), TypeScript, Tailwind CSS 4, Lucide Icons |
| **Backend** | Python 3.11+, FastAPI, Pydantic v2, httpx |
| **LLM Provider** | OpenRouter free tier (`openrouter/free` router + 5 fallback models) |
| **Testing** | pytest + pytest-asyncio (59 tests) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FRONTEND (Next.js)                    │
│  ┌──────────────┐    ┌──────────────────────────────┐   │
│  │  Pitch Input  │    │       Audit Card              │   │
│  │  - textarea   │───▶│  - Rejection Score            │   │
│  │  - persona    │    │  - Cynical Editor Verdict     │   │
│  │  - metadata   │    │  - Score Breakdown            │   │
│  │  - word count │    │  - Fluff Word Badges          │   │
│  └──────────────┘    │  - Rewritten Pitch            │   │
│          │           └──────────────────────────────┘   │
│          ▼                                               │
│  POST /api/analyze (Route Handler proxy)                │
└─────────────────┼───────────────────────────────────────┘
                  │ HTTP POST
                  ▼
┌─────────────────────────────────────────────────────────┐
│              BACKEND (Python FastAPI :8000)               │
│  Pydantic validation → Prompt construction → OpenRouter  │
│  → JSON sanitiser (3-stage) → Schema validation         │
└─────────────────┼───────────────────────────────────────┘
                  │ HTTPS
                  ▼
         OpenRouter API (free tier)
```

---

## Prerequisites

- **Node.js** 18+ and npm
- **Python** 3.11+
- **OpenRouter API key** (free — sign up at [openrouter.ai](https://openrouter.ai))

---

## Setup

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd pitchroast
```

### 2. Frontend (Next.js)

```bash
npm install
```

### 3. Backend (FastAPI)

```bash
cd backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -e ".[dev]"

# Create environment file
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY
```

### 4. Environment Variables

Create `backend/.env`:

```env
# Required — your OpenRouter API key (free tier)
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Optional — set to "true" for offline/demo mode (no API calls)
MOCK_LLM=false
```

---

## Running the App

You need **two terminals** — one for the backend, one for the frontend.

### Terminal 1 — Backend (port 8000)

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

### Terminal 2 — Frontend (port 3000)

```bash
npm run dev
```

Open **http://localhost:3000** in your browser.

### Demo / Mock Mode (no API key needed)

```bash
cd backend
source .venv/bin/activate
MOCK_LLM=true uvicorn app.main:app --reload --port 8000
```

Then start the frontend normally. All pitch analyses return realistic mock data — zero API calls, zero cost, zero failure risk.

---

## Running Tests

### Backend Tests (59 tests)

```bash
cd backend
source .venv/bin/activate
python -m pytest tests/ -v
```

**Useful flags:**

| Flag | Description |
|---|---|
| `-v` | Verbose — shows each test name |
| `-vv` | Extra verbose — shows full assert diffs |
| `-k "test_clean"` | Run only tests matching that name |
| `-x` | Stop on first failure |
| `--tb=short` | Shorter tracebacks |

### Frontend Build Check

```bash
npx next build
```

Verifies TypeScript compilation and Next.js build with zero errors.

---

## API Reference

### `POST /audit`

Audit a cold PR pitch against a simulated editor persona.

**Request body:**

```json
{
  "pitch_text": "Your cold PR pitch here (min 50 chars, max 4000)",
  "persona": "techcrunch",
  "company_name": "Optional company name",
  "target_publication": "Optional target publication",
  "campaign_angle": "Optional campaign angle"
}
```

**Valid personas:** `techcrunch`, `forbes`, `the_verge`, `gulf_news`, `roastbot`

**Response (200):**

```json
{
  "persona": "TechCrunch Sarah",
  "persona_avatar": "👩‍💻",
  "roast": "Your pitch is a buzzword bingo card...",
  "scores": [
    {"name": "Clarity", "score": 3, "feedback": "...", "suggestion": "..."},
    {"name": "Specificity", "score": 2, "feedback": "...", "suggestion": "..."},
    {"name": "Buzzword Density", "score": 1, "feedback": "...", "suggestion": "..."},
    {"name": "Length", "score": 5, "feedback": "...", "suggestion": "..."},
    {"name": "Relevance", "score": 4, "feedback": "...", "suggestion": "..."},
    {"name": "Readability", "score": 6, "feedback": "...", "suggestion": "..."}
  ],
  "overall_score": 3.5,
  "redlines": [
    {"original": "revolutionary", "replacement": "new", "reason": "Buzzword"}
  ],
  "rewritten_pitch": "Hi — we help SaaS teams cut onboarding time by 40%...",
  "model_used": "openrouter/free"
}
```

**Error responses:** `422` (validation), `429` (rate limit), `503` (model unavailable)

### `GET /health`

Returns `{"status": "ok"}`.

---

## Project Structure

```
pitchroast/
├── app/
│   ├── api/analyze/route.ts    # Next.js proxy to FastAPI
│   ├── globals.css              # Dark mode theme + Tailwind
│   ├── layout.tsx               # Root layout with metadata
│   └── page.tsx                 # Split-screen dashboard
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app + POST /audit
│   │   ├── schemas.py           # Pydantic v2 models
│   │   └── services.py          # LLM integration, retry, mock
│   ├── tests/
│   │   ├── __init__.py
│   │   └── test_analyzer.py     # 59 pytest tests
│   ├── .env.example
│   └── pyproject.toml
├── PRD.md                       # Ground-truth specification
├── package.json
├── tsconfig.json
└── README.md
```

---

## Contributing

Contributions are welcome. This project follows **trunk-based development** with small, verifiable commits.

### Workflow

1. **Fork** the repository
2. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
3. **Write tests first** (TDD) — add failing tests in `backend/tests/` before implementing
4. **Implement** the feature
5. **Run all tests** to verify:
   ```bash
   cd backend && source .venv/bin/activate && python -m pytest tests/ -v
   npx next build
   ```
6. **Commit** with conventional messages:
   ```
   feat: add dark mode toggle to header
   fix: handle 503 gateway errors with immediate failover
   test: add parser tests for fenced JSON with noise
   docs: update README with mock mode instructions
   chore: bump dependencies
   ```
7. **Open a Pull Request** against `main`

### Commit Convention

| Prefix | When to use |
|---|---|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `test:` | Adding or updating tests |
| `docs:` | Documentation changes |
| `refactor:` | Code restructuring without behavior change |
| `chore:` | Dependencies, config, CI |

### Code Style

- **Backend:** Follow existing Pydantic model patterns in `schemas.py`
- **Frontend:** Use Tailwind utility classes, Lucide icons, and the existing color variables (`--accent`, `--card`, etc.)
- **Tests:** Mock all external API calls — never hit OpenRouter in tests

---

## License

MIT

---

*Built as a demo for Pathos Communications Interview*
