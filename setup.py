from setuptools import setup, find_packages

setup(
    name="aritiq",
    version="0.2.0",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        "pydantic>=2",          # strict validation of extraction output
        "certifi>=2023.7.22",   # CA bundle for verifying sec.gov TLS (EDGAR fetch)
        "python-dotenv>=1.0",   # loads your .env (BYOK settings)
    ],
    extras_require={
        # Model backends (BYOK) — install whichever matches ARITIQ_PROVIDER.
        # None are required to run the verifier, the tests, or the offline
        # (replay) demo.
        "anthropic": ["anthropic>=0.39"],
        "openai": ["openai>=1.0"],
        "gemini": ["google-genai>=1.0"],
        "api": ["fastapi>=0.115", "uvicorn[standard]>=0.30"],
        "dev": ["pytest>=7"],
    },
)
