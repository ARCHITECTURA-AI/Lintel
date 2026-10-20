"""Vocabulary for the deterministic checks.

TOOLS maps every alias to one canonical name. A tool named in a sentence must be named in a
cited fact. The list is deliberately broad: a tool missing from it falls through to the
proper-name check, which is stricter, not looser.
"""

from __future__ import annotations

_TOOL_GROUPS: dict[str, list[str]] = {
    "python": ["python", "python3"],
    "javascript": ["javascript", "js", "ecmascript"],
    "typescript": ["typescript", "ts"],
    "java": ["java"],
    "kotlin": ["kotlin"],
    "scala": ["scala"],
    "go": ["golang"],  # bare "Go" is handled case-sensitively
    "rust": ["rust"],
    "c++": ["c++", "cpp"],
    "c#": ["c#", "csharp"],
    "ruby": ["ruby"],
    "php": ["php"],
    "swift": [],
    "objective-c": ["objective-c"],
    "elixir": ["elixir"],
    "haskell": ["haskell"],
    "clojure": ["clojure"],
    "lua": ["lua"],
    "perl": ["perl"],
    "bash": ["bash", "shell scripting", "zsh"],
    "sql": ["sql"],
    "graphql": ["graphql"],
    "html": ["html", "html5"],
    "css": ["css", "css3", "scss", "sass"],
    "solidity": ["solidity"],
    "matlab": ["matlab"],
    # web frameworks
    "react": ["react", "react.js", "reactjs"],
    "react native": ["react native"],
    "next.js": ["next.js", "nextjs"],
    "vue": ["vue", "vue.js", "vuejs", "nuxt"],
    "angular": ["angular", "angularjs"],
    "svelte": ["svelte", "sveltekit"],
    "node.js": ["node", "node.js", "nodejs"],
    "express": ["express", "express.js"],
    "nestjs": ["nestjs", "nest.js"],
    "deno": ["deno"],
    "bun": ["bun"],
    "tailwind": ["tailwind", "tailwindcss"],
    "redux": ["redux"],
    "webpack": ["webpack"],
    "vite": ["vite"],
    "django": ["django"],
    "flask": ["flask"],
    "fastapi": ["fastapi"],
    "pydantic": ["pydantic"],
    "celery": ["celery"],
    "spring boot": ["spring boot", "springboot"],
    "rails": ["rails", "ruby on rails"],
    "laravel": ["laravel"],
    ".net": [".net", "dotnet", "asp.net"],
    "grpc": ["grpc"],
    "rest": ["rest", "restful"],
    "websockets": ["websocket", "websockets"],
    # data and ML
    "pytorch": ["pytorch", "torch"],
    "tensorflow": ["tensorflow"],
    "keras": ["keras"],
    "jax": ["jax"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "polars": ["polars"],
    "spark": ["spark", "pyspark", "apache spark"],
    "hadoop": ["hadoop"],
    "airflow": ["airflow", "apache airflow"],
    "dbt": ["dbt"],
    "kafka": ["kafka", "apache kafka"],
    "flink": ["flink"],
    "hugging face": ["hugging face", "huggingface", "transformers"],
    "langchain": ["langchain"],
    "langgraph": ["langgraph"],
    "llamaindex": ["llamaindex"],
    "openai api": ["openai api"],
    "anthropic api": ["anthropic api", "claude api"],
    "rag": ["rag", "retrieval-augmented generation", "retrieval augmented generation"],
    "llm": ["llm", "llms", "large language model", "large language models"],
    "mlflow": ["mlflow"],
    "weights & biases": ["wandb", "weights & biases"],
    "cuda": ["cuda"],
    "onnx": ["onnx"],
    "vllm": ["vllm"],
    "opencv": ["opencv"],
    "jupyter": ["jupyter"],
    "tableau": ["tableau"],
    "looker": ["looker"],
    "power bi": ["power bi"],
    "excel": ["excel"],
    # databases
    "postgres": ["postgres", "postgresql", "psql"],
    "mysql": ["mysql"],
    "sqlite": ["sqlite"],
    "mongodb": ["mongodb", "mongo"],
    "redis": ["redis"],
    "elasticsearch": ["elasticsearch", "elastic", "opensearch"],
    "cassandra": ["cassandra"],
    "dynamodb": ["dynamodb"],
    "snowflake": ["snowflake"],
    "bigquery": ["bigquery"],
    "redshift": ["redshift"],
    "clickhouse": ["clickhouse"],
    "neo4j": ["neo4j"],
    "pinecone": ["pinecone"],
    "pgvector": ["pgvector"],
    "supabase": ["supabase"],
    "firebase": ["firebase", "firestore"],
    "prisma": ["prisma"],
    "sqlalchemy": ["sqlalchemy"],
    "alembic": ["alembic"],
    # cloud and infra
    "aws": ["aws", "amazon web services"],
    "gcp": ["gcp", "google cloud", "google cloud platform"],
    "azure": ["azure"],
    "lambda": ["aws lambda"],
    "s3": ["s3"],
    "ec2": ["ec2"],
    "ecs": ["ecs"],
    "eks": ["eks"],
    "cloud run": ["cloud run"],
    "kubernetes": ["kubernetes", "k8s"],
    "docker": ["docker", "containers", "containerization"],
    "helm": ["helm"],
    "terraform": ["terraform"],
    "pulumi": ["pulumi"],
    "ansible": ["ansible"],
    "nginx": ["nginx"],
    "linux": ["linux", "ubuntu", "debian"],
    "vercel": ["vercel"],
    "netlify": ["netlify"],
    "heroku": ["heroku"],
    "cloudflare": ["cloudflare"],
    "rabbitmq": ["rabbitmq"],
    "sqs": ["sqs"],
    "pubsub": ["pub/sub", "pubsub"],
    "prometheus": ["prometheus"],
    "grafana": ["grafana"],
    "datadog": ["datadog"],
    "sentry": ["sentry"],
    "opentelemetry": ["opentelemetry", "otel"],
    "github actions": ["github actions"],
    "gitlab ci": ["gitlab ci"],
    "jenkins": ["jenkins"],
    "circleci": ["circleci"],
    "ci/cd": ["ci/cd", "cicd", "continuous integration", "continuous delivery", "continuous deployment"],
    "git": ["git"],
    "github": ["github"],
    "gitlab": ["gitlab"],
    # testing and tools
    "playwright": ["playwright"],
    "selenium": ["selenium"],
    "cypress": ["cypress"],
    "jest": ["jest"],
    "pytest": ["pytest"],
    "vitest": ["vitest"],
    "storybook": ["storybook"],
    "figma": ["figma"],
    "jira": ["jira"],
    "linear": [],
    "notion": [],
    "stripe": ["stripe api"],
    "twilio": ["twilio"],
    "oauth": ["oauth", "oauth2", "oidc", "openid connect"],
    "jwt": ["jwt"],
    "microservices": ["microservices", "microservice"],
    "serverless": ["serverless"],
    "unity": [],
    "unreal": ["unreal engine"],
    "ios": ["ios"],
    "android": ["android"],
    "flutter": ["flutter"],
    "electron": ["electron"],
    "wasm": ["wasm", "webassembly"],
    "kubeflow": ["kubeflow"],
    "ray": [],
}

# Words that are tools only when capitalized mid-sentence ("Go", "Swift", "Linear").
CASE_SENSITIVE_TOOLS: dict[str, str] = {
    "Go": "go",
    "Swift": "swift",
    "Linear": "linear",
    "Notion": "notion",
    "Unity": "unity",
    "Ray": "ray",
    "Stripe": "stripe",
    "R": "r",
    "C": "c",
}

TOOLS: dict[str, str] = {}
for canonical, aliases in _TOOL_GROUPS.items():
    TOOLS[canonical] = canonical
    for alias in aliases:
        TOOLS[alias] = canonical
for canonical in CASE_SENSITIVE_TOOLS.values():
    TOOLS.setdefault(canonical, canonical)
# Aliases that are also plain English ("the rest of", "excel at", "at the helm") count as tools
# only when written capitalized or upper-case in the sentence.
AMBIGUOUS_ALIASES = {
    "node", "express", "rest", "excel", "elastic", "containers", "bun", "transformers", "torch", "rails",
    "spark", "helm", "jest", "flask", "vue", "redux", "airflow", "polars", "sentry", "looker", "lambda",
    "celery", "prisma", "electron", "flutter", "ts", "js", "rag", "jax", "deno", "vite", "dbt",
}

MAX_TOOL_WORDS = max(len(k.split()) for k in TOOLS)

WELL_KNOWN_ORGS = [
    "Google", "Alphabet", "Meta", "Facebook", "Amazon", "AWS", "Apple", "Microsoft", "Netflix", "Uber",
    "Lyft", "Airbnb", "Stripe", "Shopify", "Atlassian", "Salesforce", "Oracle", "IBM", "Intel", "Nvidia",
    "AMD", "Adobe", "Spotify", "Twitter", "X Corp", "LinkedIn", "Snap", "Pinterest", "Dropbox", "Slack",
    "Zoom", "Coinbase", "Robinhood", "Databricks", "Snowflake", "OpenAI", "Anthropic", "DeepMind",
    "Cohere", "Mistral", "Hugging Face", "Scale AI", "Palantir", "Tesla", "SpaceX", "Infosys", "TCS",
    "Tata Consultancy Services", "Wipro", "HCL", "Accenture", "Deloitte", "McKinsey", "Goldman Sachs",
    "JPMorgan", "Morgan Stanley", "Flipkart", "Swiggy", "Zomato", "Razorpay", "Paytm", "PhonePe", "Ola",
    "Freshworks", "Zoho", "Byju's", "Cred", "Meesho", "Notion", "Figma", "Vercel", "Linear", "Ramp",
    "Brex", "Plaid", "Twilio", "Cloudflare", "Datadog", "GitHub", "GitLab", "Y Combinator", "MIT",
    "Stanford", "IIT", "IIT Bombay", "IIT Delhi", "IIT Madras", "BITS Pilani", "Harvard", "Berkeley",
]

# Capitalized words that never need a citation.
COMMON_CAPITALIZED = {
    "i", "i'm", "i've", "i'd", "i'll", "my", "me", "the", "a", "an", "and", "or", "but", "in", "on", "at",
    "for", "to", "of", "with", "by", "as", "this", "that", "these", "those", "it", "its", "we", "our", "you",
    "your", "they", "their", "he", "she", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "dear", "hiring", "manager", "team", "thanks", "thank", "best", "regards",
    "sincerely", "hi", "hello", "yes", "no", "n/a", "ok", "also", "when", "while", "after", "before",
    "during", "since", "from", "if", "because", "so", "then", "there", "here", "what", "which", "who",
    "how", "why", "today", "currently", "previously", "recently", "most", "all", "both", "each",
    "every", "some", "many", "more", "over", "under", "about", "between", "across", "through", "into",
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}
MONTH_NAMES = {v: k for k, v in MONTHS.items() if len(k) > 4 or k == "may" or k == "june" or k == "july"}

NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000, "million": 1_000_000, "dozen": 12, "twice": 2, "thrice": 3,
}
# "one" is only a quantity before a unit of time or a countable noun
ONE_UNITS = {"year", "years", "month", "months", "week", "weeks", "day", "days", "team", "person", "engineer", "service", "project", "client", "customer"}

VAGUE_MAGNITUDES = {
    "dozens": (24, 99),
    "hundreds": (100, 999),
    "thousands": (1000, 999_999),
    "millions": (1_000_000, 999_999_999),
    "billions": (1_000_000_000, 10**15),
}

PROFICIENCY_PHRASES: list[tuple[str, int]] = [
    (r"\bexpert(ise)?\b", 3),
    (r"\bdeep (knowledge|experience|expertise)\b", 3),
    (r"\badvanced\b", 3),
    (r"\bmaster(y|ed)?\b", 3),
    (r"\bextensive(ly)?\b", 3),
    (r"\bauthority\b", 3),
    (r"\bguru\b", 3),
    (r"\bseasoned\b", 3),
    (r"\bproficien(t|cy)\b", 2),
    (r"\bexperienced\b", 2),
    (r"\bstrong\b", 2),
    (r"\bsolid\b", 2),
    (r"\bskilled\b", 2),
    (r"\bcomfortable\b", 2),
    (r"\bhands-on\b", 2),
    (r"\bfamiliar(ity)?\b", 1),
    (r"\bexposure\b", 1),
    (r"\bbasic\b", 1),
    (r"\bbeginner\b", 1),
    (r"\bintroductory\b", 1),
    (r"\blearning\b", 1),
    (r"\bsome experience\b", 1),
]
PROFICIENCY_ATTR = {"familiar": 1, "working": 2, "expert": 3}
LEVEL_NAMES = {1: "familiar with", 2: "working experience with", 3: "expert in"}

LEADERSHIP = r"\b(led|lead(?:ing)?|managed|manag(?:e|ing)|mentor(?:ed|ing)?|supervis(?:ed|ing|e)|headed|direct(?:ed|ing) (?:a |the )?team|team lead|tech lead|people manager|managerial|oversaw|oversee)\b"

EMPLOYMENT_PATTERNS = [
    r"\b(worked|work|working) (at|for)\b",
    r"\bemployed\b",
    r"\bemployer\b",
    r"\b(my|our) (previous|current|last|former) (job|company|employer|role|position)\b",
    r"\b(my|the) (job|role|position) (at|as)\b",
    r"\bwhile (at|working)\b",
    r"\bintern(ed|ship)?\b",
    r"\bin production at\b",
    r"\bprofessional(ly)? (experience|work|setting)\b",
    r"\bfull[- ]time\b",
    r"\bon the job\b",
    r"\bmy (manager|colleagues|coworkers|teammates at)\b",
]

EDUCATION_PATTERNS = [
    r"\b(degree|bachelor'?s|master'?s (degree|in|of)|b\.?\s?tech|m\.?\s?tech|b\.s\.|m\.s\.|b\.sc|m\.sc|ph\.?d|graduated|gpa|cgpa)(?![\w])"
]
CERTIFICATION_PATTERNS = [r"\bcertifi(ed|cation|cate)\b"]

OVERREACH_WORDS = {
    "significantly", "dramatically", "massively", "hugely", "world-class", "best-in-class", "always",
    "never", "entire", "entirely", "sole", "solely", "single-handedly", "singlehandedly", "pioneered",
    "revolutionized", "invented", "transformed", "unparalleled", "flawless", "flawlessly", "perfect",
    "perfectly", "guaranteed", "exceptional", "renowned", "award-winning", "industry-leading", "top",
}

GENERIC_WORDS = {
    "experience", "experiences", "role", "roles", "team", "teams", "work", "worked", "working", "company",
    "excited", "exciting", "excite", "opportunity", "opportunities", "believe", "interest", "interested",
    "interesting", "passionate", "passion", "contribute", "contributing", "apply", "applying", "position",
    "help", "helping", "love", "would", "like", "want", "join", "joining", "bring", "bringing", "learn",
    "learning", "grow", "growing", "mission", "product", "products", "eager", "keen", "thrilled", "look",
    "looking", "forward", "able", "really", "very", "also", "well", "great", "good", "make", "making",
    "made", "use", "used", "using", "thing", "things", "kind", "part", "way", "ways", "time", "need",
    "needs", "into", "about", "from", "this", "that", "these", "those", "with", "have", "has", "had",
    "been", "being", "which", "their", "there", "what", "when", "where", "while", "your", "yours",
    "our", "ours", "them", "they", "will", "can", "could", "should", "more", "most", "much", "many",
    "such", "than", "then", "just", "only", "each", "both", "other", "same", "some", "any", "here",
    "skills", "skill", "background", "fit", "strong", "solid", "excellent", "engineer", "engineering",
    "software", "developer", "development", "build", "building", "built", "ship", "shipping", "shipped",
    "career", "next", "step", "journey", "values", "value", "culture", "impact", "impactful", "problems",
    "problem", "solve", "solving", "challenge", "challenges", "challenging", "focus", "focused", "care",
    "cares", "deeply", "thoughtful", "excellence", "quality", "people", "users", "user", "customers",
    "customer", "drawn", "draws", "appeal", "appeals", "particularly", "especially", "specifically",
    "currently", "recently", "previously", "including", "relevant", "directly", "closely", "hands",
    "list", "listed", "include", "includes", "résumé", "resume", "tool", "tools", "follow",
    "hello", "thank", "thanks", "talk", "chance", "welcome", "note", "wanted", "reach", "reaching",
}

STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can", "had", "her", "was", "one",
    "our", "out", "has", "him", "his", "how", "its", "may", "new", "now", "old", "see", "two", "way",
    "who", "did", "get", "let", "say", "she", "too", "use", "i'm", "i've", "i'd", "my", "me", "an", "a",
    "of", "to", "in", "on", "at", "by", "as", "is", "it", "be", "or", "so", "if", "do", "we", "us", "am",
}
