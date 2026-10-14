from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from career_ops.common.io import CareerOpsError, digest
from career_ops.common.security import canonical_url, validate_url
from career_ops.models.contracts import JobListing, Provenance


def plain(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    return "\n".join(s.strip() for s in soup.get_text("\n").splitlines() if s.strip())


def date_value(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, UTC)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError, OverflowError):
        return None


def normalize(raw: dict, source: str = "manual", source_url: str | None = None) -> JobListing:
    if not isinstance(raw, dict):
        raise CareerOpsError("invalid_job", "A job must be a JSON object")
    for required in ("title", "description"):
        if not isinstance(raw.get(required), str) or not raw[required].strip():
            raise CareerOpsError("invalid_job", f"A verified nonempty {required} is required")
    if not isinstance(source_url or raw.get("source_url"), str):
        raise CareerOpsError("invalid_job", "A verified canonical source_url is required")
    url = canonical_url(source_url or raw["source_url"])
    app = canonical_url(raw.get("application_url") or url)
    fields = {
        name: raw.get(name)
        for name in (
            "title",
            "company",
            "location",
            "work_mode",
            "country",
            "industry",
            "company_size",
            "employment_type",
            "seniority",
            "experience_required",
            "salary",
        )
    }
    description = plain(raw.get("description", ""))
    provenance = {
        k: Provenance(
            source=url, pointer=f"/{k}", evidence=json.dumps(v) if not isinstance(v, str) else v
        )
        for k, v in {**fields, "description": description}.items()
        if v is not None
    }
    return JobListing(
        job_id=digest(url)[:20],
        **fields,
        description=description,
        source=source,
        source_url=url,
        application_url=app,
        ats_id=str(raw["ats_id"]) if raw.get("ats_id") is not None else None,
        date_posted=date_value(raw.get("date_posted")),
        provenance=provenance,
    )


class Fetcher:
    def __init__(self, client: httpx.Client | None = None, *, resolve: bool = True):
        self.client = client or httpx.Client(
            timeout=20,
            follow_redirects=False,
            headers={"User-Agent": "CareerOps/0.1 (+user-directed job discovery)"},
        )
        self.resolve = resolve

    def get(self, url: str) -> httpx.Response:
        for _ in range(6):
            url = validate_url(url, resolve=self.resolve)
            response = None
            for attempt in range(3):
                try:
                    with self.client.stream("GET", url) as incoming:
                        chunks, size = [], 0
                        for chunk in incoming.iter_bytes():
                            size += len(chunk)
                            if size > 5_000_000:
                                raise CareerOpsError(
                                    "response_too_large",
                                    "Job source exceeds the 5 MB response limit",
                                )
                            chunks.append(chunk)
                        response = httpx.Response(
                            incoming.status_code,
                            headers=incoming.headers,
                            content=b"".join(chunks),
                            request=incoming.request,
                        )
                    if response.status_code not in {429, 502, 503, 504}:
                        break
                except httpx.TransportError as exc:
                    if attempt == 2:
                        raise CareerOpsError(
                            "network_failed", "Job source could not be reached"
                        ) from exc
                time.sleep(min(0.2 * 2**attempt, 1))
            if response is None:
                raise CareerOpsError("network_failed", "Job source returned no response")
            if response.is_redirect:
                url = urljoin(url, response.headers["location"])
                continue
            if response.status_code in {401, 403}:
                raise CareerOpsError(
                    "access_restricted",
                    "Authentication/access restrictions require assisted browsing",
                )
            if response.status_code in {404, 410}:
                raise CareerOpsError("expired_listing", "Job listing is no longer available")
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise CareerOpsError(
                    "source_http_error", f"Job source returned HTTP {response.status_code}"
                ) from exc
            return response
        raise CareerOpsError("redirect_limit", "Job source exceeded the redirect limit")

    def permitted_html(self, url: str, access_permitted: bool) -> str:
        if not access_permitted:
            raise CareerOpsError(
                "access_not_verified",
                "Verify website access rules before enabling direct page fetching",
            )
        robots_url = urljoin(url, "/robots.txt")
        try:
            response = self.get(robots_url)
        except CareerOpsError as exc:
            if (
                exc.code == "expired_listing"
            ):  # absent robots file; user still verifies website terms
                return self.get(url).text
            raise
        robot = RobotFileParser()
        robot.parse(response.text.splitlines())
        if not robot.can_fetch("CareerOps", url):
            raise CareerOpsError(
                "robots_denied",
                "Website robots rules disallow this fetch; use an authorized assisted route",
            )
        return self.get(url).text


class SearchProvider(Protocol):
    def discover(self, config: dict) -> list[JobListing]: ...


class PublicBoardProvider:
    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher

    def discover(self, config: dict) -> list[JobListing]:
        provider, board = config["provider"], quote(config["board"], safe="")
        company = config.get("company")  # never infer company name from a slug
        if provider == "greenhouse":
            endpoint = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
            entries = self.fetcher.get(endpoint).json()["jobs"]
            return [
                normalize(
                    dict(
                        title=j["title"],
                        company=company,
                        location=(j.get("location") or {}).get("name"),
                        description=j.get("content", ""),
                        source_url=j["absolute_url"],
                        ats_id=j["id"],
                    ),
                    provider,
                )
                for j in entries
                if j.get("content")
            ]
        if provider == "lever":
            endpoint = f"https://api.lever.co/v0/postings/{board}?mode=json"
            entries = self.fetcher.get(endpoint).json()
            result = []
            for j in entries:
                categories = j.get("categories") or {}
                description = j.get("descriptionPlain") or plain(j.get("description", ""))
                for section in j.get("lists", []):
                    description += (
                        "\n" + section.get("text", "") + "\n" + plain(section.get("content", ""))
                    )
                description += "\n" + (j.get("additionalPlain") or plain(j.get("additional", "")))
                result.append(
                    normalize(
                        dict(
                            title=j["text"],
                            company=company,
                            location=categories.get("location"),
                            employment_type=categories.get("commitment"),
                            work_mode=j.get("workplaceType"),
                            description=description,
                            source_url=j["hostedUrl"],
                            application_url=j.get("applyUrl"),
                            ats_id=j["id"],
                        ),
                        provider,
                    )
                )
            return result
        if provider == "ashby":
            endpoint = (
                f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"
            )
            entries = self.fetcher.get(endpoint).json()["jobs"]
            return [
                normalize(
                    dict(
                        title=j["title"],
                        company=company,
                        location=j.get("location"),
                        employment_type=j.get("employmentType"),
                        work_mode=j.get("workplaceType"),
                        description=j.get("descriptionPlain") or j.get("descriptionHtml", ""),
                        source_url=j["jobUrl"],
                        application_url=j.get("applyUrl"),
                        ats_id=j.get("id"),
                        date_posted=j.get("publishedAt"),
                        salary=j.get("compensation"),
                    ),
                    provider,
                )
                for j in entries
                if j.get("isListed", True)
            ]
        raise CareerOpsError(
            "unsupported_provider",
            f"No public feed integration for {provider}; use assisted import",
        )


def structured_jobs(html: str, url: str) -> list[JobListing]:
    soup = BeautifulSoup(html, "html.parser")
    result = []

    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            if value.get("@type") == "JobPosting" or "JobPosting" in (value.get("@type") or []):
                company = value.get("hiringOrganization") or {}
                location = value.get("jobLocation") or {}
                if isinstance(location, list):
                    location = location[0] if location else {}
                address = location.get("address") or {}
                location_text = (
                    ", ".join(
                        str(address[k])
                        for k in ("addressLocality", "addressRegion", "addressCountry")
                        if address.get(k)
                    )
                    or None
                )
                result.append(
                    normalize(
                        dict(
                            title=value.get("title"),
                            company=company.get("name"),
                            location=location_text,
                            description=value.get("description"),
                            source_url=urljoin(url, value.get("url") or url),
                            employment_type=value.get("employmentType"),
                            date_posted=value.get("datePosted"),
                        ),
                        "structured",
                    )
                )
            if "@graph" in value:
                visit(value["@graph"])

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            visit(json.loads(script.string or script.get_text()))
        except json.JSONDecodeError:
            continue
    return result


def board_from_url(url: str) -> dict:
    parsed = urlsplit(canonical_url(url))
    pieces = [p for p in parsed.path.split("/") if p]
    for suffix, provider in [
        ("greenhouse.io", "greenhouse"),
        ("lever.co", "lever"),
        ("ashbyhq.com", "ashby"),
    ]:
        if (parsed.hostname == suffix or parsed.hostname.endswith("." + suffix)) and pieces:
            return {
                "provider": provider,
                "board": pieces[0],
                "url": f"{parsed.scheme}://{parsed.netloc}/{pieces[0]}",
            }
    return {"provider": "assisted", "url": f"{parsed.scheme}://{parsed.netloc}/"}
