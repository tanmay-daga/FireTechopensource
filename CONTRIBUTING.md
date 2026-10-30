# Contributing to Bug Buster

Thanks for helping! This is an open-source project and contributions are welcome.

## Ground rules

- Fork the repo and open pull requests from your fork. Please do not spam issues, PRs or comments.
- Keep PRs small and focused, with a clear description of what changed and why.
- Use clear commit messages, for example `fix: reject symlinked paths in scanner`.
- **Never commit secrets** (API keys, tokens, `.env` files). The project needs none.
- Credit any library, dataset, template or code you borrow, and make sure its licence is compatible with MIT.
- Core principle: **everything stays local and patches are never auto-applied.** Changes that add cloud AI calls or auto-apply behaviour will not be accepted.

## Development setup

See the Quick start in the [README](README.md). Backend: `backend/` (FastAPI). Frontend: `frontend/` (plain HTML/CSS/JS, no build step).

## Reporting bugs

Open an issue with: what you did, what you expected, what happened, your OS, Python and Ollama versions, and any backend error text.

## Code of Conduct

Be respectful. No harassment, discrimination or disruption. We follow the [MLH Code of Conduct](https://mlh.io/code-of-conduct); report problems to incidents@mlh.io or the maintainers.
