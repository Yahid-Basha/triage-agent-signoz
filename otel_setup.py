"""
OTel wiring for the reward-regrade pipeline. One tracer provider (spans →
SigNoz via OTLP/gRPC) and one logger provider (Python `logging` records →
SigNoz, correlated to whatever span is active when the log line is emitted).

Correlation mechanism: `LoggingHandler` reads the current OTel span context
at emit time and stamps the exported LogRecord with its trace_id/span_id —
that's what lets SigNoz show a log line nested under the span that produced
it, not just a same-service log stream. Attaching the handler to the root
logger (not a specific span object) is what makes this automatic for every
`logging.info(...)` call made anywhere while a span is active.
"""

import atexit
import logging

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "triage-regrade-pipeline"
OTLP_ENDPOINT = "localhost:4317"

_tracer_provider: TracerProvider | None = None
_logger_provider: LoggerProvider | None = None


def setup_otel() -> trace.Tracer:
    """Idempotent: safe to call more than once, returns the same tracer."""
    global _tracer_provider, _logger_provider

    if _tracer_provider is not None:
        return trace.get_tracer(SERVICE_NAME)

    resource = Resource.create({"service.name": SERVICE_NAME})

    _tracer_provider = TracerProvider(resource=resource)
    _tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True))
    )
    trace.set_tracer_provider(_tracer_provider)

    _logger_provider = LoggerProvider(resource=resource)
    _logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTLP_ENDPOINT, insecure=True))
    )
    set_logger_provider(_logger_provider)

    # Attaching to the root logger means any `logging.info/warning/...` call,
    # anywhere in the process, is auto-correlated to the currently active span
    # — no need to pass a logger instance around.
    otel_handler = LoggingHandler(level=logging.INFO, logger_provider=_logger_provider)
    root_logger = logging.getLogger()
    root_logger.addHandler(otel_handler)
    root_logger.setLevel(logging.INFO)

    atexit.register(shutdown_otel)
    return trace.get_tracer(SERVICE_NAME)


def shutdown_otel() -> None:
    """Flush + shut down both providers. Anything still sitting in the
    BatchSpanProcessor/BatchLogRecordProcessor buffer is lost if this isn't
    called — call it at the end of every run, including on early exit."""
    global _tracer_provider, _logger_provider
    if _tracer_provider is not None:
        _tracer_provider.shutdown()
        _tracer_provider = None
    if _logger_provider is not None:
        _logger_provider.shutdown()
        _logger_provider = None
