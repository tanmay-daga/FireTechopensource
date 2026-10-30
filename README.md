<<<<<<< HEAD
# 🐛 Bug Buster

**Open-source visual bug-to-patch engine.** Drop in a screenshot of a bug and point at your local repo. A local open-weight AI model finds the culprit file, explains the root cause, and hands you a Git diff plus the fixed code.

Built for **Halloween Hack BLR · DevF8rge × Hacktoberfest 2026** · Theme: *AI for Open Source* / *Developer Productivity*.

## What it does

1. You upload a screenshot of the bug, enter the path to your local repo, and optionally add a hint.
2. The backend scans the repo safely (no secrets, no binaries, no symlinks, size limits).
3. **Gemma** (running locally through Ollama) reads the screenshot, then the relevant source files.
4. You get back: the **culprit file**, the **root cause**, a **Git diff**, and the **fixed code**.
5. The diff is checked against your real files. **Patches are never applied automatically**; you review and apply them yourself.

Everything runs on your machine. **No cloud AI, no paid APIs, no API keys.**

## Open models used

| Model | Role | Runs via |
|-------|------|----------|
| [Gemma 3 4B](https://ai.google.dev/gemma) (`gemma3:4b`, vision) | Screenshot understanding and code analysis | [Ollama](https://ollama.com), locally |

## AI tools used to build this project

Per the hackathon rules, we disclose AI assistance:

- **Claude (Anthropic)** assisted in writing and reviewing code and documentation. Every team member is expected to be able to explain the code in this repo.
- **Gemma 3** (above) is the AI engine inside the product itself.

## Quick start

You need [Python 3.10+](https://www.python.org) and [Ollama](https://ollama.com).

**Windows:** double-click `start.bat`
**macOS / Linux:** `chmod +x start.sh && ./start.sh`

The launcher creates a virtual environment, installs dependencies, pulls `gemma3:4b` on first run (about 3 GB), starts the backend on port 8000 and the frontend on port 5500, and opens http://localhost:5500.

### Manual setup

```bash
# 1. Model
ollama pull gemma3:4b

# 2. Backend
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
uvicorn main:app --host 127.0.0.1 --port 8000

# 3. Frontend (new terminal)
cd frontend
python -m http.server 5500
```

Open http://localhost:5500. More backend detail is in [`backend/README.md`](backend/README.md).

## Try the demo

`demo-repo/` contains a tiny login page with a deliberate bug: the login button's text colour equals its background colour, so the label is invisible.

1. Open `demo-repo/index.html` in a browser and screenshot the page.
2. In Bug Buster, upload the screenshot and enter the full path to `demo-repo`.
3. Click **EXORCISE BUG**.

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Backend and Ollama status |
| POST | `/analyze-bug` | multipart: `image`, `repo_path`, optional `issue_hint` |

`/analyze-bug` returns `culprit_file`, `root_cause`, `git_diff`, `fixed_code` (plus an `analysis` object with confidence and evidence).

## Project structure

```
backend/     FastAPI service: repo scanner, Gemma engine, patch validator
frontend/    Vanilla HTML/CSS/JS interface (no build step, no external requests)
demo-repo/   Sample buggy site used for demos
start.bat / start.sh   One-command launchers
```

## Safety by design

- Repo paths are resolved safely; symlinks are not followed.
- `.env` files, secrets, lockfiles, minified and binary files are never read or sent to the model.
- Generated patches are validated (no traversal, no deletions or renames) and **never auto-applied**.
- CORS is limited to exact local origins.

## Credits

- [Gemma](https://ai.google.dev/gemma) by Google DeepMind (model weights under the Gemma terms of use)
- [Ollama](https://ollama.com) (MIT) for local model serving
- [FastAPI](https://fastapi.tiangolo.com), [Uvicorn](https://www.uvicorn.org), [Pydantic](https://docs.pydantic.dev), [python-multipart](https://github.com/Kludex/python-multipart), [python-dotenv](https://github.com/theskumar/python-dotenv), [httpx](https://www.python-httpx.org)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Please follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE). Note that the Gemma model weights are governed by their own terms.
=======
# 🐛 BUG BUSTER

### Hunt Bugs. Generate Fixes.

**An AI-Powered Visual Bug-to-Patch Engine**

BUG BUSTER uses artificial intelligence to understand visual software bugs from screenshots. It analyzes the provided screenshot along with relevant project files to identify the possible source of the issue.

The system aims to provide:
- The likely file responsible for the bug.
- An explanation of the root cause.
- A suggested code patch.
- Fixed code to help developers resolve the issue.
---

## 💡 About the Project

**What if fixing a bug was as simple as uploading a screenshot?**

Debugging is one of the most time-consuming parts of software development. Developers often spend hours searching through source files, identifying the root cause of an issue, and manually writing code fixes.

**BUG BUSTER** aims to make this process faster and smarter.

Bug Buster is an open-source, AI-powered visual debugging engine that connects screenshots of software bugs with their underlying source code.

Simply provide a screenshot of the issue, your project repository path, and an optional description. Bug Buster analyzes the available information and helps identify the likely culprit file, explain the root cause, and generate a suggested code patch.

**Our mission is simple: Spend less time debugging and more time building.**

---

## 🎯 The Problem

Traditional debugging can be frustrating because:

- Finding the source of a visual bug often requires searching through multiple files.
- Understanding unfamiliar codebases takes time.
- Identifying the exact cause of an issue is not always straightforward.
- Manually writing and testing fixes slows down development.
- Developers often struggle to connect what they see on screen with the code responsible for it.

## 🚀 Our Solution

Bug Buster bridges the gap between visual bug reporting and source-code debugging.

Instead of manually hunting through an entire codebase, developers can submit a screenshot and repository context.

The system analyzes the available information and provides an actionable debugging report containing:

- **Culprit File:** The source file most likely responsible for the issue.
- **Root Cause:** An explanation of the suspected problem.
- **Git Diff:** A suggested code patch showing the proposed changes.
- **Fixed Code:** A preview of the proposed corrected source code.

---

## ✨ Key Features

📸 **Visual Bug Analysis**

Upload screenshots of software issues and use them as the starting point for debugging.

🔍 **Culprit File Detection**

Identify the source file most likely responsible for the reported problem.

🧠 **Root Cause Analysis**

Understand why an issue may be happening through an AI-generated explanation.

🛠️ **AI-Powered Patch Generation**

Generate suggested code changes in Git diff format.

💻 **Fixed Code Preview**

Review proposed corrected source code before applying changes.

⚡ **Developer-Friendly Experience**

Connect visual bug reports and source-code analysis in one streamlined workflow.

---

## 🔄 How It Works

**STEP 1 — Upload a Screenshot**

Provide an image showing the software bug.

**STEP 2 — Provide Repository Context**

Enter the project repository path and optionally describe the issue.

**STEP 3 — AI-Powered Analysis**

The backend processes the screenshot and available repository context.

**STEP 4 — Identify the Culprit File**

The system identifies the source file most likely associated with the issue.

**STEP 5 — Understand the Root Cause**

Receive an explanation of the suspected problem.

**STEP 6 — Generate a Suggested Fix**

Get a proposed Git diff and corrected-code preview.

**STEP 7 — Review and Test**

Review the proposed changes and test them before applying them to your project.

---

## 🛠️ Technology Stack

**Frontend:** HTML, CSS, JavaScript

**Backend:** Python, FastAPI

**AI Runtime:** Ollama

**AI Model:** Gemma 3, if configured in the backend

**Communication:** REST API

**Patch Generation:** Git Diff

---

## 📂 Project Structure

The project is organized into separate frontend and backend components.

**Frontend**
- exp.html — Application interface
- exp.css — Styling and visual design
- script.js — Frontend functionality

**Backend**
- main.py — FastAPI application
- requirements.txt — Python dependencies

**Documentation**
- README.md — Project overview and setup instructions
- CONTRIBUTING.md — Contribution guidelines
- LICENSE — Open-source license

---

## ⚙️ Installation and Setup

### Prerequisites

Before running Bug Buster, make sure you have:

- Python 3.10 or later
- Git
- Ollama
- VS Code or another code editor
- A modern web browser

### Getting Started

**1. Clone the Repository**

Clone the Bug Buster repository from GitHub and open the project folder.

**2. Create a Virtual Environment**

Create and activate a Python virtual environment for the backend.

**3. Install Dependencies**

Install the required Python packages using the project's requirements file.

**4. Set Up the AI Model**

If your backend uses Gemma 3 through Ollama, download the configured model and ensure Ollama is running.

**5. Start the Backend**

Launch the FastAPI server using Uvicorn.

**6. Start the Frontend**

Serve the frontend using Python's built-in HTTP server.

**7. Open the Application**

Visit the local frontend address in your browser and start exploring Bug Buster.

For exact terminal commands, follow the installation instructions in the project's backend and frontend configuration.

---

## 🔌 API Overview

Bug Buster uses REST API endpoints to communicate between the frontend and backend.

**Health Check**

Checks whether the backend server is running.

**Bug Analysis**

Accepts the following information:

- Screenshot image
- Repository path
- Optional issue description

The expected analysis response contains:

- Culprit file
- Root cause
- Suggested Git diff
- Fixed code

---

## 🗺️ Future Roadmap

We want to make Bug Buster even more powerful.

🔲 More accurate culprit-file identification

🔲 Improved root-cause analysis

🔲 Better AI-generated patches

🔲 Automatic patch validation

🔲 Support for additional programming languages

🔲 GitHub repository integration

🔲 One-click patch application with developer approval

🔲 Enhanced debugging reports

---

## 🤝 Open Source and Contributions

Great software is built through collaboration.

We welcome developers, designers, testers, and open-source enthusiasts to contribute to Bug Buster.

You can help by:

- Reporting bugs.
- Suggesting new features.
- Improving the user interface.
- Enhancing backend functionality.
- Improving AI analysis and patch generation.
- Improving documentation.
- Testing the application.

Read our **CONTRIBUTING.md** file to learn how to participate.

Every contribution makes Bug Buster better!

---

## 🔐 Security and Reliability

Bug Buster generates suggested code changes, which may not always be correct or complete.

We recommend:

- Reviewing every generated patch before applying it.
- Testing proposed changes before deployment.
- Maintaining backups and using Git version control.
- Only analyzing repositories you are authorized to access.
- Never sharing passwords, API keys, or private credentials.

---

## 👥 Meet the Team — FIRETECH

Built with passion, creativity, and a vision to simplify software debugging.

**Dibakar Das**

**Tanmay Daga**

**Suryansh Singh**

Together, we are **TEAM FIRETECH**.

---

## ⭐ Support Bug Buster

Like our idea?

- Give the repository a ⭐ Star.
- Share the project with fellow developers.
- Report issues and suggest improvements.
- Fork the project and experiment.
- Contribute to making debugging easier for everyone.

Your support motivates us to keep building!

---

# 🐛 BUG BUSTER

### Hunt Bugs. Generate Fixes.

**Made with ❤️ by TEAM FIRETECH**

*Turning visual bugs into actionable code fixes.*
>>>>>>> 0d688398557ebf0e25b0c205b4fa089a3158e6b3
