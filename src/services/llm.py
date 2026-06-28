import base64
import json
import re
import logging
import httpx
from ollama import Client as OllamaClient
from openai import OpenAI
from src.config import settings
from src.services.executer import execute_single_command, safe_file_edit
from ddgs import DDGS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

ollama_client = OllamaClient(host=settings.OLLAMA_URL)
vsegpt_client = OpenAI(
    api_key=settings.API_KEY,
    base_url=settings.BASE_URL,
)


def _build_context_message(task_context: dict) -> str:
    lines = [
        "Session context:",
        f"- Original task: {task_context.get('task', '')}"
    ]
    
    if completed := task_context.get("completed_steps"):
        lines.append("- Completed steps:")
        lines.extend(f"  * {step}" for step in completed[-5:])
    
    if facts := task_context.get("facts"):
        lines.append("- Known facts:")
        lines.extend(f"  * {fact}" for fact in facts[-5:])
        
    if last_error := task_context.get("last_error"):
        lines.append(f"- Last error: {last_error}")

    lines.append("- Instruction: use this context; do not repeat successful steps and adapt if a previous command failed.")
    return "\n".join(lines)


def _get_llm_response(messages: list[dict], provider: str) -> str:
    if provider == "ollama":
        response = ollama_client.chat(
            model=settings.OLLAMA_MODEL, 
            messages=messages, 
            format="json",  
            options={"think": False}
        )
        return response["message"]["content"]
    
    if provider == "vsegpt":
        response = vsegpt_client.chat.completions.create(
            model=settings.MODEL_ID,
            messages=messages,
            max_tokens=5000,
            temperature=0.1
        )
        return response.choices[0].message.content
        
    raise ValueError(f"Provider '{provider}' is not supported.")


def _handle_tool_execution(parsed_response: dict, task_context: dict, messages: list[dict]) -> tuple[bool, str]:
    if "done" in parsed_response:
        logger.info(f"Task completed. Final message: {parsed_response['done']}")
        return True, parsed_response["done"]

    if "error" in parsed_response:
        logger.warning(f"Execution blocked by model: {parsed_response['error']}")
        return True, f"Execution blocked: {parsed_response['error']}"

    if "replace_in_file" in parsed_response:
        edit_data = parsed_response["replace_in_file"]
        logger.info(f"Editing file {edit_data.get('path')}")
        res = safe_file_edit(
            edit_data.get("path"), 
            edit_data.get("old_string"), 
            edit_data.get("new_string"), 
            settings.OS_PASSWORD
        )
        messages.append({"role": "user", "content": f"File edit result: {json.dumps(res)}"})
        return False, ""

    if "write_file" in parsed_response:
        write_data = parsed_response["write_file"]
        file_path = write_data.get("path")
        logger.info(f"Writing new file to {file_path}")
        
        encoded_content = base64.b64encode(write_data.get("content", "").encode('utf-8')).decode('utf-8')
        write_cmd = f"echo '{encoded_content}' | base64 -d | sudo -S tee {file_path} > /dev/null"
        res = execute_single_command(write_cmd)
        
        messages.append({"role": "user", "content": f"File write result: {json.dumps({'success': res['success'], 'error': res.get('stderr', '')})}"})
        return False, ""

    if "search" in parsed_response:
        query = parsed_response["search"]
        logger.info(f"Executing search: {query}")
        try:
            search_results = DDGS().text(query, max_results=3)
            formatted_results = "\n".join([f"Title: {r['title']}\nLink: {r['href']}\nSnippet: {r['body']}" for r in search_results])
            messages.append({"role": "user", "content": f"Search results for '{query}':\n{formatted_results}\n\nAnalyze these snippets. If you need full page content, use 'fetch_webpage'. Otherwise, output 'done' or next action."})
        except Exception as e:
            logger.error(f"Search failed: {e}")
            messages.append({"role": "user", "content": f"Search failed: {e}"})
        return False, ""

    if "fetch_webpage" in parsed_response:
        url = parsed_response["fetch_webpage"]
        logger.info(f"Fetching webpage content: {url}")
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as http_client:
                res = http_client.get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64)"})
                # Очистка HTML от лишнего
                text_content = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', res.text)
                text_content = re.sub(r'<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>', '', text_content)
                text_content = re.sub(r'<[^>]+>', ' ', text_content)
                text_content = re.sub(r'\s+', ' ', text_content).strip()
                
            messages.append({"role": "user", "content": f"Raw text content of URL <{url}>:\n\"\"\"\n{text_content[:4000]}\n\"\"\"\nExtract required information from this text."})
        except Exception as e:
            logger.error(f"Failed to fetch webpage {url}: {e}")
            messages.append({"role": "user", "content": f"Failed to fetch webpage: {e}"})
        return False, ""

    if "commands" in parsed_response and isinstance(parsed_response["commands"], list):
        execution_results = []
        for cmd in parsed_response["commands"]:
            logger.info(f"Executing command: {cmd}")
            res = execute_single_command(cmd)
            execution_results.append(res)
            
            if res["success"]:
                task_context["completed_steps"].append(cmd)
            else:
                error_msg = f"{cmd} -> {res.get('stderr', '')[:200]}"
                task_context["facts"].append(f"Command failed: {error_msg}")
                task_context["last_error"] = error_msg
                logger.warning(f"Command failed with code {res['return_code']}: {res['stderr']}")
                break  # Прерываем цепочку команд при ошибке
                
        messages.append({"role": "user", "content": f"Execution results:\n{json.dumps(execution_results)}\nAnalyze these results. If task is complete, return {{'done': 'message'}}. If further action is needed, return {{'commands': [...]}}"})
        return False, ""

    # Если JSON распарсился, но нет известных ключей
    logger.warning("LLM response missing known action keys. Sending error back.")
    messages.append({"role": "user", "content": "System error: Missing or invalid action key. Please provide exactly one valid key: 'commands', 'search', 'fetch_webpage', 'replace_in_file', 'write_file' or 'done'."})
    return False, ""


def llm_request(input_text: str, provider: str = "ollama") -> str:
    logger.info(f"Starting agentic loop via '{provider}'. Task: '{input_text}'")
    
    messages = [{"role": "system", "content": settings.SYSTEM_PROMPT}]
    task_context = {
        "task": input_text,
        "completed_steps": [],
        "facts": [],
        "last_error": None,
    }
    
    for iteration in range(settings.MAX_ITERATIONS):
        logger.info(f"--- Iteration {iteration + 1}/{settings.MAX_ITERATIONS} ---")
        
        # Обновление контекста текущего шага
        messages.append({
            "role": "user",
            "content": f"{input_text}\n\n{_build_context_message(task_context)}"
        })

        try:
            ai_message = _get_llm_response(messages, provider)
        except Exception as e:
            logger.error(f"LLM request failed via {provider}: {str(e)}")
            return f"Error during LLM request ({provider}): {str(e)}"

        # Запись ответа в историю
        messages.append({"role": "assistant", "content": ai_message})
        logger.info(f"LLM output: {ai_message}")
        
        # Валидация ответа LLM
        try:
            parsed_response = json.loads(ai_message.strip(), strict=False)
            if not isinstance(parsed_response, dict):
                raise TypeError("Response is not a JSON object (dict)")
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Invalid JSON format: {str(e)}. Sending error back to LLM.")
            messages.append({"role": "user", "content": "System error: Your response was not a valid JSON object. Fix the formatting and return ONLY a valid JSON object. Ensure all strings with newlines are properly escaped inside JSON."})
            continue

        # Обработка действий (мутирует messages и task_context)
        is_done, final_result = _handle_tool_execution(parsed_response, task_context, messages)
        if is_done:
            return final_result

    logger.error("Maximum iterations reached. Terminating loop.")
    return "Task terminated: Exceeded maximum iterations limit."