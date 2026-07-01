from setuptools import setup, find_packages

setup(
    name="aritiq",
    version="0.2.0",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "pydantic>=2",          # strict validation of LLM extraction output
        "certifi>=2023.7.22",   # CA bundle for verifying sec.gov TLS (EDGAR fetch)
    ],
    extras_require={
        # Model backends — install whichever you call. Neither is required to
        # run the verifier, the tests, or the offline (replay) benchmark.
        "anthropic": ["anthropic>=0.39"],
        "openai": ["openai>=1.0"],
        "gemini": ["google-genai>=1.0"],
        "api": ["fastapi>=0.115", "uvicorn[standard]>=0.30"],
        "dev": ["pytest>=7"],
    },
)
