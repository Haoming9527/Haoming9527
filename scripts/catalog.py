"""What the profile can recognise: tools detected from repository manifests, and logos.

Adding a tool here is enough for it to appear on the profile once a repository uses it.
Logos resolve in order: a file in assets/logos, the remote source listed here, then an
automatic guess against Devicon and Simple Icons. The collector caches remote logos in
the snapshot, so a new language or tool gets its logo without anyone editing the repo.
"""
from __future__ import annotations

import hashlib
import json
import re

DEVICON = "https://cdn.jsdelivr.net/npm/devicon@2.17.0/icons/{}.svg"
SIMPLE_ICONS = "https://cdn.jsdelivr.net/npm/simple-icons@16.35.0/icons/{}.svg"

# Logos shipped in assets/logos: name -> (file, share of the disc it fills).
VENDORED = {
    "JavaScript": ("javascript.svg", .56), "TypeScript": ("typescript.svg", .56), "HTML": ("html.svg", .6),
    "CSS": ("css.svg", .6), "Java": ("java.svg", .62), "Go": ("go.svg", .7), "PLpgSQL": ("postgresql.svg", .6),
    "Shell": ("shell.svg", .6), "Batchfile": ("batchfile.svg", .5), "Rust": ("rust.svg", .62),
    "Dockerfile": ("docker.svg", .64), "PowerShell": ("powershell.svg", .6),
    "React": ("react.svg", .64), "Next.js": ("nextjs.svg", .6), "Node.js": ("nodejs.svg", .6),
    "PostgreSQL": ("postgresql.svg", .6), "Docker": ("docker.svg", .64), "Ollama": ("ollama.svg", .56),
    "AI SDK": ("aisdk.svg", .5), "MCP": ("mcp.svg", .56), "OpenAI": ("openai.svg", .58), "Vercel": ("aisdk.svg", .5),
    "Gemini": ("gemini.svg", .6),
}

# Remote logos for names without a vendored file. ("devicon", path) or ("si", slug, hex colour).
REMOTE = {
    "Python": ("devicon", "python/python-original"), "Kotlin": ("devicon", "kotlin/kotlin-original"),
    "Swift": ("devicon", "swift/swift-original"), "C#": ("devicon", "csharp/csharp-original"),
    "C++": ("devicon", "cplusplus/cplusplus-original"), "C": ("devicon", "c/c-original"),
    "Ruby": ("devicon", "ruby/ruby-original"), "PHP": ("devicon", "php/php-original"),
    "Dart": ("devicon", "dart/dart-original"), "Lua": ("devicon", "lua/lua-original"),
    "Vue": ("devicon", "vuejs/vuejs-original"), "Svelte": ("devicon", "svelte/svelte-original"),
    "SCSS": ("devicon", "sass/sass-original"), "Jupyter Notebook": ("devicon", "jupyter/jupyter-original"),
    "Solidity": ("devicon", "solidity/solidity-original"), "R": ("devicon", "r/r-original"),
    "Scala": ("devicon", "scala/scala-original"), "Elixir": ("devicon", "elixir/elixir-original"),
    "Haskell": ("devicon", "haskell/haskell-original"), "Zig": ("devicon", "zig/zig-original"),
    "Astro": ("devicon", "astro/astro-original"), "HCL": ("devicon", "terraform/terraform-original"),
    "Objective-C": ("devicon", "objectivec/objectivec-plain"), "Perl": ("devicon", "perl/perl-original"),
    "Julia": ("devicon", "julia/julia-original"), "MDX": ("si", "mdx", "1B1F24"), "EJS": ("si", "ejs", "B4CA65"),
    "Nuxt": ("devicon", "nuxtjs/nuxtjs-original"), "Angular": ("devicon", "angularjs/angularjs-original"),
    "Tailwind CSS": ("devicon", "tailwindcss/tailwindcss-original"), "Vite": ("devicon", "vitejs/vitejs-original"),
    "Three.js": ("devicon", "threejs/threejs-original"), "Electron": ("devicon", "electron/electron-original"),
    "React Native": ("devicon", "react/react-original"), "Express": ("si", "express", "000000"),
    "NestJS": ("devicon", "nestjs/nestjs-original"), "FastAPI": ("devicon", "fastapi/fastapi-original"),
    "Flask": ("devicon", "flask/flask-original"), "Django": ("devicon", "django/django-plain"),
    "Spring": ("devicon", "spring/spring-original"), "Gin": ("si", "gin", "008ECF"),
    "Socket.IO": ("devicon", "socketio/socketio-original"), "Bun": ("devicon", "bun/bun-original"),
    "MySQL": ("devicon", "mysql/mysql-original"), "MongoDB": ("devicon", "mongodb/mongodb-original"),
    "Redis": ("devicon", "redis/redis-original"), "SQLite": ("devicon", "sqlite/sqlite-original"),
    "Prisma": ("devicon", "prisma/prisma-original"), "Drizzle": ("si", "drizzle", "C5F74F"),
    "Supabase": ("devicon", "supabase/supabase-original"), "Firebase": ("devicon", "firebase/firebase-original"),
    "Anthropic": ("si", "anthropic", "191919"),
    "LangChain": ("si", "langchain", "1C3C3C"), "Hugging Face": ("si", "huggingface", "FFD21E"),
    "PyTorch": ("devicon", "pytorch/pytorch-original"), "TensorFlow": ("devicon", "tensorflow/tensorflow-original"),
    "pandas": ("devicon", "pandas/pandas-original"), "NumPy": ("devicon", "numpy/numpy-original"),
    "Kubernetes": ("devicon", "kubernetes/kubernetes-original"), "Terraform": ("devicon", "terraform/terraform-original"),
    "GitHub Actions": ("devicon", "githubactions/githubactions-original"), "Jest": ("devicon", "jest/jest-plain"),
    "Vitest": ("devicon", "vitest/vitest-original"), "Playwright": ("devicon", "playwright/playwright-original"),
    "Stripe": ("si", "stripe", "635BFF"), "XRPL": ("si", "xrp", "23292F"),
    "Chrome Extensions": ("devicon", "chrome/chrome-original"), "Expo": ("si", "expo", "000020"),
}

# Detection rules. npm/python/cargo: exact package names; npm_prefix: package prefixes;
# go/maven/text: substrings of go.mod, pom.xml/build.gradle, or compose/Dockerfile text;
# files: file names anywhere in the tree; paths: substrings of any path.
TOOLS = {
    "Node.js": {"files": ["package.json"]},
    "React": {"npm": ["react"]},
    "Next.js": {"npm": ["next"]},
    "Vue": {"npm": ["vue"]},
    "Nuxt": {"npm": ["nuxt"]},
    "Svelte": {"npm": ["svelte"]},
    "Angular": {"npm": ["@angular/core"]},
    "React Native": {"npm": ["react-native"]},
    "Expo": {"npm": ["expo"]},
    "Electron": {"npm": ["electron"]},
    "Chrome Extensions": {"npm": ["wxt", "plasmo", "@crxjs/vite-plugin"], "npm_prefix": ["@types/chrome"]},
    "Tailwind CSS": {"npm": ["tailwindcss"], "npm_prefix": ["@tailwindcss/"]},
    "Vite": {"npm": ["vite"]},
    "Three.js": {"npm": ["three"]},
    "Socket.IO": {"npm": ["socket.io", "socket.io-client"]},
    "Express": {"npm": ["express"]},
    "NestJS": {"npm": ["@nestjs/core"]},
    "Bun": {"files": ["bun.lockb", "bun.lock"]},
    "FastAPI": {"python": ["fastapi"]},
    "Flask": {"python": ["flask"]},
    "Django": {"python": ["django"]},
    "Spring": {"maven": ["spring-boot"]},
    "Gin": {"go": ["gin-gonic/gin"]},
    "PostgreSQL": {"npm": ["pg", "postgres", "pg-promise", "@neondatabase/serverless", "@vercel/postgres"],
                   "python": ["psycopg", "psycopg2", "psycopg2-binary", "asyncpg"],
                   "go": ["jackc/pgx", "lib/pq"], "text": ["postgres"]},
    "MySQL": {"npm": ["mysql", "mysql2"], "python": ["pymysql", "mysqlclient"], "maven": ["mysql-connector"],
              "text": ["image: mysql", "image: mariadb"]},
    "MongoDB": {"npm": ["mongodb", "mongoose"], "python": ["pymongo", "motor"], "text": ["image: mongo"]},
    "Redis": {"npm": ["redis", "ioredis"], "python": ["redis"], "go": ["redis/go-redis"], "text": ["image: redis"]},
    "SQLite": {"npm": ["sqlite3", "better-sqlite3", "sqlite"], "python": ["sqlite-utils"]},
    "Prisma": {"npm": ["prisma", "@prisma/client"], "files": ["schema.prisma"]},
    "Drizzle": {"npm": ["drizzle-orm"]},
    "Supabase": {"npm": ["@supabase/supabase-js", "@supabase/ssr"], "python": ["supabase"]},
    "Firebase": {"npm": ["firebase", "firebase-admin"], "files": ["firebase.json"]},
    "AI SDK": {"npm": ["ai"], "npm_prefix": ["@ai-sdk/"]},
    "OpenAI": {"npm": ["openai", "@ai-sdk/openai"], "python": ["openai"], "go": ["sashabaranov/go-openai", "openai/openai-go"]},
    "Anthropic": {"npm": ["@anthropic-ai/sdk", "@ai-sdk/anthropic"], "python": ["anthropic"]},
    "Gemini": {"npm": ["@google/generative-ai", "@google/genai", "@ai-sdk/google"],
               "python": ["google-generativeai", "google-genai"]},
    "LangChain": {"npm": ["langchain"], "npm_prefix": ["@langchain/"], "python": ["langchain"]},
    "Hugging Face": {"npm_prefix": ["@huggingface/"], "python": ["transformers", "huggingface-hub"]},
    "Ollama": {"npm": ["ollama"], "npm_prefix": ["ollama-ai-provider"], "python": ["ollama"], "go": ["ollama/ollama"],
               "text": ["ollama"]},
    "MCP": {"npm": ["@modelcontextprotocol/sdk"], "python": ["mcp", "fastmcp"],
            "go": ["modelcontextprotocol/go-sdk", "mark3labs/mcp-go"]},
    "PyTorch": {"python": ["torch"]},
    "TensorFlow": {"python": ["tensorflow"]},
    "pandas": {"python": ["pandas"]},
    "NumPy": {"python": ["numpy"]},
    "Docker": {"files": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"]},
    "Kubernetes": {"files": ["Chart.yaml", "kustomization.yaml"]},
    "Terraform": {"paths": [".tf"]},
    "GitHub Actions": {"paths": [".github/workflows/"]},
    "Vercel": {"files": ["vercel.json"]},
    "Jest": {"npm": ["jest"]},
    "Vitest": {"npm": ["vitest"]},
    "Playwright": {"npm": ["@playwright/test", "playwright"], "python": ["playwright"]},
    "Stripe": {"npm": ["stripe", "@stripe/stripe-js"], "python": ["stripe"]},
    "XRPL": {"npm": ["xrpl"], "python": ["xrpl-py"]},
}

# Manifests the collector reads to learn which packages a repository depends on.
MANIFESTS = ("package.json", "go.mod", "requirements.txt", "requirements-dev.txt", "pyproject.toml", "Pipfile",
             "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts", "Dockerfile", "docker-compose.yml",
             "docker-compose.yaml", "compose.yml", "compose.yaml")

RULES_VERSION = hashlib.sha256(json.dumps([TOOLS, MANIFESTS], sort_keys=True).encode()).hexdigest()[:12]


def tool_matches(rules: dict, facts: dict) -> bool:
    if set(rules.get("npm", ())) & facts["npm"] or set(rules.get("python", ())) & facts["python"]:
        return True
    if set(rules.get("cargo", ())) & facts["cargo"] or set(rules.get("files", ())) & facts["files"]:
        return True
    if any(name.startswith(prefix) for prefix in rules.get("npm_prefix", ()) for name in facts["npm"]):
        return True
    if any(token in facts["go"] for token in rules.get("go", ())) or any(token in facts["maven"] for token in rules.get("maven", ())):
        return True
    if any(token in facts["text"] for token in rules.get("text", ())):
        return True
    return any(token in path for token in rules.get("paths", ()) for path in facts["paths"])


def slug(name: str) -> str:
    """Simple Icons / Devicon style slug: "Next.js" -> "nextdotjs", "C++" -> "cplusplus"."""
    value = name.lower().replace("+", "plus").replace(".", "dot").replace("#", "sharp").replace("&", "and")
    return re.sub(r"[^a-z0-9]", "", value)


def logo_urls(name: str, colour: str = "000000") -> list[tuple[str, str | None]]:
    """Candidate (url, fill colour) pairs for a logo that is not vendored."""
    source = REMOTE.get(name)
    candidates = []
    if source and source[0] == "devicon":
        candidates.append((DEVICON.format(source[1]), None))
    elif source:
        candidates.append((SIMPLE_ICONS.format(source[1]), source[2]))
    guess = slug(name)
    if guess:
        candidates += [(DEVICON.format(f"{guess}/{guess}-original"), None), (DEVICON.format(f"{guess}/{guess}-plain"), None),
                       (SIMPLE_ICONS.format(guess), colour)]
    return list(dict.fromkeys(candidates))
