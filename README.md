# 🔍 PRLens

AI-assisted Pull Request review system for GitHub.

PRLens analyzes Pull Requests using static analysis tools and automatically posts:

- Executive review summaries
- Security findings
- Code quality findings
- Inline review comments on changed lines
- AI-powered remediation guidance

The goal is to provide fast, actionable code review feedback directly inside GitHub PRs.

---

# Features

## Static Analysis

PRLens currently supports:

| Tool | Purpose |
|--------|----------|
| Semgrep | Security & code quality rules |
| Bandit | Python security analysis |
| Ruff | Python linting & best practices |
| Eslint | JS linting & best practices |
| Typescript | TS best practices |
| Gitleaks | Find secret leakage |

Only files modified in the Pull Request are reviewed.

---

## AI Executive Summary

PRLens generates a high-level review summary including:

- Overall risk assessment
- Key risk themes
- Recommended remediation priorities

Powered by Ollama.

---

## AI Finding Explanations

For high-priority findings, PRLens generates developer-friendly explanations:

- Why the issue matters
- Security / reliability impact
- Suggested fix
- Example remediation

---

## GitHub Review Integration

PRLens automatically:

- Creates PR review summaries
- Updates existing PR summary comments
- Creates inline review comments
- Tracks review history

---

# Architecture

```text
GitHub PR
    │
    ▼
Webhook
    │
    ▼
Review Service
    │
    ├── Clone Repository
    │
    ├── Semgrep
    ├── Bandit
    ├── Ruff
    │
    ▼
Normalize Findings
    │
    ▼
AI Summary
    │
    ▼
AI Explanations
    │
    ▼
GitHub Review Comment
```

---

# Tech Stack

## Backend

- Python 3.12+
- FastAPI
- SQLAlchemy Async
- PostgreSQL

## Analysis

- Semgrep
- Bandit
- Ruff

## AI

- Ollama
- Qwen 2.5
- Llama 3.2

## Source Control

- GitHub App

---

# Requirements

## Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Pull required models:

```bash
ollama pull qwen2.5:3b
ollama pull llama3.2:3b
```

Verify:

```bash
ollama list
```

---

# Installation

Clone repository:

```bash
git clone https://github.com/your-org/prlens.git

cd prlens
```

Create virtual environment:

```bash
python -m venv .venv

source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

# Configuration

Create:

```bash
.env
```

Example:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/prlens

GITHUB_APP_ID=12345

GITHUB_PRIVATE_KEY_PATH=./private-key.pem

WEBHOOK_SECRET=replace_me

OLLAMA_HOST=http://localhost:11434
```

---

# Database

Create database:

```sql
CREATE DATABASE prlens;
```

Run migrations:

```bash
alembic upgrade head
```

---

# Running Locally

Start Ollama:

```bash
ollama serve
```

Run FastAPI:

```bash
uvicorn app.main:app --reload
```

Application:

```text
http://localhost:8000
```

---

# GitHub App Setup

Create a GitHub App:

Settings → Developer Settings → GitHub Apps

Required permissions:

### Repository

```text
Contents: Read
Pull Requests: Read & Write
Metadata: Read
```

### Events

```text
Pull Request
Pull Request Review
Pull Request Review Comment
```

Install the app on your repository.

---

# Review Workflow

When a Pull Request is opened or updated:

1. GitHub sends webhook event
2. Repository is cloned
3. Changed files are detected
4. Static analyzers run
5. Findings are filtered to changed lines
6. AI summary is generated
7. AI explanations are generated
8. GitHub review comment is posted
9. Review metadata is saved

---

# Example Output

## Executive Summary

```md
## 📑 PRLens Executive Summary

### Overall Risk

The Pull Request contains multiple high-severity security findings related to command execution and unsafe dynamic evaluation.

### Key Risk Themes

- Command injection risk
- Unsafe code execution
- Missing request protection

### Recommended Priorities

1. Remove unsafe eval usage
2. Eliminate shell=True subprocess calls
3. Review request validation controls
```

---

## Inline Review Example

```md
### Impact

Using shell=True may allow command injection if user-controlled input reaches the command.

### Recommendation

Use shell=False and pass arguments as a list.

### Example Fix

subprocess.run(["ls", "-la"], shell=False)
```

---

# Current Limitations

- Supports Python and JavaScript projects
- Reviews only changed files in Pull Requests
- Inline comments are currently created per review run
- AI quality depends on local Ollama model

---

# Roadmap

- CodeQL integration
- SARIF support
- Multi-language support
- Review history dashboard
- Team metrics
- Slack notifications
- Redis caching
- Background workers

---

# Contributing

Create a feature branch:

```bash
git checkout -b feature/my-feature
```

Run quality checks:

```bash
ruff check .

bandit -r .

semgrep scan .
```

Create Pull Request.

---

---
## Demo 
[▶ Watch the Demo Video](./demo.mp4)
<img width="2452" height="7701" alt="pr-lens-review-comment-to-repo" src="https://github.com/user-attachments/assets/290cc660-f780-4d3c-a04d-ec341598b4c1" />


# License

MIT License
