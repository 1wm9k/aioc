import subprocess
import json
import re
import logging
import tempfile
import os
from typing import List, Dict, Any
from src.config import settings

logger = logging.getLogger(__name__)

def parse_commands(llm_response: str) -> List[str]:
    """Вытаскивает чистый JSON из ответа модели, даже если там маркдаун."""
    text = llm_response.strip()
    match = re.search(r"```(?:json)?(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
        
    try:
        commands = json.loads(text, strict=False)
        if isinstance(commands, list):
            if commands and isinstance(commands[0], dict) and "error" in commands[0]:
                logger.warning(f"Blocked by model: {commands[0]['error']}")
                return []
            return [str(cmd) for cmd in commands]
        return []
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON: {llm_response}")
        return []

def execute_single_command(command: str) -> Dict[str, Any]:
    command = command.strip()
    
    # Автоподстановка -S для всех sudo в пайплайне
    if settings.OS_PASSWORD and "sudo " in command and "sudo -S" not in command:
        command = re.sub(r'(^|&&|\|\||;|\|)\s*sudo\s+', r'\1 sudo -S ', command)

    kwargs = {
        "shell": True,
        "capture_output": True,
        "text": True,
        "timeout": 60
    }
    
    if settings.OS_PASSWORD and "sudo -S" in command:
        kwargs["input"] = f"{settings.OS_PASSWORD}\n"

    # Фоновые команды (&)
    if command.endswith("&"):
        try:
            popen_kwargs = {
                "shell": True,
                "text": True,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL
            }
            process = subprocess.Popen(command, **popen_kwargs)
            return {
                "command": command,
                "return_code": 0,
                "stdout": f"Background process started. PID: {process.pid}",
                "stderr": "",
                "success": True
            }
        except Exception as e:
            return {
                "command": command,
                "return_code": -1,
                "stdout": "",
                "stderr": str(e),
                "success": False
            }

    # Синхронные команды
    try:
        result = subprocess.run(command, **kwargs)
        return {
            "command": command,
            "return_code": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "success": result.returncode == 0
        }
    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "return_code": -1,
            "stdout": "",
            "stderr": "Command execution timed out after 60 seconds",
            "success": False
        }
    except Exception as e:
        return {
            "command": command,
            "return_code": -1,
            "stdout": "",
            "stderr": str(e),
            "success": False
        }

def is_command_acceptable(command: str, return_code: int) -> bool:
    """
    Определяет, является ли код возврата ошибкой для конкретной команды.
    Для утилит проверки (grep, ls, which и т.д.) ненулевой код — это нормальный ответ.
    """
    if return_code == 0:
        return True
        
    # Очищаем команду от sudo и флагов для анализа исполняемого файла
    clean_cmd = re.sub(r'^sudo(\s+-S)?\s+', '', command.strip())
    
    # Список утилит, чей статус-код не означает крах пайплайна
    soft_commands = ['grep', 'ls', 'which', 'pg_isready', 'test', 'find', 'dpkg']
    
    if any(clean_cmd.startswith(pkg) for pkg in soft_commands):
        return True # Не прерываем пайплайн, это просто проверка
        
    return False

def run_pipeline(llm_response: str) -> List[Dict[str, Any]]:
    commands = parse_commands(llm_response)
    if not commands:
        return [{"error": "No valid commands to execute"}]
        
    execution_results = []
    for cmd in commands:
        res = execute_single_command(cmd)
        execution_results.append(res)
        
        # Переопределяем успех с учетом специфики команды
        is_ok = is_command_acceptable(cmd, res["return_code"])
        
        # Корректируем флаг success для модели, чтобы она понимала, что это штатный результат
        if is_ok and res["return_code"] != 0:
            res["success"] = True
            
        if not is_ok:
            logger.warning(f"Pipeline stopped due to critical error in command: {cmd} (code: {res['return_code']})")
            break
            
    return execution_results

def safe_file_edit(file_path: str, old_text: str, new_text: str, password: str) -> Dict[str, Any]:
    """Безопасная перезапись через временный файл (исключает локи и кривые потоки ввода)."""
    read_cmd = f"sudo -S cat {file_path}" if password else f"cat {file_path}"
    read_kwargs = {"shell": True, "capture_output": True, "text": True}
    if password:
        read_kwargs["input"] = f"{password}\n"
        
    try:
        read_result = subprocess.run(read_cmd, **read_kwargs)
        if read_result.returncode != 0:
            return {"success": False, "error": f"Read failed: {read_result.stderr.strip()}"}
            
        content = read_result.stdout
        if old_text not in content:
            return {"success": False, "error": f"Substring '{old_text}' not found"}
            
        updated_content = content.replace(old_text, new_text)
        
        # Создаем временный файл
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tf:
            tf.write(updated_content)
            temp_path = tf.name

        # Копируем поверх оригинала (сохраняет владельца и права исходного файла)
        write_cmd = f"sudo -S cp {temp_path} {file_path}" if password else f"cp {temp_path} {file_path}"
        write_kwargs = {"shell": True, "capture_output": True, "text": True}
        if password:
            write_kwargs["input"] = f"{password}\n"
            
        write_result = subprocess.run(write_cmd, **write_kwargs)
        
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        if write_result.returncode != 0:
            return {"success": False, "error": f"Write failed: {write_result.stderr.strip()}"}
            
        return {"success": True, "message": f"Successfully updated {file_path}"}
        
    except Exception as e:
        return {"success": False, "error": str(e)}