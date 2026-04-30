import os
import json
import re
import time
import urllib.request
import urllib.error


class LLMError(Exception):
    pass


def call_llm(system_prompt, user_prompt, max_tokens=800, max_retries=2, timeout_s=22.0):
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY not set")

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode("utf-8")

    last_err = None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
            return data["content"][0]["text"]
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 or e.code >= 500:
                if attempt < max_retries:
                    time.sleep((2 ** attempt) * 0.5)
                    continue
            raise LLMError("HTTP " + str(e.code) + ": " + str(e.reason))
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                time.sleep((2 ** attempt) * 0.3)
                continue
            raise LLMError("Error: " + str(e)[:100])
    raise LLMError("All retries exhausted: " + str(last_err))


def call_llm_json(system_prompt, user_prompt, max_tokens=800, timeout_s=22.0):
    def parse(raw):
        cleaned = raw.strip()
        if "```" in cleaned:
            cleaned = cleaned.split("```")[-2] if "```" in cleaned else cleaned
            cleaned = re.sub(r"^json\n?", "", cleaned).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)
        return json.loads(cleaned)

    raw = call_llm(system_prompt, user_prompt, max_tokens, timeout_s=timeout_s)
    try:
        return parse(raw)
    except json.JSONDecodeError:
        retry = user_prompt + "\n\nRespond with ONLY a valid JSON object. No markdown."
        return parse(call_llm(system_prompt, retry, max_tokens, max_retries=1, timeout_s=timeout_s))