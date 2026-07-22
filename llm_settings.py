import json
import os

from utils import LLM_URL

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'llm_settings.json')
DEFAULT_MODEL = 'qwen3.6:latest'

_settings = {'llm_url': LLM_URL, 'llm_model': DEFAULT_MODEL}


def _save():
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(_settings, f, indent=2)


def _load():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE) as f:
                saved = json.load(f)
            _settings.update({k: v for k, v in saved.items() if k in _settings and v})
        except (json.JSONDecodeError, OSError):
            pass
    else:
        _save()


_load()


def get_llm_url():
    return _settings['llm_url']


def get_llm_model():
    return _settings['llm_model']


def update_llm_settings(llm_url=None, llm_model=None):
    if llm_url:
        _settings['llm_url'] = llm_url.rstrip('/')
    if llm_model:
        _settings['llm_model'] = llm_model
    _save()
    return dict(_settings)
