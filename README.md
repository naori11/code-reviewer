# Code Review Automator

An automated, AI-powered code review assistant built with **FastAPI** and **Google Gemini**. This service listens for GitHub Pull Request webhooks, analyzes code diffs for bugs, security vulnerabilities, and performance issues, and posts a detailed, "brutal" senior-level review directly back to the PR as a comment.

---

## 🚀 Core Features

- **Automated AI Analysis:** Leverages **Gemini 2.5 Flash** to perform rigorous code reviews focusing on:
  - **Bugs:** Logic errors, null handling, and race conditions.
  - **Security:** Injection risks, auth bypass, and data exposure.
  - **Performance:** N+1 queries, memory leaks, and blocking I/O.
  - **Maintainability:** Naming, complexity, and separation of concerns.
- **Enterprise-Grade Security:**
  - **GitHub App Support:** Uses Installation Access Tokens for granular permissions.
  - **Webhook Verification:** Rigorous HMAC-SHA256 signature verification for every incoming request.
- **Resilient Architecture:**
  - **Intelligent Retries:** Implements exponential backoff using `tenacity` for GitHub and Gemini API calls.
  - **Async/Sync Optimization:** Uses `anyio` thread pooling to prevent blocking the FastAPI event loop during heavy I/O tasks.
- **Smart Constraints:**
  - **Token Management:** Automatically counts Gemini tokens and blocks reviews for excessively large diffs (100k token limit).
  - **Comment Handling:** Gracefully truncates reviews to stay within GitHub's 65,536 character comment limit.
- **Production Logging:** Structured logging configuration with `dictConfig` for clear audit trails and debugging.

---

## 🛠 Tech Stack

- **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python 3.10+)
- **AI Engine:** [Google Gemini API](https://ai.google.dev/) (`google-genai`)
- **API Integration:** [PyGithub](https://pygithub.readthedocs.io/) & [HTTPX](https://www.python-httpx.org/)
- **Reliability:** [Tenacity](https://tenacity.readthedocs.io/) (Retries) & [AnyIO](https://anyio.readthedocs.io/) (Concurrency)
- **Environment:** [Python-Dotenv](https://saurabh-kumar.com/python-dotenv/)
- **Server:** [Uvicorn](https://www.uvicorn.org/)

---

## 📂 Architecture & Directory Structure

```text
code-reviewer/
├── main.py              # Application entry point, FastAPI routes, and core logic
├── requirements.txt     # Project dependencies
├── .env.example         # Template for environment variables
├── .gitignore           # Standard Python/Node git ignore rules
└── venv/                # Python virtual environment (ignored by git)
```

---

## 📋 Prerequisites

Before running the application, ensure you have the following:

- **Python 3.10+**
- **Google Gemini API Key:** Obtain from [Google AI Studio](https://aistudio.google.com/).
- **GitHub Configuration:** (Choose one)
  - **GitHub App (Recommended):** `App ID` and `Private Key`.
  - **Personal Access Token (PAT):** For legacy/quick setup.
- **Webhook Secret:** A unique string for securing GitHub Webhooks.

---

## ⚙️ Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/code-reviewer.git
cd code-reviewer
```

### 2. Set Up Virtual Environment
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create a `.env` file in the root directory:
```bash
cp .env.example .env
```

Edit the `.env` file with your credentials:
```env
# Required for Webhook Security
WEBHOOK_SECRET=your_github_webhook_secret

# AI Configuration
GEMINI_API_KEY=your_gemini_api_key

# GitHub Auth (Option A: App - Recommended)
GITHUB_APP_ID=your_app_id
GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"

# GitHub Auth (Option B: PAT - Fallback)
# GITHUB_TOKEN=your_personal_access_token
```

### 4. Run the Application
```bash
uvicorn main.py:app --host 0.0.0.0 --port 8000 --reload
```

---

## 📖 Usage

### GitHub Webhook Configuration
1. Go to your GitHub Repository/App settings -> **Webhooks**.
2. Set **Payload URL** to `http://your-server-ip:8000/webhook`.
3. Set **Content type** to `application/json`.
4. Enter your `WEBHOOK_SECRET` in the **Secret** field.
5. Select **Individual events**: `Pull requests`.

### Application Logic
The app automatically triggers a review when a Pull Request is:
- **Opened**
- **Synchronized** (new commits pushed)
- **Reopened**

---

## 📡 API Documentation

### Primary Endpoint

| Method | Endpoint    | Description                                      |
| :----- | :---------- | :----------------------------------------------- |
| `POST` | `/webhook`  | Entry point for GitHub Pull Request event hooks. |

**Expected Payload (GitHub Standard):**
```json
{
  "action": "opened",
  "pull_request": {
    "number": 1,
    "installation": { "id": 123456 }
  },
  "repository": {
    "full_name": "owner/repo"
  }
}
```

---

## 🤝 Contributing

1. **Open an Issue:** Describe the bug or feature request.
2. **Fork & Branch:** Create a branch for your fix/feature.
3. **Submit PR:** Ensure your code follows the existing style and includes proper logging.
4. **Verification:** All PRs must pass signature verification and logic tests.

---

**Tone:** This is a production-grade tool designed for high-signal code reviews. Please use responsibly and verify AI suggestions before merging.
