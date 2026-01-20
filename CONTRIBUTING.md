# Contributing to RoK Stats Hub

Thank you for your interest in contributing to RoK Stats Hub! This document provides guidelines and instructions for contributing.

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for everyone.

## How to Contribute

### Reporting Bugs

1. Check if the bug has already been reported in [Issues](../../issues)
2. If not, create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Screenshots if applicable
   - Your environment (OS, Python version, Node version)

### Suggesting Features

1. Check if the feature has already been suggested
2. Create a new issue with the `enhancement` label
3. Describe the feature and its use case

### Pull Requests

1. Fork the repository
2. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. Make your changes following our coding standards
4. Test your changes thoroughly
5. Commit with clear messages:
   ```bash
   git commit -m "Add feature: description of what you added"
   ```
6. Push and create a Pull Request

## Development Setup

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # or .\.venv\Scripts\activate on Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt  # if available

# Run tests
pytest

# Run linter
flake8 app/
```

### Frontend

```bash
cd frontend-next
npm install

# Run linter
npm run lint

# Run type check
npm run type-check
```

## Coding Standards

### Python (Backend)

- Follow PEP 8
- Use type hints where possible
- Document functions with docstrings
- Keep functions focused and small

### TypeScript (Frontend)

- Use TypeScript strictly (no `any` unless necessary)
- Follow React best practices
- Use functional components with hooks
- Keep components small and reusable

### Commits

- Use clear, descriptive commit messages
- Start with a verb: Add, Fix, Update, Remove, Refactor
- Reference issues when applicable: `Fix #123: description`

## Project Structure

```
backend/
├── app/
│   ├── main.py          # Routes and app setup
│   ├── models.py        # Database models
│   ├── schemas.py       # Pydantic schemas
│   ├── auth.py          # Authentication logic
│   └── database.py      # DB connection
└── alembic/             # Migrations

frontend-next/
├── app/                 # Next.js pages (App Router)
├── components/          # Reusable components
└── lib/                 # Utilities and hooks
```

## Questions?

Feel free to open an issue or reach out if you have any questions.

Thank you for contributing! 🎮
