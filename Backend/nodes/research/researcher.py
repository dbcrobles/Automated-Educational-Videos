"""Automated researcher: 4 Gemini passes (scout → curate → deep dive → currentness audit).

Moved verbatim from Backend/nodes/scripting/node1_scripting.py (Phase 2 pre-work).
node1_scripting.py imports everything from here so the legacy shorts pipeline
keeps working unchanged.
"""
import os
import sys
import json
import re
import requests
from datetime import date
from typing import Literal, Optional
from urllib.parse import parse_qsl, urlsplit
from pydantic import BaseModel, Field
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from database import database
from nodes.research import prompts

COST_SCOUT_CALL = 0.03
COST_CURATE_CALL = 0.01
COST_DEEP_RESEARCH_CALL = 0.05
COST_CURRENTNESS_CALL = 0.05

GEMINI_MODEL_RESEARCH = "gemini-3.1-pro-preview"
GEMINI_MODEL_STRUCTURED = "gemini-3.5-flash"


class AnchorArticle(BaseModel):
    title: str
    url: str
    access_url: str
    publisher: str
    publication_date: str
    source_type: str
    selection_reason: str

class SourceCandidate(BaseModel):
    candidate_id: str
    title: str
    url: str
    source_type: str
    publisher: str
    publication_date: str
    central_finding: str
    distinct_value: str

class SourceScout(BaseModel):
    candidates: list[SourceCandidate]

class AnchorChoice(BaseModel):
    candidate_id: str
    selection_reason: str

class AnchorSelection(BaseModel):
    choices: list[AnchorChoice]

class ChartPoint(BaseModel):
    label: str
    value: float

class EvidenceClaim(BaseModel):
    claim: str
    source_url: str
    access_url: str
    source_title: str
    publisher: str
    publication_date: str
    evidence_role: Literal["core", "update", "context", "counterpoint"]
    currentness: Literal["latest_available", "historical", "superseded", "uncertain"]
    usage: Literal["current_fact", "dated_context", "do_not_use"]
    as_of_date: str
    currentness_note: str
    population_or_geography: str
    date_or_period: str
    caveat: str
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    chart_recommended: bool
    chart_unit: Optional[str] = None
    chart_points: list[ChartPoint] = Field(default_factory=list)

class SourceReference(BaseModel):
    title: str
    publisher: str
    url: str
    access_url: str
    publication_date: str
    evidence_role: Literal["core", "update", "context", "counterpoint"]

class ResearchDossier(BaseModel):
    thesis: str
    core_thesis: str
    as_of_date: str
    anchors: list[AnchorArticle]
    evidence_ledger: list[EvidenceClaim]
    related_sources: list[SourceReference]
    tensions_or_unknowns: list[str]
    currentness_warnings: list[str]


def _grounding_urls(response):
    """Extract source URLs supplied by Gemini's Google Search grounding metadata."""
    try:
        metadata = response.candidates[0].grounding_metadata
        chunks = metadata.grounding_chunks or []
    except (AttributeError, IndexError, TypeError):
        return []
    urls = []
    for chunk in chunks:
        uri = getattr(getattr(chunk, 'web', None), 'uri', None)
        if uri and uri not in urls:
            urls.append(uri)
    return urls

def _grounding_source_records(response):
    """Keep Google's titled click-through links so inaccessible sources remain usable."""
    try:
        chunks = response.candidates[0].grounding_metadata.grounding_chunks or []
    except (AttributeError, IndexError, TypeError):
        return []
    records = []
    for chunk in chunks:
        web = getattr(chunk, 'web', None)
        uri = getattr(web, 'uri', None)
        if not uri:
            continue
        resolved_url = uri
        if 'vertexaisearch.cloud.google.com' in uri:
            try:
                reply = requests.get(uri, allow_redirects=True, stream=True, timeout=8)
                resolved_url = reply.url
                reply.close()
            except requests.RequestException:
                pass
        records.append({
            'title': getattr(web, 'title', None) or urlsplit(resolved_url).netloc,
            'access_url': uri,
            'resolved_url': resolved_url,
        })
    return records

def _url_key(url):
    """Normalize harmless URL variations without changing the URL used as evidence."""
    parsed = urlsplit(str(url or '').strip())
    query = tuple(sorted(
        (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith('utm_')
        and key.lower() not in {'fbclid', 'gclid', 'mc_cid', 'mc_eid'}
    ))
    return (parsed.netloc.lower().removeprefix('www.'), parsed.path.rstrip('/') or '/', query)

def _retrieval_statuses(response, requested_urls):
    """Map each requested URL to its URL Context status, tolerating redirects."""
    try:
        metadata = response.candidates[0].url_context_metadata
        entries = metadata.url_metadata or []
    except (AttributeError, IndexError, TypeError):
        entries = []
    records = [
        (
            _url_key(entry.retrieved_url),
            str(getattr(entry.url_retrieval_status, 'value', entry.url_retrieval_status)).upper(),
        )
        for entry in entries
    ]
    by_url = dict(records)
    return {
        url: by_url.get(
            _url_key(url),
            records[index][1] if len(records) == len(requested_urls) else 'NOT_REPORTED',
        )
        for index, url in enumerate(requested_urls)
    }

def _anchors_from_choices(choices, candidates, excluded_ids=()):
    """Resolve curator IDs in code so the model never has to reproduce a URL."""
    by_id = {candidate['candidate_id']: candidate for candidate in candidates}
    excluded = set(excluded_ids)
    anchors = []
    for choice in choices:
        candidate = by_id.get(choice.get('candidate_id'))
        if not candidate or candidate['candidate_id'] in excluded:
            continue
        anchors.append({
            'title': candidate['title'],
            'url': candidate['url'],
            'access_url': candidate['url'],
            'publisher': candidate['publisher'],
            'publication_date': candidate['publication_date'],
            'source_type': candidate['source_type'],
            'selection_reason': choice.get('selection_reason') or candidate['distinct_value'],
        })
    return anchors[:2]

def _resolve_doi_anchors(anchors):
    """Replace DOI resolver links with their public article destinations when available."""
    resolved = []
    for anchor in anchors:
        anchor = dict(anchor)
        if urlsplit(anchor['url']).netloc.lower().removeprefix('www.') == 'doi.org':
            try:
                response = requests.get(anchor['url'], allow_redirects=True, stream=True, timeout=8)
                if response.ok and urlsplit(response.url).netloc.lower() != 'doi.org':
                    anchor['url'] = response.url
                response.close()
            except requests.RequestException as error:
                print(f"Node 1: DOI resolution skipped for {anchor['url']}: {error}")
        resolved.append(anchor)
    return resolved

def _retrieval_failures(statuses, research_text):
    """Reject explicit failures; missing optional metadata is inconclusive, not fatal."""
    dossier_urls = {_url_key(url) for url in _urls_from_text(research_text)}
    explicit_failures = ('ERROR', 'PAYWALL', 'UNSAFE')
    return {
        url: status for url, status in statuses.items()
        if status.endswith(explicit_failures)
        or (status == 'NOT_REPORTED' and _url_key(url) not in dossier_urls)
    }

def _urls_from_text(text):
    return {
        url.rstrip('.,;:')
        for url in re.findall(r'https?://[^\s<>"\]\)]+', text or '')
    }

def _latest_year(value):
    years = [int(year) for year in re.findall(r'\b(?:19|20)\d{2}\b', str(value or ''))]
    return max(years) if years else None

def _normalize_dossier(dossier, grounding_responses=()):
    """Backfill old dossiers and attach titled Vertex Search fallback links."""
    dossier = dict(dossier or {})
    today = date.today().isoformat()
    dossier.setdefault('core_thesis', dossier.get('thesis', ''))
    dossier['as_of_date'] = today
    redirects = {}
    titles = {}
    for response in grounding_responses:
        for record in _grounding_source_records(response):
            redirects[_url_key(record['resolved_url'])] = record['access_url']
            titles[_url_key(record['resolved_url'])] = record['title']

    anchors = dossier.get('anchors') or []
    anchor_keys = set()
    for anchor in anchors:
        url = anchor.get('url', '')
        key = _url_key(url)
        anchor_keys.add(key)
        anchor.setdefault('access_url', redirects.get(key, url))
        if key in redirects:
            anchor['access_url'] = redirects[key]
        anchor.setdefault('publisher', urlsplit(url).netloc.removeprefix('www.'))
        anchor.setdefault('publication_date', '')

    warnings = list(dossier.get('currentness_warnings') or [])
    for item in dossier.get('evidence_ledger') or []:
        url = item.get('source_url', '')
        key = _url_key(url)
        item.setdefault('access_url', redirects.get(key, url))
        if key in redirects:
            item['access_url'] = redirects[key]
        item.setdefault('source_title', titles.get(key) or urlsplit(url).netloc.removeprefix('www.'))
        item.setdefault('publisher', urlsplit(url).netloc.removeprefix('www.'))
        item.setdefault('publication_date', item.get('date_or_period', ''))
        item.setdefault('evidence_role', 'core' if key in anchor_keys else 'context')
        item.setdefault('as_of_date', today)
        if not item.get('currentness'):
            year = _latest_year(item.get('date_or_period'))
            item['currentness'] = 'historical' if year and year < date.today().year - 2 else 'uncertain'
        if not item.get('usage'):
            item['usage'] = ('current_fact' if item['currentness'] == 'latest_available'
                             else 'dated_context')
        item.setdefault('currentness_note', 'Legacy evidence; currentness was not previously audited.')
        if item['currentness'] == 'superseded':
            item['usage'] = 'do_not_use'
        elif item['currentness'] != 'latest_available' and item['usage'] == 'current_fact':
            item['usage'] = 'dated_context'
        if item['usage'] != 'current_fact':
            warning = f"{item.get('source_title')}: {item['currentness_note']}"
            if warning not in warnings:
                warnings.append(warning)

    related = []
    for source in dossier.get('related_sources') or []:
        if isinstance(source, str):
            source = {'url': source}
        source = dict(source)
        url = source.get('url', '')
        key = _url_key(url)
        source.setdefault('title', titles.get(key) or urlsplit(url).netloc.removeprefix('www.'))
        source.setdefault('publisher', urlsplit(url).netloc.removeprefix('www.'))
        source.setdefault('access_url', redirects.get(key, url))
        if key in redirects:
            source['access_url'] = redirects[key]
        source.setdefault('publication_date', '')
        source.setdefault('evidence_role', 'context')
        related.append(source)
    dossier['related_sources'] = related
    dossier['currentness_warnings'] = warnings
    return dossier

def _audit_currentness(client, topic, dossier, video_id, cost_stage='script'):
    """Search specifically for changes after the core sources before scripting."""
    print("Node 1: Pass 3b (Currentness and thesis-expansion audit)...")
    response = client.models.generate_content(
        model=GEMINI_MODEL_RESEARCH,
        contents=prompts.currentness_audit_prompt(topic, dossier),
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}],
            response_mime_type="application/json",
            response_schema=ResearchDossier,
            temperature=0.1,
        ),
    )
    database.log_cost(video_id, COST_CURRENTNESS_CALL, cost_stage)
    if not response.text:
        raise Exception("Currentness audit returned no research dossier.")
    return _normalize_dossier(json.loads(response.text), [response]), response

def _research_quality_issues(dossier):
    issues = []
    if not dossier.get('anchors'):
        issues.append('research has no core anchor article')
    usable = [item for item in dossier.get('evidence_ledger', [])
              if item.get('usage') != 'do_not_use']
    if len(usable) < 4:
        issues.append('fewer than four usable evidence claims remain after currentness review')
    for item in usable:
        if item.get('usage') == 'current_fact' and item.get('currentness') != 'latest_available':
            issues.append(f"non-current evidence marked current: {item.get('claim', '')[:80]}")
    return issues

def _dossier_needs_audit(dossier):
    """Re-check legacy or month-old research; ordinary same-month rewrites stay cheap."""
    try:
        checked = date.fromisoformat(str(dossier.get('as_of_date', ''))[:10])
    except (TypeError, ValueError):
        return True
    return (date.today() - checked).days > 30 or any(
        not item.get('currentness') or not item.get('usage')
        for item in dossier.get('evidence_ledger', []))

def _source_details(dossier, used_urls):
    """Build labeled, clickable citations with core articles kept first."""
    records = []
    for anchor in dossier.get('anchors', []):
        records.append({
            'title': anchor.get('title') or anchor.get('url'),
            'publisher': anchor.get('publisher') or urlsplit(anchor.get('url', '')).netloc,
            'role': 'core',
            'url': anchor.get('url'),
            'access_url': anchor.get('access_url') or anchor.get('url'),
        })
    used_keys = {_url_key(url) for url in used_urls}
    for item in dossier.get('evidence_ledger', []):
        if (_url_key(item.get('source_url')) not in used_keys
                or item.get('usage') == 'do_not_use'):
            continue
        records.append({
            'title': item.get('source_title') or item.get('source_url'),
            'publisher': item.get('publisher') or urlsplit(item.get('source_url', '')).netloc,
            'role': item.get('evidence_role', 'context'),
            'url': item.get('source_url'),
            'access_url': item.get('access_url') or item.get('source_url'),
        })
    unique = []
    seen = set()
    for record in records:
        key = _url_key(record.get('url'))
        if not key[0] or key in seen:
            continue
        unique.append(record)
        seen.add(key)
    return unique

def _grounding_redirect_map(response, target_urls):
    """Match Google's always-fetchable grounding redirect links to failing source URLs."""
    redirects = [url for url in _grounding_urls(response)
                 if 'vertexaisearch.cloud.google.com' in url]
    resolved = {}
    for redirect in redirects[:12]:
        try:
            reply = requests.get(redirect, allow_redirects=True, stream=True, timeout=8)
            resolved[redirect] = reply.url
            reply.close()
        except requests.RequestException:
            continue
    mapping = {}
    for target in target_urls:
        key = _url_key(target)
        exact = [red for red, final in resolved.items() if _url_key(final) == key]
        same_site = [red for red, final in resolved.items() if _url_key(final)[0] == key[0]]
        if exact:
            mapping[target] = exact[0]
        elif len(same_site) == 1:
            mapping[target] = same_site[0]
    return mapping

def _deep_research(client, topic, anchor_urls, research_profile, locate_by_search=None):
    access_instruction = "Use URL context to read every anchor."
    if locate_by_search:
        titles = [{'title': anchor['title'], 'source_type': anchor['source_type']}
                  for anchor in locate_by_search]
        access_instruction = f"""URL Context could not retrieve some anchors directly. Use Google Search
    to locate and read the same articles by title and publisher before extracting evidence:
    {json.dumps(titles)}"""
    print("Node 1: Pass 3 (Anchor deep dive + related evidence)...")
    return client.models.generate_content(
        model=GEMINI_MODEL_RESEARCH,
        contents=prompts.deep_research_prompt(topic, anchor_urls, research_profile, access_instruction),
        config=types.GenerateContentConfig(
            tools=[{"url_context": {}}, {"google_search": {}}],
            response_mime_type="application/json",
            response_schema=ResearchDossier,
            temperature=0.2,
        ),
    )

def _build_research_dossier(client, topic, research_profile, video_id, cost_stage='script'):
    """Run expensive research once and return a checkpointable dossier."""
    print(f"Node 1: Pass 1 (Source scout) for '{topic}'...")
    scout_response = client.models.generate_content(
        model=GEMINI_MODEL_STRUCTURED,
        contents=prompts.scout_prompt(topic, research_profile),
        config=types.GenerateContentConfig(
            temperature=0.3,
            tools=[{"google_search": {}}],
            response_mime_type="application/json",
            response_schema=SourceScout,
        ),
    )
    database.log_cost(video_id, COST_SCOUT_CALL, cost_stage)
    scout_text = scout_response.text or ''
    candidates = json.loads(scout_text or '{}').get('candidates', [])
    candidates = [candidate for candidate in candidates
                  if str(candidate.get('url', '')).startswith(('http://', 'https://'))]
    for index, candidate in enumerate(candidates, 1):
        candidate['candidate_id'] = f"C{index:02d}"
    if len(candidates) < 2:
        raise Exception("Source scout found fewer than two verifiable article URLs.")

    curate_prompt = prompts.curate_prompt(topic, candidates)
    print("Node 1: Pass 2 (Anchor curation)...")
    curate_response = client.models.generate_content(
        model=GEMINI_MODEL_STRUCTURED,
        contents=curate_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=AnchorSelection,
            temperature=0.1,
        ),
    )
    database.log_cost(video_id, COST_CURATE_CALL, cost_stage)
    anchor_choices = json.loads(curate_response.text or '{}').get('choices', [])[:2]
    anchors = _anchors_from_choices(anchor_choices, candidates)
    if not anchors:
        raise Exception("Anchor curator did not return a candidate ID from the source scout.")
    selected_ids = [choice['candidate_id'] for choice in anchor_choices]
    anchors = _resolve_doi_anchors(anchors)
    anchor_urls = [anchor['url'] for anchor in anchors]

    def _deep_dive(fetch_urls, locate_by_search=False):
        response = _deep_research(client, topic, fetch_urls, research_profile,
                                  locate_by_search=anchors if locate_by_search else None)
        database.log_cost(video_id, COST_DEEP_RESEARCH_CALL, cost_stage)
        text = response.text
        failures = {}
        if text and not locate_by_search:
            failures = _retrieval_failures(_retrieval_statuses(response, fetch_urls), text)
        return response, text, failures

    deep_response, research_text, failed = _deep_dive(anchor_urls)
    if not research_text:
        raise Exception("Anchor deep dive returned no research dossier.")
    source_redirects = {}
    if failed:
        database.record_pipeline_error(
            video_id, 'Node 1', 'URL_CONTEXT_RECOVERY', str(failed),
            {'failed': failed}, auto_recovered=True)
        print(f"Node 1: URL Context recovery needed: {failed}")

        # Fallback 1: retry the same anchors through Google's grounding redirect links.
        source_redirects = _grounding_redirect_map(scout_response, list(failed))
        if source_redirects:
            print(f"Node 1: retrying {len(source_redirects)} anchor(s) via grounding redirects.")
            fetch_urls = [source_redirects.get(url, url) for url in anchor_urls]
            deep_response, retry_text, retry_failed = _deep_dive(fetch_urls)
            if retry_text:
                research_text = retry_text
                failed = {url: retry_failed[fetch] for url, fetch in zip(anchor_urls, fetch_urls)
                          if fetch in retry_failed}

        # Fallback 2: keep the retrievable anchors, or curate replacements.
        if failed:
            usable = set(anchor_urls) - set(failed)
            if usable:
                anchors = [anchor for anchor in anchors if anchor['url'] in usable]
            else:
                failed_keys = {_url_key(url) for url in failed}
                failed_ids = [candidate['candidate_id'] for candidate in candidates
                              if _url_key(candidate['url']) in failed_keys]
                retry_prompt = curate_prompt + f"""

                URL Context could not retrieve candidate IDs {json.dumps(failed_ids)}.
                Exclude those and previously selected IDs {json.dumps(selected_ids)}.
                Select 1-2 different, publicly accessible candidates.
                """
                retry_response = client.models.generate_content(
                    model=GEMINI_MODEL_STRUCTURED,
                    contents=retry_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=AnchorSelection,
                        temperature=0.1,
                    ),
                )
                database.log_cost(video_id, COST_CURATE_CALL, cost_stage)
                retry_choices = json.loads(retry_response.text or '{}').get('choices', [])
                replacements = _anchors_from_choices(
                    retry_choices, candidates, set(failed_ids) | set(selected_ids))
                if replacements:
                    anchors = _resolve_doi_anchors(replacements)
            anchor_urls = [anchor['url'] for anchor in anchors]
            deep_response, retry_text, retry_failed = _deep_dive(anchor_urls)
            if retry_text:
                research_text, failed = retry_text, retry_failed

        # Fallback 3: last resort — Google Search grounding locates the anchors itself.
        if failed or not research_text:
            print("Node 1: falling back to search-grounded deep dive.")
            deep_response, research_text, _ = _deep_dive(anchor_urls, locate_by_search=True)
            if not research_text:
                raise Exception(f"Search-grounded deep dive also failed after URL Context errors: {failed}")
            database.record_pipeline_error(
                video_id, 'Node 1', 'URL_CONTEXT_SEARCH_FALLBACK',
                f"Anchors read via Google Search grounding instead of direct URLs: {sorted(failed)}",
                {'failed': failed}, auto_recovered=True)
    dossier = json.loads(research_text)
    dossier['anchors'] = anchors
    if source_redirects:
        dossier['source_redirects'] = source_redirects
    dossier = _normalize_dossier(dossier, [scout_response, deep_response])
    original_anchors = dossier['anchors']
    dossier, audit_response = _audit_currentness(client, topic, dossier, video_id, cost_stage)
    audited_access = {_url_key(a.get('url')): a.get('access_url')
                      for a in dossier.get('anchors', [])}
    for anchor in original_anchors:
        anchor['access_url'] = audited_access.get(
            _url_key(anchor.get('url')), anchor.get('access_url') or anchor.get('url'))
    dossier['anchors'] = original_anchors
    research_issues = _research_quality_issues(dossier)
    if research_issues:
        raise Exception("Research quality gate failed: " + "; ".join(research_issues))
    verified_urls = ({candidate['url'] for candidate in candidates} | set(anchor_urls)
                     | set(source_redirects.values()) | _urls_from_text(json.dumps(dossier))
                     | set(_grounding_urls(deep_response)) | set(_grounding_urls(audit_response)))
    return dossier, verified_urls