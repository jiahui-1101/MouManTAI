"""Replaceable bounded HTTP transport. HTTPX is optional and imported lazily."""
import asyncio
from dataclasses import dataclass, field
import json
import os
import re
from urllib.parse import urlsplit

from .protocol import InferenceFailure, InferenceInput, InferenceOutput, validate_evidence


@dataclass(frozen=True)
class EndpointConfig:
    url: str
    api_key: str = field(repr=False)
    mode: str = "runpod"
    timeout_seconds: float = 125
    max_response_bytes: int = 131072

    def __post_init__(self):
        parsed = urlsplit(self.url)
        local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (parsed.scheme != "https" and not (local and parsed.scheme == "http")) or not parsed.hostname:
            raise ValueError("Configured endpoint must use HTTPS (except loopback development)")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Endpoint credentials belong in environment variables, not URLs")
        if self.mode not in {"runpod", "direct"} or not 0 < self.timeout_seconds <= 180:
            raise ValueError("Invalid endpoint mode or timeout")
        if not 1024 <= self.max_response_bytes <= 262144:
            raise ValueError("Invalid response budget")
        if not self.api_key:
            raise ValueError("Endpoint API key required")
        if self.mode == "runpod" and not parsed.path.endswith(("/run", "/runsync")):
            raise ValueError("Runpod URL must end in /run or /runsync")

    @classmethod
    def from_env(cls):
        return cls(url=os.environ["P1_AI_ENDPOINT_URL"], api_key=os.environ["P1_AI_API_KEY"],
                   mode=os.environ.get("P1_AI_ENDPOINT_MODE", "runpod"),
                   timeout_seconds=float(os.environ.get("P1_AI_TIMEOUT_SECONDS", "125")))


class EndpointAdapter:
    """Concurrency 1, no queued caller and NO automatic POST retries.

    A local timeout does not prove cancellation of an already submitted paid job.
    Runpod policy additionally caps execution at 90s and total job TTL at 120s.
    """
    def __init__(self, config: EndpointConfig, *, transport=None):
        self.config = config
        self.transport = transport
        self.busy = False
        self.last_output = None
        self.last_provider_metrics = {}

    async def infer(self, request: InferenceInput) -> InferenceOutput:
        if self.busy:
            raise InferenceFailure("busy")
        self.busy = True
        self.last_output = None
        self.last_provider_metrics = {}
        job_id = None
        try:
            import httpx

            payload = request.model_dump(mode="json")
            if self.config.mode == "runpod":
                payload = {"input": payload, "policy": {"executionTimeout": 90000, "ttl": 120000}}
            async with asyncio.timeout(self.config.timeout_seconds):
                async with httpx.AsyncClient(transport=self.transport, timeout=self.config.timeout_seconds,
                                            follow_redirects=False, trust_env=False) as client:
                    body = await self._exchange(client, "POST", self.config.url, payload)
                    if self.config.mode == "runpod":
                        candidate_id = body.get("id") if isinstance(body, dict) else None
                        if isinstance(candidate_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", candidate_id):
                            job_id = candidate_id
                        polls = 0
                        while isinstance(body, dict) and body.get("status") in {"IN_QUEUE", "IN_PROGRESS"} and job_id:
                            if polls >= 60:
                                raise TimeoutError()
                            await asyncio.sleep(min(0.5 + polls * 0.1, 3))
                            body = await self._exchange(client, "GET", self.config.url.rsplit("/", 1)[0] + "/status/" + job_id)
                            if body.get("id", job_id) != job_id:
                                raise InferenceFailure("job_id_mismatch")
                            polls += 1
            if self.config.mode == "runpod":
                if isinstance(body, dict):
                    # Provider-observed execution/delay metrics are NOT a bill.
                    self.last_provider_metrics = {k: body[k] for k in ("id", "executionTime", "delayTime")
                                                  if k in body and isinstance(body[k], (str, int, float))}
                if not isinstance(body, dict) or body.get("status") != "COMPLETED":
                    raise InferenceFailure("endpoint_job_not_completed")
                body = body.get("output")
            self.last_output = InferenceOutput.model_validate(body)
            return validate_evidence(self.last_output, request)
        except InferenceFailure:
            raise
        except TimeoutError:
            if job_id:
                await self._cancel(job_id)
            raise InferenceFailure("timeout") from None
        except Exception:
            raise InferenceFailure("transport_or_schema_error") from None
        finally:
            self.busy = False

    async def _exchange(self, client, method, url, payload=None):
        async with client.stream(method, url, json=payload,
                                 headers={"Authorization": "Bearer " + self.config.api_key}) as response:
            if response.status_code != 200:
                raise InferenceFailure("endpoint_http_error")
            chunks = bytearray()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > self.config.max_response_bytes:
                    raise InferenceFailure("response_budget_exceeded")
        return json.loads(chunks)

    async def _cancel(self, job_id):
        # Best effort, additional maximum 2s. A cancel request is not proof of
        # cancellation or an account spending cap. Never resubmit the job.
        import httpx
        try:
            async with asyncio.timeout(2):
                async with httpx.AsyncClient(transport=self.transport, timeout=2, follow_redirects=False, trust_env=False) as client:
                    body = await self._exchange(client, "POST", self.config.url.rsplit("/", 1)[0] + "/cancel/" + job_id, {})
                    self.last_provider_metrics.update(id=job_id, cancel_status=body.get("status", "requested"))
        except Exception:
            self.last_provider_metrics.update(id=job_id, cancel_status="unverified")
