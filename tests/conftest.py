from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider
from opentelemetry.sdk.metrics.export import AggregationTemporality, InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from umami_mcp_server.settings import get_settings


@dataclass(frozen=True)
class OtelCapture:
    span_exporter: InMemorySpanExporter
    metric_reader: InMemoryMetricReader


@pytest.fixture(scope="session")
def otel_capture() -> Iterator[OtelCapture]:
    environment_names = (
        "OTEL_SDK_DISABLED",
        "OTEL_TRACES_SAMPLER",
        "OTEL_TRACES_SAMPLER_ARG",
        "OTEL_METRICS_EXEMPLAR_FILTER",
    )
    saved_environment = {name: os.environ.get(name) for name in environment_names}
    for name in environment_names:
        os.environ.pop(name, None)

    span_exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider(shutdown_on_exit=False)
    tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    metric_reader = InMemoryMetricReader(
        preferred_temporality={
            Counter: AggregationTemporality.DELTA,
            Histogram: AggregationTemporality.DELTA,
        }
    )
    meter_provider = MeterProvider(
        metric_readers=[metric_reader],
        shutdown_on_exit=False,
    )
    metrics.set_meter_provider(meter_provider)

    yield OtelCapture(span_exporter=span_exporter, metric_reader=metric_reader)

    tracer_provider.force_flush()
    meter_provider.force_flush()
    for name, value in saved_environment.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture(autouse=True)
def _isolate_otel_capture(otel_capture: OtelCapture) -> Iterator[None]:
    otel_capture.span_exporter.clear()
    otel_capture.metric_reader.get_metrics_data()
    yield
    otel_capture.span_exporter.clear()
    otel_capture.metric_reader.get_metrics_data()


@pytest.fixture(autouse=True)
def _isolate_umami_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (
        "UMAMI_API_KEY",
        "UMAMI_USERNAME",
        "UMAMI_PASSWORD",
        "UMAMI_API_BASE",
        "UMAMI_LIVE_CLOUD_API_KEY",
        "UMAMI_LIVE_CLOUD_WEBSITE_ID",
        "UMAMI_LIVE_CLOUD_API_BASE",
        "OTEL_SDK_DISABLED",
        "OTEL_PROPAGATORS",
        "OTEL_SERVICE_NAME",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_TRACES_SAMPLER",
        "OTEL_TRACES_SAMPLER_ARG",
        "OTEL_METRICS_EXEMPLAR_FILTER",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
