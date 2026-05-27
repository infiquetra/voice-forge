"""Test-only stub modules.

Modules in this package are NOT shipped with voice-forge. They exist solely
so unit tests can inject fakes via ``sys.modules`` or ``_BACKEND_MODULES``
without depending on optional runtime libraries (neutts, llama_cpp, kokoro).
"""
