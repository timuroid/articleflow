# syntax=docker/dockerfile:1
FROM python:3.12-slim
RUN --mount=type=secret,id=proxy_ca,required=true \
    PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir \
    lxml==6.0.2 python-docx==1.2.0 Pillow==11.3.0 PyMuPDF==1.26.5 \
    numpy==2.3.3 httpx==0.28.1 jsonschema==4.25.1
WORKDIR /work
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/engine
USER 65534:65534
ENTRYPOINT ["python", "-m", "articleflow.worker034"]
