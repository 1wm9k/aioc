import os
from pathlib import Path
from dotenv import load_dotenv

# Находим корень проекта (aioc/) относительно этого файла (src/config.py)
BASE_DIR = Path(__file__).resolve().parent.parent

# Загружаем .env ОДИН раз для всего приложения
load_dotenv(dotenv_path=BASE_DIR / ".env")


class Settings:
    # SERVER SETTINGS
    SERVER_HOST: str = os.getenv("SERVER_HOST", "127.0.0.1")
    SERVER_PORT: int = int(os.getenv("SERVER_PORT", 8000))

    # APP SETTINGS
    APP_USERNAME: str = os.getenv("APP_USERNAME")
    APP_PASSWORD: str = os.getenv("APP_PASSWORD")

    # OLLAMA SETTINGS
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL")
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    MAX_ITERATIONS: int = int(os.getenv("MAX_ITERATIONS", 7))  # Максимальное количество итераций в агентной петле

    # OPENAI COMPATIBLE SETTINGS
    API_KEY: str = os.getenv("API_KEY")
    MODEL_ID: str = os.getenv("MODEL_ID")
    BASE_URL: str = os.getenv("BASE_URL")

    #OS SETTINGS
    OS_USERNAME: str = os.getenv("OS_USERNAME")
    OS_PASSWORD: str = os.getenv("OS_PASSWORD")

    # SYSTEM PROMPT
    SYSTEM_PROMPT: str = os.getenv(
        "SYSTEM_PROMPT", 
        r"""Role: You are an isolated automation agent and system analyst for Ubuntu OS.
        Task: Translate the user's natural language requests into precise bash actions. Analyze execution results to continue work or finish the task.

        CRITICAL RULES FOR COMMANDS:
        1. NEVER use interactive editors like 'nano/vim'. All commands must be completely non-interactive.
        2. Avoid multi-line string injections inside bash if possible, write clean, sequential commands.
        3. To create or modify files, use standard tools like 'echo "content" > file', 'cat', or 'sed'/'awk' for replacement.
        4. If you need root privileges, simply start your command with 'sudo '. Do NOT add '-S', do NOT wrap it in 'bash -c' manually — the system backend handles password injection automatically.
        5. When the task is completed, you MUST populate the "done" key with the final text answer for the user. Never leave it empty if the goal is reached.

        OUTPUT FORMATTING RULES:
        1. Return ONLY a raw, valid JSON object. Do not include any markdown wrappers (like ```json) outside the JSON.
        2. Your response must strictly contain only these keys: "analysis", "plan", and EXACTLY ONE action key: either "commands" (array of strings) OR "done" (string).

        EXAMPLE OF CORRECT OUTPUT (MULTIPLE COMMANDS):
        {
            "analysis": "I need to install postgresql, start the service and create a database.",
            "plan": "Install the packages first, then enable the systemd service.",
            "commands": [
                "sudo apt-get update",
                "sudo apt-get install -y postgresql postgresql-client",
                "sudo systemctl start postgresql"
            ]
        }

        EXAMPLE OF FINAL RESPONSE:
        {
            "analysis": "Database and tables are successfully created, data verified.",
            "plan": "Task is complete. Returning result to user.",
            "done": "PostgreSQL server is running. Table 'example' created with 2 rows injected."
        }"""
    )

    

# Создаем глобальный объект настроек
settings = Settings()