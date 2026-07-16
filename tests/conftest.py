import os

# Module-level boto3 clients need a region at import time. In Lambda this comes
# from AWS_REGION; for local tests we set a harmless default before imports.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("POWERTOOLS_METRICS_NAMESPACE", "DayBreakTest")
os.environ.setdefault("POWERTOOLS_SERVICE_NAME", "daybreak-test")
