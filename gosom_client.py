from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from config import get_settings


settings = get_settings()


@dataclass(slots=True)
class GosomClient:
    base_url: str = settings.gosom_base_url
    timeout: float = 30.0

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=self.timeout)

    def submit_job(self, payload: dict) -> dict:
        with self._client() as client:
            response = client.post("/jobs", json=payload)
            response.raise_for_status()
            return response.json()

    def get_job(self, job_id: str) -> dict:
        with self._client() as client:
            response = client.get(f"/jobs/{job_id}")
            response.raise_for_status()
            return response.json()

    def download_results(self, job_id: str) -> dict:
        with self._client() as client:
            response = client.get(f"/jobs/{job_id}/download")
            response.raise_for_status()
            return response.json()
