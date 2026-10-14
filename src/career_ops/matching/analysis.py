from __future__ import annotations

import re
from collections import defaultdict

from career_ops.common.io import digest
from career_ops.models.contracts import JobAnalysis, JobListing, Requirement

# Canonical names with bounded aliases; a bare C must not match CDC or C++.
VOCABULARY = {
    "Programming Languages": {
        "C++": ["c++20", "c++"],
        "Go": ["golang", "go"],
        "C": ["c"],
        "Python": ["python"],
        "Java": ["java"],
        "SQL": ["sql"],
        "Rust": ["rust"],
        "JavaScript": ["javascript"],
        "TypeScript": ["typescript"],
    },
    "Frameworks": {
        "Spring": ["spring"],
        "FastAPI": ["fastapi"],
        "React": ["react"],
        "Node.js": ["node.js", "nodejs"],
    },
    "Databases": {
        "MySQL": ["mysql"],
        "PostgreSQL": ["postgresql", "postgres"],
        "StarRocks": ["starrocks"],
        "Redis": ["redis"],
        "LSM trees": ["lsm-tree", "lsm tree", "lsm trees"],
        "MVCC": ["mvcc"],
        "WAL": ["write ahead log", "write-ahead log", "wal"],
        "SSTables": ["sstable", "sstables"],
        "Bloom filters": ["bloom filter", "bloom filters"],
        "Database Systems": ["database systems", "storage engine"],
    },
    "Distributed Systems": {
        "Distributed Systems": ["distributed systems"],
        "Concurrency": ["concurrency", "concurrent", "multithreading", "multithreaded"],
        "Raft": ["raft"],
        "Kafka": ["kafka"],
        "REST APIs": ["rest api", "rest apis", "restful api", "restful apis", "http api"],
        "Fault tolerance": [
            "fault tolerance",
            "fault-tolerant",
            "crash-recovery",
            "crash recovery",
        ],
    },
    "Cloud and Infrastructure": {
        "AWS": ["aws", "amazon web services"],
        "Azure": ["azure"],
        "Docker": ["docker", "containerized", "containerisation"],
        "Kubernetes": ["kubernetes", "k8s"],
        "Linux": ["linux"],
        "Git": ["git", "github"],
    },
    "Data Engineering": {
        "Apache Flink": ["apache flink", "flink"],
        "Change Data Capture": ["change data capture", "cdc"],
        "Data Pipelines": ["data pipeline", "data pipelines"],
        "ETL": ["etl"],
        "Microsoft Fabric": ["microsoft fabric"],
        "Data Archival": ["data archival", "database archival", "archival system"],
        "Backup and Recovery": [
            "backup and recovery",
            "backup and recovery system",
            "point in time recovery",
        ],
    },
    "AI and Machine Learning": {
        "LLMs": ["llm", "llms", "large language models"],
        "RAG": ["rag", "retrieval-augmented generation"],
        "PyTorch": ["pytorch"],
        "LangChain": ["langchain"],
        "Agentic AI": ["agentic ai", "ai agents"],
        "vLLM": ["vllm"],
    },
    "Software Engineering Practices": {
        "Testing": ["testing", "tests", "test"],
        "CI/CD": ["ci/cd", "github actions"],
        "Performance Optimization": [
            "performance optimization",
            "performance optimisation",
            "benchmark",
            "benchmarks",
        ],
        "Authentication": ["authentication", "authorization"],
    },
}


def mentions(text: str, alias: str) -> bool:
    # Exclude plus signs from Go/C boundaries and avoid substring false positives.
    return bool(re.search(r"(?<![\w+])" + re.escape(alias) + r"(?![\w+])", text, re.I))


def technologies(text: str) -> dict[str, list[str]]:
    return {
        category: [
            name
            for name, aliases in names.items()
            if any(mentions(text, alias) for alias in aliases)
        ]
        for category, names in VOCABULARY.items()
        if any(any(mentions(text, alias) for alias in aliases) for aliases in names.values())
    }


def tech_set(text: str) -> set[str]:
    return {s for values in technologies(text).values() for s in values}


def analyze(job: JobListing) -> JobAnalysis:
    result = JobAnalysis(
        job_id=job.job_id,
        input_hash=digest(["analyzer-v2", job.description, job.title, VOCABULARY]),
    )
    section = "unknown"
    categories: dict[str, set[str]] = defaultdict(set)
    for raw in job.description.splitlines():
        line = raw.strip(" \t•*-")
        if not line:
            continue
        lower = line.lower().rstrip(":")
        if len(line) < 90 and lower in {
            "requirements",
            "required qualifications",
            "minimum qualifications",
            "qualifications",
            "what you bring",
            "must have",
        }:
            section = "required"
            continue
        if len(line) < 90 and any(
            x in lower for x in ("preferred qualifications", "nice to have", "bonus skills")
        ):
            section = "preferred"
            continue
        if len(line) < 90 and lower in {
            "responsibilities",
            "what you will do",
            "what you’ll do",
            "the role",
            "your impact",
        }:
            section = "responsibilities"
            continue
        found = technologies(line)
        flattened = [s for values in found.values() for s in values]
        for category, values in found.items():
            categories[category].update(values)
        is_preferred = section == "preferred" or bool(
            re.search(r"preferred|nice.to.have|a plus|bonus", line, re.I)
        )
        is_required = section == "required" or bool(
            re.search(r"\bmust\b|\brequired\b|minimum|at least", line, re.I)
        )
        category = next(iter(found), "Other Qualifications")
        requirement = Requirement(
            text=line,
            category=category,
            technologies=flattened,
            evidence=line,
            hard=is_required and not is_preferred,
        )
        if is_preferred:
            result.preferred_qualifications.append(requirement)
        elif is_required:
            result.required_qualifications.append(requirement)
        elif section == "responsibilities":
            result.responsibilities.append(line)
        else:
            result.uncertainties.append(f"Unclassified employer text: {line}")
        if re.search(r"\b(degree|bachelor|master|phd|education)\b", line, re.I) and (
            is_required or is_preferred
        ):
            result.education_requirements.append(line)
        if (
            is_required
            and not is_preferred
            and re.search(
                r"authorization|authorised|authorized|citizenship|citizen|clearance|sponsorship|reside|resident",
                line,
                re.I,
            )
        ):
            result.eligibility_requirements.append(requirement)
        years = re.search(
            r"(\d+(?:\.\d+)?)\s*(?:[-–]\s*(\d+(?:\.\d+)?))?\s*\+?\s*years?\b", line, re.I
        )
        if years and is_required and not is_preferred:
            minimum = float(years.group(1))
            if result.minimum_years is None or minimum > result.minimum_years:
                result.minimum_years = minimum
                result.maximum_years = float(years.group(2)) if years.group(2) else None
                result.experience_evidence = line
    result.technologies = {c: sorted(v) for c, v in categories.items()}
    result.ats_terminology = sorted({s for v in result.technologies.values() for s in v})
    result.emphasis_areas = sorted({r.category for r in result.required_qualifications})
    title = job.title.lower()
    result.seniority = next(
        (
            s
            for s in ("principal", "staff", "senior", "junior", "intern")
            if re.search(r"\b" + s + r"\b", title)
        ),
        None,
    )
    if result.minimum_years is None:
        result.uncertainties.append("Required years of experience were not established")
    return result
