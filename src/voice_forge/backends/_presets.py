"""Hardcoded preset catalogs for preset-only TTS backends.

Each backend that ships pre-trained voices (kokoro, piper, melotts) declares
its ``KNOWN_PRESETS`` here so the /lab preset browser can list + sample
them without per-host model-cache crawling.

The catalogs are intentionally curated subsets:

- Kokoro: full upstream set (~54 voices) since they all ship with the
  ~330 MB model — no per-voice download.
- Piper: ~20 curated voices spanning major languages. Each is a separate
  ~30-50 MB ONNX file that piper-tts downloads from HF on first sample
  call. The full ~100-voice Piper catalog is too long for casual browsing.
- MeloTTS: language presets (not speaker names) — each "preset" maps to a
  language code; the model picks the speaker.

To grow these lists, edit this file. They're hardcoded (not auto-discovered)
because the upstream APIs don't all expose enumerable preset lists, and
curating gives us a chance to label them with language + gender for the UI.
"""

from __future__ import annotations

KOKORO_PRESETS: list[dict] = [
    # American English female
    {"id": "af_alloy", "language": "en-us", "gender": "f", "label": "Alloy"},
    {"id": "af_aoede", "language": "en-us", "gender": "f", "label": "Aoede"},
    {"id": "af_bella", "language": "en-us", "gender": "f", "label": "Bella"},
    {"id": "af_heart", "language": "en-us", "gender": "f", "label": "Heart"},
    {"id": "af_jadzia", "language": "en-us", "gender": "f", "label": "Jadzia"},
    {"id": "af_jessica", "language": "en-us", "gender": "f", "label": "Jessica"},
    {"id": "af_kore", "language": "en-us", "gender": "f", "label": "Kore"},
    {"id": "af_nicole", "language": "en-us", "gender": "f", "label": "Nicole"},
    {"id": "af_nova", "language": "en-us", "gender": "f", "label": "Nova"},
    {"id": "af_river", "language": "en-us", "gender": "f", "label": "River"},
    {"id": "af_sarah", "language": "en-us", "gender": "f", "label": "Sarah"},
    {"id": "af_sky", "language": "en-us", "gender": "f", "label": "Sky"},
    {"id": "af_v0bella", "language": "en-us", "gender": "f", "label": "Bella (v0)"},
    {"id": "af_v0irulan", "language": "en-us", "gender": "f", "label": "Irulan (v0)"},
    # American English male
    {"id": "am_adam", "language": "en-us", "gender": "m", "label": "Adam"},
    {"id": "am_echo", "language": "en-us", "gender": "m", "label": "Echo"},
    {"id": "am_eric", "language": "en-us", "gender": "m", "label": "Eric"},
    {"id": "am_fenrir", "language": "en-us", "gender": "m", "label": "Fenrir"},
    {"id": "am_liam", "language": "en-us", "gender": "m", "label": "Liam"},
    {"id": "am_michael", "language": "en-us", "gender": "m", "label": "Michael"},
    {"id": "am_onyx", "language": "en-us", "gender": "m", "label": "Onyx"},
    {"id": "am_puck", "language": "en-us", "gender": "m", "label": "Puck"},
    {"id": "am_santa", "language": "en-us", "gender": "m", "label": "Santa"},
    {"id": "am_v0adam", "language": "en-us", "gender": "m", "label": "Adam (v0)"},
    {"id": "am_v0gurney", "language": "en-us", "gender": "m", "label": "Gurney (v0)"},
    # British English female
    {"id": "bf_alice", "language": "en-gb", "gender": "f", "label": "Alice"},
    {"id": "bf_emma", "language": "en-gb", "gender": "f", "label": "Emma"},
    {"id": "bf_isabella", "language": "en-gb", "gender": "f", "label": "Isabella"},
    {"id": "bf_lily", "language": "en-gb", "gender": "f", "label": "Lily"},
    # British English male
    {"id": "bm_daniel", "language": "en-gb", "gender": "m", "label": "Daniel"},
    {"id": "bm_fable", "language": "en-gb", "gender": "m", "label": "Fable"},
    {"id": "bm_george", "language": "en-gb", "gender": "m", "label": "George"},
    {"id": "bm_lewis", "language": "en-gb", "gender": "m", "label": "Lewis"},
    # European Spanish + Portuguese + French + Italian + Hindi + Japanese + Chinese
    {"id": "ef_dora", "language": "es", "gender": "f", "label": "Dora"},
    {"id": "em_alex", "language": "es", "gender": "m", "label": "Alex"},
    {"id": "em_santa", "language": "es", "gender": "m", "label": "Santa"},
    {"id": "ff_siwis", "language": "fr", "gender": "f", "label": "Siwis"},
    {"id": "hf_alpha", "language": "hi", "gender": "f", "label": "Alpha"},
    {"id": "hf_beta", "language": "hi", "gender": "f", "label": "Beta"},
    {"id": "hm_omega", "language": "hi", "gender": "m", "label": "Omega"},
    {"id": "hm_psi", "language": "hi", "gender": "m", "label": "Psi"},
    {"id": "if_sara", "language": "it", "gender": "f", "label": "Sara"},
    {"id": "im_nicola", "language": "it", "gender": "m", "label": "Nicola"},
    {"id": "jf_alpha", "language": "ja", "gender": "f", "label": "Alpha"},
    {"id": "jf_gongitsune", "language": "ja", "gender": "f", "label": "Gongitsune"},
    {"id": "jf_nezumi", "language": "ja", "gender": "f", "label": "Nezumi"},
    {"id": "jf_tebukuro", "language": "ja", "gender": "f", "label": "Tebukuro"},
    {"id": "jm_kumo", "language": "ja", "gender": "m", "label": "Kumo"},
    {"id": "pf_dora", "language": "pt-br", "gender": "f", "label": "Dora"},
    {"id": "pm_alex", "language": "pt-br", "gender": "m", "label": "Alex"},
    {"id": "pm_santa", "language": "pt-br", "gender": "m", "label": "Santa"},
    {"id": "zf_xiaobei", "language": "zh", "gender": "f", "label": "Xiaobei"},
    {"id": "zf_xiaoni", "language": "zh", "gender": "f", "label": "Xiaoni"},
    {"id": "zf_xiaoxiao", "language": "zh", "gender": "f", "label": "Xiaoxiao"},
    {"id": "zf_xiaoyi", "language": "zh", "gender": "f", "label": "Xiaoyi"},
    {"id": "zm_yunjian", "language": "zh", "gender": "m", "label": "Yunjian"},
    {"id": "zm_yunxi", "language": "zh", "gender": "m", "label": "Yunxi"},
    {"id": "zm_yunxia", "language": "zh", "gender": "m", "label": "Yunxia"},
    {"id": "zm_yunyang", "language": "zh", "gender": "m", "label": "Yunyang"},
]

# Curated Piper voice set — full list at https://huggingface.co/rhasspy/piper-voices
# Each downloads ~30-50 MB ONNX on first sample call. Quality "medium" balances
# size and naturalness; "high" is +50% size for marginally better prosody.
PIPER_PRESETS: list[dict] = [
    # English US
    {"id": "en_US-amy-medium", "language": "en-us", "gender": "f", "label": "Amy (US, medium)"},
    {"id": "en_US-amy-low", "language": "en-us", "gender": "f", "label": "Amy (US, low)"},
    {
        "id": "en_US-lessac-medium",
        "language": "en-us",
        "gender": "f",
        "label": "Lessac (US, medium)",
    },
    {"id": "en_US-lessac-high", "language": "en-us", "gender": "f", "label": "Lessac (US, high)"},
    {
        "id": "en_US-libritts-high",
        "language": "en-us",
        "gender": "n",
        "label": "LibriTTS (US, multi)",
    },
    {"id": "en_US-ryan-medium", "language": "en-us", "gender": "m", "label": "Ryan (US, medium)"},
    {"id": "en_US-ryan-high", "language": "en-us", "gender": "m", "label": "Ryan (US, high)"},
    # English GB
    {"id": "en_GB-alan-medium", "language": "en-gb", "gender": "m", "label": "Alan (GB, medium)"},
    {
        "id": "en_GB-cori-high",
        "language": "en-gb",
        "gender": "f",
        "label": "Cori (GB, high)",
    },
    {
        "id": "en_GB-northern_english_male-medium",
        "language": "en-gb",
        "gender": "m",
        "label": "Northern English Male",
    },
    {
        "id": "en_GB-southern_english_female-low",
        "language": "en-gb",
        "gender": "f",
        "label": "Southern English Female",
    },
    # Other languages — one voice each (download-on-demand)
    {"id": "es_ES-sharvard-medium", "language": "es", "gender": "n", "label": "Sharvard (ES)"},
    {"id": "fr_FR-siwis-medium", "language": "fr", "gender": "f", "label": "Siwis (FR)"},
    {"id": "de_DE-thorsten-medium", "language": "de", "gender": "m", "label": "Thorsten (DE)"},
    {"id": "it_IT-riccardo-x_low", "language": "it", "gender": "m", "label": "Riccardo (IT)"},
    {"id": "nl_NL-mls-medium", "language": "nl", "gender": "n", "label": "MLS (NL)"},
    {"id": "pt_BR-faber-medium", "language": "pt-br", "gender": "m", "label": "Faber (BR)"},
    {"id": "zh_CN-huayan-medium", "language": "zh", "gender": "f", "label": "Huayan (CN)"},
    {"id": "ru_RU-irina-medium", "language": "ru", "gender": "f", "label": "Irina (RU)"},
]

# MeloTTS — preset IDs are language codes; each language carries a single
# (or curated) speaker. Provisioning is currently blocked on arm64 macOS
# (see LEARNINGS 2026-05-25 § "Upstream packaging defects").
MELOTTS_PRESETS: list[dict] = [
    {"id": "EN-US", "language": "en-us", "gender": "n", "label": "EN-US"},
    {"id": "EN-BR", "language": "en-gb", "gender": "n", "label": "EN-BR (British)"},
    {"id": "EN-INDIA", "language": "en-in", "gender": "n", "label": "EN-INDIA"},
    {"id": "EN-AU", "language": "en-au", "gender": "n", "label": "EN-AU"},
    {"id": "EN_NEWEST", "language": "en-us", "gender": "n", "label": "EN (newest)"},
    {"id": "ES", "language": "es", "gender": "n", "label": "Español"},
    {"id": "FR", "language": "fr", "gender": "n", "label": "Français"},
    {"id": "ZH", "language": "zh", "gender": "n", "label": "中文"},
    {"id": "JP", "language": "ja", "gender": "n", "label": "日本語"},
    {"id": "KR", "language": "ko", "gender": "n", "label": "한국어"},
]
